"""WhatsApp voice calls (Meta's Business Calling API), the pure rules (no Frappe, tested offline).

What Meta sends in the `calls` webhook field, as far as its documentation says (the exact field names are UNVERIFIED against a
live call, so every reader below is tolerant and ignores what it does not know):
  value.calls[]    {id, from, to, event, direction, timestamp, session: {sdp_type, sdp}, status, start_time, end_time, duration}
                   event: connect (a customer is calling; session.sdp is Meta's OFFER, or the answer to our own outgoing offer),
                   terminate (the call ended: status COMPLETED or FAILED, duration only if it was picked up),
                   call_recording_available (audio of a recorded call), call_transcription_available
  value.statuses[] {id, type: "call", status: RINGING | ACCEPTED | REJECTED, recipient_id, timestamp}  (progress of OUR outgoing call)
  value.contacts[] the caller's name and number or user id, as for a message
direction is USER_INITIATED (the customer calls us) or BUSINESS_INITIATED (we call the customer).
"""

import datetime

CALLS_FIELD = "calls"

USER_INITIATED, BUSINESS_INITIATED = "USER_INITIATED", "BUSINESS_INITIATED"
INCOMING, OUTGOING = "Incoming", "Outgoing"

RINGING, ANSWERED, COMPLETED, MISSED, NO_ANSWER, REJECTED, FAILED, CANCELLED = (
	"Ringing", "Answered", "Completed", "Missed", "No answer", "Rejected", "Failed", "Cancelled",
)
STATUSES = (RINGING, ANSWERED, COMPLETED, MISSED, NO_ANSWER, REJECTED, FAILED, CANCELLED)
FINISHED = (COMPLETED, MISSED, NO_ANSWER, REJECTED, FAILED, CANCELLED)

# Who rings (Waba Settings > Calls). The assigned agent and the Team Leads over the number is the default.
RING_ASSIGNED_AND_LEADS = "Assigned agent and Team Leads"
RING_ASSIGNED = "Assigned agent only"
RING_EVERYONE = "Every available call-taker"
RING_LEADS = "Team Leads only"
RING_MODES = (RING_ASSIGNED_AND_LEADS, RING_ASSIGNED, RING_EVERYONE, RING_LEADS)
DEFAULT_RING_SECONDS = 30  # Meta gives the business about 30 to 60 seconds to answer

# Meta's limits for calling a customer
PERMISSION_REQUESTS_PER_DAY = 1
PERMISSION_REQUESTS_PER_WEEK = 2
CONNECTED_CALLS_PER_DAY = 100
UNANSWERED_BEFORE_REVOKE = 4
TEMPORARY_PERMISSION_DAYS = 7

PERMISSION_NONE, PERMISSION_TEMPORARY, PERMISSION_PERMANENT, PERMISSION_DECLINED = "None", "Temporary", "Permanent", "Declined"

MAX_SDP = 60_000
RECORDING_PURPOSE = "Quality and training: this call is recorded by Splashjet."


def _int(value):
	try:
		return int(value)
	except (TypeError, ValueError):
		return None


def clean_sdp(sdp):
	"""(sdp, problem). An SDP is plain text starting with v=0; anything else is refused before it goes to Meta or a browser."""
	if not isinstance(sdp, str):
		return None, "The call description is missing."
	text = sdp.replace("\r\n", "\n").strip()
	if not text.startswith("v=0") or len(text) > MAX_SDP or "\x00" in text:
		return None, "The call description is not valid."
	return "\r\n".join(text.split("\n")) + "\r\n", None


def phone_of(value):
	"""'+<digits>' for a plain-digits number Meta sends, else None (a user id such as IN.123 is never a phone)."""
	from waba.rules.phone import e164

	text = str(value or "").strip()
	if not text or any(ch.isalpha() or ch == "." for ch in text):
		return None
	return e164(text)


def bsuid_of(*values):
	for value in values:
		text = str(value or "").strip()
		if text and any(ch.isalpha() or ch == "." for ch in text):
			return text
	return None


