"""Store what customers send: one Conversation per (business number, customer), one Message per WhatsApp message.

Called by waba.api.webhook.process_event with the `value` of a `messages` change. Idempotent: a message id is stored
once however many times Meta re-sends it, and a second worker creating the same conversation at the same moment
loses cleanly to the unique key. Sender matching, the 24-hour window and assignment (waba.assignment) are applied here.
"""

import datetime

import frappe
from frappe.utils import convert_utc_to_system_timezone, now_datetime

from waba import assignment, matching, parties
from waba.rules import inbound, window


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
		if frappe.db.exists("Waba Message", {"message_id": m["message_id"]}):
			counts["duplicates"] += 1
			continue
		conversation = _conversation(key, number, m)
		sent_at = _when(m["timestamp"])
		try:
			frappe.get_doc(
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
				}
			).insert(ignore_permissions=True)
		except frappe.DuplicateEntryError:
			counts["duplicates"] += 1
			continue
		_update_conversation(conversation, m, sent_at, portfolio)
		counts["stored"] += 1
		_keyword(conversation, m["body"])
		_route(conversation, m["body"])
		assignment.notify(conversation, "message")
	return counts


def _keyword(conversation, body):
	"""STOP / START from the customer. A failure here must never lose the stored message."""
	try:
		parties.handle_keyword(conversation, body)
	except Exception:
		frappe.log_error(title="Waba: handling STOP / START failed")


def _route(conversation, body):
	"""Give the conversation to someone by the number's rules. A failure here must never lose the stored message."""
	try:
		assignment.assign(conversation, body)
	except Exception:
		frappe.log_error(title="Waba: assigning a conversation failed")


def _conversation(key, number, m):
	name = frappe.db.get_value("Waba Conversation", {"conversation_key": key}, "name")
	if name:
		return frappe.get_doc("Waba Conversation", name)
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
				"match_state": "Triage",
				"status": "Open",
				"unread_count": 0,
			}
		).insert(ignore_permissions=True)
	except frappe.DuplicateEntryError:
		return frappe.get_doc("Waba Conversation", frappe.db.get_value("Waba Conversation", {"conversation_key": key}, "name"))


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
