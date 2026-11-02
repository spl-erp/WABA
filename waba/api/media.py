"""Customer files and their downloads for the inbox. Every call applies the conversation visibility rules; a stored
file is never reachable through a public address."""

import frappe
from frappe import _

from waba import media, permissions
from waba.api.send import SENDERS
from waba.rules import media as rules


def _message(name):
	frappe.only_for(SENDERS)
	message = frappe.get_doc("Waba Message", name)
	conversation = frappe.get_doc("Waba Conversation", message.conversation)
	if not permissions.conversation_has_permission(conversation):
		frappe.throw(_("You may not open this conversation."), frappe.PermissionError)
	return message


def _read_bytes(record):
	"""The file's exact bytes. File.get_content() tries to decode as text, which would corrupt a picture or a voice note."""
	with open(record.get_full_path(), "rb") as handle:
		return handle.read()


@frappe.whitelist(methods=["GET"])
def file(message: str, download: int | str = 0):
	"""The file of a message as the browser should receive it (shown in place for images, audio and video)."""
	msg = _message(message)
	if not msg.media_file or msg.media_status != "Downloaded":
		frappe.throw(_("This file is not available."), frappe.DoesNotExistError)
	record = frappe.get_doc("File", {"file_url": msg.media_file, "attached_to_name": msg.name})
	content_type, disposition = rules.serve_as(msg.media_mime)
	if str(download) in ("1", "true", "True"):
		disposition = "attachment"
	frappe.local.response.filename = rules.safe_filename(msg.media_filename or record.file_name, msg.media_mime)
	frappe.local.response.filecontent = _read_bytes(record)
	frappe.local.response.content_type = content_type
	frappe.local.response.display_content_as = disposition
	frappe.local.response.type = "download"


@frappe.whitelist(methods=["POST"])
def retry(message: str):
	"""Try again to fetch a customer's file that failed."""
	msg = _message(message)
	if msg.media_status != "Failed":
		frappe.throw(_("Only a file that failed can be fetched again."))
	return {"ok": bool(media.retry_now(msg.name))}
