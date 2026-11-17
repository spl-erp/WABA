"""Store what customers send: one Conversation per (business number, customer), one Message per WhatsApp message.

Called by waba.api.webhook.process_event with the `value` of a `messages` change. Idempotent: a message id is stored
once however many times Meta re-sends it, and a second worker creating the same conversation at the same moment
loses cleanly to the unique key. Sender matching, the 24-hour window and assignment (waba.assignment) are applied here.
"""

import datetime
import json

import frappe
from frappe import _
from frappe.utils import convert_utc_to_system_timezone, now_datetime

from waba import assignment, locks, matching, media, parties
from waba.rules import coexistence, inbound, window


def _details(m):
	"""The file reference, place, contact cards and reply id of a message, as Waba Message field values."""
	values = {
		"latitude": m.get("latitude"),
		"longitude": m.get("longitude"),
		"interactive_id": m.get("interactive_id"),
		"contacts_json": json.dumps(m["contacts"], ensure_ascii=False) if m.get("contacts") else None,
	}
	if m.get("media_id"):
		values.update(
			media_id=m["media_id"],
			media_mime=m.get("media_mime"),
			media_filename=m.get("media_filename"),
			media_sha256=m.get("media_sha256"),
			voice=m.get("voice") or 0,
			media_status="Pending",
		)
	return values


def _react(m):
	"""Put a customer's reaction on the message it refers to (an empty emoji removes it). True when the target is ours."""
	target = m.get("reaction_to")
	row = frappe.db.get_value("Waba Message", {"message_id": target}, ["name", "conversation"], as_dict=True) if target else None
	if not row:
		return False
	frappe.db.set_value("Waba Message", row.name, "customer_reaction", (m.get("body") if m.get("body") != "[reaction]" else "") or None, update_modified=False)
	assignment.notify(row.conversation, "reaction")
	return True


def store_messages(value, number, event):
	"""Returns {"stored": n, "duplicates": n, "unidentified": n}."""
	account, portfolio = frappe.db.get_value("Waba Number", number, "account"), None
	if account:
		portfolio = frappe.db.get_value("Waba Account", account, "portfolio")
	counts = {"stored": 0, "duplicates": 0, "unidentified": 0}
	for m in inbound.parse_messages(value):
		key = inbound.conversation_key(number, m["phone"], m["bsuid"])
		if not key:
			counts["unidentified"] += 1
			continue
		if m["type"] == "reaction":
			counts["ignored"] = counts.get("ignored", 0) + (0 if _react(m) else 1)  # a reaction is not a new message: no bubble, no unread, no reopening
			continue
		if frappe.db.exists("Waba Message", {"message_id": m["message_id"]}):
			counts["duplicates"] += 1
			continue
		conversation = _conversation(key, number, m)
		sent_at = _when(m["timestamp"])
		try:
			stored = frappe.get_doc(
				{
					"doctype": "Waba Message",
					"message_id": m["message_id"],
					"conversation": conversation.name,
					"direction": "In",
					"message_type": m["type"],
					"preview": inbound.preview(m["body"]),
					"status": "Received",
					"sent_at": sent_at,
					"waba_number": number,
					"body": m["body"],
					"reply_to_message_id": m["reply_to"],
					"event": event,
					**_details(m),
				}
			).insert(ignore_permissions=True)
		except _CLASH:
			counts["duplicates"] += 1
			continue
		if m.get("media_id"):
			media.queue_download(stored.name)  # claimed first, so one file is fetched once however often Meta repeats the delivery
		with locks.conversation(conversation.name):  # one message at a time per conversation: no double assignment
			conversation.reload()
			_update_conversation(conversation, m, sent_at, portfolio)
			counts["stored"] += 1
			_keyword(conversation, m["body"])
			_campaign_reply(conversation)
			_bot(conversation, stored.name)  # after STOP / START (an opted-out customer is never answered) and before routing (a chat in a bot's hands is not handed to an agent)
			_route(conversation, m["body"])
		assignment.notify(conversation, "message")
	return counts


