"""Automatic WhatsApp notifications: quotation follow-up, payment reminder, enquiry acknowledgement.

What is due and what holds a message back is decided by the pure rules in waba/rules/notify.py. This module is the database
side:

  scan_dates / scan_leads   look at quotations, invoices and new leads and write one Waba Notification Log per message that
                            is due (Pending approval for a rule in Manual mode, Queued for Automatic); a database-unique key
                            means the same message can never be queued twice
  dispatch                  every two minutes: Automatic logs that are clear to go are claimed once and sent by a background job
  send_log / deliver        the send itself: it RE-CHECKS everything (the record, consent, STOP, the template, quiet hours,
                            limits, the switches, receive-only) and goes through waba.api.send.send_automatic, so every check of
                            a person's send still applies
  waiting / preview / approve / dismiss   the Manual mode screens

Nothing runs unless Waba Settings has notifications switched on and the rule is switched on and complete. No message is ever
sent from a request or a document save: only from the job.
"""

import contextlib

import frappe
from frappe import _
from frappe.utils import add_days, add_to_date, getdate, now_datetime
from frappe.utils import strip_html_tags

from waba import assignment, claims, inbound, parties
from waba.api import send
from waba.constants import ROLE_ADMIN, ROLE_SUPERVISOR
from waba.rules import hours as rules_hours
from waba.rules import inbound as rules_inbound
from waba.rules import notify as rules
from waba.rules import phone as rules_phone
from waba.rules import purposes

LOG = "Waba Notification Log"
RULE = "Waba Notification Rule"
APPROVERS = ("System Manager", ROLE_ADMIN, ROLE_SUPERVISOR)
SCAN_LIMIT = 300  # candidate records looked at per rule and run
NEW_PER_RUN = 100  # most new logs one run may write (a flood guard, e.g. after a big import)
DISPATCH_LIMIT = 50
SKIP_NOISE_DAYS = 7  # a record that cannot be messaged is noted once a week, not every day

_REFERENCE = {rules.QUOTATION: "Quotation", rules.PAYMENT: "Sales Invoice", rules.ENQUIRY: "Lead"}


# ------------------------------------------------------------------------------------------------ small helpers


@contextlib.contextmanager
def as_system():
	"""Run as Administrator (the job has no person) and put the previous user back."""
	previous = frappe.session.user
	frappe.set_user("Administrator")
	try:
		yield
	finally:
		frappe.set_user(previous)


def _commit():
	if not frappe.flags.get("waba_no_commit"):
		frappe.db.commit()  # nosemgrep


def _settings():
	return frappe.get_single("Waba Settings")


def switched_on():
	return bool(_settings().notifications_enabled)


def ready_rules(kinds=None):
	"""Enabled rules that have everything they need (timing, number, template)."""
	out = []
	for rule in frappe.get_all(RULE, filters={"enabled": 1}, fields=["*"]):
		if kinds and rule.message_type not in kinds:
			continue
		if rules.rule_problems(rule):
			continue
		out.append(rule)
	return out


def _history(rule, doctype, name):
	"""Dates of the messages already made or queued for this record under this rule (cancelled and skipped ones do not count)."""
	rows = frappe.get_all(
		LOG,
		filters={"rule": rule, "reference_doctype": doctype, "reference_name": name, "status": ["not in", [rules.CANCELLED, rules.SKIPPED]]},
		pluck="scheduled_for",
	)
	return [getdate(r) for r in rows if r]


def recipient(kind, doc):
	"""(phone key or None, (party doctype, party name)) for a quotation, invoice or lead."""
	cc = parties.default_country_code()
	keys = []
	if kind == rules.ENQUIRY:
		party = ("Lead", doc.name)
	else:
		party = (doc.get("quotation_to") or "Customer", doc.get("party_name")) if kind == rules.QUOTATION else ("Customer", doc.get("customer"))
		if party[0] not in ("Lead", "Customer"):
			party = ("Customer", doc.get("party_name") or doc.get("customer"))
		if doc.get("contact_mobile"):
			keys.append(rules_phone.from_typed(doc.contact_mobile, cc))
		if doc.get("contact_person"):
			keys += [p["key"] for p in parties.phones("Contact", doc.contact_person)]
	if party[1]:
		keys += [p["key"] for p in parties.phones(party[0], party[1])]
	return rules.pick_phone([{"key": k} for k in keys]), party


