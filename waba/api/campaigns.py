"""The calls the campaign screens make: build a Set from a Customer or Lead list, and copy a locked Set.

Only a Waba Campaign Manager or a Waba Admin may call these, and a Set is visible to its creator and to Waba Admins
(waba.permissions). The review is read-only; create_set applies the same rules again before anything is stored."""

import json

import frappe
from frappe import _
from frappe.utils import add_to_date, cint, get_datetime, getdate, now_datetime

from waba import campaign_engine as engine
from waba import campaigns, parties, teams, templating
from waba.api import send
from waba.rules import campaign as rules
from waba.rules import consent as consent_rules
from waba.rules import notify as notify_rules
from waba.rules import phone as phone_rules


def _set(name):
	campaigns.only_managers()
	if not frappe.db.exists("Waba Recipient Set", name):
		frappe.throw(_("That Set does not exist."))
	doc = frappe.get_doc("Waba Recipient Set", name)
	doc.check_permission("read")
	return doc


@frappe.whitelist()
def review_set(doctype: str, names: str | list | None = None, filters: str | list | None = None):
	"""Who would be in a Set made from the ticked rows (or everything matching the list's filters), and who would be left out."""
	campaigns.only_managers()
	picked = campaigns.chosen_names(doctype, names, filters)
	if not picked:
		frappe.throw(_("Tick at least one {0} first.").format(_(doctype)))
	return campaigns.review(doctype, picked)


@frappe.whitelist(methods=["POST"])
def create_set(title: str, doctype: str, names: str | list, note: str | None = None, copied_from: str | None = None):
	"""Lock a Set for the people left ticked in the review window; returns {"name"}."""
	campaigns.only_managers()
	picked = campaigns.chosen_names(doctype, names=names)
	if copied_from:
		_set(copied_from)
	return {"name": campaigns.create_set(title, doctype, picked, note, copied_from)}


@frappe.whitelist()
def set_people(name: str):
	"""The people in a locked Set, for the form (name, record, number)."""
	doc = _set(name)
	rows = frappe.get_all(
		"Waba Recipient Set Member",
		filters={"recipient_set": doc.name},
		fields=["party", "party_name", "phone"],
		order_by="party_name asc",
		limit_page_length=500,
	)
	return {"doctype": doc.party_doctype, "total": doc.included_count, "rows": rows}


@frappe.whitelist()
def copy_set_people(name: str):
	"""Everyone who is in a locked Set, so the review window can be opened again on them ("Copy as new Set")."""
	doc = _set(name)
	return {"doctype": doc.party_doctype, "names": campaigns.member_names(doc.name), "title": _("Copy of {0}").format(doc.title)}


@frappe.whitelist()
def can_create_set():
	"""True when this user may build Sets (the list-view action shows only then)."""
	return bool(set(campaigns.MANAGERS) & set(frappe.get_roles())) or teams.is_admin(frappe.session.user)


# ================================================================================================ W4b: the campaign


def _campaign(name, owner_only=False):
	"""The campaign, after checking the caller may use it. `owner_only` for actions that change it (not Waba Admins' reading)."""
	campaigns.only_managers()
	if not frappe.db.exists("Waba Campaign", name):
		frappe.throw(_("That campaign does not exist."))
	doc = frappe.get_doc("Waba Campaign", name)
	doc.check_permission("read")
	if owner_only and not (doc.owner == frappe.session.user or teams.is_admin(frappe.session.user)):
		frappe.throw(_("Only the person who made this campaign, or a Waba Admin, can change it."), frappe.PermissionError)
	return doc


def _sample_member(set_name):
	row = frappe.get_all("Waba Recipient Set Member", filters={"recipient_set": set_name}, fields=["party", "party_name", "phone"], order_by="party_name asc", limit_page_length=1)
	return row[0] if row else None


@frappe.whitelist()
def campaign_numbers():
	"""Numbers a campaign can be sent from (switched on for Campaigns), with what a person needs to know about each."""
	campaigns.only_managers()
	rows = frappe.get_all(
		"Waba Number",
		filters={"enabled": 1, "purpose_campaigns": 1},
		fields=["name", "display_name", "display_number", "account", "receive_only", "quality_rating"],
		order_by="name asc",
	)
	enabled = set(frappe.get_all("Waba Account", filters={"enabled": 1}, pluck="name"))
	return [r for r in rows if r.account in enabled]