def store_echoes(value, number, event):
	"""Messages the business typed in the WhatsApp Business app (coexistence). Returns {"stored", "duplicates", "unidentified", "edited"}.

	These are OUR side of the chat, so they never run the customer-message logic: no unread, no 24-hour window change, no
	STOP / START, no campaign reply, no bot start, no assignment, no ring. They are stored as outgoing "Phone app" messages with
	no ERP user. A message Waba itself sent is already stored under the same id and is skipped. An unknown customer gets an
	unassigned Triage conversation (nobody is alerted)."""
	counts = {"stored": 0, "duplicates": 0, "unidentified": 0, "edited": 0}
	for m in inbound.parse_echoes(value):
		key = inbound.conversation_key(number, m["phone"], m["bsuid"])
		if not key:
			counts["unidentified"] += 1
			continue
		if m["action"] != "new":
			counts["edited"] += _edit_echo(m)
			continue
		if frappe.db.exists("Waba Message", {"message_id": m["message_id"]}):
			counts["duplicates"] += 1
			continue
		conversation = _conversation(key, number, m)
		sent_at = _when(m["timestamp"])
		first_reply = not frappe.db.exists(
			"Waba Message", {"conversation": conversation.name, "direction": "Out", "origin": "Phone app", "sent_at": [">=", conversation.last_inbound_at or sent_at]}
		)
		try:
			stored = frappe.get_doc(
				{
					"doctype": "Waba Message",
					"message_id": m["message_id"],
					"conversation": conversation.name,
					"direction": "Out",
					"message_type": m["type"],
					"preview": inbound.preview(m["body"]),
					"status": "Sent",
					"sent_at": sent_at,
					"waba_number": number,
					"body": m["body"],
					"reply_to_message_id": m["reply_to"],
					"event": event,
					"origin": "Phone app",
					**_details(m),
				}
			).insert(ignore_permissions=True)
		except _CLASH:
			counts["duplicates"] += 1
			continue
		if m.get("media_id"):
			media.queue_download(stored.name)
		with locks.conversation(conversation.name):
			conversation.reload()
			_after_echo(conversation, m, sent_at, first_reply)
		counts["stored"] += 1
	return counts


def _after_echo(conversation, m, sent_at, first_reply):
	"""What a phone-app reply changes on the conversation: the last message (only if newer) and, on the first reply to a
	customer message, a note and the end of any bot session. Nothing else."""
	last = conversation.last_message_at
	if not last or sent_at >= last:
		frappe.db.set_value(
			"Waba Conversation", conversation.name, {"last_message_at": sent_at, "last_message_preview": inbound.preview(m["body"])}, update_modified=False
		)
	if first_reply:
		assignment.add_event(conversation.name, _("Answered from the phone app."))
	try:
		from waba import bot

		bot.on_phone_reply(conversation)
	except Exception:
		frappe.log_error(title="Waba: stopping a bot after a phone-app reply failed")


def _edit_echo(m):
	"""A message edited or deleted in the phone app: change the stored copy. 1 when one was changed."""
	name = frappe.db.get_value("Waba Message", {"message_id": m["original_id"]}, ["name", "body"], as_dict=True)
	if not name:
		return 0
	body = coexistence.revoked_body(name.body) if m["action"] == "revoke" else m["body"]
	frappe.db.set_value("Waba Message", name.name, {"body": body, "preview": inbound.preview(body)}, update_modified=False)
	return 1


def _keyword(conversation, body):
	"""STOP / START from the customer. A failure here must never lose the stored message."""
	try:
		parties.handle_keyword(conversation, body)
	except Exception:
		frappe.log_error(title="Waba: handling STOP / START failed")


def _campaign_reply(conversation):
	"""A customer who wrote back after a campaign message is counted as having replied. Never loses the stored message."""
	try:
		from waba import campaign_engine

		campaign_engine.on_inbound(conversation)
	except Exception:
		frappe.log_error(title="Waba: attributing a reply to a campaign failed")


def _bot(conversation, message):
	"""Let a bot take this message if one should. It only decides and queues the work (nothing is sent here). Never loses the stored message."""
	try:
		from waba import bot

		bot.on_inbound(conversation, message)
	except Exception:
		frappe.log_error(title="Waba: starting a bot failed")


def _route(conversation, body):
	"""Give the conversation to someone by the number's rules. A failure here must never lose the stored message."""
	try:
		assignment.assign(conversation, body)
	except Exception:
		frappe.log_error(title="Waba: assigning a conversation failed")


