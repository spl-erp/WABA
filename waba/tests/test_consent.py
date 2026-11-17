"""Run without a site:  python -m unittest waba.tests.test_consent"""

import unittest

from waba.rules import consent as c


class TestCheckTemplate(unittest.TestCase):
	def ok(self, **kw):
		args = {"category": "UTILITY", "has_written_before": False, "consent": "Yes", "opted_out": False}
		args.update(kw)
		return c.check_template(**args)

	def test_utility_with_consent_is_allowed(self):
		self.assertEqual(self.ok(), (True, None, None))

	def test_only_utility_starts_a_conversation(self):
		for category in ("MARKETING", "AUTHENTICATION", "", None):
			ok, code, msg = self.ok(category=category)
			self.assertEqual((ok, code), (False, c.NOT_UTILITY), category)
			self.assertTrue(msg)

	def test_category_is_case_insensitive(self):
		self.assertTrue(self.ok(category="utility")[0])

	def test_no_consent_blocks(self):
		for consent in ("Unknown", "", None, "No-ish"):
			self.assertEqual(self.ok(consent=consent)[:2], (False, c.NO_CONSENT), consent)

	def test_consent_no_or_opted_out_always_blocks_even_after_the_customer_wrote(self):
		self.assertEqual(self.ok(consent="No", has_written_before=True)[:2], (False, c.OPTED_OUT))
		self.assertEqual(self.ok(opted_out=True, has_written_before=True)[:2], (False, c.OPTED_OUT))
		self.assertEqual(self.ok(opted_out=True)[:2], (False, c.OPTED_OUT))

	def test_a_customer_who_wrote_first_needs_no_stored_consent(self):
		self.assertEqual(self.ok(consent="Unknown", has_written_before=True), (True, None, None))

	def test_opt_out_is_reported_before_missing_consent(self):
		self.assertEqual(self.ok(consent="No")[1], c.OPTED_OUT)


class TestLimit(unittest.TestCase):
	def test_tiers(self):
		self.assertEqual(c.daily_limit("TIER_250"), 250)
		self.assertEqual(c.daily_limit("tier_1k"), 1000)
		self.assertEqual(c.daily_limit("TIER_10K"), 10000)
		self.assertEqual(c.daily_limit("TIER_100K"), 100000)
		self.assertIsNone(c.daily_limit("TIER_UNLIMITED"))

	def test_blank_or_unknown_tier_is_the_cautious_default(self):
		for tier in (None, "", "   ", "SOMETHING_NEW"):
			self.assertEqual(c.daily_limit(tier), 250, repr(tier))

	def test_limit_check(self):
		self.assertEqual(c.check_daily_limit(10, 250), (True, None, None))
		ok, code, msg = c.check_daily_limit(200, 250)
		self.assertTrue(ok)
		self.assertIsNone(code)
		self.assertIn("200 of 250", msg)
		ok, code, msg = c.check_daily_limit(250, 250)
		self.assertEqual((ok, code), (False, c.LIMIT_REACHED))
		self.assertEqual(c.check_daily_limit(10 ** 6, None), (True, None, None))


class TestKeywords(unittest.TestCase):
	def test_stop(self):
		for text in ("STOP", "stop", " Stop. ", "Unsubscribe", "stop all", "STOP!"):
			self.assertTrue(c.is_stop(text), text)

	def test_a_sentence_containing_stop_is_not_an_opt_out(self):
		for text in ("please do not stop the delivery", "bus stop near the factory", "", None, "stopping by tomorrow"):
			self.assertFalse(c.is_stop(text), repr(text))

	def test_start(self):
		for text in ("START", "start", "Unstop"):
			self.assertTrue(c.is_start(text), text)
		self.assertFalse(c.is_start("start the order please"))


class TestMarketingTemplatesOneToOne(unittest.TestCase):
	def check(self, category="MARKETING", **kw):
		args = dict(category=category, has_written_before=False, consent="Yes", opted_out=False, allow_marketing=True)
		args.update(kw)
		return c.check_template(**args)

	def test_marketing_is_still_refused_unless_the_switch_is_on(self):
		self.assertEqual(self.check(allow_marketing=False)[:2], (False, c.NOT_UTILITY))

	def test_marketing_follows_the_general_consent_when_the_switch_is_on(self):
		self.assertTrue(self.check()[0])
		self.assertEqual(self.check(consent="Unknown")[:2], (False, c.NO_CONSENT))
		self.assertTrue(self.check(consent="Unknown", has_written_before=True)[0])

	def test_stop_and_marketing_no_still_block_it(self):
		self.assertEqual(self.check(opted_out=True)[:2], (False, c.OPTED_OUT))
		self.assertEqual(self.check(marketing_blocked=True)[:2], (False, c.MARKETING_OPTED_OUT))

	def test_a_marketing_block_does_not_stop_utility(self):
		self.assertTrue(self.check(category="UTILITY", marketing_blocked=True)[0])

	def test_authentication_never_goes(self):
		self.assertEqual(self.check(category="AUTHENTICATION")[:2], (False, c.NOT_UTILITY))

	def test_the_notification_rules_stay_utility_only(self):
		import os
		path = os.path.join(os.path.dirname(__file__), "..", "waba", "doctype", "waba_notification_rule", "waba_notification_rule.py")
		self.assertIn('tpl.category != "UTILITY"', open(path, encoding="utf-8").read())
