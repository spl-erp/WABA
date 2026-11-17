"""Run without a site:  python -m unittest waba.tests.test_campaign_run

W4b: the pure rules a running campaign obeys (consent, hours, daily allowance, spreading, safety pauses, recurrence,
cost, counters) and the wiring of the engine, API and screens."""

import datetime as dt
import json
import os
import re
import unittest

from waba.rules import campaign as c

APP = os.path.join(os.path.dirname(__file__), "..")


def read(*parts):
	with open(os.path.join(APP, *parts), encoding="utf-8") as handle:
		return handle.read()


class TestConsent(unittest.TestCase):
	def ok(self, category="MARKETING", **kw):
		args = dict(consent="Unknown", marketing_consent="Unknown", opted_out=False, marketing_blocked=False)
		args.update(kw)
		return c.check_consent(category, **args)[0]

	def test_everyone_rule_lets_unknown_consent_through(self):
		self.assertTrue(self.ok())
		self.assertTrue(self.ok("UTILITY"))

	def test_authentication_never_goes(self):
		self.assertFalse(self.ok("AUTHENTICATION"))

	def test_stop_always_blocks(self):
		for rule in c.RULES:
			self.assertFalse(self.ok(opted_out=True, rule=rule))
		self.assertFalse(self.ok(consent="No"))

	def test_stop_promo_blocks_marketing_only(self):
		self.assertFalse(self.ok("MARKETING", marketing_blocked=True))
		self.assertTrue(self.ok("UTILITY", marketing_blocked=True))
		self.assertFalse(self.ok("MARKETING", marketing_consent="No"))

	def test_stricter_rules(self):
		self.assertFalse(self.ok(rule=c.RULE_GENERAL))
		self.assertTrue(self.ok(rule=c.RULE_GENERAL, consent="Yes"))
		self.assertTrue(self.ok(rule=c.RULE_GENERAL, has_written_before=True))
		self.assertFalse(self.ok(rule=c.RULE_MARKETING))
		self.assertTrue(self.ok(rule=c.RULE_MARKETING, marketing_consent="Yes"))
		self.assertTrue(self.ok("UTILITY", rule=c.RULE_MARKETING))


class TestHoursAndBudget(unittest.TestCase):
	def test_allowed_hours(self):
		at = lambda h: dt.datetime(2026, 11, 5, h, 0)
		self.assertTrue(c.in_allowed_hours(at(9)))
		self.assertTrue(c.in_allowed_hours(at(19)))
		self.assertFalse(c.in_allowed_hours(at(20)))
		self.assertFalse(c.in_allowed_hours(at(8)))
		self.assertTrue(c.in_allowed_hours(at(23), 22, 6))  # overnight
		self.assertTrue(c.in_allowed_hours(at(3), 22, 6))
		self.assertFalse(c.in_allowed_hours(at(12), 22, 6))
		self.assertTrue(c.in_allowed_hours(at(3), None, None) is False)

	def test_allowance_keeps_a_share(self):
		self.assertEqual(c.daily_allowance(250, 20), 200)
		self.assertEqual(c.daily_allowance(1000, 0), 1000)
		self.assertIsNone(c.daily_allowance(None))
		self.assertEqual(c.daily_allowance(1, 90), 1)

	def test_remaining_budget(self):
		self.assertEqual(c.remaining_budget(250, 50, 20), 150)
		self.assertEqual(c.remaining_budget(250, 500, 20), 0)
		self.assertIsNone(c.remaining_budget(None, 5))

	def test_batch_never_exceeds_speed_pending_or_budget(self):
		self.assertEqual(c.batch_size(30, 100, None), 30)
		self.assertEqual(c.batch_size(30, 10, None), 10)
		self.assertEqual(c.batch_size(30, 100, 5), 5)
		self.assertEqual(c.batch_size(30, 100, 0), 0)
		self.assertEqual(c.batch_size(None, 100, None), c.DEFAULT_SPEED)

	def test_spreading_over_days(self):
		self.assertEqual(c.days_needed(100, 250, 20), 1)
		self.assertEqual(c.days_needed(200, 250, 20), 1)
		self.assertEqual(c.days_needed(201, 250, 20), 2)
		self.assertEqual(c.days_needed(1000, 250, 20), 5)
		self.assertEqual(c.days_needed(1000, 250, 20, used_now=150), 6)
		self.assertEqual(c.days_needed(1000, None), 1)
		self.assertEqual(c.days_needed(0, 250), 1)


