"""Run campaigns: start each run, send the recipients a few at a time, and stop by itself when something is wrong.

A scheduler tick every minute does the work. Each tick, for each Scheduled or Running campaign: start a due run (one
recipient row per person in the locked Set), then check the safety rails (the number's quality, a run of failures,
allowed hours, Meta's daily allowance for new chats, a back-off Meta asked for), then claim a small batch of
recipients and queue one job each (claims.claim_and_enqueue: each person is sent exactly once). The job re-checks
everything (the campaign still running, test mode, opt-outs inside waba.api.send) and sends through the same
`send_automatic` every notification uses, with the origin Campaign. The decisions are waba.rules.campaign."""

import json

import frappe
from frappe import _
from frappe.utils import add_to_date, cint, get_datetime, getdate, now_datetime, strip_html_tags

from waba import assignment, campaigns, claims, inbound, parties
from waba.api import send
from waba.rules import campaign as rules
from waba.rules import consent as consent_rules
from waba.rules import inbound as rules_inbound
from waba.rules import purposes

CAMPAIGN = "Waba Campaign"
RECIPIENT = "Waba Campaign Recipient"
SET = "Waba Recipient Set"
BACKOFF_MINUTES = 15
STREAK_WINDOW = 60


def _commit():
	if not frappe.flags.get("waba_no_commit"):
		frappe.db.commit()  # nosemgrep


def as_system():
	from waba.notify import as_system as _as_system

	return _as_system()


def _num(value, default):
	"""A Waba Settings number, or the default when it was never set (an unset Single field reads as 0)."""
	return cint(value) or default


def settings():
	"""The campaign settings with their defaults filled in."""
	s = frappe.get_single("Waba Settings")
	start, end = cint(s.campaign_hours_start), cint(s.campaign_hours_end)
	if not start and not end:
		start, end = rules.DEFAULT_START_HOUR, rules.DEFAULT_END_HOUR
	return frappe._dict(
		hours_start=start,
		hours_end=end,
		speed=_num(s.campaign_speed, rules.DEFAULT_SPEED),
		failure_streak=_num(s.campaign_failure_streak, rules.DEFAULT_FAILURE_STREAK),
		reserved=_num(s.campaign_reserved_percent, rules.DEFAULT_RESERVED),
		reply_days=_num(s.campaign_reply_days, 3),
		rate_marketing=s.rate_marketing or rules.DEFAULT_RATE_MARKETING,
		rate_utility=s.rate_utility or rules.DEFAULT_RATE_UTILITY,
		gst=s.gst_percent or rules.DEFAULT_GST,
		needs_approval=bool(s.campaigns_need_approval),
		test_phones=s.test_phones,
		sender_label=s.sender_label,
	)


def hours_of(camp, cfg):
	"""(start, end) hour for a campaign: its own when set, else the settings."""
	start = camp.hours_start if camp.hours_start not in (None, "") and (camp.hours_start or camp.hours_end) else cfg.hours_start
	end = camp.hours_end if camp.hours_end not in (None, "") and (camp.hours_start or camp.hours_end) else cfg.hours_end
	return start, end


def speed_of(camp, cfg):
	return cint(camp.speed_per_minute) or cfg.speed


# ------------------------------------------------------------------------------------------------ facts about the number


def portfolio_of(number):
	account = frappe.db.get_value("Waba Number", number, "account")
	return frappe.db.get_value("Waba Account", account, "portfolio") if account else None


def budget_for(number, cfg):
	"""New conversations the campaign may still open now (None = unlimited)."""
	portfolio = portfolio_of(number)
	limit = consent_rules.daily_limit(frappe.db.get_value("Waba Portfolio", portfolio, "messaging_tier")) if portfolio else consent_rules.DEFAULT_LIMIT
	return rules.remaining_budget(limit, parties.started_in_24h(portfolio) if portfolio else 0, cfg.reserved), limit


def streak_of(campaign):
	rows = frappe.get_all(
		RECIPIENT,
		filters={"campaign": campaign, "is_test": 0, "status": ["in", [rules.R_SENT, rules.R_DELIVERED, rules.R_READ, rules.R_REPLIED, rules.R_FAILED]]},
		pluck="status",
		order_by="modified desc",
		limit_page_length=STREAK_WINDOW,
	)
	return rules.failure_streak(reversed(rows))


