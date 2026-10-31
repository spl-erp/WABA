"""Run without a site:  python -m unittest waba.tests.test_purposes"""

import json
import os
import unittest

from waba.rules import purposes as p

ROOT = os.path.join(os.path.dirname(__file__), "..", "waba", "doctype")


def definition(folder):
	with open(os.path.join(ROOT, folder, f"{folder}.json"), encoding="utf-8") as f:
		return json.load(f)


class TestPurposes(unittest.TestCase):
	def test_every_origin_that_can_be_sent_has_a_purpose(self):
		for origin in p.ORIGINS:
			if origin == p.PHONE_APP:
				self.assertIsNone(p.purpose_for(origin))  # typed in the phone app; never sent by Waba
			else:
				self.assertIn(p.purpose_for(origin), p.PURPOSES, origin)

	def test_a_number_must_be_on_for_the_purpose(self):
		flags = {"conversations": 1, "documents": 1, "notifications": 0, "campaigns": 0}
		self.assertTrue(p.check_origin(flags, p.PERSON)[0])
		self.assertEqual(p.check_origin(flags, p.NOTIFICATION)[:2], (False, p.NOT_ALLOWED))
		self.assertEqual(p.check_origin(flags, p.CAMPAIGN)[:2], (False, p.NOT_ALLOWED))

	def test_a_notification_only_number_cannot_carry_a_reps_chat(self):
		flags = {"conversations": 0, "notifications": 1}
		ok, code, message = p.check_origin(flags, p.PERSON)
		self.assertEqual((ok, code), (False, p.NOT_ALLOWED))
		self.assertIn("conversations with customers", message)
		self.assertTrue(p.check_origin(flags, p.REMINDER)[0])

	def test_phone_app_and_unknown_origins_are_refused(self):
		self.assertEqual(p.check_origin({"conversations": 1}, p.PHONE_APP)[1], p.UNKNOWN_ORIGIN)
		self.assertEqual(p.check_origin({"conversations": 1}, "Nonsense")[1], p.UNKNOWN_ORIGIN)
		self.assertEqual(p.check({"conversations": 1}, "nonsense")[1], p.UNKNOWN_ORIGIN)

	def test_missing_flags_mean_not_allowed(self):
		self.assertFalse(p.check(None, p.CONVERSATIONS)[0])
		self.assertFalse(p.check({}, p.DOCUMENTS)[0])

	def test_reply_pool_applies_only_to_numbers_not_used_for_conversations(self):
		self.assertTrue(p.replies_go_to_pool({"conversations": 0}, p.REPLY_POOL))
		self.assertFalse(p.replies_go_to_pool({"conversations": 1}, p.REPLY_POOL))
		self.assertFalse(p.replies_go_to_pool({"conversations": 0}, p.REPLY_NORMAL))
		self.assertFalse(p.replies_go_to_pool({"conversations": 0}, None))


class TestDefinitionsAgree(unittest.TestCase):
	def test_message_origin_options_match_the_rules(self):
		fields = {f["fieldname"]: f for f in definition("waba_message")["fields"]}
		self.assertEqual(tuple(fields["origin"]["options"].split("\n")), p.ORIGINS)
		self.assertEqual(fields["origin"]["read_only"], 1)

	def test_number_purpose_fields_and_reply_policy_match_the_rules(self):
		fields = {f["fieldname"]: f for f in definition("waba_number")["fields"]}
		for purpose in p.PURPOSES:
			self.assertIn(f"purpose_{purpose}", fields)
		self.assertEqual(tuple(fields["reply_policy"]["options"].split("\n")), p.REPLY_POLICIES)
		self.assertEqual(fields["reply_policy"]["default"], p.REPLY_NORMAL)


if __name__ == "__main__":
	unittest.main()