def _label(kind, doc):
	if kind == rules.ENQUIRY:
		return doc.get("lead_name") or doc.name
	return doc.get("customer_name") or doc.get("party_name") or doc.get("customer") or doc.name


# ------------------------------------------------------------------------------------------------ writing logs


def _make_log(rule, doctype, name, event, phone, status, reason=None):
	key = rules.dedupe_key(rule.name, doctype, name, event, phone or "-", getdate().isoformat())
	if frappe.db.exists(LOG, {"dedupe_key": key}):
		return None
	try:
		return frappe.get_doc(
			{
				"doctype": LOG,
				"rule": rule.name,
				"message_type": rule.message_type,
				"status": status,
				"mode": rule.mode,
				"reference_doctype": doctype,
				"reference_name": name,
				"event": event,
				"phone": phone,
				"reason": reason,
				"scheduled_for": now_datetime(),
				"dedupe_key": key,
			}
		).insert(ignore_permissions=True)
	except (frappe.UniqueValidationError, frappe.DuplicateEntryError):
		return None  # another run wrote it a moment ago


def _recently_skipped(rule, doctype, name, event):
	return frappe.db.exists(LOG, {"rule": rule.name, "reference_doctype": doctype, "reference_name": name, "event": event, "status": rules.SKIPPED, "creation": [">", add_days(now_datetime(), -SKIP_NOISE_DAYS)]})


def _note_candidate(rule, doc, event, budget):
	"""Write the log for one due record. Returns how many logs were written (0 or 1)."""
	kind = rule.message_type
	doctype = _REFERENCE[kind]
	phone, _party = recipient(kind, doc)
	if not phone:
		if _recently_skipped(rule, doctype, doc.name, event):
			return 0
		return 1 if _make_log(rule, doctype, doc.name, event, None, rules.SKIPPED, "There is no usable phone number on the record or its contact.") else 0
	return 1 if _make_log(rule, doctype, doc.name, event, phone, rules.initial_status(rule.mode)) else 0


# ------------------------------------------------------------------------------------------------ scanning


def _already_chased(rule, doctype):
	"""Records with an open or sent message under this rule: they stay candidates beyond the lookback so repeats can follow."""
	return list(set(frappe.get_all(LOG, filters={"rule": rule.name, "reference_doctype": doctype, "status": ["not in", [rules.CANCELLED, rules.SKIPPED]]}, pluck="reference_name")))


def _candidates(rule, today, now):
	kind = rule.message_type
	days = int(rule.days_after or 0)
	look = int(rule.lookback_days or 0)
	if kind == rules.QUOTATION:
		latest = add_days(today, -days)
		filters = {"docstatus": 1, "status": ["in", list(rules.QUOTATION_OPEN)], "transaction_date": ["<=", latest]}
		if look:
			filters["transaction_date"] = ["between", [add_days(latest, -look), latest]]
		fields = ["name", "docstatus", "status", "transaction_date", "quotation_to", "party_name", "customer_name", "contact_mobile", "contact_person"]
		rows = frappe.get_all("Quotation", filters=filters, fields=fields, order_by="transaction_date desc", limit_page_length=SCAN_LIMIT)
		more = _already_chased(rule, "Quotation")
		if more:
			rows += frappe.get_all("Quotation", filters={"name": ["in", more], "docstatus": 1, "status": ["in", list(rules.QUOTATION_OPEN)]}, fields=fields)
		return rows
	if kind == rules.PAYMENT:
		latest = add_days(today, -days)
		filters = {"docstatus": 1, "is_return": 0, "outstanding_amount": [">", 0], "due_date": ["<=", latest]}
		if look:
			filters["due_date"] = ["between", [add_days(latest, -look), latest]]
		fields = ["name", "docstatus", "is_return", "outstanding_amount", "due_date", "customer", "customer_name", "contact_mobile", "contact_person"]
		rows = frappe.get_all("Sales Invoice", filters=filters, fields=fields, order_by="due_date desc", limit_page_length=SCAN_LIMIT)
		more = _already_chased(rule, "Sales Invoice")
		if more:
			rows += frappe.get_all("Sales Invoice", filters={"name": ["in", more], "docstatus": 1, "is_return": 0, "outstanding_amount": [">", 0]}, fields=fields)
		return rows
	if kind == rules.ENQUIRY:
		since = add_to_date(now, minutes=-int(rule.ack_within_minutes or 0))
		return frappe.get_all("Lead", filters={"creation": [">=", since]}, fields=["name", "lead_name", "status", "creation", "disabled", "unsubscribed", "customer"], order_by="creation asc", limit_page_length=SCAN_LIMIT)
	return []