# ------------------------------------------------------------------------------------------------ counters


def update_counters(campaign):
	rows = frappe.get_all(RECIPIENT, filters={"campaign": campaign, "is_test": 0}, pluck="status", limit_page_length=0)
	c = rules.counters(rows)
	frappe.db.set_value(
		CAMPAIGN,
		campaign,
		{f"c_{k}": v for k, v in c.items()},
		update_modified=False,
	)
	return c


def _notify_owner(camp, text):
	"""A Notification Log line for the person who made the campaign."""
	try:
		frappe.get_doc(
			{
				"doctype": "Notification Log",
				"for_user": camp.owner,
				"type": "Alert",
				"subject": _("Campaign {0}: {1}").format(camp.title, text),
				"document_type": CAMPAIGN,
				"document_name": camp.name,
			}
		).insert(ignore_permissions=True)
	except Exception:
		frappe.log_error(title="Waba: could not notify the campaign owner")


# ------------------------------------------------------------------------------------------------ starting a run


def start_run(camp, run_on):
	"""One Pending recipient row for each person in the locked Set (once per run date); the campaign is Running."""
	if not frappe.db.exists(RECIPIENT, {"campaign": camp.name, "run_on": run_on, "is_test": 0}):
		members = frappe.get_all("Waba Recipient Set Member", filters={"recipient_set": camp.recipient_set}, fields=["party", "party_name", "phone"], order_by="creation asc", limit_page_length=0)
		now = frappe.utils.now()
		values = [
			(frappe.generate_hash(length=10), now, now, camp.owner, camp.owner, 0, 0, camp.name, run_on, m.party, m.party_name, m.phone, rules.R_PENDING, 0)
			for m in members
		]
		frappe.db.bulk_insert(
			RECIPIENT,
			["name", "creation", "modified", "owner", "modified_by", "docstatus", "idx", "campaign", "run_on", "party", "party_name", "phone", "status", "is_test"],
			values,
			chunk_size=1000,
		)
	values = {"status": rules.RUNNING, "next_run_on": None}
	if not camp.started_on:
		values["started_on"] = now_datetime()
	frappe.db.set_value(CAMPAIGN, camp.name, values, update_modified=False)
	update_counters(camp.name)


def _run_dates(camp):
	first = getdate(camp.start_at)
	return rules.run_dates(first, camp.recurrence if camp.schedule_mode == rules.RECURRING else None, camp.ends_on and getdate(camp.ends_on), camp.max_runs or None)


def due(camp, now):
	"""True when a Scheduled campaign's next run should start now."""
	when = get_datetime(camp.start_at)
	day = getdate(camp.next_run_on) if camp.next_run_on else getdate(when)
	return now >= get_datetime(f"{day} {when.time()}")


def finish_run(camp):
	"""All recipients of this run are done: schedule the next run of a series, or the campaign is Done."""
	runs = cint(camp.runs_done) + 1
	dates = _run_dates(camp)
	if camp.schedule_mode == rules.RECURRING and runs < len(dates):
		frappe.db.set_value(CAMPAIGN, camp.name, {"status": rules.SCHEDULED, "runs_done": runs, "next_run_on": dates[runs]}, update_modified=False)
		_notify_owner(camp, _("run {0} finished; the next run is on {1}.").format(runs, dates[runs]))
	else:
		frappe.db.set_value(CAMPAIGN, camp.name, {"status": rules.DONE, "runs_done": runs, "finished_on": now_datetime()}, update_modified=False)
		_notify_owner(camp, _("finished."))
	update_counters(camp.name)


def pause(camp_name, reason, by_system=True):
	frappe.db.set_value(CAMPAIGN, camp_name, {"status": rules.PAUSED, "pause_reason": reason}, update_modified=False)
	if by_system:
		_notify_owner(frappe.get_doc(CAMPAIGN, camp_name), _("paused. {0}").format(reason))


# ------------------------------------------------------------------------------------------------ the tick


