"""The customer's record (Lead, Contact or Customer) as Waba needs it: phone numbers, consent, opt-out.

Waba is generic: where the ERP keeps a person's numbers or an older opt-out flag is answered by the extension hooks

    waba_party_phones = ["myapp.module.function"]   # (doctype, name) -> [{"label": "Mobile", "value": "98765 43210"}, ...]
    waba_opt_out      = ["myapp.module.function"]   # (doctype, name) -> True when the record says "do not contact"

and when no app answers the standard ERPNext fields are read. The decision itself is waba.rules.consent."""

import frappe
from frappe import _

from waba import matching
from waba.rules import consent as rules
from waba.rules import inbound as inbound_rules
from waba.rules import phone

PARTY_DOCTYPES = ("Lead", "Contact", "Customer")

# standard ERPNext fields, in the order a rep would try them
_PHONE_FIELDS = {
	"Lead": (("whatsapp_no", "WhatsApp"), ("mobile_no", "Mobile"), ("phone", "Phone")),
	"Contact": (("mobile_no", "Mobile"), ("phone", "Phone")),
	"Customer": (("mobile_no", "Mobile"),),
}


def default_country_code():
	return str(frappe.conf.get("waba_default_country_code") or phone.DEFAULT_COUNTRY_CODE)


def phones(doctype, name):
	"""[{"label", "raw", "key"}] the record's numbers, best first; `key` is "+<digits>" or None when the number cannot be used."""
	found = []
	for path in frappe.get_hooks("waba_party_phones"):
		try:
			answer = frappe.get_attr(path)(doctype, name)
		except Exception:
			frappe.log_error(title=f"Waba: phone hook {path} failed")
			continue
		if answer:
			found = [(row.get("label") or "", row.get("value")) for row in answer]
			break
	if not found:
		found = _standard_phones(doctype, name)
	out, seen = [], set()
	for label, raw in found:
		if not raw or not str(raw).strip():
			continue
		key = phone.from_typed(raw, default_country_code())
		if key and key in seen:
			continue
		seen.add(key)
		out.append({"label": label, "raw": str(raw).strip(), "key": key})
	return out


def _standard_phones(doctype, name):
	fields = _PHONE_FIELDS.get(doctype, ())
	values = frappe.db.get_value(doctype, name, [f for f, _l in fields], as_dict=True) or {}
	rows = [(label, values.get(field)) for field, label in fields]
	if doctype == "Contact":
		for row in frappe.get_all("Contact Phone", filters={"parent": name, "parenttype": "Contact"}, fields=["phone", "is_primary_mobile_no"], order_by="idx"):
			rows.append(("Mobile" if row.is_primary_mobile_no else "Phone", row.phone))
	return rows


def opt_out_flag(doctype, name):
	"""True when an app's own do-not-contact flag on the record says so (for example Lead.unsubscribed)."""
	for path in frappe.get_hooks("waba_opt_out"):
		try:
			if frappe.get_attr(path)(doctype, name):
				return True
		except Exception:
			frappe.log_error(title=f"Waba: opt-out hook {path} failed")
	return False


def consent(doctype, name):
	"""{"state", "on", "source", "flag", "marketing": {"state", "on", "source"}} for a record.

	`state` is the service and order-update consent C7 enforces; `marketing` is the separate agreement marketing messages
	will need. `flag` is an app's own do-not-contact flag (hook)."""
	blank = {"state": rules.CONSENT_UNKNOWN, "on": None, "source": None}
	if not (doctype in PARTY_DOCTYPES and name and frappe.db.exists(doctype, name)):
		return {**blank, "flag": False, "marketing": dict(blank)}
	fields = ["waba_consent", "waba_consent_on", "waba_consent_source"]
	has_marketing = frappe.get_meta(doctype).has_field("waba_marketing_consent")
	if has_marketing:
		fields += ["waba_marketing_consent", "waba_marketing_consent_on", "waba_marketing_consent_source"]
	row = frappe.db.get_value(doctype, name, fields, as_dict=True) or {}
	return {
		"state": row.get("waba_consent") or rules.CONSENT_UNKNOWN,
		"on": row.get("waba_consent_on"),
		"source": row.get("waba_consent_source"),
		"flag": opt_out_flag(doctype, name),
		"marketing": {
			"state": row.get("waba_marketing_consent") or rules.CONSENT_UNKNOWN,
			"on": row.get("waba_marketing_consent_on"),
			"source": row.get("waba_marketing_consent_source"),
		},
	}


