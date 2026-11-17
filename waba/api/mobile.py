"""Calls made for the phone inbox (the Call Tracker app). They add nothing to what a person may see or do: the phone uses the same
inbox, send and media calls as the browser, so both always follow the same rules. This file only holds what a phone needs that
the browser works out for itself."""

import frappe
from frappe import _
from frappe.utils import now_datetime

from waba import bot_records, dedupe, teams
from waba.api import inbox, send
from waba.api.send import PRINTABLE, SENDERS
from waba.rules import media as media_rules
from waba.rules import mobile as rules
from waba.rules import purposes

API_VERSION = 1  # raised when a call changes in a way an installed app would notice


@frappe.whitelist()
def me():
	"""Who the phone is signed in as and what the inbox offers them, in one call: name, what they oversee, their numbers, the tab
	counts, availability, the upload limits and the server's time. The browser infers this from several calls; the app asks once."""
	frappe.only_for(SENDERS)
	scope = teams.user_scope()
	counts = inbox.summary()
	return {
		"api_version": API_VERSION,
		"user": frappe.session.user,
		"full_name": frappe.utils.get_fullname(frappe.session.user),
		"is_admin": teams.is_admin(frappe.session.user),
		"can_oversee": bool(scope.is_lead),
		"numbers": inbox.my_numbers(),
		"counts": counts,
		"unread_chats": inbox.unread_total(),
		"available": counts.get("available"),
		"limits": {"media_bytes": dict(media_rules.LIMITS), "caption_chars": media_rules.MAX_CAPTION},
		"server_time": str(now_datetime()),
	}


@frappe.whitelist(methods=["POST"])
def send_device_file(conversation: str, caption: str = "", reply_to: str | None = None, override_reason: str | None = None, filename: str = "", client_key: str | None = None):
	"""A file from the phone's own storage, sent as a multipart upload (field `file`). It goes through the same sender as every other
	file (window, privacy scan, receive-only, type and size checks), so the phone and the browser refuse and allow the same things.
	Nothing is kept on our side except the sent message's own private copy."""
	frappe.only_for(SENDERS)
	upload = _uploaded_file()
	if not upload:
		frappe.throw(_("No file was sent."))
	return dedupe.once(conversation, client_key, lambda: _send_upload(upload, conversation, caption, reply_to, override_reason, filename))


def _send_upload(upload, conversation, caption, reply_to, override_reason, filename):
	limit = max(media_rules.LIMITS.values())
	content = upload.stream.read(limit + 1)  # never read more than the largest thing WhatsApp accepts
	if len(content) > limit:
		frappe.throw(_("This file is larger than WhatsApp allows."))
	name = filename or upload.filename or "file"
	declared = media_rules.clean_mime(upload.mimetype)
	mime = declared if declared and declared != "application/octet-stream" else send._mime_of(name)
	return send._send_media(conversation, content, name, mime, caption, reply_to, purposes.PERSON, override_reason)


def _uploaded_file():
	"""The multipart file field of this request, or None."""
	request = getattr(frappe, "request", None)
	return request.files.get("file") if request is not None else None


_DOC_FIELDS = ("customer_name", "party_name", "customer", "transaction_date", "posting_date", "grand_total", "currency", "status")


@frappe.whitelist()
def documents_for_chat(conversation: str, doctype: str, query: str = ""):
	"""ERP documents to send as a PDF in this chat: first the chat's own customer's, then (when a search is typed) any other the person
	may read, which is what the browser's document box offers. Permissions apply to every row; `send_document` stays the send call."""
	conv = inbox._open(conversation)
	if doctype not in PRINTABLE:
		frappe.throw(_("{0} cannot be sent from here.").format(doctype))
	if not frappe.has_permission(doctype, "read"):
		return []  # this person has no access to those documents at all: an empty picker, not an error
	query = rules.clean_query(query)
	meta = frappe.get_meta(doctype)
	fields = ["name", "docstatus"] + [f for f in _DOC_FIELDS if meta.has_field(f)]
	base = {"docstatus": ["<", 2]}  # cancelled documents are never offered

	def rows(filters=None, or_filters=None):
		found = frappe.get_list(doctype, filters={**base, **(filters or {})}, or_filters=or_filters, fields=fields, order_by="creation desc", limit_page_length=rules.MAX_DOCUMENTS)
		return [_document(doctype, r) for r in found]

	customers, leads = bot_records.customer_scope(conv)
	own = []
	if doctype == "Quotation":
		if customers:
			own += rows({"quotation_to": "Customer", "party_name": ["in", customers]})
		if leads:
			own += rows({"quotation_to": "Lead", "party_name": ["in", leads]})
	elif customers:
		own += rows({"customer": ["in", customers]})
	others = []
	if len(query) >= rules.MIN_QUERY:
		like = f"%{query}%"
		names = [["name", "like", like]] + ([["customer_name", "like", like]] if meta.has_field("customer_name") else [])
		others = rows(or_filters=names)
	return rules.arrange_documents(own, others)


def _document(doctype, row):
	return {
		"doctype": doctype,
		"name": row.name,
		"title": row.get("customer_name") or row.get("party_name") or row.get("customer") or "",
		"date": str(row.get("transaction_date") or row.get("posting_date") or ""),
		"total": row.get("grand_total"),
		"currency": row.get("currency"),
		"status": row.get("status") or "",
		"draft": row.docstatus == 0,
	}