def tick():
	"""Every minute. Returns how many recipients were queued (used by the check script)."""
	queued = 0
	with as_system():
		for name in frappe.get_all(CAMPAIGN, filters={"status": ["in", list(rules.LIVE)]}, pluck="name"):
			try:
				queued += _tick_one(name)
			except Exception:
				frappe.log_error(title=f"Waba: campaign {name} tick failed")
		_commit()
	return queued


def _tick_one(name):
	camp = frappe.get_doc(CAMPAIGN, name)
	cfg = settings()
	now = now_datetime()
	if camp.status == rules.SCHEDULED:
		if not due(camp, now):
			return 0
		if not rules.in_allowed_hours(now, *hours_of(camp, cfg)):
			return 0  # a run waits for the allowed hours
		start_run(camp, getdate(camp.next_run_on) if camp.next_run_on else getdate(camp.start_at))
		camp.reload()
	if camp.backoff_until and get_datetime(camp.backoff_until) > now:
		return 0
	quality = frappe.db.get_value("Waba Number", camp.waba_number, "quality_rating")
	why = rules.pause_reason(streak_of(camp.name), cfg.failure_streak, quality)
	if why:
		pause(camp.name, why)
		return 0
	if not rules.in_allowed_hours(now, *hours_of(camp, cfg)):
		return 0
	pending = frappe.get_all(RECIPIENT, filters={"campaign": camp.name, "is_test": 0, "status": rules.R_PENDING}, pluck="name", order_by="creation asc", limit_page_length=max(speed_of(camp, cfg), 1) * 4)
	in_flight = frappe.db.count(RECIPIENT, {"campaign": camp.name, "is_test": 0, "status": rules.R_QUEUED})
	if not pending and not in_flight:
		finish_run(camp)
		return 0
	if not pending:
		return 0
	budget, _limit = budget_for(camp.waba_number, cfg)
	size = rules.batch_size(speed_of(camp, cfg), len(pending), budget)
	queued = 0
	for rname in pending:
		if queued >= size:
			break
		held = rules.recipient_held(test_list=cfg.test_phones, phone=frappe.db.get_value(RECIPIENT, rname, "phone"))
		if held:
			frappe.db.set_value(RECIPIENT, rname, {"status": rules.R_SKIPPED, "reason": held[1]}, update_modified=False)
			continue
		if claims.claim_and_enqueue(RECIPIENT, rname, "waba.campaign_engine.send_recipient", from_status=rules.R_PENDING, to_status=rules.R_QUEUED):
			queued += 1
	update_counters(camp.name)
	return queued


# ------------------------------------------------------------------------------------------------ sending one person


def _conversation_for(camp, phone, party):
	key = rules_inbound.conversation_key(camp.waba_number, phone, None)
	existed = bool(inbound._find(key))
	conv = inbound._conversation(key, camp.waba_number, {"phone": phone, "bsuid": None, "profile_name": None}, party=party)
	if not existed:
		assignment.add_event(conv.name, _("Started by the campaign {0}.").format(camp.title))
	return conv


def _mark(name, status, reason=None, **more):
	frappe.db.set_value(RECIPIENT, name, {"status": status, "reason": reason, **more}, update_modified=True)


def send_recipient(doctype, name):
	"""The background job for one claimed recipient."""
	with as_system():
		_send_one(name)
		_commit()


