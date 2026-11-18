"""WhatsApp voice calls, the Frappe side: store Meta's `calls` events as Waba Call rows, ring the right people, let exactly one of them take
the call, finish it, alert on a missed call, fetch the recording, and tell the ERP's call log.

Browser-direct design: Meta's SDP offer waits in the cache for two minutes and the agent's browser fetches it (waba.api.calls.offer);
the browser makes the WebRTC answer and Waba relays pre_accept / accept to Meta. Audio never passes through the ERP server.
The decisions (statuses, who rings, Meta's limits) are in waba.rules.calls (tested offline). Nothing here dials a customer."""

import datetime

import frappe
from frappe import _
from frappe.utils import add_to_date, convert_utc_to_system_timezone, cint, now_datetime

from waba import assignment, locks, matching, teams
from waba.meta import graph
from waba.rules import calls as rules

OFFER_SECONDS = 120
RECORDING_LINK_SECONDS = 240  # Meta's download link lives about 5 minutes: retry only inside it
RECORDING_TRIES = 3
SWEEP_GRACE = 30  # seconds past the ring time before a call nobody ended is closed here


# ------------------------------------------------------------------------------------------------ settings and people


def has_fields():
	"""False until the migrate that adds the calling fields has run (new code before the migrate: nothing happens, nothing rings)."""
	return frappe.get_meta("Waba Settings").has_field("calls_enabled") and frappe.db.table_exists("Waba Call")


def listen_only_on():
	"""Waba Settings > Allow calls without a microphone: ON until someone chooses otherwise (an unsaved Single field has no stored row)."""
	if not frappe.get_meta("Waba Settings").has_field("call_listen_only"):
		return True
	rows = frappe.db.sql("select `value` from `tabSingles` where `doctype` = 'Waba Settings' and `field` = 'call_listen_only'")
	stored = rows[0][0] if rows else None
	return True if stored is None else bool(cint(stored))


def enabled():
	return has_fields() and bool(cint(frappe.db.get_single_value("Waba Settings", "calls_enabled")))


def _ring_mode():
	return frappe.db.get_single_value("Waba Settings", "call_ring_mode") or rules.RING_ASSIGNED_AND_LEADS


def _ring_seconds():
	return max(10, cint(frappe.db.get_single_value("Waba Settings", "call_ring_seconds")) or rules.DEFAULT_RING_SECONDS)


def takers(number):
	"""({users who may take calls}, {users who are Available}) on this number."""
	rows = frappe.get_all("Waba Agent Access", filters={"parent": number}, fields=["user", "available", "may_take_calls"], parent_doctype="Waba Number")
	enabled_users = set(frappe.get_all("User", filters={"enabled": 1, "name": ["in", [r.user for r in rows] or [""]]}, pluck="name"))
	return (
		{r.user for r in rows if r.may_take_calls and r.user in enabled_users},
		{r.user for r in rows if r.available and r.user in enabled_users},
	)


def ring_list(number, conversation=None):
	"""Who rings for a call on `number`, in the configured mode."""
	assignee = frappe.db.get_value("Waba Conversation", conversation, "assigned_to") if conversation else None
	can_take, available = takers(number)
	overseers = teams.number_overseers(number, None)
	return rules.ring_recipients(_ring_mode(), assignee, overseers, can_take, available | set(overseers))


def may_hear(call, user):
	"""May `user` take or end this call: they were rung, or they are an admin."""
	if teams.is_admin(user):
		return True
	return user in set(filter(None, (call.ring_recipients or "").split(", ")))


# ------------------------------------------------------------------------------------------------ the webhook


