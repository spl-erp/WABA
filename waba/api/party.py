"""Start and follow a WhatsApp conversation from a Lead, Contact or Customer, and keep the consent record.

Every refusal happens BEFORE anything is created, so a blocked attempt leaves no empty conversation behind. The checks
are the same ones the inbox's Send Template applies (waba.api.send.send_template calls waba.parties and the consent
rules too); this module adds who may use which number and which of the record's phone numbers may be written to."""

import frappe
from frappe import _
from frappe.utils import now_datetime
from frappe.utils.password import get_decrypted_password

from waba import assignment, parties, permissions, teams
from waba.api import send
from waba.api.send import SENDERS
from waba.rules import consent as rules
from waba.rules import inbound, outbound, window

CONSENT_SOURCES = ["IndiaMART enquiry", "Website form", "Verbal / phone call", "QR code scan", "Email", "WhatsApp message", "Other"]


def _party(doctype, name):
	frappe.only_for(SENDERS)
	if doctype not in parties.PARTY_DOCTYPES or not frappe.db.exists(doctype, name):
		frappe.throw(_("Choose a Lead, a Contact or a Customer."))
	if not frappe.has_permission(doctype, "read", name):
		frappe.throw(_("You may not open this record."), frappe.PermissionError)


def _my_numbers():
	"""The business numbers this person may start conversations from."""
	scope = teams.user_scope()
	rows = frappe.get_all(
		"Waba Number",
		filters={"enabled": 1},
		fields=["name", "display_name", "display_number", "account", "purpose_conversations"],
		order_by="name asc",
	)
	if not scope.everything:
		mine = set(frappe.get_all("Waba Agent Access", filters={"user": scope.me}, pluck="parent", parent_doctype="Waba Number")) | set(scope.lead_numbers)
		rows = [r for r in rows if r.name in mine]
	enabled_accounts = set(frappe.get_all("Waba Account", filters={"enabled": 1}, pluck="name"))
	return [r for r in rows if r.purpose_conversations and r.account in enabled_accounts]


@frappe.whitelist()
def context(doctype, name):
	"""Everything the WhatsApp dialog and the form's WhatsApp section need."""
	_party(doctype, name)
	info = parties.consent(doctype, name)
	numbers = []
	for n in _my_numbers():
		templates = frappe.get_all(
			"Waba Template",
			filters={"account": n.account, "status": "APPROVED", "category": rules.UTILITY},
			fields=["name", "title", "body_text", "variable_count", "language"],
			order_by="title asc",
		)
		numbers.append({"name": n.name, "label": n.display_name or n.display_number or n.name, "templates": templates})
	phone_rows = parties.phones(doctype, name)
	keys = [p["key"] for p in phone_rows if p["key"]]
	now = now_datetime()
	conversations = []
	for c in frappe.get_all(
		"Waba Conversation",
		or_filters=[["party", "=", name], ["customer_phone", "in", keys or [""]]],
		fields=["name", "waba_number", "status", "last_inbound_at", "last_message_at", "last_message_preview", "assigned_to", "waba_number", "opted_out", "party_doctype", "party"],
		order_by="last_message_at desc",
		limit_page_length=20,
	):
		if c.party and c.party_doctype != doctype:
			continue
		if not permissions.conversation_has_permission(frappe._dict(c)):
			continue
		c["window_open"] = window.is_window_open(c.last_inbound_at, now)
		c["number_name"] = frappe.db.get_value("Waba Number", c.waba_number, "display_name") or c.waba_number
		conversations.append(c)
	opted_out = info["flag"] or info["state"] == rules.CONSENT_NO or any(c.get("opted_out") for c in conversations)
	return {
		"title": parties.title_of(doctype, name),
		"consent": {**info, "opted_out": opted_out},
		"phones": phone_rows,
		"numbers": numbers,
		"conversations": conversations,
		"can_record_consent": bool(frappe.has_permission(doctype, "write", name)),
		"sources": CONSENT_SOURCES,
	}


@frappe.whitelist(methods=["POST"])
def record_consent(doctype, name, consent, source, on=None):
	"""Record that the customer agreed (Yes) or withdrew (No) to be messaged on WhatsApp."""
	_party(doctype, name)
	if not frappe.has_permission(doctype, "write", name):
		frappe.throw(_("You may not change this record."), frappe.PermissionError)
	if consent not in (rules.CONSENT_YES, rules.CONSENT_NO):
		frappe.throw(_("Consent is either Yes or No."))
	source = (source or "").strip()
	if not source:
		frappe.throw(_("Say where the agreement came from."))
	if len(source) > 140:
		frappe.throw(_("Keep the source under 140 characters."))
	if on and frappe.utils.getdate(on) > frappe.utils.getdate(frappe.utils.today()):
		frappe.throw(_("The date cannot be in the future."))
	parties.set_consent(doctype, name, consent, source, on)
	return parties.consent(doctype, name)


