"""Sending from the ERP: a free-text reply inside the 24-hour window, or an approved template at any time.

Who may send: Waba Admin, Waba Supervisor, Waba Agent and System Manager; which conversations a person may open or send in is
decided by waba.permissions (the team tree). Every send is stored as an outgoing Waba Message BEFORE Meta is
called (status Queued), so a failure is never lost: it is kept as Failed with Meta's code and a plain explanation. Meta
then reports Sent / Delivered / Read / Failed through the webhook (see waba.status_updates).

A template goes out only when waba.rules.consent allows it: Utility only, never to a customer who opted out, and without
stored consent only to a customer who has written to us first; a business-started one also counts against Meta's daily
limit. (Starting a conversation from a Lead, Contact or Customer is waba.api.party.start.)
"""

import json
import mimetypes

import frappe
from frappe import _
from frappe.utils import now_datetime
from frappe.utils.password import get_decrypted_password

from waba.constants import DEFAULT_API_VERSION, ROLE_ADMIN, ROLE_AGENT, ROLE_SUPERVISOR
from waba import parties, permissions, teams
from waba.meta import graph
from waba.rules import consent as rules_consent
from waba.rules import purposes
from waba.rules import errors, outbound, window
from waba.rules import media as media_rules
from waba.rules.inbound import preview as make_preview

SENDERS = (ROLE_ADMIN, ROLE_SUPERVISOR, ROLE_AGENT, "System Manager")


class _Context:
	def __init__(self, conversation, need_token=True, purpose=purposes.CONVERSATIONS):
		"""`need_token=False` for actions that only read the ERP's own records (listing templates) or can do without Meta.
		`purpose` is what the message is for; the number must be switched on for it (waba.rules.purposes)."""
		frappe.only_for(SENDERS)
		self.conversation = frappe.get_doc("Waba Conversation", conversation)
		if not permissions.conversation_has_permission(self.conversation):
			frappe.throw(_("You may not open this conversation."), frappe.PermissionError)
		self.number = frappe.get_doc("Waba Number", self.conversation.waba_number)
		self.account = frappe.get_doc("Waba Account", self.number.account)
		if not (self.number.enabled and self.account.enabled):
			frappe.throw(_("The number or its WhatsApp account is switched off."))
		self.refuse_unless(purposes.check({p: self.number.get(f"purpose_{p}") for p in purposes.PURPOSES}, purpose))
		self.token = get_decrypted_password("Waba Portfolio", self.account.portfolio, "access_token", raise_exception=False)
		if need_token and not self.token:
			frappe.throw(_("Save the access token on the portfolio {0} first.").format(self.account.portfolio))
		self.version = self.account.api_version or DEFAULT_API_VERSION

	def refuse_unless(self, check):
		ok, _code, message = check
		if not ok:
			frappe.throw(_(message))


def _as_list(params):
	if params is None or params == "":
		return []
	if isinstance(params, str):
		try:
			loaded = json.loads(params)
			if isinstance(loaded, list):
				return loaded
		except ValueError:
			pass
		return [line for line in params.splitlines()]
	return list(params)


@frappe.whitelist(methods=["POST"])
def send_text(conversation: str, body: str, reply_to: str | None = None):
	"""A rep's reply. Always origin Person: the browser cannot choose another origin."""
	return _send_text(conversation, body, reply_to, purposes.PERSON)


def _send_text(conversation, body, reply_to, origin):
	ctx = _Context(conversation, purpose=purposes.purpose_for(origin))
	ctx.refuse_unless(outbound.check_free_text(body, ctx.conversation.last_inbound_at, now_datetime()))
	ctx.refuse_unless(outbound.check_recipient(ctx.conversation.customer_phone))
	payload = outbound.text_payload(ctx.conversation.customer_phone, body, reply_to)
	return _deliver(ctx, payload, {"message_type": "text", "body": body.strip(), "reply_to_message_id": reply_to}, origin)


@frappe.whitelist(methods=["POST"])
def send_template(conversation: str, template: str, params: str | list | None = None):
	"""A rep's template. Always origin Person: the browser cannot choose another origin."""
	return _send_template(conversation, template, params, purposes.PERSON)