def _scan(kinds):
	if not switched_on():
		return 0
	today, now = getdate(), now_datetime()
	written = 0
	for rule in ready_rules(kinds):
		seen = set()
		for row in _candidates(rule, today, now):
			if row.name in seen:
				continue
			seen.add(row.name)
			if written >= NEW_PER_RUN:
				break
			doctype = _REFERENCE[rule.message_type]
			history = _history(rule.name, doctype, row.name)
			if rule.message_type == rules.QUOTATION:
				event, _why = rules.quotation_event(row, rule, history, today)
			elif rule.message_type == rules.PAYMENT:
				event, _why = rules.invoice_event(row, rule, history, today)
			else:
				event, _why = rules.lead_event(row, rule, history, now)
			if event:
				written += _note_candidate(rule, frappe._dict(row), event, NEW_PER_RUN - written)
	if written:
		_commit()
	return written


def scan_dates():
	"""Hourly: quotations to follow up and invoices to remind about."""
	return _scan((rules.QUOTATION, rules.PAYMENT))


def scan_leads():
	"""Every two minutes: leads created in the last few minutes."""
	return _scan((rules.ENQUIRY,))


def sweep_open():
	"""Cancel messages still waiting whose record no longer calls for them (ordered, lost, paid, ...)."""
	cancelled = 0
	for log in frappe.get_all(LOG, filters={"status": ["in", [rules.PENDING_APPROVAL, rules.QUEUED]]}, fields=["name", "message_type", "reference_doctype", "reference_name"], limit_page_length=300):
		if not frappe.db.exists(log.reference_doctype, log.reference_name):
			why = "The record no longer exists."
		else:
			why = rules.record_problem(log.message_type, frappe.get_doc(log.reference_doctype, log.reference_name).as_dict())
		if why:
			_finish(log.name, rules.CANCELLED, why)
			cancelled += 1
	if cancelled:
		_commit()
	return cancelled


# ------------------------------------------------------------------------------------------------ the checks before a send


