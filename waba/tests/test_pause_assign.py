"""Run without a site:  python -m unittest waba.tests.test_pause_assign

Automatic re-assignment away from an Away agent is paused behind a Waba Settings switch (off by default)."""

import json
import os
import unittest

APP = os.path.join(os.path.dirname(__file__), "..")


def read(*parts):
	with open(os.path.join(APP, *parts), encoding="utf-8") as handle:
		return handle.read()


ASSIGN = read("assignment.py")


class TestSwitch(unittest.TestCase):
	def test_the_setting_exists_and_is_off_by_default(self):
		fields = {f["fieldname"]: f for f in json.loads(read("waba", "doctype", "waba_settings", "waba_settings.json"))["fields"]}
		self.assertEqual(fields["auto_reassign_away"]["fieldtype"], "Check")
		self.assertIn(fields["auto_reassign_away"].get("default"), (None, "0", 0))

	def test_assign_keeps_the_chat_before_choosing_anyone(self):
		body = ASSIGN.split("def assign(")[1].split("\nREASONS")[0]
		self.assertIn("keep_with_current(", body)
		self.assertLess(body.index("keep_with_current("), body.index("choose_assignee("))

	def test_the_waiting_job_is_a_no_op_while_paused(self):
		body = ASSIGN.split("def assign_waiting(")[1].split("\ndef alert_unanswered")[0]
		self.assertIn("if not auto_reassign_on()", body)  # (also needs the new-chat switch, see TestNewChatsWaitForALead)
		self.assertLess(body.index("auto_reassign_on()"), body.index("frappe.get_all("))

	def test_a_broken_assignment_is_checked_for(self):
		body = ASSIGN.split("def _assignee_valid(")[1].split("\ndef assign(")[0]
		self.assertIn('"enabled"', body)
		self.assertIn("Waba Agent Access", body)

	def test_the_unanswered_alert_is_untouched(self):
		self.assertNotIn("auto_reassign_on", ASSIGN.split("def alert_unanswered(")[1].split("\ndef _notification_log")[0])


if __name__ == "__main__":
	unittest.main()


class TestNewChatsWaitForALead(unittest.TestCase):
	"""Waba Settings > Assign new chats automatically (default on). Off: a chat nobody can take waits for a Team Lead."""

	def test_the_setting_exists_and_is_on_by_default(self):
		fields = {f["fieldname"]: f for f in json.loads(read("waba", "doctype", "waba_settings", "waba_settings.json"))["fields"]}
		self.assertEqual(fields["auto_assign_new_chats"]["fieldtype"], "Check")
		self.assertEqual(str(fields["auto_assign_new_chats"]["default"]), "1")
		order = json.loads(read("waba", "doctype", "waba_settings", "waba_settings.json"))["field_order"]
		self.assertIn("auto_assign_new_chats", order)
		self.assertLess(order.index("assignment_section"), order.index("auto_assign_new_chats"))

	def test_needs_lead_table(self):
		from waba.rules import routing

		for assignee, valid, switch, expected in (
			(None, False, True, False),  # switch on: today's behaviour
			("a@x.com", True, True, False),
			("a@x.com", False, True, False),
			(None, False, False, True),  # off: nobody has it, so it waits
			("a@x.com", True, False, False),  # off but a valid agent has it: untouched
			("a@x.com", False, False, True),  # off and the agent can no longer take it: waits
			("", True, False, True),
		):
			self.assertEqual(routing.needs_lead(assignee, valid, switch), expected, (assignee, valid, switch))

	def test_assign_checks_it_before_choosing_anyone_and_records_the_wait_once(self):
		body = ASSIGN.split("def assign(")[1].split("\nREASONS")[0]
		self.assertIn("routing.needs_lead(", body)
		self.assertLess(body.index("keep_with_current("), body.index("needs_lead("))
		self.assertLess(body.index("needs_lead("), body.index("choose_assignee("))
		self.assertIn("if conversation.waiting_since and not conversation.assigned_to:", body)  # one Event note, not one per message

	def test_the_waiting_job_needs_both_switches(self):
		body = ASSIGN.split("def assign_waiting(")[1].split("\ndef alert_unanswered")[0]
		self.assertIn("if not auto_reassign_on() or not auto_assign_new_on():", body)

	def test_a_site_that_never_saved_the_setting_keeps_the_old_behaviour(self):
		body = ASSIGN.split("def auto_assign_new_on(")[1].split("\ndef ")[0]
		self.assertIn("True if value is None", body)
		self.assertIn('has_field("auto_assign_new_chats")', body)  # before the migrate the field does not exist: no error, old behaviour
		self.assertLess(body.index("has_field("), body.index("get_single_value("))

	def test_the_event_and_reason_text(self):
		self.assertIn('"lead_assign": "waiting for a Team Lead to assign it"', ASSIGN)
		self.assertIn("Waiting for a Team Lead to assign it: automatic assignment of new chats is off.", ASSIGN)