# A database unique-key clash on a field (conversation_key, message_id) raises UniqueValidationError; a clash on the
# record's name raises DuplicateEntryError. Either means "someone else just created it".
_CLASH = (frappe.DuplicateEntryError, frappe.UniqueValidationError)


def _find(key):
	return frappe.db.get_value("Waba Conversation", {"conversation_key": key}, "name")


def _fresh_snapshot():
	"""Start a new database snapshot, so a row another worker committed a moment ago can be seen (REPEATABLE READ would
	keep showing the old state). Skipped in a check script that wraps its work in a savepoint it rolls back."""
	if not frappe.flags.get("waba_no_commit"):
		frappe.db.commit()  # nosemgrep


def _conversation(key, number, m, party=None):
	"""The conversation for this customer and number, created once even when two deliveries from a new customer arrive in the
	same second (two workers). One worker at a time creates it; a loser that still hits the unique key reads the winner's row
	with a locking read, because its own transaction snapshot may predate the winner's commit.
	`party` is (doctype, name) when the caller already knows the record (an automatic notification): the conversation is
	then created Matched to it; an existing one without a record gets it."""
	name = _find(key)
	if name:
		return _with_party(frappe.get_doc("Waba Conversation", name), party)
	with locks.conversation(f"create:{key}"):
		_fresh_snapshot()
		name = _find(key)
		if name:
			return _with_party(frappe.get_doc("Waba Conversation", name), party)
		try:
			return frappe.get_doc(
				{
					"doctype": "Waba Conversation",
					"conversation_key": key,
					"waba_number": number,
					"customer_phone": m["phone"],
					"customer_bsuid": m["bsuid"],
					"profile_name": m["profile_name"],
					"customer_label": inbound.customer_label(m["profile_name"], m["phone"], m["bsuid"]),
					"match_state": "Matched" if party else "Triage",
					"party_doctype": party[0] if party else None,
					"party": party[1] if party else None,
					"status": "Open",
					"unread_count": 0,
				}
			).insert(ignore_permissions=True)
		except _CLASH:
			name = frappe.db.get_value("Waba Conversation", {"conversation_key": key}, "name", for_update=True)
			if not name:
				raise
			return _with_party(frappe.get_doc("Waba Conversation", name), party)


def _with_party(conversation, party):
	"""A conversation known only by phone gets the record the caller matched it to."""
	if party and not conversation.party:
		frappe.db.set_value("Waba Conversation", conversation.name, {"party_doctype": party[0], "party": party[1], "match_state": "Matched"}, update_modified=False)
		conversation.reload()
	return conversation


def _update_conversation(conversation, m, sent_at, portfolio):
	values = {
		"last_message_at": sent_at,
		"last_message_preview": inbound.preview(m["body"]),
		"unread_count": (conversation.unread_count or 0) + 1,
		"status": "Open",  # a new customer message reopens a finished conversation
	}
	# the window only moves forward (a late-arriving old message must not shorten it)
	last = conversation.last_inbound_at
	if not last or sent_at > last:
		values["last_inbound_at"] = sent_at
		values["window_expires_at"] = window.window_expires_at(sent_at)
	for field, source in (("customer_phone", "phone"), ("customer_bsuid", "bsuid"), ("profile_name", "profile_name")):
		if m[source] and not conversation.get(field):
			values[field] = m[source]
	values["customer_label"] = inbound.customer_label(
		values.get("profile_name") or conversation.profile_name,
		values.get("customer_phone") or conversation.customer_phone,
		values.get("customer_bsuid") or conversation.customer_bsuid,
	)

	party = None
	if conversation.match_state != "Matched":
		party = matching.find_party(m["phone"] or conversation.customer_phone, m["bsuid"] or conversation.customer_bsuid, portfolio)
		if party:
			values.update({"match_state": "Matched", "party_doctype": party[0], "party": party[1]})
	else:
		party = (conversation.party_doctype, conversation.party)
	matching.remember_identity(portfolio, m["bsuid"], m["phone"], m["profile_name"], party)
	frappe.db.set_value("Waba Conversation", conversation.name, values, update_modified=False)
	conversation.update(values)


def _when(epoch):
	"""Message time in the site's timezone; the arrival time when Meta sent none."""
	if not epoch:
		return now_datetime()
	return convert_utc_to_system_timezone(datetime.datetime.fromtimestamp(epoch, tz=datetime.timezone.utc)).replace(tzinfo=None)