def _evaluate(log, rule, approving=False):
	"""The first reason this message must wait or be skipped, as (code, plain words), or None when it may go."""
	settings = _settings()
	number = frappe.db.get_value("Waba Number", rule.waba_number, ["enabled", "purpose_notifications", "receive_only", "account", "hours_enabled", "hours_start", "hours_end", "working_days"], as_dict=True) or {}
	account_ok = bool(frappe.db.get_value("Waba Account", number.get("account"), "enabled")) if number else False
	now = now_datetime()
	sent_hour = frappe.db.count("Waba Message", {"origin": ["in", [purposes.NOTIFICATION, purposes.REMINDER]], "direction": "Out", "creation": [">", add_to_date(now, hours=-1)]})
	sent_today = 0
	if log.phone and rule.waba_number:
		conv = frappe.db.get_value("Waba Conversation", {"conversation_key": rules_inbound.conversation_key(rule.waba_number, log.phone, None)}, "name")
		if conv:
			sent_today = frappe.db.count("Waba Message", {"conversation": conv, "direction": "Out", "origin": ["in", [purposes.NOTIFICATION, purposes.REMINDER]], "creation": [">=", getdate()]})
	quiet_ok = rules_hours.is_within_hours(now, rules_hours.as_time(number.get("hours_start")), rules_hours.as_time(number.get("hours_end")), number.get("working_days"), bool(number.get("hours_enabled")))
	return rules.hold_reason(
		enabled=bool(settings.notifications_enabled),
		rule_enabled=bool(rule.enabled),
		mode=rule.mode,
		receive_only=bool(number.get("receive_only")),
		number_ok=bool(number.get("enabled") and number.get("purpose_notifications") and account_ok),
		quiet_ok=quiet_ok,
		phone=log.phone or "",
		test_list=settings.test_phones,
		sent_last_hour=sent_hour,
		max_per_hour=settings.max_sends_per_hour,
		sent_today=sent_today,
		max_per_day=rule.max_per_customer_per_day,
	)


def _finish(name, status, reason=None, message=None, conversation=None, approved_by=None):
	values = {"status": status, "reason": reason}
	if status == rules.SENT:
		values["sent_at"] = now_datetime()
	if message:
		values["message"] = message
	if conversation:
		values["conversation"] = conversation
	if approved_by:
		values["approved_by"] = approved_by
	frappe.db.set_value(LOG, name, values, update_modified=False)


def _conversation_for(rule, log, party):
	key = rules_inbound.conversation_key(rule.waba_number, log.phone, None)
	existed = bool(inbound._find(key))
	conv = inbound._conversation(key, rule.waba_number, {"phone": log.phone, "bsuid": None, "profile_name": None}, party=party)
	if not existed:
		assignment.add_event(conv.name, _("Started by an automatic WhatsApp message: {0}.").format(rule.rule_name))
	return conv


def deliver(log_name, approved_by=None):
	"""Send one log's message now, after re-checking everything. Returns (ok, plain-words result). Never raises for a refusal."""
	log = frappe.get_doc(LOG, log_name)
	if log.status not in (rules.PENDING_APPROVAL, rules.QUEUED, rules.SENDING):
		return False, _("This message is already {0}.").format(log.status)
	rule = frappe.get_doc(RULE, log.rule) if frappe.db.exists(RULE, log.rule) else None
	if not rule:
		_finish(log.name, rules.CANCELLED, "The rule no longer exists.")
		return False, _("The rule no longer exists.")
	problems = rules.rule_problems(rule.as_dict())
	if problems:
		_finish(log.name, rules.SKIPPED, " ".join(problems))
		return False, " ".join(problems)
	if not frappe.db.exists(log.reference_doctype, log.reference_name):
		_finish(log.name, rules.CANCELLED, "The record no longer exists.")
		return False, _("The record no longer exists.")
	record = frappe.get_doc(log.reference_doctype, log.reference_name)
	why = rules.record_problem(rule.message_type, record.as_dict())
	if why:
		_finish(log.name, rules.CANCELLED, why)
		return False, why
	hold = _evaluate(log, rule, approving=bool(approved_by))
	if hold:
		if rules.retry_later(hold[0]) and not approved_by:
			_finish(log.name, rules.QUEUED, hold[1])  # stays queued; the next run tries again
		else:
			_finish(log.name, rules.SKIPPED, hold[1])
		return False, hold[1]
	if not log.phone:
		_finish(log.name, rules.SKIPPED, "There is no usable phone number.")
		return False, _("There is no usable phone number.")
	_phone, party = recipient(rule.message_type, frappe._dict(record.as_dict()))
	conv = _conversation_for(rule, log, party)
	try:
		result = send.send_automatic(conv.name, rule.template, None, purposes.NOTIFICATION, _settings().sender_label, reference=record.as_dict())
	except (frappe.ValidationError, frappe.PermissionError) as e:
		text = strip_html_tags(str(e)) or _("Refused.")
		_finish(log.name, rules.SKIPPED, text, conversation=conv.name, approved_by=approved_by)
		return False, text
	except Exception:
		frappe.log_error(title="Waba: notification could not be sent")
		_finish(log.name, rules.FAILED, "Unexpected error; see the Error Log.", conversation=conv.name, approved_by=approved_by)
		return False, _("Unexpected error; see the Error Log.")
	if result.get("ok"):
		_finish(log.name, rules.SENT, None, message=result.get("message"), conversation=conv.name, approved_by=approved_by)
		assignment.add_event(conv.name, _("Automatic WhatsApp message sent: {0}.").format(rule.rule_name))
		return True, ""
	_finish(log.name, rules.FAILED, result.get("error"), message=result.get("message"), conversation=conv.name, approved_by=approved_by)
	return False, result.get("error") or _("Not delivered.")