@frappe.whitelist(methods=["POST"])
def start(doctype, name, number, phone, template, params=None):
	"""Send the first template to a customer from their record. Creates the conversation and assigns it to the sender."""
	_party(doctype, name)
	numbers = {n.name: n for n in _my_numbers()}
	if number not in numbers:
		frappe.throw(_("You may not send from that number."), frappe.PermissionError)
	account = frappe.get_doc("Waba Account", numbers[number].account)
	if not get_decrypted_password("Waba Portfolio", account.portfolio, "access_token", raise_exception=False):
		frappe.throw(_("Save the access token on the portfolio {0} first.").format(account.portfolio))

	usable = {p["raw"]: p["key"] for p in parties.phones(doctype, name) if p["key"]}
	key = usable.get(phone) or (phone if phone in usable.values() else None)
	if not key:
		frappe.throw(_("That is not a usable phone number on this record. Fix the number on the record first."))

	tpl = frappe.get_doc("Waba Template", template)
	if tpl.account != account.name or tpl.status != "APPROVED":
		frappe.throw(_("That template is not approved on this number's WhatsApp account."))
	values = send._as_list(params)
	problems = outbound.validate_params(tpl.body_text, values)
	if problems:
		frappe.throw("<br>".join(_(p) for p in problems), title=_("Please fix the template values"))

	conversation_key = inbound.conversation_key(number, key, None)
	existing = frappe.db.get_value("Waba Conversation", {"conversation_key": conversation_key}, "name")
	probe = frappe.get_doc("Waba Conversation", existing) if existing else frappe._dict(
		party_doctype=doctype, party=name, customer_phone=key, waba_number=number, last_inbound_at=None, opted_out=0
	)
	if existing and not permissions.conversation_has_permission(probe):
		who = frappe.db.get_value("User", probe.assigned_to, "full_name") if probe.assigned_to else None
		frappe.throw(_("This customer is already in a conversation on that number{0}. Ask a supervisor to hand it to you.").format(f" ({who})" if who else ""))
	if not existing:  # a not-yet-created conversation is judged on the record's own consent
		probe.party_doctype, probe.party = doctype, name
	ok, _code, message = parties.check_conversation_template(probe, tpl.category)
	if not ok:
		frappe.throw(_(message))
	ok, _code, message = rules.check_daily_limit(parties.started_in_24h(account.portfolio), rules.daily_limit(frappe.db.get_value("Waba Portfolio", account.portfolio, "messaging_tier")))
	if not ok:
		frappe.throw(_(message))

	conv = _conversation(existing, conversation_key, number, key, doctype, name)
	result = send.send_template(conv.name, tpl.name, values)
	result["conversation"] = conv.name
	parties.comment(doctype, name, _("WhatsApp template {0} sent to {1} by {2}{3}.").format(
		tpl.title, key, frappe.utils.get_fullname(), "" if result.get("ok") else _(" (not delivered: {0})").format(result.get("error"))))
	return result


def _conversation(existing, conversation_key, number, key, doctype, name):
	now = now_datetime()
	me = frappe.session.user
	if existing:
		conv = frappe.get_doc("Waba Conversation", existing)
		changes = {}
		if conv.status == "Done":
			changes["status"] = "Open"
		if not conv.party:
			changes.update({"party_doctype": doctype, "party": name, "match_state": "Matched"})
		if changes:
			frappe.db.set_value("Waba Conversation", conv.name, changes, update_modified=False)
			conv.reload()
		return conv
	conv = frappe.get_doc(
		{
			"doctype": "Waba Conversation",
			"conversation_key": conversation_key,
			"waba_number": number,
			"customer_phone": key,
			"customer_label": parties.label_for(doctype, name, key),
			"profile_name": parties.title_of(doctype, name),
			"match_state": "Matched",
			"party_doctype": doctype,
			"party": name,
			"status": "Open",
			"unread_count": 0,
			"assigned_to": me,
			"assigned_at": now,
			"assigned_reason": _("started by {0}").format(frappe.utils.get_fullname(me)),
		}
	).insert(ignore_permissions=True)
	assignment.add_event(conv.name, _("Conversation started by {0} from {1} {2}.").format(frappe.utils.get_fullname(me), doctype, name))
	assignment.notify(conv, "assigned")
	return conv
