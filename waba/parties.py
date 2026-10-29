"""The customer's record (Lead, Contact or Customer) as Waba needs it: phone numbers, consent, opt-out.

Waba is generic: where the ERP keeps a person's numbers or an older opt-out flag is answered by the extension hooks

    waba_party_phones = ["myapp.module.function"]   # (doctype, name) -> [{"label": "Mobile", "value": "98765 43210"}, ...]
    waba_opt_out      = ["myapp.module.function"]   # (doctype, name) -> True when the record says "do not contact"

and when no app answers the standard ERPNext fields are read. The decision itself is waba.rules.consent."""

import frappe
from frappe import _

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
	"""{"state": "Yes"|"No"|"Unknown", "on", "source", "flag": bool} for a record."""
	if not (doctype in PARTY_DOCTYPES and name and frappe.db.exists(doctype, name)):
		return {"state": rules.CONSENT_UNKNOWN, "on": None, "source": None, "flag": False}
	row = frappe.db.get_value(doctype, name, ["waba_consent", "waba_consent_on", "waba_consent_source"], as_dict=True) or {}
	return {
		"state": row.get("waba_consent") or rules.CONSENT_UNKNOWN,
		"on": row.get("waba_consent_on"),
		"source": row.get("waba_consent_source"),
		"flag": opt_out_flag(doctype, name),
	}


def set_consent(doctype, name, state, source, on=None, by=None):
	"""Write the consent and leave a comment on the record. The caller has already checked the person may do this."""
	on = on or frappe.utils.today()
	frappe.db.set_value(doctype, name, {"waba_consent": state, "waba_consent_on": on, "waba_consent_source": source})
	who = by or frappe.session.user
	text = _("WhatsApp consent set to {0} ({1}) on {2} by {3}.").format(state, source, on, who)
	comment(doctype, name, text)


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


def check_conversation_template(conversation, category):
	"""(ok, code, message) for sending a template of `category` into `conversation`."""
	state, flag = rules.CONSENT_UNKNOWN, False
	if conversation.party_doctype and conversation.party:
		info = consent(conversation.party_doctype, conversation.party)
		state, flag = info["state"], info["flag"]
	return rules.check_template(category, written_before(conversation), state, bool(conversation.get("opted_out")) or flag)


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


def handle_keyword(conversation, text):
	"""A customer's STOP closes the door; START (only after a STOP) opens it again. Returns "stop", "start" or None."""
	from waba import assignment

	if rules.is_stop(text):
		frappe.db.set_value("Waba Conversation", conversation.name, "opted_out", 1, update_modified=False)
		conversation.opted_out = 1
		if conversation.party_doctype and conversation.party:
			set_consent(conversation.party_doctype, conversation.party, rules.CONSENT_NO, "Customer replied STOP", by="the customer")
		assignment.add_event(conversation.name, _("The customer replied STOP. No WhatsApp template can be sent to them."))
		return "stop"
	if rules.is_start(text) and conversation.get("opted_out"):
		frappe.db.set_value("Waba Conversation", conversation.name, "opted_out", 0, update_modified=False)
		conversation.opted_out = 0
		if conversation.party_doctype and conversation.party:
			set_consent(conversation.party_doctype, conversation.party, rules.CONSENT_YES, "Customer replied START", by="the customer")
		assignment.add_event(conversation.name, _("The customer replied START. WhatsApp templates are allowed again."))
		return "start"
	return None


def label_for(doctype, name, key):
	return inbound_rules.customer_label(title_of(doctype, name), key, None)