def send_log(doctype, name):
	"""The background job for one claimed Automatic log."""
	with as_system():
		deliver(name)
		_commit()


def dispatch():
	"""Every two minutes: cancel what is no longer wanted, then send the Automatic logs that are clear to go (each exactly once)."""
	if not switched_on():
		return 0
	with as_system():
		sweep_open()
		sent = 0
		for row in frappe.get_all(LOG, filters={"status": rules.QUEUED}, fields=["name", "rule", "phone"], order_by="creation asc", limit_page_length=DISPATCH_LIMIT):
			log = frappe.get_doc(LOG, row.name)
			rule = frappe.get_doc(RULE, row.rule) if frappe.db.exists(RULE, row.rule) else None
			if not rule:
				_finish(row.name, rules.CANCELLED, "The rule no longer exists.")
				continue
			if rule.mode != rules.AUTOMATIC:  # the rule was switched to Manual after this was queued: a person decides now
				_finish(row.name, rules.PENDING_APPROVAL, "The rule is now in Manual mode.")
				continue
			hold = _evaluate(log, rule)
			if hold:
				if rules.retry_later(hold[0]):
					_finish(row.name, rules.QUEUED, hold[1])
				else:
					_finish(row.name, rules.SKIPPED, hold[1])
				continue
			if claims.claim_and_enqueue(LOG, row.name, "waba.notify.send_log", status_field="status", from_status=rules.QUEUED, to_status=rules.SENDING):
				sent += 1
		_commit()
	return sent


# ------------------------------------------------------------------------------------------------ Manual mode: the screens


def _only_approvers():
	frappe.only_for(APPROVERS)


@frappe.whitelist()
def waiting(limit: int | str = 100):
	"""The messages waiting for a person to look at and send."""
	_only_approvers()
	rows = frappe.get_all(
		LOG,
		filters={"status": rules.PENDING_APPROVAL},
		fields=["name", "rule", "message_type", "reference_doctype", "reference_name", "event", "phone", "creation"],
		order_by="creation asc",
		limit_page_length=int(limit),
	)
	for r in rows:
		r["customer"] = _label_of(r["message_type"], r["reference_doctype"], r["reference_name"])
	return rows


def _label_of(kind, doctype, name):
	try:
		if not frappe.db.exists(doctype, name):
			return name
		return _label(kind, frappe._dict(frappe.get_doc(doctype, name).as_dict()))
	except Exception:
		return name


@frappe.whitelist()
def preview(log: str):
	"""What would go out for this log, with the values filled in from the record, and anything that stands in the way."""
	_only_approvers()
	row = frappe.get_doc(LOG, log)
	rule = frappe.get_doc(RULE, row.rule)
	tpl = frappe.get_doc("Waba Template", rule.template)
	record = frappe.get_doc(row.reference_doctype, row.reference_name)
	_phone, party = recipient(rule.message_type, frappe._dict(record.as_dict()))
	form = send._template_form(tpl, party[0], party[1], _label(rule.message_type, frappe._dict(record.as_dict())), "", None, _settings().sender_label, reference=record.as_dict())
	problem = rules.record_problem(rule.message_type, record.as_dict())
	hold = _evaluate(row, rule, approving=True)
	form.update({"log": row.name, "rule_name": rule.rule_name, "phone": row.phone, "status": row.status, "problem_record": problem, "hold": hold[1] if hold else "", "unfilled": [s["id"] for s in form["slots"] if s["needs_input"]]})
	return form