def handle_changes(payload, account, event):
	"""Every `calls` change of a delivery. Returns the notes for the stored event."""
	notes, made, finished, other, unknown = [], 0, 0, 0, set()
	if not has_fields():
		return notes
	for entry in payload.get("entry") or []:
		for change in (entry.get("changes") or []) if isinstance(entry, dict) else []:
			value = change.get("value") if isinstance(change, dict) and isinstance(change.get("value"), dict) else None
			if not value or change.get("field") != rules.CALLS_FIELD:
				continue
			phone_number_id = str((value.get("metadata") or {}).get("phone_number_id") or "")
			number = frappe.db.get_value("Waba Number", {"phone_number_id": phone_number_id, "account": account}, "name") if phone_number_id else None
			if not number:
				unknown.add(phone_number_id)
				continue
			for ev in rules.parse_calls(value):
				kind = ev["event"]
				if kind == "connect" and ev["direction"] == rules.USER_INITIATED:
					made += 1 if _incoming(number, ev, event) else 0
				elif kind == "connect":
					_outgoing_answer(ev)
					other += 1
				elif kind == "terminate":
					finished += 1 if _finish(ev) else 0
				elif kind == "call_recording_available":
					_recording_ready(ev)
					other += 1
				else:
					other += 1
			for item in rules.parse_call_statuses(value):
				_progress(item)
				other += 1
	if made:
		notes.append(f"{made} incoming call(s) stored.")
	if finished:
		notes.append(f"{finished} call(s) ended.")
	if other:
		notes.append(f"{other} other call update(s) applied.")
	if unknown:
		notes.append("Number not set up yet (run Sync numbers on the account): " + ", ".join(sorted(unknown)) + ".")
	return notes


def _when(epoch):
	if not epoch:
		return now_datetime()
	return convert_utc_to_system_timezone(datetime.datetime.fromtimestamp(epoch, tz=datetime.timezone.utc)).replace(tzinfo=None)


def _portfolio(number):
	account = frappe.db.get_value("Waba Number", number, "account")
	return frappe.db.get_value("Waba Account", account, "portfolio") if account else None


def _incoming(number, ev, event):
	"""A customer is calling. Stores the call, keeps the offer for the browser and rings. False when we already know this call."""
	if frappe.db.exists("Waba Call", {"call_id": ev["call_id"]}):
		return False
	party = matching.find_party(ev["phone"], ev["bsuid"], _portfolio(number)) if (ev["phone"] or ev["bsuid"]) else None
	conversation = None
	key = f"{number}|{ev['phone'] or ev['bsuid']}" if (ev["phone"] or ev["bsuid"]) else None
	if key:
		conversation = frappe.db.get_value("Waba Conversation", {"conversation_key": key}, "name")
	if not conversation and party:
		conversation = _open_conversation(number, key, ev, party)
	doc = frappe.get_doc(
		{
			"doctype": "Waba Call",
			"call_id": ev["call_id"],
			"waba_number": number,
			"direction": rules.INCOMING,
			"status": rules.RINGING,
			"caller_phone": ev["phone"],
			"caller_bsuid": ev["bsuid"],
			"caller_name": ev["profile_name"],
			"party_doctype": party[0] if party else None,
			"party": party[1] if party else None,
			"conversation": conversation,
			"started_at": _when(ev["timestamp"]),
		}
	).insert(ignore_permissions=True)
	if ev["sdp"]:
		frappe.cache.set_value(_offer_key(doc.name), ev["sdp"], expires_in_sec=OFFER_SECONDS)
	_remember_customer_call(conversation)
	recipients = ring_list(number, conversation) if enabled() else []
	frappe.db.set_value("Waba Call", doc.name, "ring_recipients", ", ".join(recipients) or None, update_modified=False)
	for user in recipients:
		_publish(user, "ring", doc, seconds=_ring_seconds())
	return True


def _open_conversation(number, key, ev, party):
	"""A known customer who never wrote gets a conversation (Matched, nobody assigned, nothing unread) so the call has a home.
	An unknown caller gets none: only the call itself is kept."""
	from waba import inbound

	try:
		conversation = inbound._conversation(key, number, {"phone": ev["phone"], "bsuid": ev["bsuid"], "profile_name": ev["profile_name"]}, party)
		return conversation.name
	except Exception:
		frappe.log_error(title="Waba: opening a conversation for a call failed")
		return None