@frappe.whitelist()
def template_choices(number: str):
	"""Approved Marketing and Utility templates on the number's WhatsApp account that the ERP can send."""
	campaigns.only_managers()
	account = frappe.db.get_value("Waba Number", number, "account")
	return frappe.get_all(
		"Waba Template",
		filters={"account": account, "status": "APPROVED", "category": ["in", ["MARKETING", "UTILITY"]], "unsendable_reason": ["is", "not set"]},
		fields=["name", "title", "category", "language", "body_text", "variable_count"],
		order_by="title asc",
	)


def _rows_override(sources, shared=None):
	"""The resolver rows for a campaign's own choices."""
	return {slot: {"source_type": c["source_type"], "source": c.get("source") or "", "fallback": c.get("fallback") or ""} for slot, c in sources.items()}


@frappe.whitelist()
def template_form(recipient_set: str, template: str, sources: str | dict | None = None):
	"""The message dialog: the template, where each value comes from (with a sensible starting choice), a preview for a
	sample person and a preview for a person whose record has no value."""
	campaigns.only_managers()
	doc = frappe.get_doc("Waba Recipient Set", recipient_set)
	doc.check_permission("read")
	tpl = frappe.get_doc("Waba Template", template)
	sample = _sample_member(recipient_set)
	chosen = frappe.parse_json(sources) if isinstance(sources, str) and sources.strip() else (sources or {})
	structure = templating.structure_of(tpl)
	choices = campaigns.slot_choices(tpl, structure, chosen)
	rows = _rows_override({c["id"]: c["choice"] for c in choices})
	owner_label = engine.settings().sender_label or frappe.utils.get_fullname(frappe.session.user)
	form = send._template_form(tpl, doc.party_doctype, sample.party if sample else None, sample.party_name if sample else "", "", None, owner_label, None, rows)
	blank = send._template_form(tpl, None, None, "", "", None, owner_label, None, rows)
	form["blank_preview"] = blank["preview"]
	form["choices"] = choices
	form["record_fields"] = campaigns.record_fields(doc.party_doctype)
	form["sample_name"] = sample.party_name if sample else ""
	form["warnings"] = rules.template_warnings(tpl.category, form["parts"]["buttons"])
	return form


_SOURCE_WORDS = {"Customer name": "each person's name", "Record field": "a field of each person's record", "Sender name": "the sender's name", "Today": "today's date", "Literal": "the same text for everyone", "Shared file": "a file from the shared library"}


def _values_text(sources):
	parts = []
	for slot, c in sources.items():
		what = _SOURCE_WORDS.get(c["source_type"], c["source_type"])
		extra = f': "{c["source"]}"' if c["source_type"] in ("Literal", "Record field") and c.get("source") else ""
		stand_in = f' (if empty: "{c["fallback"]}")' if c.get("fallback") else ""
		parts.append(f"{slot} = {what}{extra}{stand_in}")
	return "; ".join(parts)


@frappe.whitelist(methods=["POST"])
def save_values(campaign: str, values: str | dict | None = None, sources: str | dict | None = None):
	"""Keep, on the draft campaign, where each template value comes from. `sources` is {slot: {source_type, source, fallback}}.
	(`values`, the old typed form, is still accepted and is kept as Literal text for everyone.)"""
	doc = _campaign(campaign, owner_only=True)
	if doc.status != rules.DRAFT:
		frappe.throw(_("Only a draft can be changed."))
	chosen = frappe.parse_json(sources) if isinstance(sources, str) and sources.strip() else (sources or {})
	typed = frappe.parse_json(values) if isinstance(values, str) and values.strip() else (values or {})
	for slot, text in (typed or {}).items():
		if isinstance(text, dict) and text.get("shared_file"):
			chosen.setdefault(slot, {"source_type": "Shared file", "source": text["shared_file"], "fallback": ""})
		elif isinstance(text, str) and text.strip():
			chosen.setdefault(slot, {"source_type": "Literal", "source": text.strip(), "fallback": ""})
	from waba.rules import template_vars as tv

	for slot, c in chosen.items():
		why = tv.row_problem(c)
		if why:
			frappe.throw(_("{0}: {1}").format(slot, _(why)))
	tpl = frappe.get_doc("Waba Template", doc.template)
	sample = _sample_member(doc.recipient_set)
	owner_label = engine.settings().sender_label or frappe.utils.get_fullname(doc.owner)
	structure, _filled, missing, problems = templating.prepare(tpl, doc.party_doctype, sample.party if sample else None, "", "", None, owner_label, None, _rows_override(chosen))
	if problems or missing:
		frappe.throw("<br>".join(_(p) for p in problems) or _("Say where these values come from: {0}").format(", ".join(missing)))
	doc.db_set({"template_values": json.dumps({"sources": chosen}), "values_summary": _values_text(chosen)})
	return {"ok": True, "summary": doc.values_summary}