def set_consent(doctype, name, state, source, on=None, by=None, purpose="service"):
	"""Write the consent and leave a comment on the record. The caller has already checked the person may do this.

	`purpose` is "service" (service and order updates) or "marketing"."""
	on = on or frappe.utils.today()
	prefix = "waba_marketing_consent" if purpose == "marketing" else "waba_consent"
	frappe.db.set_value(doctype, name, {prefix: state, f"{prefix}_on": on, f"{prefix}_source": source})
	who = by or frappe.session.user
	kind = _("marketing consent") if purpose == "marketing" else _("WhatsApp consent")
	comment(doctype, name, _("{0} set to {1} ({2}) on {3} by {4}.").format(kind, state, source, on, who))


def comment(doctype, name, text):
	frappe.get_doc({"doctype": "Comment", "comment_type": "Info", "reference_doctype": doctype, "reference_name": name, "content": text}).insert(ignore_permissions=True)


def title_of(doctype, name):
	field = frappe.get_meta(doctype).get_title_field()
	return (frappe.db.get_value(doctype, name, field) if field else None) or name


# ------------------------------------------------------------------------------------------------ for a conversation


def written_before(conversation):
	"""True when this customer has ever written to this WhatsApp business (any of its numbers)."""
	if conversation.last_inbound_at:
		return True
	if not conversation.customer_phone:
		return False
	numbers = frappe.get_all("Waba Number", filters={"account": frappe.db.get_value("Waba Number", conversation.waba_number, "account")}, pluck="name")
	return bool(
		frappe.db.exists(
			"Waba Conversation",
			{"customer_phone": conversation.customer_phone, "waba_number": ["in", numbers or [""]], "last_inbound_at": ["is", "set"]},
		)
	)


def _portfolio_numbers(waba_number):
	"""Every business number of the same Meta portfolio as `waba_number`: an opt-out is told to the business, not to one number."""
	account = frappe.db.get_value("Waba Number", waba_number, "account")
	portfolio = frappe.db.get_value("Waba Account", account, "portfolio") if account else None
	if not portfolio:
		return [waba_number]
	accounts = frappe.get_all("Waba Account", filters={"portfolio": portfolio}, pluck="name")
	return frappe.get_all("Waba Number", filters={"account": ["in", accounts or [""]]}, pluck="name") or [waba_number]


def phone_opt_outs(phone, waba_number):
	"""{"opted_out", "marketing_opted_out"}: True when this phone number told ANY number of the business to stop."""
	blank = {"opted_out": False, "marketing_opted_out": False}
	if not (phone and waba_number):
		return blank
	rows = frappe.get_all(
		"Waba Conversation",
		filters={"customer_phone": phone, "waba_number": ["in", _portfolio_numbers(waba_number)]},
		fields=["opted_out", "marketing_opted_out"],
	)
	return {"opted_out": any(r.opted_out for r in rows), "marketing_opted_out": any(r.marketing_opted_out for r in rows)}


def check_conversation_template(conversation, category):
	"""(ok, code, message) for sending a template of `category` into `conversation`."""
	state, flag = rules.CONSENT_UNKNOWN, False
	if conversation.party_doctype and conversation.party:
		info = consent(conversation.party_doctype, conversation.party)
		state, flag = info["state"], info["flag"]
	elsewhere = phone_opt_outs(conversation.get("customer_phone"), conversation.get("waba_number"))["opted_out"]
	return rules.check_template(category, written_before(conversation), state, bool(conversation.get("opted_out")) or flag or elsewhere)