def _remember_customer_call(conversation):
	"""A customer's own call gives the business temporary permission to call back (Meta, when callback permission is on)."""
	if not conversation or not frappe.get_meta("Waba Conversation").has_field("call_permission"):
		return
	now = now_datetime()
	current = frappe.db.get_value("Waba Conversation", conversation, "call_permission")
	if current == rules.PERMISSION_PERMANENT:
		return
	frappe.db.set_value(
		"Waba Conversation", conversation,
		{"call_permission": rules.PERMISSION_TEMPORARY, "call_permission_until": add_to_date(now, days=rules.TEMPORARY_PERMISSION_DAYS)},
		update_modified=False,
	)


def _outgoing_answer(ev):
	"""Meta's answer to an outgoing call (Stage 3 places them): the browser that placed it takes the answer."""
	call = frappe.db.get_value("Waba Call", {"call_id": ev["call_id"]}, ["name", "started_by"], as_dict=True)
	if call and ev["sdp"]:
		frappe.cache.set_value(_answer_key(call.name), ev["sdp"], expires_in_sec=OFFER_SECONDS)
		if call.started_by:
			frappe.publish_realtime("waba_call", {"call": call.name, "kind": "answer"}, user=call.started_by, after_commit=True)


def _progress(item):
	name = frappe.db.get_value("Waba Call", {"call_id": item["call_id"]}, ["name", "status", "direction"], as_dict=True)
	if not name:
		return
	new = rules.status_after_progress(name.status, item["status"])
	if new != name.status:
		values = {"status": new, "meta_status": item["status"]}
		if new == rules.ANSWERED:
			values["answered_at"] = _when(item["timestamp"])
		frappe.db.set_value("Waba Call", name.name, values, update_modified=False)
		_publish_to_call(name.name, "progress")


def _finish(ev):
	"""Meta says the call ended."""
	row = frappe.db.get_value("Waba Call", {"call_id": ev["call_id"]}, ["name", "status", "direction", "conversation", "waba_number", "answered_by"], as_dict=True)
	if not row or row.status in rules.FINISHED:
		return False
	direction = ev["direction"] or (rules.BUSINESS_INITIATED if row.direction == rules.OUTGOING else rules.USER_INITIATED)
	status = rules.status_after_terminate(row.status, direction, ev["status"], ev["duration"])
	ended = _when(ev["end_time"] or ev["timestamp"])
	frappe.db.set_value(
		"Waba Call", row.name,
		{"status": status, "ended_at": ended, "duration": ev["duration"] or 0, "meta_status": ev["status"],
		 "recording_status": None if status != rules.COMPLETED else (frappe.db.get_value("Waba Call", row.name, "recording_status") or "Waiting")},
		update_modified=False,
	)
	frappe.cache.delete_value(_offer_key(row.name))
	_publish_to_call(row.name, "ended")
	call = frappe.get_doc("Waba Call", row.name)
	_timeline(call)
	if status in (rules.MISSED,):
		_missed(call)
	_tell_erp(call)
	return True


def _timeline(call):
	if not call.conversation:
		return
	who = frappe.utils.get_fullname(call.answered_by) if call.answered_by else None
	assignment.add_event(call.conversation, rules.event_line(call.direction == rules.OUTGOING and rules.BUSINESS_INITIATED or rules.USER_INITIATED, call.status, who, call.duration))
	assignment.notify(call.conversation, "call")


