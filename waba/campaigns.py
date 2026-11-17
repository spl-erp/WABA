"""Campaign Sets: read the chosen people from the database, apply waba.rules.campaign, and write the locked Set.

The decision is the pure module; this one only fetches (people, their numbers and consent, who told the business to stop)
and stores. Everything runs as the logged-in user, so the list a Campaign Manager may build a Set from is exactly the list
the ERP lets them read."""

import json

import frappe
from frappe import _

from waba import parties
from waba.constants import ROLE_ADMIN, ROLE_CAMPAIGN
from waba.rules import campaign as rules

SET_DOCTYPES = ("Customer", "Lead")
MANAGERS = (ROLE_ADMIN, ROLE_CAMPAIGN)
CHUNK = 1000
EXCLUDED_KEPT = 2000  # the left-out report stores this many rows; the counts are always complete


def only_managers():
	frappe.only_for(MANAGERS)


def audience_rule():
	return rules.rule_or_default(frappe.db.get_single_value("Waba Settings", "campaign_audience_rule"))


def chosen_names(doctype, names=None, filters=None):
	"""The record names to build a Set from: the ticked rows, or everything matching the list's filters (permission checked)."""
	if doctype not in SET_DOCTYPES:
		frappe.throw(_("A Set can be made from Customers or Leads."))
	if not frappe.has_permission(doctype, "read"):
		frappe.throw(_("You may not read {0} records.").format(_(doctype)), frappe.PermissionError)
	names = _as_list(names)
	filters = (frappe.parse_json(filters) if filters.strip() else None) if isinstance(filters, str) else filters
	if names:
		allowed = set()
		for i in range(0, len(names), CHUNK):
			allowed.update(frappe.get_list(doctype, filters={"name": ["in", names[i : i + CHUNK]]}, pluck="name", limit_page_length=0))
		picked = [n for n in names if n in allowed]
	else:
		picked = frappe.get_list(doctype, filters=filters or [], pluck="name", limit_page_length=rules.MAX_SET_SIZE + 1, order_by="creation asc")
	return list(dict.fromkeys(picked))


def _as_list(value):
	if not value:
		return []
	if isinstance(value, str):
		return frappe.parse_json(value) if value.strip() else []
	return list(value)


def candidates(doctype, names):
	"""One dict per person, in the order given, with the first usable number and everything the rule needs."""
	meta = frappe.get_meta(doctype)
	title_field = meta.get_title_field()
	fields = ["name"] + ([title_field] if title_field and title_field != "name" else [])
	for f in ("waba_consent", "waba_marketing_consent"):
		if meta.has_field(f):
			fields.append(f)
	rows = {}
	for i in range(0, len(names), CHUNK):
		for row in frappe.get_all(doctype, filters={"name": ["in", names[i : i + CHUNK]]}, fields=fields, limit_page_length=0):
			rows[row.name] = row
	out = []
	for name in names:
		row = rows.get(name)
		if not row:
			continue
		key = next((p["key"] for p in parties.phones(doctype, name) if p["key"]), None)
		out.append(
			{
				"party": name,
				"name": (row.get(title_field) if title_field else None) or name,
				"phone": key,
				"service_consent": row.get("waba_consent") or "Unknown",
				"marketing_consent": row.get("waba_marketing_consent") or "Unknown",
				"flag": parties.opt_out_flag(doctype, name),
			}
		)
	_mark_phone_opt_outs(out)
	return out


def _mark_phone_opt_outs(people):
	"""Set phone_opted_out / phone_marketing_opted_out on everyone whose number told ANY business number to stop.

	Which portfolio the campaign will use is not known yet, so the Set is cautious (any number). The campaign checks again
	for its own portfolio when it sends."""
	keys = sorted({p["phone"] for p in people if p["phone"]})
	stopped, stopped_promo = set(), set()
	for i in range(0, len(keys), CHUNK):
		for row in frappe.get_all(
			"Waba Conversation",
			filters={"customer_phone": ["in", keys[i : i + CHUNK]]},
			or_filters=[["opted_out", "=", 1], ["marketing_opted_out", "=", 1]],
			fields=["customer_phone", "opted_out", "marketing_opted_out"],
			limit_page_length=0,
		):
			if row.opted_out:
				stopped.add(row.customer_phone)
			if row.marketing_opted_out:
				stopped_promo.add(row.customer_phone)
	for p in people:
		p["phone_opted_out"] = p["phone"] in stopped
		p["phone_marketing_opted_out"] = p["phone"] in stopped_promo