def _estimate(doc, cfg):
	people = doc.people or frappe.db.get_value("Waba Recipient Set", doc.recipient_set, "included_count") or 0
	cost = rules.estimate_cost(people, doc.template_category, cfg.rate_marketing, cfg.rate_utility, cfg.gst)
	budget, limit = engine.budget_for(doc.waba_number, cfg)
	started = parties.started_in_24h(engine.portfolio_of(doc.waba_number))
	days = rules.days_needed(people, limit, cfg.reserved, started)
	return people, cost, limit, days


@frappe.whitelist()
def review(campaign: str):
	"""What the campaign will do, in numbers and warnings. Saved on the form too."""
	doc = _campaign(campaign)
	cfg = engine.settings()
	people, cost, limit, days = _estimate(doc, cfg)
	start, end = engine.hours_of(doc, cfg)
	warnings = []
	number = frappe.db.get_value("Waba Number", doc.waba_number, ["receive_only", "quality_rating", "enabled"], as_dict=True) or {}
	if number.get("receive_only"):
		warnings.append(_("The number is set to Receive only, so nothing can be sent from it. Switch that off on the number first."))
	if str(number.get("quality_rating") or "").upper() == "RED":
		warnings.append(_("The number's quality rating is red; sending will pause at once."))
	if cfg.test_phones and cfg.test_phones.strip():
		listed = [p for p in frappe.get_all("Waba Recipient Set Member", filters={"recipient_set": doc.recipient_set}, pluck="phone", limit_page_length=0) if notify_rules.in_test_list(p, cfg.test_phones)]
		warnings.append(_("Test mode is on in Waba Settings: only the numbers on the test list receive campaigns. {0} of the {1} people in this Set are on it.").format(len(listed), people))
	tpl = frappe.get_doc("Waba Template", doc.template) if doc.template else None
	if tpl:
		parts = templating.structure_of(tpl)
		warnings += rules.template_warnings(tpl.category, [{"type": b["type"], "text": b["text"]} for b in parts["buttons"]])
	if days > 1:
		finish = add_to_date(getdate(), days=days - 1)
		warnings.append(_("This Set is bigger than the number of new chats WhatsApp allows each day ({0} a day, keeping {1}% for notifications and reps). It will be spread over {2} days and finish about {3}.").format(limit, cfg.reserved, days, finish))
	if doc.template_category == "MARKETING":
		warnings.append(_("Marketing messages cost about 7 to 8 times a Utility message."))
	text = _("{0} people. About Rs {1} before GST (Rs {2} with GST), an estimate at Rs {3} a message. Sends between {4}:00 and {5}:00 at {6} a minute.").format(
		people, cost["subtotal"], cost["total"], cost["each"], start, end, engine.speed_of(doc, cfg)
	)
	doc.db_set("estimate_text", text)
	return {"people": people, "cost": cost, "days": days, "limit": limit, "hours": [start, end], "speed": engine.speed_of(doc, cfg), "warnings": warnings, "text": text, "approval": cfg.needs_approval}


def _own_numbers():
	"""The caller's own phone from their User record (mobile, then phone)."""
	row = frappe.db.get_value("User", frappe.session.user, ["mobile_no", "phone"], as_dict=True) or {}
	cc = parties.default_country_code()
	for raw in (row.get("mobile_no"), row.get("phone")):
		key = phone_rules.from_typed(raw, cc) if raw else None
		if key:
			return [key]
	return []


@frappe.whitelist(methods=["POST"])
def send_test(campaign: str, include_mine: int | bool = 1):
	"""Send the real message to the caller's own number and the typed test numbers; nobody else. Test sends are kept apart from the report."""
	doc = _campaign(campaign, owner_only=True)
	if doc.status not in (rules.DRAFT, rules.PENDING_APPROVAL, rules.SCHEDULED, rules.PAUSED):
		frappe.throw(_("A test can be sent before or between runs."))
	keys = _own_numbers() if cint(include_mine) else []
	cc = parties.default_country_code()
	for line in (doc.test_numbers or "").replace(",", "\n").splitlines():
		key = phone_rules.from_typed(line.strip(), cc) if line.strip() else None
		if key and key not in keys:
			keys.append(key)
	if not keys:
		frappe.throw(_("There is no number to test with. Add your mobile number to your user, or type test numbers."))
	tpl = frappe.get_doc("Waba Template", doc.template)
	sample = _sample_member(doc.recipient_set)
	sources = campaigns.parse_sources(doc.template_values)
	_s, values, missing, problems = templating.prepare(tpl, doc.party_doctype, sample.party if sample else None, "", "", None, campaigns.sender_name(doc.owner, engine.settings().sender_label), None, _rows_override(sources))
	if problems or missing:
		frappe.throw(_("Fill the message values first."))
	out = []
	with engine.as_system():
		for key in keys:
			rec = frappe.get_doc({"doctype": "Waba Campaign Recipient", "campaign": doc.name, "run_on": getdate(), "party": None, "party_name": _("Test"), "phone": key, "status": rules.R_QUEUED, "is_test": 1}).insert(ignore_permissions=True)
			engine._send_one(rec.name, values_override=values, test=True)
			rec.reload()
			out.append({"phone": key, "status": rec.status, "reason": rec.reason})
	return {"results": out}