def parse_calls(value):
	"""One dict per call event of a `calls` change value. The customer is the party that is not our number."""
	if not isinstance(value, dict):
		return []
	contacts = [c for c in (value.get("contacts") or []) if isinstance(c, dict)]
	business = str((value.get("metadata") or {}).get("display_phone_number") or "").lstrip("+")
	out = []
	for call in value.get("calls") or []:
		if not isinstance(call, dict) or not call.get("id"):
			continue
		direction = str(call.get("direction") or "").upper() or USER_INITIATED
		sender, receiver = call.get("from"), call.get("to")
		customer_raw = receiver if direction == BUSINESS_INITIATED else sender
		if business and str(customer_raw or "").lstrip("+") == business:
			customer_raw = sender if customer_raw == receiver else receiver
		contact = next((c for c in contacts if customer_raw and customer_raw in (c.get("wa_id"), c.get("user_id"))), contacts[0] if len(contacts) == 1 else {})
		profile = contact.get("profile") if isinstance(contact.get("profile"), dict) else {}
		session = call.get("session") if isinstance(call.get("session"), dict) else {}
		out.append(
			{
				"call_id": str(call["id"]),
				"event": str(call.get("event") or "").lower(),
				"direction": direction,
				"phone": phone_of(customer_raw) or phone_of(contact.get("wa_id")),
				"bsuid": bsuid_of(customer_raw, call.get("from_user_id"), call.get("to_user_id"), contact.get("user_id")),
				"profile_name": profile.get("name"),
				"timestamp": _int(call.get("timestamp")),
				"sdp_type": str(session.get("sdp_type") or "").lower() or None,
				"sdp": session.get("sdp") if isinstance(session.get("sdp"), str) else None,
				"status": str(call.get("status") or "").upper() or None,
				"start_time": _int(call.get("start_time")),
				"end_time": _int(call.get("end_time")),
				"duration": _int(call.get("duration")),
				"recording": _recording(call),
				"payload": call.get("biz_opaque_callback_data") or call.get("deeplink_payload"),
			}
		)
	return out


def _recording(call):
	"""The recording reference of a call_recording_available event: {"url", "id", "mime"} or None. Meta's shape (read 18 Nov 2026):
	call_recording: {type: "audio", audio: {id, sha256, mime_type, url}}; the url lives about 5 minutes, the audio 7 days."""
	holder = call.get("call_recording") if isinstance(call.get("call_recording"), dict) else {}
	part = holder.get("audio") if isinstance(holder.get("audio"), dict) else call.get("recording") if isinstance(call.get("recording"), dict) else {}
	url = part.get("url") or part.get("download_url")
	identifier = part.get("id") or part.get("media_id")
	if not url and not identifier:
		return None
	mime = str(part.get("mime_type") or part.get("content_type") or "audio/ogg").split(";")[0].strip()
	return {"url": url, "id": str(identifier) if identifier else None, "mime": mime, "sha256": part.get("sha256")}


def parse_call_statuses(value):
	"""Progress reports of OUR outgoing calls: [{call_id, status RINGING|ACCEPTED|REJECTED, phone, timestamp}]."""
	out = []
	for item in (value.get("statuses") or []) if isinstance(value, dict) else []:
		if isinstance(item, dict) and str(item.get("type") or "").lower() == "call" and item.get("id"):
			out.append({"call_id": str(item["id"]), "status": str(item.get("status") or "").upper(), "phone": phone_of(item.get("recipient_id")), "timestamp": _int(item.get("timestamp"))})
	return out


def direction_label(direction):
	return OUTGOING if str(direction or "").upper() == BUSINESS_INITIATED else INCOMING


def status_after_terminate(current, direction, meta_status, duration):
	"""The final status when Meta reports that a call ended. A call that was picked up is Completed; one nobody picked up is Missed
	(incoming) or No answer (outgoing); Meta's FAILED stays Failed unless the call had been answered."""
	answered = current == ANSWERED or bool(duration)
	outgoing = direction_label(direction) == OUTGOING
	if current == REJECTED:
		return REJECTED
	if answered:
		return COMPLETED
	if str(meta_status or "").upper() == "FAILED" and current != RINGING:
		return FAILED
	if current in (CANCELLED,):
		return CANCELLED
	return NO_ANSWER if outgoing else MISSED


def status_after_progress(current, meta_status):
	"""Our outgoing call's progress: ACCEPTED means the customer picked up."""
	if current in FINISHED:
		return current
	return {"RINGING": RINGING, "ACCEPTED": ANSWERED, "REJECTED": REJECTED}.get(str(meta_status or "").upper(), current)


def can_accept(status):
	return status == RINGING


