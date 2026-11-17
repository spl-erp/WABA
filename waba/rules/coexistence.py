"""WhatsApp Business app coexistence: the same number used in the phone app and through Waba (no Frappe, tested offline).

What Meta sends for a coexistence number, as far as the documentation says (UNVERIFIED against a live number):
  * field `smb_message_echoes`: a message the business typed in the phone app (or a linked device), edited it, or deleted it.
    `value.message_echoes[]` holds {from: <our number>, to: <customer>, to_user_id, id, timestamp, type, <type>: {...}}; an edit or
    a revoke also carries `original_message_id` (an edit has the new content in a nested `message`).
  * field `account_update`: the link to the phone app changed. `value.event` is PARTNER_REMOVED (disconnected, with
    `disconnection_info`), ACCOUNT_OFFBOARDED (device change or re-registration) or ACCOUNT_RECONNECTED.
  * fields `history` and `smb_app_state_sync`: the one-time history and the contact list. Not imported yet.
Echoes are OUR side of the chat: they are stored as outgoing "Phone app" messages and never run the inbound logic.
"""

ECHO_FIELD = "smb_message_echoes"
ACCOUNT_FIELD = "account_update"
NOT_IMPORTED_FIELDS = ("history", "smb_app_state_sync")

CONNECTED, DISCONNECTED, OFFBOARDED = "Connected", "Disconnected", "Offboarded"

# account_update event -> the state kept on the Waba Number
STATE_OF_EVENT = {
	"PARTNER_REMOVED": DISCONNECTED,
	"ACCOUNT_OFFBOARDED": OFFBOARDED,
	"ACCOUNT_RECONNECTED": CONNECTED,
}

REASON_TEXT = {
	"PRIMARY_INACTIVITY": "the phone app was not opened for about 14 days",
	"COMPANION_INACTIVITY": "a linked device was inactive for about 30 days",
	"CHANGE_NUMBER": "the number was changed",
	"BUSINESS_DOWNGRADE": "the account was downgraded to a normal WhatsApp account",
	"USER_RE_REGISTERED": "the number was registered again",
	"ACCOUNT_DISCONNECTED": "it was disconnected in the phone app",
}


def account_event(value):
	"""(event, state, reason text) of one `account_update` value. state is None for an event we do not track."""
	value = value if isinstance(value, dict) else {}
	event = str(value.get("event") or "").upper()
	info = value.get("disconnection_info") if isinstance(value.get("disconnection_info"), dict) else {}
	reason = str(info.get("reason") or "").upper()
	return event, STATE_OF_EVENT.get(event), REASON_TEXT.get(reason, reason.lower().replace("_", " ") if reason else "")


def state_sentence(event, state, reason):
	"""The plain sentence the overseers and the number's note get."""
	if state == CONNECTED:
		return "The WhatsApp Business app link was restored. Sending works again."
	if state == OFFBOARDED:
		return "The WhatsApp Business app link was reset (device change or re-registration). Sending from Waba pauses until Meta reconnects it" + (f": {reason}." if reason else ".")
	if state == DISCONNECTED:
		return "The WhatsApp Business app was disconnected from Waba" + (f" because {reason}." if reason else ".")
	return f"Meta reported {event or 'an account update'} for this account."


def is_edit_or_revoke(message):
	"""'edit', 'revoke' or None (a new message) for one echo."""
	if not isinstance(message, dict) or not message.get("original_message_id"):
		return None
	return "edit" if isinstance(message.get("message"), dict) else "revoke"


def revoked_body(old_body):
	"""A deleted message stays readable for the team, marked as deleted on the phone."""
	old = (old_body or "").strip()
	return f"[deleted from the phone app] {old}".strip()
