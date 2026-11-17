"""Who goes into a campaign Set, and who is left out and why. No Frappe import, so it is tested offline.

A Set is built once from a ticked list of Customers or Leads and then locked. This module decides, for each person,
whether they are IN the Set or LEFT OUT, and says why in plain words. The glue (waba.campaigns) reads the people from
the database and calls build_set; the send-time checks of the campaign itself arrive with the engine (W4b) and never
trust this result alone, because a person may opt out after the Set was made.

Reasons, checked in this order (the first that applies is the one shown):
  no_phone      no number that WhatsApp can use (none, or an Indian landline)
  opted_out     replied STOP, said no to WhatsApp, or the record says "do not contact"
  marketing_no  replied STOP PROMO or said no to marketing messages
  no_consent    the audience rule asks for a consent this person has not given
  duplicate     the same number as an earlier person in the list (the first one stays)
"""

from waba.rules import phone as phone_rules

NO_PHONE = "no_phone"
OPTED_OUT = "opted_out"
MARKETING_NO = "marketing_no"
NO_CONSENT = "no_consent"
DUPLICATE = "duplicate"

REASONS = (NO_PHONE, OPTED_OUT, MARKETING_NO, NO_CONSENT, DUPLICATE)

LABELS = {
	NO_PHONE: "No usable WhatsApp number",
	OPTED_OUT: "Asked not to be contacted",
	MARKETING_NO: "Opted out of promotions",
	NO_CONSENT: "Has not given the required consent",
	DUPLICATE: "Same number as someone already in the Set",
}

# the choices of Waba Settings > Campaign audience rule
RULE_EVERYONE = "Everyone"
RULE_GENERAL = "General consent Yes"
RULE_MARKETING = "Marketing consent Yes"
RULES = (RULE_EVERYONE, RULE_GENERAL, RULE_MARKETING)

MAX_SET_SIZE = 20000

YES = "Yes"
NO = "No"


def label(reason):
	return LABELS.get(reason, reason)


def exclusion_reason(candidate, rule=RULE_EVERYONE):
	"""The reason this person cannot be in a Set, or None. Does not look at other people (see build_set for duplicates).

	`candidate` keys (all optional): phone ("+<digits>" or empty), service_consent, marketing_consent ("Yes", "No" or
	"Unknown"), flag (the record says do-not-contact), phone_opted_out, phone_marketing_opted_out (the number replied STOP
	or STOP PROMO to a business number)."""
	if not candidate.get("phone") or not phone_rules.is_mobile_like(candidate["phone"]):
		return NO_PHONE
	if candidate.get("flag") or candidate.get("phone_opted_out") or candidate.get("service_consent") == NO:
		return OPTED_OUT
	if candidate.get("phone_marketing_opted_out") or candidate.get("marketing_consent") == NO:
		return MARKETING_NO
	if rule == RULE_GENERAL and candidate.get("service_consent") != YES:
		return NO_CONSENT
	if rule == RULE_MARKETING and candidate.get("marketing_consent") != YES:
		return NO_CONSENT
	return None


def build_set(candidates, rule=RULE_EVERYONE):
	"""Split `candidates` (dicts with "party" and "name" plus the keys of exclusion_reason) into who is in and who is out.

	Returns {"included": [{"party", "name", "phone"}], "excluded": [{"party", "name", "phone", "reason", "label"}],
	"counts": {reason: n}}. The order of the input is kept; of two people on one number the first stays."""
	included, excluded, taken = [], [], set()
	counts = {reason: 0 for reason in REASONS}
	for c in candidates:
		reason = exclusion_reason(c, rule)
		if reason is None and c["phone"] in taken:
			reason = DUPLICATE
		if reason is None:
			taken.add(c["phone"])
			included.append({"party": c["party"], "name": c.get("name") or c["party"], "phone": c["phone"]})
			continue
		counts[reason] += 1
		excluded.append(
			{"party": c["party"], "name": c.get("name") or c["party"], "phone": c.get("phone") or "", "reason": reason, "label": label(reason)}
		)
	return {"included": included, "excluded": excluded, "counts": counts}


def rule_or_default(value):
	"""The audience rule from Waba Settings, or "Everyone" when it is blank or not one of the known choices."""
	return value if value in RULES else RULE_EVERYONE


def summary(result):
	"""One plain sentence for the review window."""
	n_in, n_out = len(result["included"]), len(result["excluded"])
	text = f"{n_in} can be messaged"
	if n_out:
		text += f", {n_out} left out"
	return text + "."


def mask_phone(phone):
	"""+91 ******3210 style, for lists that other people may read."""
	digits = str(phone or "")
	return digits[:3] + "*" * max(0, len(digits) - 7) + digits[-4:] if len(digits) > 7 else digits


# ================================================================================================ W4b: the campaign itself
# Everything below is pure (no database): the engine in waba.campaign_engine reads the facts and asks these questions.

import calendar
import datetime

from waba.rules import consent as consent_rules
from waba.rules import errors as error_rules
from waba.rules import notify as notify_rules

