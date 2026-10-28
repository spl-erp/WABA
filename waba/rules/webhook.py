"""Pure helpers for Meta's webhook: the subscribe handshake, a stable id for a delivery, and a summary of what a
delivery contains. No Frappe import, so it is tested offline (tests/test_webhook.py).

A delivery looks like
  {"object": "whatsapp_business_account",
   "entry": [{"id": "<WABA id>", "changes": [{"field": "messages",
       "value": {"metadata": {"display_phone_number": "...", "phone_number_id": "..."},
                 "messages": [...], "statuses": [...], "contacts": [...]}}]}]}
Other fields (account_update, message_template_status_update, phone_number_quality_update ...) carry no
metadata or messages; they are logged and summarised the same way.
"""

import hashlib
import hmac
import json

OBJECT = "whatsapp_business_account"


def verify_handshake(mode, token, expected_token):
	"""Meta's GET check: hub.mode must be "subscribe" and hub.verify_token must equal ours."""
	if mode != "subscribe" or not token or not expected_token:
		return False
	return hmac.compare_digest(str(token).encode(), str(expected_token).encode())


def body_hash(raw_body):
	"""Same bytes -> same id. Meta re-sends a delivery unchanged until it gets a 200, so this is the duplicate key."""
	raw = raw_body if isinstance(raw_body, bytes) else str(raw_body).encode("utf-8")
	return hashlib.sha256(raw).hexdigest()


def parse(raw_body):
	"""The decoded delivery, or None when it is not a JSON object."""
	try:
		data = json.loads(raw_body)
	except (TypeError, ValueError):
		return None
	return data if isinstance(data, dict) else None


def summarise(payload):
	"""What a delivery holds, for the log and for finding the account and number it is about."""
	out = {
		"is_whatsapp": payload.get("object") == OBJECT,
		"waba_ids": [],
		"phone_number_ids": [],
		"fields": [],
		"message_count": 0,
		"status_count": 0,
	}
	for entry in _list(payload.get("entry")):
		if not isinstance(entry, dict):
			continue
		_add(out["waba_ids"], entry.get("id"))
		for change in _list(entry.get("changes")):
			if not isinstance(change, dict):
				continue
			_add(out["fields"], change.get("field"))
			value = change.get("value") if isinstance(change.get("value"), dict) else {}
			metadata = value.get("metadata") if isinstance(value.get("metadata"), dict) else {}
			_add(out["phone_number_ids"], metadata.get("phone_number_id"))
			out["message_count"] += len(_list(value.get("messages")))
			out["status_count"] += len(_list(value.get("statuses")))
	return out


def _list(value):
	return value if isinstance(value, list) else []


def _add(items, value):
	if value is not None and str(value) and str(value) not in items:
		items.append(str(value))


def title(summary):
	"""A readable name for a stored delivery, e.g. "messages: 2 message(s), 0 status update(s)"."""
	kinds = ", ".join(summary["fields"]) or "event"
	return f"{kinds}: {summary['message_count']} message(s), {summary['status_count']} status update(s)"