class TestSafetyRails(unittest.TestCase):
	def test_red_quality_pauses(self):
		self.assertIn("red", c.pause_reason(0, 20, "RED"))
		self.assertIsNone(c.pause_reason(0, 20, "GREEN"))
		self.assertIsNone(c.pause_reason(0, 20, ""))

	def test_failure_streak_pauses(self):
		self.assertIsNone(c.pause_reason(19, 20, "GREEN"))
		self.assertIn("20 messages failed", c.pause_reason(20, 20, "GREEN"))
		self.assertIn("20", c.pause_reason(20, None, None))

	def test_streak_counts_failures_at_the_end(self):
		self.assertEqual(c.failure_streak(["Sent", "Failed", "Failed"]), 2)
		self.assertEqual(c.failure_streak(["Failed", "Sent", "Failed"]), 1)
		self.assertEqual(c.failure_streak(["Failed", "Failed", "Read"]), 0)
		self.assertEqual(c.failure_streak(["Failed", "Skipped", "Limited by Meta", "Failed"]), 2)
		self.assertEqual(c.failure_streak([]), 0)

	def test_test_mode_limits_recipients(self):
		self.assertIsNone(c.recipient_held(test_list="", phone="+919000000001"))
		self.assertIsNone(c.recipient_held(test_list="+91 90000 00001", phone="+919000000001"))
		self.assertEqual(c.recipient_held(test_list="+919000000002", phone="+919000000001")[0], "test_mode")

	def test_error_classes(self):
		self.assertEqual(c.classify_error(131049), c.R_LIMITED)
		self.assertEqual(c.classify_error("131049"), c.R_LIMITED)
		self.assertEqual(c.classify_error(130429), "retry")
		self.assertEqual(c.classify_error(131026), c.R_FAILED)
		self.assertEqual(c.classify_error(None), c.R_FAILED)


class TestSchedule(unittest.TestCase):
	def test_next_run(self):
		d = dt.date
		self.assertEqual(c.next_run(d(2026, 11, 5), c.DAILY), d(2026, 11, 6))
		self.assertEqual(c.next_run(d(2026, 11, 5), c.WEEKLY), d(2026, 11, 12))
		self.assertEqual(c.next_run(d(2026, 1, 31), c.MONTHLY), d(2026, 2, 28))
		self.assertEqual(c.next_run(d(2026, 12, 15), c.MONTHLY), d(2027, 1, 15))
		self.assertIsNone(c.next_run(d(2026, 1, 1), "Hourly"))

	def test_run_dates(self):
		d = dt.date
		self.assertEqual(c.run_dates(d(2026, 11, 5), None), [d(2026, 11, 5)])
		self.assertEqual(len(c.run_dates(d(2026, 11, 5), c.DAILY, d(2026, 11, 9))), 5)
		self.assertEqual(len(c.run_dates(d(2026, 11, 5), c.WEEKLY, None, 4)), 4)
		self.assertEqual(c.run_dates(d(2026, 11, 5), c.WEEKLY), [])  # a series needs an end
		self.assertEqual(len(c.run_dates(d(2026, 11, 5), c.DAILY, d(2026, 12, 31), 3)), 3)  # whichever comes first

	def test_state_rules(self):
		self.assertTrue(c.can_pause(c.RUNNING) and not c.can_pause(c.DONE))
		self.assertTrue(c.can_resume(c.PAUSED) and not c.can_resume(c.RUNNING))
		self.assertTrue(c.can_cancel(c.PAUSED) and not c.can_cancel(c.DONE) and not c.can_cancel(c.CANCELLED))


class TestCostAndCounters(unittest.TestCase):
	def test_cost(self):
		m = c.estimate_cost(2000, "MARKETING", 0.8631, 0.115, 18)
		self.assertEqual(m["subtotal"], 1726.2)
		self.assertEqual(m["total"], 2036.92)
		u = c.estimate_cost(500, "UTILITY", 0.8631, 0.115, 18)
		self.assertEqual(u["subtotal"], 57.5)

	def test_counters(self):
		n = c.counters(["Pending", "Queued", "Sent", "Delivered", "Read", "Replied", "Failed", "Limited by Meta", "Skipped"])
		self.assertEqual(n["total"], 9)
		self.assertEqual(n["pending"], 2)
		self.assertEqual(n["attempted"], 6)
		self.assertEqual((n["sent"], n["delivered"], n["read"], n["replied"]), (4, 3, 2, 1))
		self.assertEqual((n["limited"], n["failed"], n["skipped"]), (1, 1, 1))

	def test_stop_promotions_warning(self):
		self.assertTrue(c.template_warnings("MARKETING", []))
		self.assertTrue(c.template_warnings("MARKETING", [{"type": "QUICK_REPLY", "text": "Thanks"}]))
		self.assertFalse(c.template_warnings("MARKETING", [{"type": "QUICK_REPLY", "text": "Stop promotions"}]))
		self.assertFalse(c.template_warnings("UTILITY", []))