def _send_template(conversation, template, params, origin):
	"""The one template sender. Notifications, reminders and campaigns call this with their own origin (server side only)."""
	ctx = _Context(conversation, purpose=purposes.purpose_for(origin))
	tpl = frappe.get_doc("Waba Template", template)
	if tpl.account != ctx.account.name:
		frappe.throw(_("That template belongs to a different WhatsApp account."))
	if tpl.status != "APPROVED":
		frappe.throw(_("Template {0} is {1}, so it cannot be sent.").format(tpl.title, tpl.status))
	ctx.refuse_unless(parties.check_conversation_template(ctx.conversation, tpl.category))
	if not window.is_window_open(ctx.conversation.last_inbound_at, now_datetime()):  # a business-started conversation counts against Meta's daily limit
		limit = rules_consent.daily_limit(frappe.db.get_value("Waba Portfolio", ctx.account.portfolio, "messaging_tier"))
		ctx.refuse_unless(rules_consent.check_daily_limit(parties.started_in_24h(ctx.account.portfolio), limit))
	values = _as_list(params)
	problems = outbound.validate_params(tpl.body_text, values)
	if problems:
		frappe.throw("<br>".join(_(p) for p in problems), title=_("Please fix the template values"))
	ctx.refuse_unless(outbound.check_recipient(ctx.conversation.customer_phone))
	payload = outbound.template_payload(ctx.conversation.customer_phone, tpl.template_name, tpl.language, values)
	return _deliver(
		ctx,
		payload,
		{
			"message_type": "template",
			"waba_template": tpl.name,
			"business_initiated": 0 if window.is_window_open(ctx.conversation.last_inbound_at, now_datetime()) else 1,
			"body": outbound.fill(tpl.body_text, [str(v).strip() for v in values]),
		},
		origin,
	)


@frappe.whitelist()
def templates_for(conversation: str):
	"""Sendable templates for the conversation's account, for the Send template dialog. Reads the ERP only, so no token is needed."""
	ctx = _Context(conversation, need_token=False)
	return frappe.get_all(
		"Waba Template",
		filters={"account": ctx.account.name, "status": "APPROVED", "category": "UTILITY"},
		fields=["name", "title", "category", "body_text", "variable_count"],
		order_by="title asc",
	)


@frappe.whitelist(methods=["POST"])
def mark_read(conversation: str):
	"""Clear the unread count and tell WhatsApp the customer's latest message was read (best effort)."""
	ctx = _Context(conversation, need_token=False)
	latest = frappe.db.get_value(
		"Waba Message",
		{"conversation": ctx.conversation.name, "direction": "In", "message_id": ["is", "set"]},
		"message_id",
		order_by="sent_at desc",
	)
	if latest and ctx.token:
		try:
			graph.send_message(ctx.token, ctx.number.phone_number_id, outbound.read_receipt_payload(latest), ctx.version)
		except graph.GraphError:
			pass
	frappe.db.set_value("Waba Conversation", ctx.conversation.name, "unread_count", 0, update_modified=False)
	return {"ok": True}


def _deliver(ctx, payload, values, origin=purposes.PERSON, on_created=None):
	"""Record the message, then send it. `payload` may be a function that builds the payload (a file upload belongs
	there: it must happen after the record exists and its failure must leave a Failed row, never a Queued one).
	`on_created(message)` runs once the record exists (a file copy is attached to it there)."""
	now = now_datetime()
	shown = values.get("preview") or make_preview(values.get("body"))
	message = frappe.get_doc(
		{
			"doctype": "Waba Message",
			"conversation": ctx.conversation.name,
			"direction": "Out",
			"status": "Queued",
			"sent_at": now,
			"waba_number": ctx.number.name,
			"sent_by": frappe.session.user,
			"origin": origin,
			**{"preview": shown, **values},
		}
	).insert(ignore_permissions=True)
	if on_created:
		try:
			on_created(message)
		except Exception:
			frappe.log_error(title="Waba: could not keep a copy of a sent file")
			text = _("The file could not be prepared, so nothing was sent.")
			message.db_set({"status": "Failed", "error_message": text})
			_commit()
			return {"ok": False, "error": text, "message": message.name}
	_commit()  # the record must exist before Meta can report on it

	try:
		if callable(payload):
			payload = payload()
		response = graph.send_message(ctx.token, ctx.number.phone_number_id, payload, ctx.version)
	except graph.GraphError as e:
		text = graph.explain(e)
		message.db_set({"status": "Failed", "error_code": str(e.code or ""), "error_message": text})
		_note_account_problem(ctx.account, e, text)
		_commit()
		return {"ok": False, "error": text, "message": message.name}

	message_id = outbound.sent_message_id(response)
	if not message_id:
		text = _("Meta accepted the request but returned no message ID; check the Webhook Events.")
		message.db_set({"status": "Failed", "error_message": text})
		_commit()
		return {"ok": False, "error": text, "message": message.name}

	message.db_set({"message_id": message_id, "status": "Sent"})
	frappe.db.set_value(
		"Waba Conversation",
		ctx.conversation.name,
		{"last_message_at": now, "last_message_preview": shown},
		update_modified=False,
	)
	_commit()
	return {"ok": True, "message": message.name, "message_id": message_id}