def _missed(call):
	"""A missed call: a toast on the screen of everyone who was rung (and the Team Leads), and a Notification Log for the Team Leads."""
	who = label_of(call)
	rung = set(filter(None, (call.ring_recipients or "").split(", "))) | set(teams.number_overseers(call.waba_number, None))
	for user in rung:
		_publish(user, "missed", call, status=call.status)
	for user in teams.number_overseers(call.waba_number, None):
		frappe.get_doc(
			{
				"doctype": "Notification Log", "for_user": user, "type": "Alert",
				"subject": _("WhatsApp: missed call from {0}").format(who),
				"document_type": "Waba Call", "document_name": call.name,
			}
		).insert(ignore_permissions=True)


def _tell_erp(call):
	"""Let the ERP's call log (an app-supplied hook) know the call is finished. A failure here must never undo the call."""
	for path in frappe.get_hooks("waba_call_ended"):
		try:
			frappe.get_attr(path)(call)
		except Exception:
			frappe.log_error(title="Waba: the call-ended hook failed")


# ------------------------------------------------------------------------------------------------ ringing and answering


def _offer_key(name):
	return f"waba_call_offer|{name}"


def _answer_key(name):
	return f"waba_call_answer|{name}"


def _declined_key(name):
	return f"waba_call_declined|{name}"


def _party_name(party_doctype, party):
	"""The readable name of the matched record (a company or person), not its id."""
	if not party_doctype or not party:
		return None
	meta = frappe.get_meta(party_doctype)
	for field in ("company_name", "customer_name", "lead_name", "full_name", "title"):
		if meta.has_field(field):
			value = frappe.db.get_value(party_doctype, party, field)
			if rules.clean_name(value):
				return value
	return None if party_doctype in ("Lead", "Customer") else party


def label_of(call):
	"""Who is calling, for the popup, the alert and the chat line."""
	return rules.caller_label(call.caller_name, _party_name(call.party_doctype, call.party), call.caller_phone, call.caller_bsuid)


def _publish(user, kind, call, **extra):
	frappe.publish_realtime(
		"waba_call",
		{"call": call.name, "kind": kind, "number": call.waba_number, "phone": call.caller_phone, "name": call.caller_name, "label": label_of(call), "party_doctype": call.party_doctype, "party": call.party, "conversation": call.conversation, "direction": call.direction, **extra},
		user=user, after_commit=True,
	)


def _publish_to_call(name, kind, **extra):
	call = frappe.get_doc("Waba Call", name)
	for user in set(filter(None, (call.ring_recipients or "").split(", "))) | ({call.answered_by} if call.answered_by else set()) | ({call.started_by} if call.started_by else set()):
		_publish(user, kind, call, status=call.status, **extra)


def offer_for(name, user):
	"""Meta's SDP offer for a ringing call, for a person who was rung. Raises when it is not theirs or no longer ringing."""
	call = frappe.get_doc("Waba Call", name)
	if not may_hear(call, user):
		frappe.throw(_("This call did not ring for you."), frappe.PermissionError)
	if call.status != rules.RINGING:
		frappe.throw(_("This call is no longer ringing."))
	sdp = frappe.cache.get_value(_offer_key(name))
	if not sdp:
		frappe.throw(_("This call has ended."))
	return {"sdp": sdp, "sdp_type": "offer", "ring_seconds": _ring_seconds(), "caller": call.caller_name or call.caller_phone, "party_doctype": call.party_doctype, "party": call.party}