class TestValueSources(unittest.TestCase):
	from waba.rules import template_vars as tv

	def test_guessing_from_the_label(self):
		g = self.tv.guess_source
		self.assertEqual(g("Customer name")[0], self.tv.CUSTOMER)
		self.assertEqual(g("Customer name")[1], "Sir/Madam")
		self.assertEqual(g("Agent name")[0], self.tv.SENDER)
		self.assertEqual(g("Sender")[0], self.tv.SENDER)
		self.assertEqual(g("Offer date")[0], self.tv.TODAY)
		self.assertEqual(g("Offer code", "SAVE10")[0], self.tv.LITERAL)
		self.assertEqual(g("Body value 1")[0], self.tv.LITERAL)

	def test_a_stand_in_covers_a_record_with_no_value(self):
		rows = [{"slot": "body.1", "source_type": self.tv.CUSTOMER, "fallback": "Sir/Madam"}, {"slot": "body.2", "source_type": self.tv.RECORD, "source": "city", "fallback": "your city"}]
		values, missing = self.tv.resolve(rows, {"customer_name": "", "record": {}})
		self.assertEqual(values, {"body.1": "Sir/Madam", "body.2": "your city"})
		self.assertEqual(missing, [])
		values, _m = self.tv.resolve(rows, {"customer_name": "Ravi", "record": {"city": "Pune"}})
		self.assertEqual(values, {"body.1": "Ravi", "body.2": "Pune"})

	def test_without_a_stand_in_an_empty_value_is_missing(self):
		values, missing = self.tv.resolve([{"slot": "body.1", "source_type": self.tv.CUSTOMER}], {"customer_name": ""})
		self.assertEqual(missing, ["body.1"])

	def test_a_stand_in_is_not_used_for_fixed_sources(self):
		values, missing = self.tv.resolve([{"slot": "body.1", "source_type": self.tv.SENDER, "fallback": "x"}], {"sender": ""})
		self.assertEqual(missing, ["body.1"])

	def test_choices_are_checked(self):
		p = self.tv.row_problem
		self.assertIsNone(p({"source_type": "Customer name", "fallback": "Sir/Madam"}))
		self.assertIn("stand-in", p({"source_type": "Customer name", "fallback": ""}) .replace("use when a person's record has no value", "stand-in") or "stand-in")
		self.assertTrue(p({"source_type": "Customer name", "fallback": ""}))
		self.assertTrue(p({"source_type": "Literal", "source": " "}))
		self.assertIsNone(p({"source_type": "Literal", "source": "SAVE10"}))
		self.assertTrue(p({"source_type": "Record field", "source": "", "fallback": "x"}))
		self.assertTrue(p({"source_type": "Shared file", "source": ""}))
		self.assertTrue(p({"source_type": "Nonsense"}))
		self.assertIsNone(p({"source_type": "Sender name"}))
		self.assertIsNone(p({"source_type": "Today"}))