# campaign status
DRAFT, PENDING_APPROVAL, SCHEDULED, RUNNING, PAUSED, DONE, CANCELLED, REJECTED = (
	"Draft", "Pending approval", "Scheduled", "Running", "Paused", "Done", "Cancelled", "Rejected",
)
# recipient status
R_PENDING, R_QUEUED, R_SENT, R_DELIVERED, R_READ, R_REPLIED, R_SKIPPED, R_FAILED, R_LIMITED = (
	"Pending", "Queued", "Sent", "Delivered", "Read", "Replied", "Skipped", "Failed", "Limited by Meta",
)
R_FINAL = (R_SENT, R_DELIVERED, R_READ, R_REPLIED, R_SKIPPED, R_FAILED, R_LIMITED)

NOW, LATER, RECURRING = "Now", "Later", "Recurring"
DAILY, WEEKLY, MONTHLY = "Daily", "Weekly", "Monthly"

DEFAULT_START_HOUR, DEFAULT_END_HOUR = 9, 20
DEFAULT_SPEED = 30
DEFAULT_FAILURE_STREAK = 20
DEFAULT_RESERVED = 20  # percent of the daily first-contact allowance kept for notifications and reps
DEFAULT_RATE_MARKETING, DEFAULT_RATE_UTILITY, DEFAULT_GST = 0.8631, 0.115, 18.0  # vendor-reported, UNVERIFIED: editable in Waba Settings
MARKETING, UTILITY = "MARKETING", "UTILITY"

LIVE = (SCHEDULED, RUNNING)


def check_consent(category, consent, marketing_consent, opted_out, marketing_blocked, rule=RULE_EVERYONE, has_written_before=False):
	"""(ok, code, plain words) for sending a campaign message to one person. STOP, a no and STOP PROMO (for a Marketing
	template) always block; beyond that the audience rule decides. Authentication templates never go in a campaign."""
	category = (category or "").upper()
	if category not in (MARKETING, UTILITY):
		return False, "category", "Only Marketing and Utility templates can be used in a campaign."
	if opted_out or consent == NO:
		return False, consent_rules.OPTED_OUT, "This customer has opted out of WhatsApp messages."
	if category == MARKETING and (marketing_blocked or marketing_consent == NO):
		return False, consent_rules.MARKETING_OPTED_OUT, "This customer has opted out of marketing messages."
	if rule == RULE_GENERAL and consent != YES and not has_written_before:
		return False, consent_rules.NO_CONSENT, "There is no WhatsApp consent on this customer's record."
	if rule == RULE_MARKETING and category == MARKETING and marketing_consent != YES:
		return False, consent_rules.NO_MARKETING_CONSENT, "There is no marketing consent on this customer's record."
	return True, None, None


def in_allowed_hours(now, start_hour=DEFAULT_START_HOUR, end_hour=DEFAULT_END_HOUR):
	"""True when `now` (local) is from start_hour up to, not including, end_hour. Blank hours use 9 to 20."""
	start = DEFAULT_START_HOUR if start_hour in (None, "") else int(start_hour)
	end = DEFAULT_END_HOUR if end_hour in (None, "") else int(end_hour)
	if start == end:
		return True
	if start < end:
		return start <= now.hour < end
	return now.hour >= start or now.hour < end  # an overnight window