@frappe.whitelist(methods=["POST"])
def approve(log: str):
	"""A person presses Send on a waiting message. The same checks as an automatic send run; the result says why if it was refused."""
	_only_approvers()
	person = frappe.session.user
	with as_system():
		ok, text = deliver(log, approved_by=person)
		_commit()
	return {"ok": ok, "error": text}


@frappe.whitelist(methods=["POST"])
def dismiss(log: str, reason: str = ""):
	_only_approvers()
	row = frappe.get_doc(LOG, log)
	if row.status not in (rules.PENDING_APPROVAL, rules.QUEUED):
		frappe.throw(_("Only a waiting message can be dismissed."))
	_finish(log, rules.CANCELLED, (reason or "").strip() or _("Dismissed by {0}.").format(frappe.utils.get_fullname(frappe.session.user)))
	return {"ok": True}


@frappe.whitelist()
def would_send(rule: str):
	"""A dry run for the rule form: which records would get a message if the rule ran now. Writes and sends nothing."""
	_only_approvers()
	row = frappe.get_doc(RULE, rule)
	problems = rules.rule_problems(row.as_dict())
	if problems:
		return {"ready": False, "problems": problems, "would": []}
	today, now = getdate(), now_datetime()
	out = []
	for cand in _candidates(row, today, now)[:SCAN_LIMIT]:
		doctype = _REFERENCE[row.message_type]
		history = _history(row.name, doctype, cand.name)
		if row.message_type == rules.QUOTATION:
			event, why = rules.quotation_event(cand, row, history, today)
		elif row.message_type == rules.PAYMENT:
			event, why = rules.invoice_event(cand, row, history, today)
		else:
			event, why = rules.lead_event(cand, row, history, now)
		if event:
			phone, _party = recipient(row.message_type, frappe._dict(cand))
			out.append({"name": cand.name, "event": event, "customer": _label(row.message_type, frappe._dict(cand)), "phone": phone or "", "problem": "" if phone else "no usable phone number"})
	return {"ready": True, "problems": [], "would": out[:100], "count": len(out)}


@frappe.whitelist(methods=["POST"])
def prepare_for_document(doctype: str, name: str):
	"""From a Quotation, Sales Invoice or Lead form: put a message for this document in the waiting list now (the timing is
	skipped, the record's state and every send check are not) and return its log so the preview can open."""
	_only_approvers()
	kind = next((k for k, d in _REFERENCE.items() if d == doctype), None)
	if not kind:
		frappe.throw(_("{0} has no WhatsApp notification.").format(doctype))
	if not frappe.has_permission(doctype, "read", name):
		frappe.throw(_("You may not read {0} {1}.").format(doctype, name), frappe.PermissionError)
	rule = next(iter(ready_rules((kind,))), None)
	if not rule:
		frappe.throw(_("No complete, switched-on rule exists for this. Set one up under Notification Rules first."))
	record = frappe._dict(frappe.get_doc(doctype, name).as_dict())
	why = rules.record_problem(kind, record)
	if why:
		frappe.throw(why)
	existing = frappe.db.get_value(LOG, {"rule": rule.name, "reference_doctype": doctype, "reference_name": name, "status": rules.PENDING_APPROVAL}, "name")
	if existing:
		return {"log": existing}
	phone, _party = recipient(kind, record)
	if not phone:
		frappe.throw(_("There is no usable phone number on this record or its contact."))
	count = len(_history(rule.name, doctype, name)) + 1
	log = _make_log(rule, doctype, name, f"manual-{count}", phone, rules.PENDING_APPROVAL)
	if not log:
		frappe.throw(_("A message for this record was already prepared today."))
	return {"log": log.name}