def answer(name, sdp, user, client=graph):
	"""`user` takes the call: the first one wins. pre_accept then accept go to Meta with the browser's answer; Meta's recording is asked for.
	Returns {"ok": True} or {"ok": False, "reason": ...}."""
	sdp, problem = rules.clean_sdp(sdp)
	if problem:
		frappe.throw(_(problem))
	with locks.conversation(f"call|{name}"):
		call = frappe.get_doc("Waba Call", name)
		if not may_hear(call, user):
			frappe.throw(_("This call did not ring for you."), frappe.PermissionError)
		if not rules.can_accept(call.status):
			taker = frappe.utils.get_fullname(call.answered_by) if call.answered_by else None
			return {"ok": False, "reason": _("Taken by {0}.").format(taker) if taker else _("This call is no longer ringing.")}
		token, version, phone_number_id = _credentials(call.waba_number)
		try:
			client.call_action(token, phone_number_id, "pre_accept", call_id=call.call_id, sdp=sdp, sdp_type="answer", version=version)
			client.call_action(token, phone_number_id, "accept", call_id=call.call_id, sdp=sdp, sdp_type="answer", recording=_recording_object(), version=version)
		except graph.GraphError as e:
			frappe.db.set_value("Waba Call", name, "error", graph.explain(e)[:140], update_modified=False)
			return {"ok": False, "reason": graph.explain(e)}
		frappe.db.set_value(
			"Waba Call", name,
			{"status": rules.ANSWERED, "answered_by": user, "answered_at": now_datetime(), "recording_status": "Requested"}, update_modified=False,
		)
	for other in set(filter(None, (call.ring_recipients or "").split(", "))) - {user}:
		_publish(other, "taken", call, taken_by=frappe.utils.get_fullname(user))
	return {"ok": True}


def decline(name, user, client=graph):
	"""One person declines. The call keeps ringing for the others; when everybody who was rung has declined, it is rejected at Meta."""
	call = frappe.get_doc("Waba Call", name)
	if not may_hear(call, user) or call.status != rules.RINGING:
		return {"ok": True}
	declined = set(frappe.cache.get_value(_declined_key(name)) or [])
	declined.add(user)
	frappe.cache.set_value(_declined_key(name), list(declined), expires_in_sec=OFFER_SECONDS)
	_publish(user, "dismiss", call)
	rung = set(filter(None, (call.ring_recipients or "").split(", ")))
	if rung and rung <= declined:
		token, version, phone_number_id = _credentials(call.waba_number)
		try:
			client.call_action(token, phone_number_id, "reject", call_id=call.call_id, version=version)
		except graph.GraphError as e:
			frappe.db.set_value("Waba Call", name, "error", graph.explain(e)[:140], update_modified=False)
			return {"ok": False, "reason": graph.explain(e)}
		frappe.db.set_value("Waba Call", name, {"status": rules.REJECTED, "ended_at": now_datetime()}, update_modified=False)
		_timeline(frappe.get_doc("Waba Call", name))
	return {"ok": True}


def hangup(name, user, client=graph):
	"""End a call: the person who has it, a Team Lead or an admin."""
	call = frappe.get_doc("Waba Call", name)
	if call.status not in (rules.ANSWERED, rules.RINGING) or not (call.answered_by == user or call.started_by == user or may_hear(call, user)):
		return {"ok": False, "reason": _("This call is not yours to end.")}
	token, version, phone_number_id = _credentials(call.waba_number)
	try:
		client.call_action(token, phone_number_id, "terminate", call_id=call.call_id, version=version)
	except graph.GraphError as e:
		return {"ok": False, "reason": graph.explain(e)}
	return {"ok": True}


def _recording_object():
	language = frappe.db.get_single_value("Waba Settings", "call_record_language") or "en_US"
	return rules.recording_request(language)


def _credentials(number):
	"""(token, api version, phone number id) for a number, from its account's portfolio."""
	from frappe.utils.password import get_decrypted_password

	from waba.constants import DEFAULT_API_VERSION

	doc = frappe.get_doc("Waba Number", number)
	account = frappe.get_doc("Waba Account", doc.account)
	token = get_decrypted_password("Waba Portfolio", account.portfolio, "access_token", raise_exception=False)
	if not token:
		frappe.throw(_("Save the access token on the portfolio {0} first.").format(account.portfolio))
	return token, account.api_version or DEFAULT_API_VERSION, doc.phone_number_id