def daily_allowance(limit, reserved_percent=DEFAULT_RESERVED):
	"""How many NEW conversations a campaign may open in 24 hours: the portfolio limit less the share kept for notifications
	and reps. None means unlimited."""
	if limit is None:
		return None
	keep = min(max(int(reserved_percent if reserved_percent not in (None, "") else DEFAULT_RESERVED), 0), 90)
	return max(int(limit) - int(limit) * keep // 100, 1)


def remaining_budget(limit, started_24h, reserved_percent=DEFAULT_RESERVED):
	"""New conversations still allowed now (None = unlimited)."""
	allowance = daily_allowance(limit, reserved_percent)
	return None if allowance is None else max(allowance - int(started_24h), 0)


def batch_size(speed_per_minute, pending, budget):
	"""How many recipients to send this minute: the speed, but never more than are pending or than the budget allows."""
	speed = int(speed_per_minute) if speed_per_minute not in (None, "", 0) else DEFAULT_SPEED
	n = min(max(speed, 1), int(pending))
	return n if budget is None else min(n, max(int(budget), 0))


def days_needed(people, limit, reserved_percent=DEFAULT_RESERVED, used_now=0):
	"""How many calendar days a Set of `people` needs given the daily allowance (1 when it fits today)."""
	allowance = daily_allowance(limit, reserved_percent)
	if allowance is None or people <= 0:
		return 1
	today_left = max(allowance - int(used_now), 0)
	if people <= today_left:
		return 1
	rest = people - today_left
	return 1 + -(-rest // allowance)


def pause_reason(failure_streak, threshold, quality):
	"""Why a running campaign must stop by itself, or None. A red quality rating or a long run of failures."""
	if str(quality or "").upper() == "RED":
		return "The number's quality rating turned red. Sending was paused to protect the number."
	limit = int(threshold) if threshold not in (None, "") else DEFAULT_FAILURE_STREAK
	if limit > 0 and int(failure_streak) >= limit:
		return f"{int(failure_streak)} messages failed in a row. Sending was paused; check the number, the template and the Error Log."
	return None


def failure_streak(recent_statuses):
	"""Failures in a row at the end of `recent_statuses` (oldest first). Sent, Delivered, Read and Replied end a streak;
	Skipped and Limited by Meta are neither."""
	streak = 0
	for status in reversed(list(recent_statuses)):
		if status == R_FAILED:
			streak += 1
		elif status in (R_SENT, R_DELIVERED, R_READ, R_REPLIED):
			break
	return streak


def classify_error(code):
	"""What to do with a recipient after Meta refused its message: R_LIMITED (Meta's marketing cap: never retry),
	"retry" (back off and try again later) or R_FAILED."""
	action = error_rules.classify(code)[0]
	if action == error_rules.DO_NOT_RETRY_24H:
		return R_LIMITED
	if action in (error_rules.BACKOFF_RETRY, error_rules.RETRY_LATER):
		return "retry"
	return R_FAILED


def next_run(last, recurrence):
	"""The date after `last` for Daily, Weekly or Monthly (a monthly run on the 31st falls on a short month's last day)."""
	if recurrence == DAILY:
		return last + datetime.timedelta(days=1)
	if recurrence == WEEKLY:
		return last + datetime.timedelta(days=7)
	if recurrence == MONTHLY:
		year, month = (last.year + (last.month == 12), 1 if last.month == 12 else last.month + 1)
		return datetime.date(year, month, min(last.day, calendar.monthrange(year, month)[1]))
	return None


def run_dates(first, recurrence, ends_on=None, max_runs=None, limit=400):
	"""Every run date from `first`: one for a single send; for a series up to `ends_on` and/or `max_runs` (at least one end)."""
	if recurrence not in (DAILY, WEEKLY, MONTHLY):
		return [first]
	if not ends_on and not max_runs:
		return []
	out, day = [], first
	while len(out) < limit and (not ends_on or day <= ends_on) and (not max_runs or len(out) < int(max_runs)):
		out.append(day)
		day = next_run(day, recurrence)
	return out


def estimate_cost(people, category, rate_marketing=DEFAULT_RATE_MARKETING, rate_utility=DEFAULT_RATE_UTILITY, gst_percent=DEFAULT_GST):
	"""{"each", "subtotal", "gst", "total"} in rupees for `people` messages of `category`. A rough forecast: Meta's invoice is the truth."""
	each = float(rate_marketing if str(category).upper() == MARKETING else rate_utility)
	subtotal = round(each * int(people), 2)
	gst = round(subtotal * float(gst_percent) / 100, 2)
	return {"each": each, "subtotal": subtotal, "gst": gst, "total": round(subtotal + gst, 2)}


def template_warnings(category, buttons):
	"""Plain-words warnings for the review: a Marketing template with no quick-reply button that lets people stop promotions."""
	out = []
	if str(category).upper() == MARKETING:
		quick = [b for b in (buttons or []) if str(b.get("type") or "").upper() == "QUICK_REPLY"]
		if not any("stop" in str(b.get("text") or "").lower() for b in quick):
			out.append("This Marketing template has no \"Stop promotions\" button. People can still reply STOP PROMO, but a button is easier for them and protects your number. Copy the template as a new draft and add one.")
	return out


def recipient_held(*, test_list, phone):
	"""A recipient that must not receive the message now, as (code, words), or None. Test mode: only the numbers on the
	test list (Waba Settings) may receive a campaign."""
	if not notify_rules.in_test_list(phone, test_list):
		return "test_mode", "Test mode is on and this phone is not on the test list."
	return None


def can_pause(status):
	return status in (SCHEDULED, RUNNING)


def can_resume(status):
	return status == PAUSED


def can_cancel(status):
	return status in (SCHEDULED, RUNNING, PAUSED, PENDING_APPROVAL, DRAFT)


def counters(statuses):
	"""Totals for the campaign card from recipient statuses: attempted (sent or failed), sent, delivered, read, replied,
	limited, other failures, skipped, pending. 'sent' counts every message Meta accepted (a delivered one was also sent)."""
	c = {k: 0 for k in ("total", "pending", "attempted", "sent", "delivered", "read", "replied", "limited", "failed", "skipped")}
	for s in statuses:
		c["total"] += 1
		if s in (R_PENDING, R_QUEUED):
			c["pending"] += 1
		elif s == R_SKIPPED:
			c["skipped"] += 1
		else:
			c["attempted"] += 1
			if s == R_LIMITED:
				c["limited"] += 1
			elif s == R_FAILED:
				c["failed"] += 1
			else:
				c["sent"] += 1
				if s in (R_DELIVERED, R_READ, R_REPLIED):
					c["delivered"] += 1
				if s in (R_READ, R_REPLIED):
					c["read"] += 1
				if s == R_REPLIED:
					c["replied"] += 1
	return c
