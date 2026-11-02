"""When an automatic WhatsApp notification is due, and when it must be held back (no Frappe, tested offline).

Three message types, each with its own rule record (see the Waba Notification Rule doctype):

  Quotation follow-up       a submitted quotation still open `days_after` days after its date
  Payment reminder          a submitted invoice with money outstanding `days_after` days after its due date, then every
                            `repeat_every_days` up to `max_sends`
  Enquiry acknowledgement   a new Lead, within `ack_within_minutes` of being created

A rule with a timing left at 0 (blank), no template or no number is never evaluated (`rule_problems` says why), so nothing
runs until the owner has filled it in. Every decision is re-checked when the message is about to go (`record_problem`), so
a quotation that was ordered meanwhile or an invoice that was paid is never chased.
"""

import datetime
import hashlib
import re

QUOTATION = "Quotation follow-up"
PAYMENT = "Payment reminder"
ENQUIRY = "Enquiry acknowledgement"
TYPES = (QUOTATION, PAYMENT, ENQUIRY)

MANUAL = "Manual"
AUTOMATIC = "Automatic"

PENDING_APPROVAL = "Pending approval"
QUEUED = "Queued"
SENDING = "Sending"
SENT = "Sent"
SKIPPED = "Skipped"
FAILED = "Failed"
CANCELLED = "Cancelled"
OPEN_STATES = (PENDING_APPROVAL, QUEUED, SENDING)  # still waiting to go out

QUOTATION_OPEN = ("Open", "Replied")
LEAD_STOP_STATUS = ("Do Not Contact", "Converted")


def _n(value):
	try:
		return int(value or 0)
	except (TypeError, ValueError):
		return 0


def rule_problems(rule):
	"""Plain-words list of what a rule still needs before it can run (empty = ready)."""
	problems = []
	kind = rule.get("message_type")
	if kind not in TYPES:
		return ["Choose the kind of message."]
	if not rule.get("waba_number"):
		problems.append("Choose the WhatsApp number to send from.")
	if not rule.get("template"):
		problems.append("Choose an approved Utility template.")
	if kind == QUOTATION and _n(rule.get("days_after")) < 1:
		problems.append("Set how many days after the quotation date to follow up (at least 1).")
	if kind == PAYMENT:
		if _n(rule.get("days_after")) < 1:
			problems.append("Set how many days after the due date to send the first reminder (at least 1).")
		if _n(rule.get("max_sends")) < 1:
			problems.append("Set the most reminders to send for one invoice (at least 1).")
		elif _n(rule.get("max_sends")) > 1 and _n(rule.get("repeat_every_days")) < 1:
			problems.append("Set how many days between reminders (at least 1).")
	if kind == ENQUIRY and _n(rule.get("ack_within_minutes")) < 1:
		problems.append("Set how many minutes after a new enquiry the acknowledgement may still be sent (at least 1).")
	return problems


def initial_status(mode):
	return QUEUED if mode == AUTOMATIC else PENDING_APPROVAL


# ------------------------------------------------------------------------------------------------ record state


def record_problem(kind, doc):
	"""Why the record no longer calls for this message ('' when it does). Used when scanning and again just before sending."""
	if kind == QUOTATION:
		if doc.get("docstatus") != 1:
			return "The quotation is not submitted."
		if doc.get("status") not in QUOTATION_OPEN:
			return f"The quotation is {doc.get('status') or 'no longer open'}."
		return ""
	if kind == PAYMENT:
		if doc.get("docstatus") != 1:
			return "The invoice is not submitted."
		if doc.get("is_return"):
			return "This is a return, not an invoice to collect."
		if not (float(doc.get("outstanding_amount") or 0) > 0):
			return "Nothing is outstanding on the invoice any more."
		return ""
	if kind == ENQUIRY:
		if doc.get("status") in LEAD_STOP_STATUS:
			return f"The lead is marked {doc.get('status')}."
		if doc.get("disabled"):
			return "The lead is disabled."
		if doc.get("unsubscribed"):
			return "The lead has unsubscribed."
		if doc.get("customer"):
			return "The lead has already become a customer."
		return ""
	return "Unknown message type."


# ------------------------------------------------------------------------------------------------ schedule


def schedule_due(start, history, today, repeat_every_days, max_sends, lookback_days=None):
	"""(due, why-not). `start` is the first day the message may go; `history` the dates of the sends already made or queued.
	`lookback_days`: a record whose first moment is older than this is left alone, so switching a rule on never sends to
	years-old quotations or invoices."""
	count = len(history)
	if count >= max(1, _n(max_sends)):
		return False, "The most allowed for this record has been reached."
	if count == 0:
		if today < start:
			return False, f"Not due until {start.isoformat()}."
		if lookback_days and (today - start).days > _n(lookback_days):
			return False, f"Older than the {_n(lookback_days)}-day lookback, so it is left alone."
		return True, ""
	repeat = _n(repeat_every_days)
	if repeat < 1:
		return False, "Already sent once and no repeat is set."
	next_day = max(history) + datetime.timedelta(days=repeat)
	return (today >= next_day), ("" if today >= next_day else f"The next one is due on {next_day.isoformat()}.")