def answer_for(name, user):
	"""The browser that placed an outgoing call collects Meta's SDP answer here (None until Meta's answer has arrived)."""
	call = frappe.get_doc("Waba Call", name)
	if call.started_by != user:
		frappe.throw(_("This call is not yours."), frappe.PermissionError)
	sdp = frappe.cache.get_value(_answer_key(name))
	return {"sdp": sdp, "sdp_type": "answer", "status": call.status} if sdp else {"sdp": None, "status": call.status}


# ------------------------------------------------------------------------------------------------ calling a customer


def _caller_row(number, user):
	return frappe.db.get_value("Waba Agent Access", {"parent": number, "parenttype": "Waba Number", "user": user}, ["may_make_calls"], as_dict=True)


def may_place(number, user):
	"""May `user` place WhatsApp calls on this number: marked as a caller on it (Administrator always)."""
	if user == "Administrator":
		return True
	row = _caller_row(number, user)
	return bool(row and row.may_make_calls)


def _conversation_for_call(conversation, user):
	"""The open conversation, checked for visibility, and the number's rules for outgoing calls. Returns (conversation doc, number doc)."""
	conv = frappe.get_doc("Waba Conversation", conversation)
	if not frappe.has_permission("Waba Conversation", "read", doc=conv):
		frappe.throw(_("You may not open this conversation."), frappe.PermissionError)
	number = frappe.get_doc("Waba Number", conv.waba_number)
	if not may_place(number.name, user):
		frappe.throw(_("You are not marked as someone who may place WhatsApp calls."), frappe.PermissionError)
	if number.get("receive_only"):
		frappe.throw(_("This number only receives messages, so it cannot place calls."))
	if number.get("coexistence"):
		frappe.throw(_("A number that is also in the WhatsApp Business app cannot place WhatsApp calls (Meta does not support it)."))
	if not conv.customer_phone:
		frappe.throw(_("This customer has no phone number, so they cannot be called."))
	return conv, number


def can_call(conversation, user, client=graph):
	"""What the Call button needs: {"may": bool, "status", "can_call", "can_request", "reason"}. Asks Meta, because the permission lives there
	(the customer can withdraw it any time)."""
	try:
		conv, number = _conversation_for_call(conversation, user)
	except (frappe.PermissionError, frappe.ValidationError) as e:
		return {"may": False, "reason": str(e).split("\n")[0][:200]}
	token, version, phone_number_id = _credentials(number.name)
	try:
		status = rules.parse_permission_status(client.call_permissions(token, phone_number_id, conv.customer_phone, version))
	except graph.GraphError as e:
		return {"may": True, "status": "unknown", "can_call": False, "can_request": False, "reason": graph.explain(e)}
	return {"may": True, **{k: status[k] for k in ("status", "can_call", "can_request")}, "expires": status["expires"], "reason": rules.why_not_call(status)}


def request_permission(conversation, user, text=None):
	"""Ask the customer to allow calls: a free-form message, only inside the 24-hour window. Stored in the chat like any message we send."""
	from waba.api import send
	from waba.rules import outbound, purposes

	conv, number = _conversation_for_call(conversation, user)
	ctx = send._Context(conversation, purpose=purposes.purpose_for(purposes.PERSON))
	ctx.refuse_if_receive_only()
	ctx.refuse_unless(outbound.check_free_text(text or rules.PERMISSION_TEXT, ctx.conversation.last_inbound_at, now_datetime()))
	ctx.refuse_unless(outbound.check_recipient(ctx.conversation.customer_phone))
	current = can_call(conversation, user)
	if current.get("status") in ("temporary", "permanent") or current.get("can_request") is False and current.get("status") != "unknown":
		frappe.throw(_("A call request cannot be sent now: the customer has already allowed calls, or Meta's limit of one request a day (two a week) is reached."))
	payload = rules.permission_request_payload(ctx.conversation.customer_phone, text)
	result = send._deliver(ctx, payload, {"message_type": "interactive", "body": payload["interactive"]["body"]["text"]}, purposes.PERSON, sent_by=False)
	frappe.db.set_value("Waba Conversation", conversation, "call_permission_asked_at", ((conv.get("call_permission_asked_at") or "") + "\n" + now_datetime().isoformat(sep=" ")).strip()[-400:], update_modified=False)
	return result