def review(doctype, names):
	"""What the review window shows: who is in, who is left out and why. Nothing is stored."""
	if len(names) > rules.MAX_SET_SIZE:
		frappe.throw(_("A Set can hold up to {0} people. Narrow the list or make more than one Set.").format(rules.MAX_SET_SIZE))
	result = rules.build_set(candidates(doctype, names), audience_rule())
	return {"doctype": doctype, "chosen": len(names), "rule": audience_rule(), "summary": rules.summary(result), **result}


def create_set(title, doctype, names, note=None, copied_from=None):
	"""Lock a Set for the people in `names` (the ones left ticked in the review window). The rule is applied again here,
	so nobody the review would have left out can be slipped in; returns the Set's name."""
	title = (title or "").strip()
	if not title:
		frappe.throw(_("Give the Set a name."))
	result = review(doctype, names)
	if not result["included"]:
		frappe.throw(_("Nobody in this list can be messaged, so there is nothing to put in a Set."))
	doc = frappe.get_doc(
		{
			"doctype": "Waba Recipient Set",
			"title": title,
			"party_doctype": doctype,
			"confirmed_on": frappe.utils.now_datetime(),
			"confirmed_by": frappe.session.user,
			"copied_from": copied_from,
			"chosen_count": result["chosen"],
			"included_count": len(result["included"]),
			"excluded_count": len(result["excluded"]),
			"audience_rule": result["rule"],
			"note": (note or "").strip() or None,
			"excluded_json": json.dumps({"counts": result["counts"], "rows": result["excluded"][:EXCLUDED_KEPT]}),
		}
	)
	doc.insert()
	_write_members(doc.name, result["included"])
	return doc.name


def _write_members(set_name, included):
	now = frappe.utils.now()
	user = frappe.session.user
	values = [
		(frappe.generate_hash(length=10), now, now, user, user, 0, 0, set_name, p["party"], p["name"], p["phone"]) for p in included
	]
	frappe.db.bulk_insert(
		"Waba Recipient Set Member",
		["name", "creation", "modified", "owner", "modified_by", "docstatus", "idx", "recipient_set", "party", "party_name", "phone"],
		values,
		chunk_size=CHUNK,
	)


def member_names(set_name):
	return frappe.get_all("Waba Recipient Set Member", filters={"recipient_set": set_name}, pluck="party", order_by="creation asc", limit_page_length=0)


# ------------------------------------------------------------------------------------------------ message values (W4b)


def parse_sources(raw):
	"""{slot: {"source_type", "source", "fallback"}} from a campaign's stored values; {} for an older or empty value."""
	try:
		data = json.loads(raw) if raw else {}
	except ValueError:
		return {}
	sources = data.get("sources") if isinstance(data, dict) else None
	return {k: v for k, v in (sources or {}).items() if isinstance(v, dict)}


def sender_name(campaign_owner, label=None):
	"""What a "Sender name" value reads in a campaign: the Waba Settings label when set, else the campaign owner's full name."""
	return (label or "").strip() or frappe.utils.get_fullname(campaign_owner)


def slot_choices(tpl, structure, sources):
	"""One entry per value the campaign must settle: where it comes from now (the campaign's own choice, else the template's
	variable map, else a guess from its label). Media header slots are chosen separately and are not listed here."""
	from waba import templating
	from waba.rules import template_vars as tv

	mapped = {r["slot"]: r for r in templating.map_rows(tpl) if r.get("active") not in (0, "0", False)}
	out = []
	for slot in structure["slots"]:
		if slot["kind"] in ("image", "video", "document"):
			continue
		row = mapped.get(slot["id"], {})
		if slot["id"] in sources:
			choice = dict(sources[slot["id"]])
		elif row.get("source_type") and row["source_type"] != tv.ASK:
			choice = {"source_type": row["source_type"], "source": row.get("source") or "", "fallback": "Sir/Madam" if row["source_type"] == tv.CUSTOMER else ""}
		else:
			kind, fallback = tv.guess_source(row.get("label") or slot["label"], row.get("example"))
			choice = {"source_type": kind, "source": "", "fallback": fallback}
		out.append({"id": slot["id"], "label": row.get("label") or slot["label"], "example": row.get("example") or "", "choice": choice})
	return out


def record_fields(doctype):
	"""Fields of the Customer or Lead a value can be taken from: [{"fieldname", "label"}]."""
	skip = {"naming_series", "amended_from"}
	rows = [
		{"fieldname": f.fieldname, "label": f.label}
		for f in frappe.get_meta(doctype).fields
		if f.fieldtype in ("Data", "Phone", "Select", "Link", "Int", "Float", "Date", "Small Text") and f.label and not f.hidden and f.fieldname not in skip
	]
	return rows[:80]