def _check_ready(doc):
	problems = []
	if not (doc.waba_number and doc.template):
		return [_("Choose the message first (Choose message button).")]
	number = frappe.db.get_value("Waba Number", doc.waba_number, ["enabled", "receive_only", "purpose_campaigns", "account"], as_dict=True) or {}
	if not (number.get("enabled") and number.get("purpose_campaigns")):
		problems.append(_("The number is switched off or not set up for campaigns."))
	if number.get("receive_only"):
		problems.append(_("The number is set to Receive only."))
	if not frappe.db.get_value("Waba Account", number.get("account"), "enabled"):
		problems.append(_("The WhatsApp account is switched off."))
	tpl = frappe.get_doc("Waba Template", doc.template)
	structure = templating.structure_of(tpl)
	if structure["slots"] and not campaigns.parse_sources(doc.template_values) and not any(r.get("source_type") not in (None, "", "Ask each time") for r in templating.map_rows(tpl)):
		problems.append(_("Fill the message values first (Message values button)."))
	if not (doc.people or 0):
		problems.append(_("The Set is empty."))
	return problems


@frappe.whitelist(methods=["POST"])
def submit(campaign: str, confirm_name: str):
	"""Start the campaign. The person must type its name: this goes to real people."""
	doc = _campaign(campaign, owner_only=True)
	if doc.status != rules.DRAFT:
		frappe.throw(_("This campaign has already been submitted."))
	if (confirm_name or "").strip() != doc.title.strip():
		frappe.throw(_("Type the campaign's name exactly to confirm."))
	problems = _check_ready(doc)
	if problems:
		frappe.throw("<br>".join(problems), title=_("Not ready"))
	cfg = engine.settings()
	start = now_datetime() if doc.schedule_mode == rules.NOW else get_datetime(doc.start_at)
	if doc.schedule_mode != rules.NOW and start < now_datetime():
		frappe.throw(_("The start time is in the past."))
	values = {"start_at": start, "next_run_on": getdate(start), "runs_done": 0}
	if cfg.needs_approval:
		values["status"] = rules.PENDING_APPROVAL
	else:
		values["status"] = rules.SCHEDULED
	doc.db_set(values)
	engine._notify_owner(doc, _("is waiting for a Waba Admin's approval.") if cfg.needs_approval else _("is scheduled."))
	return {"status": values["status"]}


def _admin_only():
	campaigns.only_managers()
	if not teams.is_admin(frappe.session.user):
		frappe.throw(_("Only a Waba Admin can approve campaigns."), frappe.PermissionError)


@frappe.whitelist(methods=["POST"])
def approve(campaign: str):
	_admin_only()
	doc = _campaign(campaign)
	if doc.status != rules.PENDING_APPROVAL:
		frappe.throw(_("This campaign is not waiting for approval."))
	doc.db_set({"status": rules.SCHEDULED, "approved_by": frappe.session.user})
	engine._notify_owner(doc, _("was approved."))
	return {"status": rules.SCHEDULED}


@frappe.whitelist(methods=["POST"])
def reject(campaign: str, reason: str):
	_admin_only()
	doc = _campaign(campaign)
	if doc.status != rules.PENDING_APPROVAL:
		frappe.throw(_("This campaign is not waiting for approval."))
	if not (reason or "").strip():
		frappe.throw(_("Say why it was rejected."))
	doc.db_set({"status": rules.REJECTED, "rejected_reason": reason.strip()})
	engine._notify_owner(doc, _("was rejected: {0}").format(reason.strip()))
	return {"status": rules.REJECTED}


@frappe.whitelist(methods=["POST"])
def pause(campaign: str):
	doc = _campaign(campaign, owner_only=True)
	if not rules.can_pause(doc.status):
		frappe.throw(_("Only a scheduled or running campaign can be paused."))
	engine.pause(doc.name, _("Paused by {0}.").format(frappe.utils.get_fullname(frappe.session.user)), by_system=False)
	return {"status": rules.PAUSED}