def place(conversation, sdp, user, client=graph):
	"""Place an outgoing call with the browser's WebRTC offer. Meta must say we may call this customer right now. Returns {"ok", "call"}."""
	sdp, problem = rules.clean_sdp(sdp)
	if problem:
		frappe.throw(_(problem))
	conv, number = _conversation_for_call(conversation, user)
	token, version, phone_number_id = _credentials(number.name)
	try:
		status = rules.parse_permission_status(client.call_permissions(token, phone_number_id, conv.customer_phone, version))
	except graph.GraphError as e:
		return {"ok": False, "reason": graph.explain(e)}
	if not status["can_call"]:
		return {"ok": False, "reason": _(rules.why_not_call(status)), "need_permission": status["status"] == "no_permission"}
	if frappe.db.exists("Waba Call", {"conversation": conversation, "status": ["in", [rules.RINGING, rules.ANSWERED]]}):
		return {"ok": False, "reason": _("There is already a call in progress with this customer.")}
	try:
		response = client.call_action(token, phone_number_id, "connect", to=conv.customer_phone.lstrip("+"), sdp=sdp, sdp_type="offer", recording=_recording_object(), version=version)
	except graph.GraphError as e:
		return {"ok": False, "reason": graph.explain(e)}
	call_id = rules.connect_call_id(response)
	if not call_id:
		return {"ok": False, "reason": _("Meta did not return a call id.")}
	doc = frappe.get_doc(
		{
			"doctype": "Waba Call", "call_id": call_id, "waba_number": number.name, "direction": rules.OUTGOING, "status": rules.RINGING,
			"caller_phone": conv.customer_phone, "caller_bsuid": conv.customer_bsuid, "caller_name": conv.customer_label or conv.profile_name,
			"party_doctype": conv.party_doctype, "party": conv.party, "conversation": conv.name, "started_at": now_datetime(),
			"started_by": user, "ring_recipients": user, "recording_status": "Requested",
		}
	).insert(ignore_permissions=True)
	return {"ok": True, "call": doc.name}


# ------------------------------------------------------------------------------------------------ the customer's reply to a call request


def apply_permission_reply(conversation, reply):
	"""The customer answered a call request (accept once, accept for good, or decline): keep it on the conversation and say so in the chat."""
	if not conversation or not reply or not frappe.get_meta("Waba Conversation").has_field("call_permission"):
		return
	if reply["response"] != "accept":
		values = {"call_permission": rules.PERMISSION_DECLINED, "call_permission_until": None}
	elif reply["permanent"]:
		values = {"call_permission": rules.PERMISSION_PERMANENT, "call_permission_until": None}
	else:
		until = _when(reply["expires"]) if reply.get("expires") else add_to_date(now_datetime(), days=rules.TEMPORARY_PERMISSION_DAYS)
		values = {"call_permission": rules.PERMISSION_TEMPORARY, "call_permission_until": until}
	frappe.db.set_value("Waba Conversation", conversation, values, update_modified=False)
	assignment.add_event(conversation, rules.permission_reply_text(reply))
	assignment.notify(conversation, "call")


# ------------------------------------------------------------------------------------------------ recording


def _recording_ready(ev):
	"""Meta says the audio of a recorded call can be downloaded (for about 7 days; the link lives a few minutes)."""
	name = frappe.db.get_value("Waba Call", {"call_id": ev["call_id"]}, "name")
	rec = ev.get("recording")
	if not name or not rec:
		return
	frappe.db.set_value("Waba Call", name, {"recording_status": "Waiting"}, update_modified=False)
	frappe.cache.set_value(_recording_key(name), {"url": rec.get("url"), "mime": rec.get("mime"), "tries": 0}, expires_in_sec=RECORDING_LINK_SECONDS)
	frappe.enqueue("waba.calls.download_recording", queue="long", call=name, url=rec.get("url"), mime=rec.get("mime"), enqueue_after_commit=True, job_id=f"waba-rec-{name}", deduplicate=True)