def _send_one(name, values_override=None, test=False):
	rec = frappe.get_doc(RECIPIENT, name)
	if rec.status != rules.R_QUEUED:
		return
	camp = frappe.get_doc(CAMPAIGN, rec.campaign)
	if not test:
		if camp.status != rules.RUNNING:
			if camp.status == rules.PAUSED:
				_mark(name, rules.R_PENDING)  # goes out when it is resumed
			else:
				_mark(name, rules.R_SKIPPED, _("The campaign was {0}.").format(camp.status.lower()))
			return
	cfg = settings()
	held = rules.recipient_held(test_list=cfg.test_phones, phone=rec.phone)
	if held:
		return _mark(name, rules.R_SKIPPED, held[1])
	if not test:
		budget, _limit = budget_for(camp.waba_number, cfg)
		if budget is not None and budget <= 0:
			return _mark(name, rules.R_PENDING)  # today's allowance of new chats is used up; tomorrow
	party = (camp.party_doctype, rec.party) if rec.party and not test else None
	conv = _conversation_for(camp, rec.phone, party)
	sources = campaigns.parse_sources(camp.template_values)
	rows = {slot: {"source_type": c["source_type"], "source": c.get("source") or "", "fallback": c.get("fallback") or ""} for slot, c in sources.items()}
	try:
		result = send.send_automatic(conv.name, camp.template, values_override, purposes.CAMPAIGN, campaigns.sender_name(camp.owner, cfg.sender_label), rows_override=None if values_override is not None else rows)
	except (frappe.ValidationError, frappe.PermissionError) as e:
		text = strip_html_tags(str(e)) or _("Refused.")
		if "in the last 24 hours" in text:  # Meta's allowance for new chats: not the person's fault
			return _mark(name, rules.R_PENDING)
		return _mark(name, rules.R_SKIPPED, text, conversation=conv.name)
	except Exception:
		frappe.log_error(title="Waba: campaign message could not be sent")
		return _mark(name, rules.R_FAILED, _("Unexpected error; see the Error Log."), conversation=conv.name)
	message = result.get("message")
	if message:
		frappe.db.set_value("Waba Message", message, {"campaign": camp.name, "campaign_recipient": name}, update_modified=False)
	if result.get("ok"):
		frappe.db.set_value("Waba Conversation", conv.name, "last_campaign", camp.name, update_modified=False)
		_mark(name, rules.R_SENT, None, message=message, conversation=conv.name, sent_at=now_datetime())
	else:
		code = frappe.db.get_value("Waba Message", message, "error_code") if message else None
		outcome = rules.classify_error(code)
		if outcome == "retry":
			_mark(name, rules.R_PENDING, result.get("error"), error_code=code)
			frappe.db.set_value(CAMPAIGN, camp.name, "backoff_until", add_to_date(now_datetime(), minutes=BACKOFF_MINUTES), update_modified=False)
		else:
			_mark(name, outcome, result.get("error"), error_code=code, message=message, conversation=conv.name)
	if not test:
		update_counters(camp.name)


# ------------------------------------------------------------------------------------------------ what happens afterwards


def on_status(message_name, new_status, code=None):
	"""Called when Meta reports on a message: keep the recipient row in step (delivered, read, or failed after all)."""
	rec = frappe.db.get_value("Waba Message", message_name, "campaign_recipient")
	if not rec or not frappe.db.exists(RECIPIENT, rec):
		return
	current, camp = frappe.db.get_value(RECIPIENT, rec, ["status", "campaign"])
	if new_status == "Failed":
		if current in (rules.R_SENT, rules.R_QUEUED):
			outcome = rules.classify_error(code)
			_mark(rec, rules.R_LIMITED if outcome == rules.R_LIMITED else rules.R_FAILED, error_code=str(code or ""))
	elif new_status == "Delivered" and current == rules.R_SENT:
		_mark(rec, rules.R_DELIVERED)
	elif new_status == "Read" and current in (rules.R_SENT, rules.R_DELIVERED):
		_mark(rec, rules.R_READ)
	else:
		return
	update_counters(camp)


def on_inbound(conversation):
	"""A customer wrote: if a campaign message went to this phone on this number within the reply window, they replied to it."""
	days = settings().reply_days
	since = add_to_date(now_datetime(), days=-days)
	row = frappe.db.sql(
		"""select r.name, r.campaign from `tabWaba Campaign Recipient` r join `tabWaba Campaign` c on c.name = r.campaign
		where r.phone = %s and c.waba_number = %s and r.is_test = 0 and r.status in ('Sent', 'Delivered', 'Read') and r.sent_at >= %s
		order by r.sent_at desc limit 1""",
		(conversation.customer_phone, conversation.waba_number, since),
	)
	if not row:
		return
	rec, camp = row[0]
	_mark(rec, rules.R_REPLIED, replied_at=now_datetime())
	frappe.db.set_value("Waba Conversation", conversation.name, "last_campaign", camp, update_modified=False)
	update_counters(camp)