def _note_account_problem(account, error, text):
	action = errors.classify(error.code)[0]
	values = {"last_error": text}
	if action == errors.ALERT_TOKEN:
		values["token_valid"] = 0
	if action == errors.ALERT_ACCOUNT:
		values["restricted"] = 1
	frappe.db.set_value("Waba Account", account.name, values, update_modified=False)


def _commit():
	# a console check wraps its work in a savepoint it rolls back; it sets this flag so nothing is made permanent
	if not frappe.flags.get("waba_no_commit"):
		frappe.db.commit()


# ------------------------------------------------------------------------------------------------ files, reactions, retry

PRINTABLE = ("Quotation", "Sales Order", "Sales Invoice", "Delivery Note")  # ERP documents a rep may send as a PDF


def _mime_of(filename):
	return media_rules.clean_mime(mimetypes.guess_type(filename or "")[0])


def _send_media(conversation, content, filename, mime, caption, reply_to, origin):
	"""The one file sender (device file, ERP document, library file). All checks happen before anything is created."""
	ctx = _Context(conversation, purpose=purposes.purpose_for(origin))
	ctx.refuse_unless(outbound.check_media_send(ctx.conversation.last_inbound_at, now_datetime()))
	ctx.refuse_unless(outbound.check_recipient(ctx.conversation.customer_phone))
	mime = media_rules.clean_mime(mime)
	ok, kind, why = media_rules.check_upload(mime, len(content))
	if not ok:
		frappe.throw(_(why))
	ok, why = media_rules.check_content(mime, content)
	if not ok:
		frappe.throw(_(why))
	caption = (caption or "").strip()
	ok, why = media_rules.check_caption(kind, caption)
	if not ok:
		frappe.throw(_(why))
	filename = media_rules.safe_filename(filename, mime, fallback=kind)

	def build():
		media_id = graph.upload_media(ctx.token, ctx.number.phone_number_id, filename, content, mime, ctx.version)
		return outbound.media_payload(ctx.conversation.customer_phone, kind, media_id, caption, filename, reply_to)

	def keep(message):  # our own copy, private, so the inbox can show what was sent
		record = frappe.get_doc(
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
		frappe.db.set_value("Waba Message", message.name, "media_file", record.file_url, update_modified=False)

	return _deliver(
		ctx,
		build,
		{
			"message_type": kind,
			"body": caption or None,
			"preview": make_preview(f"[{kind}] {caption or filename}"),
			"media_filename": filename,
			"media_mime": mime,
			"media_size": len(content),
			"media_status": "Downloaded",
			"reply_to_message_id": reply_to,
		},
		origin,
		on_created=keep,
	)


def _read_file(record):
	with open(record.get_full_path(), "rb") as handle:
		return handle.read()


@frappe.whitelist(methods=["POST"])
def send_file(conversation: str, file_url: str, caption: str = "", reply_to: str | None = None, filename: str = ""):
	"""A rep's file from their own device. The browser uploads it privately first; only that person's own, unattached,
	private upload can be sent, so nobody can send another user's file by guessing an address."""
	frappe.only_for(SENDERS)
	record = frappe.db.get_value(
		"File",
		{"file_url": file_url, "is_private": 1, "owner": frappe.session.user},
		["name", "file_name", "file_size", "attached_to_doctype"],
		as_dict=True,
	)
	if not record or record.attached_to_doctype:
		frappe.throw(_("That upload was not found. Attach the file again."))
	if (record.file_size or 0) > max(media_rules.LIMITS.values()):
		frappe.throw(_("This file is larger than WhatsApp allows."))
	doc = frappe.get_doc("File", record.name)
	shown_name = media_rules.safe_filename(filename or doc.file_name, _mime_of(doc.file_name))  # the name the person chose; Frappe adds a suffix when a name repeats
	result = _send_media(conversation, _read_file(doc), shown_name, _mime_of(doc.file_name), caption, reply_to, purposes.PERSON)
	frappe.delete_doc("File", record.name, force=True, ignore_permissions=True)  # the message keeps its own copy
	return result


@frappe.whitelist(methods=["POST"])
def send_document(conversation: str, doctype: str, name: str, caption: str = "", reply_to: str | None = None):
	"""An ERP document (quotation, order, invoice, delivery note) as a PDF, if this person may read that document."""
	frappe.only_for(SENDERS)
	if doctype not in PRINTABLE:
		frappe.throw(_("{0} cannot be sent from here.").format(doctype))
	if not frappe.has_permission(doctype, "read", name):
		frappe.throw(_("You may not read {0} {1}.").format(doctype, name), frappe.PermissionError)
	content = frappe.get_print(doctype, name, as_pdf=True)
	return _send_media(conversation, content, f"{name}.pdf", "application/pdf", caption, reply_to, purposes.PERSON)


def _library_rows(user):
	allowed = teams.team_ids_for_quick_replies(user)
	admin = teams.is_admin(user)
	today = frappe.utils.getdate()
	rows = frappe.get_all(
		"Waba Shared File",
		fields=["name", "title", "category", "description", "scope", "team", "valid_until", "enabled", "file"],
		order_by="category asc, title asc",
	)
	return [r for r in rows if media_rules.shared_file_visible(r, today, allowed, admin)]


@frappe.whitelist()
def shared_files():
	"""The approved files this person may send (Everyone's, their team's and the teams above, not expired)."""
	frappe.only_for(SENDERS)
	out = []
	for r in _library_rows(frappe.session.user):
		record = frappe.db.get_value("File", {"file_url": r.file}, ["file_name", "file_size"], as_dict=True) or {}
		out.append(
			{
				"name": r.name,
				"title": r.title,
				"category": r.category or "",
				"description": r.description or "",
				"filename": record.get("file_name") or "",
				"size": media_rules.human_size(record.get("file_size") or 0),
			}
		)
	return out


@frappe.whitelist(methods=["POST"])
def send_library_file(conversation: str, shared_file: str, caption: str = "", reply_to: str | None = None):
	"""A file from the shared library, if it is offered to this person."""
	frappe.only_for(SENDERS)
	row = next((r for r in _library_rows(frappe.session.user) if r.name == shared_file), None)
	if not row:
		frappe.throw(_("That file is not available to you."), frappe.PermissionError)
	doc = frappe.get_doc("File", {"file_url": row.file})
	return _send_media(conversation, _read_file(doc), doc.file_name, _mime_of(doc.file_name), caption, reply_to, purposes.PERSON)


@frappe.whitelist(methods=["POST"])
def send_reaction(message: str, emoji: str = ""):
	"""React to a customer's message with an emoji (an empty emoji removes our reaction). Needs the window to be open."""
	msg = frappe.get_doc("Waba Message", message)
	ctx = _Context(msg.conversation)
	if msg.direction != "In" or not msg.message_id:
		frappe.throw(_("You can react only to a customer's message."))
	emoji = (emoji or "").strip()
	if len(emoji) > 16:
		frappe.throw(_("That is not a single emoji."))
	ctx.refuse_unless(outbound.check_media_send(ctx.conversation.last_inbound_at, now_datetime()))
	ctx.refuse_unless(outbound.check_recipient(ctx.conversation.customer_phone))
	try:
		graph.send_message(ctx.token, ctx.number.phone_number_id, outbound.reaction_payload(ctx.conversation.customer_phone, msg.message_id, emoji), ctx.version)
	except graph.GraphError as e:
		frappe.throw(graph.explain(e))
	frappe.db.set_value("Waba Message", msg.name, "our_reaction", emoji or None, update_modified=False)
	_commit()
	return {"ok": True}


@frappe.whitelist(methods=["POST"])
def retry_message(message: str):
	"""Send a failed text or file again, once. Not for failures that sending again cannot fix, and not for templates
	(their values are not kept; use Send template again)."""
	msg = frappe.get_doc("Waba Message", message)
	_Context(msg.conversation, need_token=False)  # visibility and role
	if msg.direction != "Out" or msg.status != "Failed":
		frappe.throw(_("Only a message that failed can be sent again."))
	if msg.retried:
		frappe.throw(_("This message was already sent again."))
	if msg.sent_by != frappe.session.user and not (teams.is_admin(frappe.session.user) or frappe.db.exists("Has Role", {"parent": frappe.session.user, "role": ROLE_SUPERVISOR})):
		frappe.throw(_("Only the person who wrote it, or a supervisor, can send it again."))
	if msg.error_code and errors.classify(msg.error_code)[0] in errors.NEVER_RETRY_SAME:
		frappe.throw(_("Sending the same message again would fail the same way: {0}").format(msg.error_message or ""))
	if msg.message_type == "text":
		result = _send_text(msg.conversation, msg.body or "", msg.reply_to_message_id, purposes.PERSON)
	elif msg.message_type in media_rules.TYPES and msg.media_file:
		record = frappe.get_doc("File", {"file_url": msg.media_file})
		result = _send_media(msg.conversation, _read_file(record), msg.media_filename, msg.media_mime, msg.body or "", msg.reply_to_message_id, purposes.PERSON)
	else:
		frappe.throw(_("This kind of message cannot be sent again from here. Send it again from the conversation."))
	if result.get("ok"):
		frappe.db.set_value("Waba Message", msg.name, "retried", 1, update_modified=False)
		_commit()
	return result