def download_recording(call, url=None, mime=None, client=graph):
	"""Fetch the audio into a private file on the call. A failure is kept on the call and retried by `retry_recordings`."""
	doc = frappe.get_doc("Waba Call", call)
	if doc.recording_status == "Downloaded":
		return
	try:
		if not url or not client.media_host_allowed(url):
			raise client.GraphError("The recording link is missing or not from Meta.")
		token, version, _phone = _credentials(doc.waba_number)
		content = client.download_media(token, url, 60 * 1024 * 1024)
		file = frappe.get_doc(
			{"doctype": "File", "file_name": f"{doc.call_id}.{_extension(mime)}", "attached_to_doctype": "Waba Call", "attached_to_name": doc.name, "content": content, "is_private": 1}
		).insert(ignore_permissions=True)
		frappe.db.set_value("Waba Call", doc.name, {"recording_file": file.file_url, "recording_status": "Downloaded", "recording_error": None}, update_modified=False)
		_tell_erp(frappe.get_doc("Waba Call", doc.name))
	except Exception as e:
		saved = frappe.cache.get_value(_recording_key(doc.name)) or {}
		saved["tries"] = int(saved.get("tries") or 0) + 1
		if url:
			saved.update(url=url, mime=mime)
			frappe.cache.set_value(_recording_key(doc.name), saved, expires_in_sec=RECORDING_LINK_SECONDS)
		frappe.db.set_value("Waba Call", doc.name, {"recording_status": "Failed", "recording_error": str(e)[:140]}, update_modified=False)


def _recording_key(name):
	return f"waba_call_rec|{name}"


def retry_recordings():
	"""Every minute: a download that failed while Meta's link is still alive is tried again (up to three times). After the link expires the
	recording cannot be fetched any more and stays marked Failed with the reason."""
	if not has_fields():
		return 0
	tried = 0
	for name in frappe.get_all("Waba Call", filters={"recording_status": "Failed"}, pluck="name", limit_page_length=50):
		saved = frappe.cache.get_value(_recording_key(name))
		if saved and saved.get("url") and int(saved.get("tries") or 0) < RECORDING_TRIES:
			download_recording(name, saved["url"], saved.get("mime"))
			tried += 1
	if tried and not frappe.flags.get("waba_no_commit"):
		frappe.db.commit()  # nosemgrep
	return tried


def _extension(mime):
	return {"audio/ogg": "ogg", "audio/mpeg": "mp3", "audio/mp4": "m4a", "audio/aac": "aac", "audio/wav": "wav", "audio/webm": "webm"}.get(str(mime or "").split(";")[0].strip().lower(), "ogg")


# ------------------------------------------------------------------------------------------------ scheduled


def expire_stale():
	"""Every minute: a call still Ringing long after it should have ended (the end report never came) is closed as missed, so no
	popup stays and no call is lost from the record."""
	if not has_fields():
		return 0
	cutoff = add_to_date(now_datetime(), seconds=-(_ring_seconds() + SWEEP_GRACE))
	closed = 0
	for name in frappe.get_all("Waba Call", filters={"status": rules.RINGING, "started_at": ["<", cutoff]}, pluck="name", limit_page_length=100):
		_finish({"call_id": frappe.db.get_value("Waba Call", name, "call_id"), "direction": None, "status": None, "duration": 0, "end_time": None, "timestamp": None})
		closed += 1
	if closed and not frappe.flags.get("waba_no_commit"):
		frappe.db.commit()  # nosemgrep
	return closed
