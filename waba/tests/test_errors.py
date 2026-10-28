"""Run without a site:  python -m unittest waba.tests.test_errors"""

import unittest

from waba.rules import errors as e


class TestErrors(unittest.TestCase):
	def test_the_documented_codes(self):
		expected = {
			131047: e.TEMPLATE_REQUIRED,
			131049: e.DO_NOT_RETRY_24H,
			130429: e.BACKOFF_RETRY,
			131056: e.RETRY_LATER,
			131026: e.NO_RETRY,
			131051: e.FIX_REQUEST,
			131053: e.FIX_REQUEST,
			132000: e.FIX_REQUEST,
			132001: e.TEMPLATE_PROBLEM,
			132015: e.TEMPLATE_PROBLEM,
			132016: e.TEMPLATE_PROBLEM,
			131042: e.ALERT_BILLING,
			131031: e.ALERT_ACCOUNT,
			368: e.ALERT_ACCOUNT,
			190: e.ALERT_TOKEN,
			131062: e.FALLBACK_TO_PHONE,
		}
		for code, action in expected.items():
			self.assertEqual(e.classify(code)[0], action, code)

	def test_string_and_int_codes_agree(self):
		self.assertEqual(e.classify("131047"), e.classify(131047))

	def test_unknown_codes_are_reported_not_retried(self):
		self.assertEqual(e.classify(999999)[0], "unknown")
		self.assertEqual(e.classify(None)[0], "unknown")
		self.assertEqual(e.classify("abc")[0], "unknown")
		self.assertNotIn("unknown", e.NEVER_RETRY_SAME)  # the caller decides; the table never says "retry blindly"

	def test_alerts_are_the_ones_that_stop_everyone(self):
		for code in (131042, 131031, 368, 190):
			self.assertTrue(e.needs_alert(code), code)
		for code in (131047, 131049, 130429, 131026, 132000):
			self.assertFalse(e.needs_alert(code), code)

	def test_every_code_has_a_meaning(self):
		for code, (action, meaning) in e.ACTIONS.items():
			self.assertTrue(meaning, code)
			self.assertIsInstance(code, int)

	def test_do_not_resend_the_same_message_after_a_hard_failure(self):
		for code in (131026, 131051, 132001, 131049, 131047):
			self.assertIn(e.classify(code)[0], e.NEVER_RETRY_SAME, code)
		for code in (130429, 131056):
			self.assertNotIn(e.classify(code)[0], e.NEVER_RETRY_SAME, code)


if __name__ == "__main__":
	unittest.main()