def ring_recipients(mode, assignee, overseers, takers, available=None):
	"""Who should ring for an incoming call, in the order they ring.
	assignee   the user the chat is assigned to, or None
	overseers  the Team Leads and Waba Admins over the number (told anyway)
	takers     users allowed to take calls on this number (the per-agent switch)
	available  users who are Available now (None = do not filter)
	The assigned agent and the Team Leads must be call-takers or Team Leads to ring; a Team Lead always rings in the modes that name Team Leads."""
	takers, overseers = set(takers or ()), set(overseers or ())
	ok = lambda user: user and (available is None or user in available)  # noqa: E731
	mode = mode if mode in RING_MODES else RING_ASSIGNED_AND_LEADS
	people = []
	if mode in (RING_ASSIGNED_AND_LEADS, RING_ASSIGNED) and assignee and assignee in takers and ok(assignee):
		people.append(assignee)
	if mode in (RING_ASSIGNED_AND_LEADS, RING_LEADS):
		people += sorted(u for u in overseers if u not in people)
	if mode == RING_EVERYONE:
		people += sorted(u for u in takers if ok(u) and u not in people)
		people += sorted(u for u in overseers if u not in people)
	return people


def permission_state(grants, now):
	"""The customer's calling permission now: (state, until). `grants` is {"response": "accept"|"reject", "permanent": bool,
	"expires": datetime or None, "at": datetime} of the latest reply, or None."""
	if not grants:
		return PERMISSION_NONE, None
	if str(grants.get("response") or "").lower() != "accept":
		return PERMISSION_DECLINED, None
	if grants.get("permanent"):
		return PERMISSION_PERMANENT, None
	until = grants.get("expires") or (grants["at"] + datetime.timedelta(days=TEMPORARY_PERMISSION_DAYS) if grants.get("at") else None)
	if until and until > now:
		return PERMISSION_TEMPORARY, until
	return PERMISSION_NONE, None


def may_request_permission(state, requests, now):
	"""(ok, reason). `requests` are the times we asked this customer. Meta allows 1 request in 24 hours and 2 in 7 days, and none
	while a permission is in force."""
	if state in (PERMISSION_TEMPORARY, PERMISSION_PERMANENT):
		return False, "This customer has already allowed calls."
	day = [t for t in requests if now - t < datetime.timedelta(hours=24)]
	week = [t for t in requests if now - t < datetime.timedelta(days=7)]
	if len(day) >= PERMISSION_REQUESTS_PER_DAY:
		return False, "A call request was already sent in the last 24 hours. Meta allows one a day."
	if len(week) >= PERMISSION_REQUESTS_PER_WEEK:
		return False, "Two call requests were sent this week. Meta allows two in 7 days."
	return True, ""


def may_place_call(state, connected_last_24h, unanswered_in_a_row):
	"""(ok, reason) before an outgoing call: permission in force, under 100 connected calls a day, not revoked by unanswered calls."""
	if state not in (PERMISSION_TEMPORARY, PERMISSION_PERMANENT):
		return False, "This customer has not allowed calls yet. Ask for permission first."
	if unanswered_in_a_row >= UNANSWERED_BEFORE_REVOKE:
		return False, "This customer did not answer the last calls, so Meta has withdrawn the permission. Ask again."
	if connected_last_24h >= CONNECTED_CALLS_PER_DAY:
		return False, "Meta allows 100 connected calls a day to one customer."
	return True, ""


def duration_text(seconds):
	seconds = int(seconds or 0)
	minutes, secs = divmod(seconds, 60)
	return f"{minutes}m {secs:02d}s" if minutes else f"{secs}s"


def event_line(direction, status, who, seconds):
	"""The sentence on the chat timeline."""
	kind = "Incoming" if direction_label(direction) == INCOMING else "Outgoing"
	if status == COMPLETED:
		return f"{kind} call {'answered' if kind == 'Incoming' else 'with the customer'}" + (f" by {who}" if who else "") + f", {duration_text(seconds)}."
	if status == MISSED:
		return "Missed call."
	if status == NO_ANSWER:
		return "Outgoing call: the customer did not answer."
	if status == REJECTED:
		return f"{kind} call declined."
	if status == FAILED:
		return f"{kind} call failed."
	if status == CANCELLED:
		return f"{kind} call cancelled."
	return f"{kind} call."


def call_log_values(call):
	"""The ERP Call Log values of a finished call (a plain dict; splinh fills in the record link and source)."""
	outgoing = direction_label(call.get("direction")) == OUTGOING
	status = {COMPLETED: "Completed", MISSED: "No Answer", NO_ANSWER: "No Answer", REJECTED: "Busy", FAILED: "Failed", CANCELLED: "No Answer"}.get(call.get("status"), "Completed")
	return {
		"id": "WABA-" + str(call.get("call_id")),
		"type": "Outgoing" if outgoing else "Incoming",
		"status": status,
		"duration": int(call.get("duration") or 0),
		"phone": call.get("phone"),
		"start_time": call.get("started_at"),
		"end_time": call.get("ended_at"),
	}