@frappe.whitelist(methods=["POST"])
def resume(campaign: str):
	doc = _campaign(campaign, owner_only=True)
	if not rules.can_resume(doc.status):
		frappe.throw(_("Only a paused campaign can be resumed."))
	waiting = frappe.db.count("Waba Campaign Recipient", {"campaign": doc.name, "is_test": 0, "status": ["in", [rules.R_PENDING, rules.R_QUEUED]]})
	status = rules.RUNNING if waiting else rules.SCHEDULED
	doc.db_set({"status": status, "pause_reason": None, "backoff_until": None})
	return {"status": status}


@frappe.whitelist(methods=["POST"])
def cancel(campaign: str):
	doc = _campaign(campaign, owner_only=True)
	if not rules.can_cancel(doc.status):
		frappe.throw(_("This campaign cannot be cancelled."))
	frappe.db.sql(
		"update `tabWaba Campaign Recipient` set status = %s, reason = %s where campaign = %s and is_test = 0 and status in (%s, %s)",
		(rules.R_SKIPPED, _("The campaign was cancelled."), doc.name, rules.R_PENDING, rules.R_QUEUED),
	)
	doc.db_set({"status": rules.CANCELLED, "finished_on": now_datetime()})
	engine.update_counters(doc.name)
	return {"status": rules.CANCELLED}


@frappe.whitelist(methods=["POST"])
def reschedule(campaign: str, start_at: str):
	"""Move what has not gone yet to a later time. A campaign that has not started gets a new start; one that is running or
	paused waits until then and carries on."""
	doc = _campaign(campaign, owner_only=True)
	when = get_datetime(start_at)
	if when < now_datetime():
		frappe.throw(_("Choose a time in the future."))
	if doc.status == rules.SCHEDULED:
		doc.db_set({"start_at": when, "next_run_on": getdate(when)})
	elif doc.status in (rules.RUNNING, rules.PAUSED):
		doc.db_set({"status": rules.RUNNING, "backoff_until": when, "pause_reason": None})
	else:
		frappe.throw(_("A {0} campaign cannot be rescheduled.").format(doc.status.lower()))
	return {"status": doc.status, "start_at": str(when)}


@frappe.whitelist()
def progress(campaign: str):
	"""The numbers on the campaign card, and why people were skipped or failed."""
	doc = _campaign(campaign)
	counts = engine.update_counters(doc.name) if doc.status != rules.DRAFT else rules.counters([])
	reasons = frappe.db.sql(
		"select status, reason, count(*) n from `tabWaba Campaign Recipient` where campaign = %s and is_test = 0 and status in ('Skipped', 'Failed', 'Limited by Meta') group by status, reason order by n desc limit 12",
		doc.name,
		as_dict=True,
	)
	return {"status": doc.status, "counts": counts, "reasons": reasons, "pause_reason": doc.pause_reason, "runs_done": doc.runs_done, "next_run_on": str(doc.next_run_on or ""), "backoff_until": str(doc.backoff_until or "")}


@frappe.whitelist()
def create_campaign_from_set(recipient_set: str):
	"""Start a draft campaign from a locked Set (the Set form's Create Campaign button); returns its name."""
	campaigns.only_managers()
	doc = frappe.get_doc("Waba Recipient Set", recipient_set)
	doc.check_permission("read")
	numbers = campaign_numbers()
	draft = frappe.get_doc(
		{
			"doctype": "Waba Campaign",
			"title": _("Campaign for {0}").format(doc.title),
			"recipient_set": doc.name,
			"waba_number": numbers[0].name if len(numbers) == 1 else None,
		}
	)
	draft.flags.ignore_mandatory = True
	draft.insert()
	return {"name": draft.name}


@frappe.whitelist(methods=["POST"])
def set_message(campaign: str, number: str, template: str):
	"""Choose the number and the template of a draft campaign (the form's Choose message button)."""
	doc = _campaign(campaign, owner_only=True)
	if doc.status != rules.DRAFT:
		frappe.throw(_("Only a draft can be changed."))
	if number not in {n.name for n in campaign_numbers()}:
		frappe.throw(_("That number cannot send campaigns."))
	if template not in {t.name for t in template_choices(number)}:
		frappe.throw(_("That template cannot be used on this number."))
	if doc.template != template:
		doc.template_values, doc.values_summary = None, None
	doc.waba_number, doc.template = number, template
	doc.save()
	return {"ok": True, "template_category": doc.template_category}