def started_in_24h(portfolio):
	"""How many customers this portfolio started a conversation with in the last 24 hours (Meta's business-initiated
	limit counts customers, not messages): the distinct conversations that got a template sent while their window was closed."""
	row = frappe.db.sql(
		"""select count(distinct m.conversation) from `tabWaba Message` m
		join `tabWaba Number` n on n.name = m.waba_number
		join `tabWaba Account` a on a.name = n.account
		where a.portfolio = %s and m.direction = 'Out' and m.business_initiated = 1
		and m.sent_at >= now() - interval 24 hour""",
		portfolio,
	)
	return int(row[0][0]) if row else 0


# ------------------------------------------------------------------------------------------------ STOP and START


def _set_phone_flag(conversation, field, value):
	"""Set opted_out / marketing_opted_out on every conversation this phone has with the business (all its numbers)."""
	names = frappe.get_all(
		"Waba Conversation",
		filters={"customer_phone": conversation.customer_phone, "waba_number": ["in", _portfolio_numbers(conversation.waba_number)]},
		pluck="name",
	) if conversation.customer_phone else []
	for name in set(names) | {conversation.name}:
		frappe.db.set_value("Waba Conversation", name, field, value, update_modified=False)
	conversation.set(field, value)


def _records_of(conversation):
	"""The conversation's own record plus every Lead/Contact holding the same number (a person is often both)."""
	found = []
	if conversation.party_doctype and conversation.party:
		found.append((conversation.party_doctype, conversation.party))
	for key in matching.find_all_parties(conversation.customer_phone):
		if key not in found:
			found.append(key)
	return [key for key in found if key[0] in PARTY_DOCTYPES]


def _record_consent_everywhere(conversation, state, source, purpose="service"):
	for doctype, name in _records_of(conversation):
		set_consent(doctype, name, state, source, by="the customer", purpose=purpose)


def handle_keyword(conversation, text):
	"""A customer's STOP closes the door on every number of the business; START (only after a STOP) opens it again.
	STOP PROMO stops marketing only. The choice is recorded on the conversation(s) and on every Lead/Contact holding the
	number. Returns "stop", "start", "stop_marketing", "start_marketing" or None."""
	from waba import assignment

	if rules.is_stop_marketing(text):
		_set_phone_flag(conversation, "marketing_opted_out", 1)
		_record_consent_everywhere(conversation, rules.CONSENT_NO, "Customer replied STOP PROMO", "marketing")
		assignment.add_event(conversation.name, _("The customer replied STOP PROMO. No marketing messages will be sent; service and order messages are unaffected."))
		return "stop_marketing"
	if rules.is_start_marketing(text) and conversation.get("marketing_opted_out"):
		_set_phone_flag(conversation, "marketing_opted_out", 0)
		_record_consent_everywhere(conversation, rules.CONSENT_YES, "Customer replied START PROMO", "marketing")
		assignment.add_event(conversation.name, _("The customer replied START PROMO. Marketing messages are allowed again."))
		return "start_marketing"
	if rules.is_stop(text):
		_set_phone_flag(conversation, "opted_out", 1)
		_record_consent_everywhere(conversation, rules.CONSENT_NO, "Customer replied STOP")
		assignment.add_event(conversation.name, _("The customer replied STOP. No WhatsApp template can be sent to them."))
		return "stop"
	if rules.is_start(text) and conversation.get("opted_out"):
		_set_phone_flag(conversation, "opted_out", 0)
		_record_consent_everywhere(conversation, rules.CONSENT_YES, "Customer replied START")
		assignment.add_event(conversation.name, _("The customer replied START. WhatsApp templates are allowed again."))
		return "start"
	return None


def label_for(doctype, name, key):
	return inbound_rules.customer_label(title_of(doctype, name), key, None)
