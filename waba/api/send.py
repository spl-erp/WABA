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

import frappe
from frappe import _
from frappe.utils import now_datetime
from frappe.utils.password import get_decrypted_password

from waba.constants import DEFAULT_API_VERSION, ROLE_ADMIN, ROLE_AGENT, ROLE_SUPERVISOR
from waba import parties, permissions
from waba.meta import graph
from waba.rules import consent as rules_consent
from waba.rules import purposes
from waba.rules import errors, outbound, window
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


def _deliver(ctx, payload, values, origin=purposes.PERSON):
	now = now_datetime()
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
			"preview": make_preview(values.get("body")),
			**values,
		}
	).insert(ignore_permissions=True)
	_commit()  # the record must exist before Meta can report on it

	try:
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
		{"last_message_at": now, "last_message_preview": make_preview(values.get("body"))},
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