class TestWiring(unittest.TestCase):
	ENGINE = read("campaign_engine.py")
	API = read("api", "campaigns.py")
	SEND = read("api", "send.py")
	FORM = read("waba", "doctype", "waba_campaign", "waba_campaign.js")

	def test_a_tick_runs_every_minute(self):
		hooks = read("hooks.py")
		self.assertRegex(hooks, r'"\* \* \* \* \*":\s*\[\s*"waba\.campaign_engine\.tick"')

	def test_each_recipient_is_claimed_before_it_is_queued(self):
		self.assertIn("claims.claim_and_enqueue(RECIPIENT", self.ENGINE)

	def test_sends_go_through_the_one_automatic_sender_with_origin_campaign(self):
		self.assertIn("send.send_automatic(", self.ENGINE)
		self.assertIn("purposes.CAMPAIGN", self.ENGINE)
		self.assertIn("purposes.CAMPAIGN", self.SEND.split("AUTOMATIC_ORIGINS =")[1].split("\n")[0])

	def test_campaign_consent_uses_the_campaign_rule(self):
		self.assertIn("check_campaign_template(", self.SEND)

	def test_the_job_rechecks_state_test_mode_and_budget(self):
		body = self.ENGINE.split("def _send_one(")[1].split("\ndef on_status")[0]
		for needle in ("camp.status != rules.RUNNING", "recipient_held(", "budget_for("):
			self.assertIn(needle, body)

	def test_the_tick_checks_the_rails(self):
		body = self.ENGINE.split("def _tick_one(")[1].split("\n# ----")[0]
		for needle in ("pause_reason(", "in_allowed_hours(", "backoff_until", "budget_for(", "batch_size("):
			self.assertIn(needle, body)

	def test_meta_limits_are_never_retried_and_backoff_pauses_the_campaign_briefly(self):
		body = self.ENGINE.split("def _send_one(")[1]
		self.assertIn("classify_error(", body)
		self.assertIn("BACKOFF_MINUTES", body)

	def test_status_updates_and_inbound_tell_the_engine(self):
		self.assertIn("campaign_engine.on_status", read("status_updates.py"))
		self.assertIn("campaign_engine.on_inbound", read("inbound.py"))

	def test_submit_needs_the_typed_name_and_the_owner(self):
		body = self.API.split("def submit(")[1].split("\ndef _admin_only")[0]
		self.assertIn("confirm_name", body)
		self.assertIn("owner_only=True", body)

	def test_every_write_is_post_and_checks_the_caller(self):
		for name in ("save_values", "send_test", "submit", "approve", "reject", "pause", "resume", "cancel", "reschedule", "set_message"):
			deco = re.search(r"@frappe\.whitelist\(([^)]*)\)\s*\ndef %s\(" % name, self.API)
			self.assertIsNotNone(deco, name)
			self.assertIn("POST", deco.group(1), name)

	def test_approval_is_for_waba_admins_only(self):
		self.assertIn("is_admin(", self.API.split("def _admin_only(")[1].split("\n@frappe")[0])

	def test_the_form_calls_only_real_methods(self):
		used = set(re.findall(r"waba\.api\.campaigns\.(\w+)", self.FORM + read("waba", "doctype", "waba_recipient_set", "waba_recipient_set.js")))
		defined = set(re.findall(r"\ndef (\w+)\(", self.API))
		self.assertTrue(used)
		self.assertFalse(used - defined, used - defined)

	def test_the_form_escapes_and_confirms(self):
		self.assertIn("escape_html", self.FORM)
		self.assertIn("confirm_name", self.FORM)
		self.assertIn("Type the campaign", self.FORM)

	def test_doctypes_are_visible_to_creator_and_admin_only(self):
		for name in ("waba_campaign", "waba_campaign_recipient"):
			definition = json.loads(read("waba", "doctype", name, name + ".json"))
			roles = {p["role"] for p in definition["permissions"]}
			self.assertEqual(roles, {"Waba Campaign Manager", "Waba Admin"})
		self.assertIn("waba.permissions.campaign_query_conditions", read("hooks.py"))

	def test_the_engine_resolves_each_person_with_the_campaigns_own_choices(self):
		body = self.ENGINE.split("def _send_one(")[1]
		self.assertIn("parse_sources(", body)
		self.assertIn("rows_override=", body)
		self.assertIn("sender_name(", body)

	def test_save_values_validates_every_choice(self):
		body = self.API.split("def save_values(")[1].split("\ndef _estimate")[0]
		self.assertIn("row_problem(", body)
		self.assertIn("_rows_override(", body)

	def test_the_dialog_types_nothing_per_person(self):
		form = self.FORM
		self.assertIn("Each person's name", form)
		self.assertIn("Sir/Madam", form)
		self.assertNotIn("WabaTemplateForm", form)

	def test_settings_fields_exist(self):
		fields = {f["fieldname"] for f in json.loads(read("waba", "doctype", "waba_settings", "waba_settings.json"))["fields"]}
		for f in ("campaigns_need_approval", "campaign_hours_start", "campaign_hours_end", "campaign_speed", "campaign_failure_streak", "campaign_reserved_percent", "campaign_reply_days", "rate_marketing", "rate_utility", "gst_percent"):
			self.assertIn(f, fields)

	def test_message_and_conversation_carry_the_campaign(self):
		msg = {f["fieldname"] for f in json.loads(read("waba", "doctype", "waba_message", "waba_message.json"))["fields"]}
		self.assertTrue({"campaign", "campaign_recipient"} <= msg)
		conv = {f["fieldname"] for f in json.loads(read("waba", "doctype", "waba_conversation", "waba_conversation.json"))["fields"]}
		self.assertIn("last_campaign", conv)


if __name__ == "__main__":
	unittest.main()
