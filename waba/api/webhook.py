"""The public webhook Meta calls (GET to verify the address, POST for every delivery).

One address per Meta app: /api/method/waba.api.webhook.receive?app=<webhook key>. The key finds the Meta app and so
its secret and verify token. A delivery is accepted only with a valid X-Hub-Signature-256 over the RAW body; it is
stored untouched, answered with 200 at once and examined by a queued job (Meta retries for days on a slow or
failing answer). An unsigned or badly signed request is answered 403 and NOT stored, so strangers cannot fill the
database.

receive() is a thin wrapper; handle_handshake and handle_delivery take plain values, so a console script can
exercise them without HTTP.
"""

import json

import frappe
from frappe.rate_limiter import rate_limit
from frappe.utils import now_datetime
from werkzeug.wrappers import Response

from waba.rules import signature, webhook

MAX_BODY_BYTES = 1_000_000


def _text(status, text=""):
	response = Response(text, status=status)
	response.mimetype = "text/plain"
	return response


def _meta_app(app_key):
	if not app_key:
		return None
	return frappe.db.get_value("Waba Meta App", {"webhook_key": app_key, "enabled": 1}, "name")


def _password(doctype, name, field):
	from frappe.utils.password import get_decrypted_password

	return get_decrypted_password(doctype, name, field, raise_exception=False)


@frappe.whitelist(allow_guest=True, methods=["GET", "POST"])
@rate_limit(limit=1200, seconds=60)
def receive():
	request = frappe.local.request
	form = frappe.form_dict
	if request.method == "GET":
		status, body = handle_handshake(
			form.get("app"), form.get("hub.mode"), form.get("hub.verify_token"), form.get("hub.challenge")
		)
		return _text(status, body)

	if (request.content_length or 0) > MAX_BODY_BYTES:
		return _text(413, "Too large")
	status, body, _event = handle_delivery(
		form.get("app"), request.get_data(), request.headers.get("X-Hub-Signature-256")
	)
	return _text(status, body)


def handle_handshake(app_key, mode, token, challenge):
	"""Meta's address check: echo hub.challenge when the verify token is ours."""
	app = _meta_app(app_key)
	if app and webhook.verify_handshake(mode, token, _password("Waba Meta App", app, "verify_token")):
		return 200, str(challenge or "")
	return 403, "Forbidden"


def handle_delivery(app_key, raw_body, signature_header, enqueue=True):
	"""(http status, text, event name or None). Stores a signed delivery once and queues its examination."""
	app = _meta_app(app_key)
	if not app:
		return 404, "Unknown app", None
	if not signature.verify_signature(raw_body, signature_header, _password("Waba Meta App", app, "app_secret")):
		return 403, "Bad signature", None

	payload = webhook.parse(raw_body)
	if payload is None:
		return 400, "Not a JSON object", None

	summary = webhook.summarise(payload)
	event_hash = webhook.body_hash(raw_body)
	event = frappe.get_doc(
		{
			"doctype": "Waba Webhook Event",
			"event_hash": event_hash,
			"status": "Received",
			"received_at": now_datetime(),
			"meta_app": app,
			"waba_id": ", ".join(summary["waba_ids"]),
			"phone_number_id": ", ".join(summary["phone_number_ids"]),
			"event_fields": ", ".join(summary["fields"]),
			"message_count": summary["message_count"],
			"status_count": summary["status_count"],
			"payload": json.dumps(payload, indent=1, ensure_ascii=False),
		}
	)
	try:
		event.insert(ignore_permissions=True)
	except frappe.DuplicateEntryError:
		return 200, "Duplicate", event_hash

	# no explicit commit: Frappe commits when the request ends, and enqueue_after_commit waits for that
	if enqueue:
		frappe.enqueue(
			"waba.api.webhook.process_event",
			queue="short",
			event=event.name,
			enqueue_after_commit=True,
			job_id=f"waba-event-{event.name}",
			deduplicate=True,
		)
	return 200, "OK", event.name


def process_event(event):
	"""Work out which account and number a stored delivery is about. Messages themselves are turned into
	conversations by a later release; here the delivery is only classified and the account marked as heard from."""
	doc = frappe.get_doc("Waba Webhook Event", event)
	if doc.status != "Received":
		return
	try:
		summary = webhook.summarise(json.loads(doc.payload))
		account = _account_for(summary["waba_ids"], doc.meta_app)
		number = _number_for(summary["phone_number_ids"], account)
		notes = []
		status = "Processed"
		if not summary["is_whatsapp"]:
			status = "Ignored"
			notes.append("Not a WhatsApp delivery.")
		elif not account:
			status = "Ignored"
			notes.append("No WhatsApp Account is set up for this WABA ID on this Meta app.")
		elif summary["phone_number_ids"] and not number:
			notes.append("The number is not set up yet (run Sync numbers on the account).")
		if summary["message_count"] or summary["status_count"]:
			notes.append("Stored only; conversations are built in a later release.")
		doc.db_set(
			{"status": status, "waba_account": account, "waba_number": number, "note": " ".join(notes) or None},
			update_modified=False,
		)
		if account:
			frappe.db.set_value("Waba Account", account, "last_webhook_at", now_datetime(), update_modified=False)
	except Exception:
		doc.db_set({"status": "Failed", "note": "Could not be examined; see the Error Log."}, update_modified=False)
		frappe.log_error(title="Waba: webhook event could not be examined")


def _account_for(waba_ids, meta_app):
	for waba_id in waba_ids:
		name = frappe.db.get_value("Waba Account", {"waba_id": waba_id, "meta_app": meta_app}, "name")
		if name:
			return name
	return None


def _number_for(phone_number_ids, account):
	if not account:
		return None
	for phone_number_id in phone_number_ids:
		name = frappe.db.get_value("Waba Number", {"phone_number_id": phone_number_id, "account": account}, "name")
		if name:
			return name
	return None
