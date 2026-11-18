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

from waba.rules import signature, template_events, webhook
from waba.rules import calls as calls_rules
from waba.rules import coexistence as coexistence_rules

MAX_BODY_BYTES = 1_000_000

# Meta fields a delivery may carry that this ERP acts on; anything else is stored as received and the event is marked Ignored.
HANDLED_FIELDS = ("messages", coexistence_rules.ECHO_FIELD, coexistence_rules.ACCOUNT_FIELD, calls_rules.CALLS_FIELD, *template_events.FIELDS)


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
	# Read the URL's own query string: for a POST with a JSON body (what Meta sends) Frappe replaces form_dict with the
	# body, so `?app=` would be lost there and every delivery refused as an unknown app.
	query = request.args
	app_key = query.get("app") or frappe.form_dict.get("app")
	if request.method == "GET":
		status, body = handle_handshake(app_key, query.get("hub.mode"), query.get("hub.verify_token"), query.get("hub.challenge"))
		return _text(status, body)

	if (request.content_length or 0) > MAX_BODY_BYTES:
		return _text(413, "Too large")
	status, body, _event = handle_delivery(app_key, request.get_data(), request.headers.get("X-Hub-Signature-256"))
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
			"title": webhook.title(summary),
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
			event_name=event.name,  # not `event`: that is a reserved argument of frappe.enqueue and never reaches the job
			enqueue_after_commit=True,
			job_id=f"waba-event-{event.name}",
			deduplicate=True,
		)
	return 200, "OK", event.name


def process_event(event_name):
	"""Work out which account and number a stored delivery is about and store the customer messages in it.
	Delivery status updates (sent, delivered, read) are applied by a later release."""
	doc = frappe.get_doc("Waba Webhook Event", event_name)
	if doc.status != "Received":
		return
	try:
		payload = json.loads(doc.payload)
		summary = webhook.summarise(payload)
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
		else:
			notes += _store_message_changes(payload, account, doc.name)
			notes += _store_echo_changes(payload, account, doc.name)
			status_notes, waiting = _apply_status_changes(payload)
			notes += status_notes
			from waba import calls, coexistence, template_events

			notes += template_events.apply_changes(payload, account)
			notes += coexistence.apply_account_updates(payload, account)
			notes += calls.handle_changes(payload, account, doc.name)
			unhandled = [f for f in summary["fields"] if f not in HANDLED_FIELDS]
			if unhandled:
				notes.append("Not handled yet, kept as received: " + ", ".join(unhandled) + ".")
			if waiting:
				status = "Waiting"
			elif unhandled and len(unhandled) == len(summary["fields"]):
				status = "Ignored"
		doc.db_set(
			{"status": status, "waba_account": account, "waba_number": number, "note": " ".join(notes) or None},
			update_modified=False,
		)
		if account:
			frappe.db.set_value("Waba Account", account, "last_webhook_at", now_datetime(), update_modified=False)
	except Exception:
		doc.db_set({"status": "Failed", "note": "Could not be examined; see the Error Log."}, update_modified=False)
		frappe.log_error(title="Waba: webhook event could not be examined")


def _apply_status_changes(payload):
	from waba import status_updates

	updated = unchanged = 0
	waiting = []
	for entry in payload.get("entry") or []:
		for change in (entry.get("changes") or []) if isinstance(entry, dict) else []:
			value = change.get("value") if isinstance(change, dict) and isinstance(change.get("value"), dict) else None
			if not value or change.get("field") != "messages" or not value.get("statuses"):
				continue
			result = status_updates.apply_statuses(value)
			updated += result["updated"]
			unchanged += result["unchanged"]
			waiting += result["waiting"]
	notes = []
	if updated or unchanged:
		notes.append(f"{updated} delivery update(s) applied" + (f", {unchanged} needed no change." if unchanged else "."))
	if waiting:
		notes.append(f"Waiting for {len(waiting)} message(s) the ERP has not saved yet.")
	return notes, waiting


def retry_waiting():
	"""Scheduled every few minutes: look again at deliveries that reported on a message we did not have yet. After an
	hour the message is taken to be one the ERP never sent, and the delivery is closed."""
	import datetime

	cutoff = now_datetime() - datetime.timedelta(hours=1)
	for name, received_at in frappe.get_all("Waba Webhook Event", filters={"status": "Waiting"}, fields=["name", "received_at"], limit_page_length=200, as_list=True):
		if received_at and received_at < cutoff:
			frappe.db.set_value(
				"Waba Webhook Event", name, {"status": "Ignored", "note": "Reported on a message this ERP never sent."}, update_modified=False
			)
		else:
			frappe.db.set_value("Waba Webhook Event", name, "status", "Received", update_modified=False)
			process_event(name)


def _store_message_changes(payload, account, event):
	from waba import inbound

	notes, stored, duplicates, unidentified, unknown = [], 0, 0, 0, set()
	for entry in payload.get("entry") or []:
		for change in (entry.get("changes") or []) if isinstance(entry, dict) else []:
			value = change.get("value") if isinstance(change, dict) and isinstance(change.get("value"), dict) else None
			if not value or change.get("field") != "messages" or not value.get("messages"):
				continue
			phone_number_id = str((value.get("metadata") or {}).get("phone_number_id") or "")
			number = _number_for([phone_number_id], account)
			if not number:
				unknown.add(phone_number_id)
				continue
			counts = inbound.store_messages(value, number, event)
			stored += counts["stored"]
			duplicates += counts["duplicates"]
			unidentified += counts["unidentified"]
	if stored or duplicates:
		notes.append(f"{stored} message(s) stored" + (f", {duplicates} already known." if duplicates else "."))
	if unidentified:
		notes.append(f"{unidentified} message(s) had no usable sender.")
	if unknown:
		notes.append("Number not set up yet (run Sync numbers on the account): " + ", ".join(sorted(unknown)) + ".")
	return notes


def _store_echo_changes(payload, account, event):
	"""`smb_message_echoes`: what the business typed in the WhatsApp Business app (coexistence). Stored as outgoing Phone app messages."""
	from waba import inbound
	from waba.rules import coexistence

	notes, stored, duplicates, unidentified, edited, unknown = [], 0, 0, 0, 0, set()
	for entry in payload.get("entry") or []:
		for change in (entry.get("changes") or []) if isinstance(entry, dict) else []:
			value = change.get("value") if isinstance(change, dict) and isinstance(change.get("value"), dict) else None
			if not value or change.get("field") != coexistence.ECHO_FIELD or not value.get("message_echoes"):
				continue
			phone_number_id = str((value.get("metadata") or {}).get("phone_number_id") or "")
			number = _number_for([phone_number_id], account)
			if not number:
				unknown.add(phone_number_id)
				continue
			counts = inbound.store_echoes(value, number, event)
			stored += counts["stored"]
			duplicates += counts["duplicates"]
			unidentified += counts["unidentified"]
			edited += counts["edited"]
	if stored or duplicates or edited:
		notes.append(f"{stored} phone-app message(s) stored" + (f", {duplicates} already known" if duplicates else "") + (f", {edited} edited or deleted." if edited else "."))
	if unidentified:
		notes.append(f"{unidentified} phone-app message(s) had no usable recipient.")
	if unknown:
		notes.append("Number not set up yet (run Sync numbers on the account): " + ", ".join(sorted(unknown)) + ".")
	return notes


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