def quotation_event(doc, rule, history, today):
	"""(event key or None, why-not) for a quotation."""
	why = record_problem(QUOTATION, doc)
	if why:
		return None, why
	date = _as_date(doc.get("transaction_date"))
	if not date:
		return None, "The quotation has no date."
	due, reason = schedule_due(date + datetime.timedelta(days=_n(rule.get("days_after"))), history, today, rule.get("repeat_every_days"), _n(rule.get("max_sends")) or 1, rule.get("lookback_days"))
	return (f"followup-{len(history) + 1}" if due else None), reason


def invoice_event(doc, rule, history, today):
	"""(event key or None, why-not) for a sales invoice."""
	why = record_problem(PAYMENT, doc)
	if why:
		return None, why
	date = _as_date(doc.get("due_date"))
	if not date:
		return None, "The invoice has no due date."
	due, reason = schedule_due(date + datetime.timedelta(days=_n(rule.get("days_after"))), history, today, rule.get("repeat_every_days"), _n(rule.get("max_sends")) or 1, rule.get("lookback_days"))
	return (f"reminder-{len(history) + 1}" if due else None), reason


def lead_event(doc, rule, history, now):
	"""('ack' or None, why-not) for a lead: once only, and only while the lead is fresh."""
	why = record_problem(ENQUIRY, doc)
	if why:
		return None, why
	if history:
		return None, "Already acknowledged."
	created = doc.get("creation")
	if isinstance(created, str):
		created = _as_datetime(created)
	if created and now - created > datetime.timedelta(minutes=_n(rule.get("ack_within_minutes"))):
		return None, "The enquiry is older than the acknowledgement window."
	return "ack", ""


def _as_date(value):
	if isinstance(value, datetime.datetime):
		return value.date()
	if isinstance(value, datetime.date):
		return value
	try:
		return datetime.date.fromisoformat(str(value)[:10])
	except (TypeError, ValueError):
		return None


def _as_datetime(value):
	try:
		return datetime.datetime.fromisoformat(str(value))
	except (TypeError, ValueError):
		return None


# ------------------------------------------------------------------------------------------------ holding back


def dedupe_key(rule, doctype, name, event, phone, local_date):
	"""One message of one kind to one person about one record on one day: the database refuses a second."""
	raw = "|".join(str(x) for x in (rule, doctype, name, event, phone, local_date))
	return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def digits(value):
	return re.sub(r"\D", "", str(value or ""))


def in_test_list(phone, allow_text):
	"""True when no test list is set, or the phone is on it (compared by digits, so +91 98... and 9198... match)."""
	wanted = [digits(p) for p in re.split(r"[\n,;]+", str(allow_text or "")) if digits(p)]
	if not wanted:
		return True
	return digits(phone) in wanted


def hourly_cap_reached(sent_last_hour, max_per_hour):
	limit = _n(max_per_hour)
	return limit > 0 and sent_last_hour >= limit


def customer_cap_reached(sent_today, max_per_day):
	limit = _n(max_per_day) or 1
	return sent_today >= limit


def hold_reason(*, enabled, rule_enabled, mode, receive_only, number_ok, quiet_ok, phone, test_list, sent_last_hour, max_per_hour, sent_today, max_per_day):
	"""The first reason an AUTOMATIC send must wait or be skipped, as (code, plain words) or None when it may go. Manual
	sends are approved by a person and only ever refused for the hard reasons (switches, receive-only, test list)."""
	if not enabled:
		return "switch_off", "WhatsApp notifications are switched off in Waba Settings."
	if not rule_enabled:
		return "rule_off", "This rule is switched off."
	if receive_only:
		return "receive_only", "The number is set to receive only, so nothing can be sent from it."
	if not number_ok:
		return "number", "The number is switched off or not set up for notifications."
	if not in_test_list(phone, test_list):
		return "test_mode", "Test mode is on and this phone is not on the test list."
	if mode == AUTOMATIC:
		if not quiet_ok:
			return "quiet_hours", "Outside the number's business hours; it will be tried again."
		if hourly_cap_reached(sent_last_hour, max_per_hour):
			return "hourly_cap", "The hourly sending limit was reached; it will be tried again."
		if customer_cap_reached(sent_today, max_per_day):
			return "customer_cap", "This customer already received the allowed number of notifications today."
	return None


def retry_later(code):
	"""Holds that clear by themselves (the log stays queued) versus ones that end the attempt."""
	return code in ("quiet_hours", "hourly_cap")


def pick_phone(phones):
	"""The first usable phone key from parties.phones()-style dicts, or None."""
	for p in phones or []:
		if p.get("key"):
			return p["key"]
	return None