def recording_request(language="en_US", purpose=RECORDING_PURPOSE):
	"""The `recording` object sent with accept/connect so Meta records the call (it plays its own announcement to both people)."""
	return {"status": "ENABLED", "purpose": str(purpose)[:250], "announcement_language": language}


# ------------------------------------------------------------------------------------------------ calling a customer

PERMISSION_TEXT = "Splashjet would like to call you on WhatsApp. Allow calls?"
MAX_REQUEST_TEXT = 200  # Meta gives no limit for the request text; kept short on purpose


def permission_request_payload(phone, text=PERMISSION_TEXT):
	"""The free-form call permission request (only inside an open 24-hour window). Only the body text can be changed."""
	body = " ".join(str(text or PERMISSION_TEXT).split())[:MAX_REQUEST_TEXT]
	return {
		"messaging_product": "whatsapp",
		"recipient_type": "individual",
		"to": str(phone or "").lstrip("+"),
		"type": "interactive",
		"interactive": {"type": "call_permission_request", "action": {"name": "call_permission_request"}, "body": {"text": body}},
	}


def parse_permission_reply(message):
	"""The customer's answer to a call request, from one inbound message: {"response", "permanent", "expires", "source"} or None.
	Shape: message.interactive = {type: "call_permission_reply", call_permission_reply: {response: accept|reject, is_permanent,
	expiration_timestamp (unix seconds, temporary accept only), response_source: user_action|automatic}}."""
	interactive = message.get("interactive") if isinstance(message, dict) and isinstance(message.get("interactive"), dict) else None
	if not interactive or interactive.get("type") != "call_permission_reply":
		return None
	reply = interactive.get("call_permission_reply") if isinstance(interactive.get("call_permission_reply"), dict) else {}
	response = str(reply.get("response") or "").lower()
	if response not in ("accept", "reject"):
		return None
	return {"response": response, "permanent": bool(reply.get("is_permanent")), "expires": _int(reply.get("expiration_timestamp")), "source": reply.get("response_source")}


def permission_reply_text(reply):
	"""The words shown in the chat for a permission reply."""
	if not reply or reply["response"] != "accept":
		return "Declined WhatsApp calls."
	return "Allowed WhatsApp calls (no time limit)." if reply["permanent"] else "Allowed WhatsApp calls for 7 days."


def connect_call_id(response):
	"""The id of the call Meta started for an outgoing `connect`: {"calls": [{"id": "wacid..."}]}. None when missing."""
	items = response.get("calls") if isinstance(response, dict) else None
	first = items[0] if isinstance(items, list) and items and isinstance(items[0], dict) else {}
	return str(first["id"]) if first.get("id") else None


def parse_permission_status(response):
	"""Meta's answer to GET call_permissions as {"status": no_permission|temporary|permanent, "expires": unix or None, "can_call": bool,
	"can_request": bool, "limits": [...]}."""
	response = response if isinstance(response, dict) else {}
	permission = response.get("permission") if isinstance(response.get("permission"), dict) else {}
	actions = {a.get("action_name"): a for a in (response.get("actions") or []) if isinstance(a, dict)}
	return {
		"status": str(permission.get("status") or "no_permission").lower(),
		"expires": _int(permission.get("expiration_time")),
		"can_call": bool((actions.get("start_call") or {}).get("can_perform_action")),
		"can_request": bool((actions.get("send_call_permission_request") or {}).get("can_perform_action")),
		"limits": (actions.get("start_call") or {}).get("limits") or [],
	}


def why_not_call(status):
	"""A plain sentence for a customer we cannot call now (from parse_permission_status)."""
	if status["can_call"]:
		return ""
	if status["status"] == "no_permission":
		return "This customer has not allowed calls yet. Ask for permission first."
	return "Meta does not allow a call to this customer right now (a daily limit may be reached)."


# ------------------------------------------------------------------------------------------------ how a caller is named


def clean_name(name):
	"""A WhatsApp profile name worth showing: one with at least one letter or digit ("." or "-" are not names). None otherwise."""
	text = " ".join(str(name or "").split())
	return text if any(ch.isalnum() for ch in text) else None


def caller_label(profile_name=None, party_name=None, phone=None, bsuid=None):
	"""Who is calling, for popups, alerts and chat lines: the record's name, else a real WhatsApp name, else the phone, else the user id."""
	return clean_name(party_name) or clean_name(profile_name) or (phone or None) or (bsuid or None) or "an unknown number"
