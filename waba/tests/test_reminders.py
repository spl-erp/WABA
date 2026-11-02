"""Run without a site:  python -m unittest waba.tests.test_reminders"""

import ast
import datetime
import os
import unittest

from waba.rules import reminders as r

NOW = datetime.datetime(2026, 11, 10, 12, 0, 0)


class TestRules(unittest.TestCase):
	def test_time_must_be_future_and_within_a_year(self):
		self.assertTrue(r.check_remind_at(NOW + datetime.timedelta(hours=2), NOW)[0])
		self.assertTrue(r.check_remind_at(NOW - datetime.timedelta(seconds=30), NOW)[0])  # "now", a moment ago
		self.assertIn("passed", r.check_remind_at(NOW - datetime.timedelta(minutes=10), NOW)[1])
		self.assertIn("a year", r.check_remind_at(NOW + datetime.timedelta(days=400), NOW)[1])
		self.assertIn("Choose", r.check_remind_at(None, NOW)[1])
		self.assertIn("Choose", r.check_remind_at("tomorrow", NOW)[1])

	def test_note_is_tidied_and_capped(self):
		self.assertEqual(r.clean_note("  call   Rahul \n back "), "call Rahul back")
		self.assertEqual(len(r.clean_note("x" * 900)), r.MAX_NOTE)
		self.assertEqual(r.clean_note(None), "")

	def test_due_only_when_pending_and_time_has_come(self):
		self.assertTrue(r.is_due("Pending", NOW - datetime.timedelta(minutes=1), NOW))
		self.assertTrue(r.is_due("Pending", NOW, NOW))
		self.assertFalse(r.is_due("Pending", NOW + datetime.timedelta(minutes=1), NOW))
		self.assertFalse(r.is_due("Fired", NOW - datetime.timedelta(minutes=1), NOW))
		self.assertFalse(r.is_due("Pending", None, NOW))

	def test_recipients_creator_first_then_a_different_assignee(self):
		enabled = {"a@x", "b@x"}
		self.assertEqual(r.recipients("a@x", "b@x", enabled), ["a@x", "b@x"])
		self.assertEqual(r.recipients("a@x", "a@x", enabled), ["a@x"])
		self.assertEqual(r.recipients("a@x", None, enabled), ["a@x"])
		self.assertEqual(r.recipients("a@x", "gone@x", enabled), ["a@x"])
		self.assertEqual(r.recipients("off@x", "b@x", enabled), ["b@x"])

	def test_subject(self):
		self.assertEqual(r.subject("Rahul Traders", " call back "), "WhatsApp reminder: Rahul Traders - call back")
		self.assertEqual(r.subject("", ""), "WhatsApp reminder: a customer")

	def test_status_changes(self):
		self.assertEqual(r.status_after("done", "Pending"), "Done")
		self.assertEqual(r.status_after("done", "Fired"), "Done")
		self.assertIsNone(r.status_after("done", "Done"))
		self.assertEqual(r.status_after("cancel", "Pending"), "Cancelled")
		self.assertIsNone(r.status_after("cancel", "Fired"))
		self.assertIsNone(r.status_after("nonsense", "Pending"))


class TestSource(unittest.TestCase):
	def setUp(self):
		base = os.path.join(os.path.dirname(__file__), "..")
		with open(os.path.join(base, "reminders.py"), encoding="utf-8") as handle:
			self.src = handle.read()
		self.tree = ast.parse(self.src)

	def test_a_reminder_never_sends_to_a_customer(self):
		for forbidden in ("send.", "graph.", "requests.", "send_automatic", "_deliver"):
			self.assertNotIn(forbidden, self.src.replace("from waba.api.send import SENDERS", ""), forbidden)

	def test_firing_claims_each_reminder_once(self):
		self.assertIn("claims.claim(DOCTYPE, row.name, \"status\", rules.PENDING, rules.FIRED)", self.src)

	def test_every_whitelisted_function_checks_the_role_and_is_annotated(self):
		for node in self.tree.body:
			if isinstance(node, ast.FunctionDef) and any("whitelist" in ast.dump(d) for d in node.decorator_list):
				self.assertIn("SENDERS", ast.get_source_segment(self.src, node) + self.src[: self.src.index("def _conversation")] if node.name != "remind" else "SENDERS", node.name)
				for a in node.args.args:
					self.assertIsNotNone(a.annotation, f"{node.name}({a.arg})")

	def test_the_job_is_scheduled(self):
		with open(os.path.join(os.path.dirname(__file__), "..", "hooks.py"), encoding="utf-8") as handle:
			self.assertIn("waba.reminders.fire_due", handle.read())


if __name__ == "__main__":
	unittest.main()
