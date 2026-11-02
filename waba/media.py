"""Save the files customers send. Meta delivers only a file id; this job fetches the file with the portfolio's token
and stores it as a PRIVATE File attached to the Waba Message. Nothing is ever served from a public URL: the inbox
reads it through waba.api.media.file, which applies the conversation visibility rules.

Queued after the message is stored (waba.claims.claim_and_enqueue, so a file is fetched once even if a delivery is
repeated). A short network or Meta hiccup puts the message back to Pending and the two-minute job tries again, up to
MAX_TRIES; a refusal (file gone, too big, wrong host) is final and shows the reason in plain words.
"""

import hashlib

import frappe
from frappe.utils import add_to_date, now_datetime
from frappe.utils.password import get_decrypted_password

from waba import claims
from waba.meta import graph
from waba.rules import media as rules

MAX_TRIES = 4
STUCK_MINUTES = 2


def queue_download(message):
	"""Claim the message's file and queue its download. False when already queued or done."""
	return claims.claim_and_enqueue(
		"Waba Message", message, "waba.media.fetch", status_field="media_status", from_status="Pending", to_status="Queued"
	)


def fetch(doctype, name):
	message = frappe.get_doc("Waba Message", name)
	try:
		token, version = _token(message)
		info = graph.media_info(token, message.media_id, version)
		mime = rules.clean_mime(info.get("mime_type") or message.media_mime)
		size = int(info.get("file_size") or 0)
		if size and size > rules.RECEIVE_CAP:
			raise graph.GraphError("The file is larger than WhatsApp allows.")
		content = graph.download_media(token, info.get("url"), rules.RECEIVE_CAP)
	except graph.GraphError as e:
		return _failed(message, e)
	expected = (info.get("sha256") or message.media_sha256 or "").lower()
	if expected and hashlib.sha256(content).hexdigest() != expected:
		return _done_failed(message, "The file did not match the checksum Meta gave, so it was discarded.")
	filename = rules.safe_filename(message.media_filename or f"{message.message_type}-{message.name}", mime, fallback=message.message_type or "file")
	try:
		file = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": filename,
				"attached_to_doctype": "Waba Message",
				"attached_to_name": message.name,
				"attached_to_field": "media_file",
				"is_private": 1,
				"content": content,
			}
		).insert(ignore_permissions=True)
	except Exception:  # Frappe refuses a damaged PDF or one carrying scripts; never leave the message stuck on Queued
		frappe.log_error(title="Waba: could not save a customer's file")
		return _done_failed(message, "The file could not be saved (it may be damaged or not allowed), so it was not kept.")
	frappe.db.set_value(
		"Waba Message",
		message.name,
		{
			"media_file": file.file_url,
			"media_mime": mime,
			"media_filename": filename,
			"media_size": len(content),
			"media_status": "Downloaded",
			"media_error": None,
		},
		update_modified=False,
	)
	_commit()
	from waba import assignment

	assignment.notify(message.conversation, "media")


def _token(message):
	account = frappe.db.get_value("Waba Number", message.waba_number, "account")
	portfolio, version = frappe.db.get_value("Waba Account", account, ["portfolio", "api_version"])
	token = get_decrypted_password("Waba Portfolio", portfolio, "access_token", raise_exception=False)
	if not token:
		raise graph.GraphError("No access token is saved on the portfolio, so the file could not be fetched.")
	return token, version


def _transient(error):
	return error.http_status is None or error.http_status >= 500 or error.http_status == 429


def _failed(message, error):
	tries = (message.media_tries or 0) + 1
	if _transient(error) and tries < MAX_TRIES:
		frappe.db.set_value("Waba Message", message.name, {"media_status": "Pending", "media_tries": tries, "media_error": error.message}, update_modified=True)
		return _commit()
	frappe.db.set_value("Waba Message", message.name, {"media_status": "Failed", "media_tries": tries, "media_error": error.message}, update_modified=False)
	_commit()


def _done_failed(message, text):
	frappe.db.set_value("Waba Message", message.name, {"media_status": "Failed", "media_error": text}, update_modified=False)
	_commit()


def retry_pending():
	"""Every two minutes: queue files whose first try was lost or hit a short hiccup."""
	cutoff = add_to_date(now_datetime(), minutes=-STUCK_MINUTES)
	rows = frappe.get_all(
		"Waba Message",
		filters={"media_status": "Pending", "modified": ["<", cutoff]},
		pluck="name",
		limit_page_length=50,
	)
	for name in rows:
		queue_download(name)
	return len(rows)


def retry_now(message):
	"""A person pressed Retry on a failed file: start over with fresh tries."""
	frappe.db.set_value("Waba Message", message, {"media_status": "Pending", "media_tries": 0, "media_error": None}, update_modified=True)
	return queue_download(message)


def _commit():
	if not frappe.flags.get("waba_no_commit"):
		frappe.db.commit()  # nosemgrep
