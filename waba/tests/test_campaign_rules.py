"""Run without a site:  python -m unittest waba.tests.test_campaign_rules

Who goes into a campaign Set and who is left out, with the reason."""

import unittest

from waba.rules import campaign as c


def person(party, phone="+919811111111", **more):
	return {"party": party, "name": party.title(), "phone": phone, **more}


class TestExclusion(unittest.TestCase):
	def test_a_normal_person_is_in(self):
		self.assertIsNone(c.exclusion_reason(person("a")))

	def test_no_number_is_left_out_first(self):
		self.assertEqual(c.exclusion_reason(person("a", phone=None, flag=True)), c.NO_PHONE)
		self.assertEqual(c.exclusion_reason(person("a", phone="")), c.NO_PHONE)

	def test_an_indian_landline_is_not_a_whatsapp_number(self):
		self.assertEqual(c.exclusion_reason(person("a", phone="+912223456789")), c.NO_PHONE)
		self.assertIsNone(c.exclusion_reason(person("a", phone="+919811111111")))

	def test_every_way_of_saying_stop_leaves_the_person_out(self):
		self.assertEqual(c.exclusion_reason(person("a", flag=True)), c.OPTED_OUT)
		self.assertEqual(c.exclusion_reason(person("a", phone_opted_out=True)), c.OPTED_OUT)
		self.assertEqual(c.exclusion_reason(person("a", service_consent="No")), c.OPTED_OUT)

	def test_marketing_no_leaves_the_person_out(self):
		self.assertEqual(c.exclusion_reason(person("a", marketing_consent="No")), c.MARKETING_NO)
		self.assertEqual(c.exclusion_reason(person("a", phone_marketing_opted_out=True)), c.MARKETING_NO)

	def test_opted_out_wins_over_marketing_no(self):
		self.assertEqual(c.exclusion_reason(person("a", flag=True, marketing_consent="No")), c.OPTED_OUT)

	def test_unknown_consent_is_fine_for_everyone(self):
		self.assertIsNone(c.exclusion_reason(person("a", service_consent="Unknown", marketing_consent="Unknown"), c.RULE_EVERYONE))

	def test_stop_still_excludes_under_every_rule(self):
		for rule in c.RULES:
			self.assertEqual(c.exclusion_reason(person("a", flag=True, service_consent="Yes", marketing_consent="Yes"), rule), c.OPTED_OUT)

	def test_general_consent_rule(self):
		self.assertEqual(c.exclusion_reason(person("a", service_consent="Unknown"), c.RULE_GENERAL), c.NO_CONSENT)
		self.assertIsNone(c.exclusion_reason(person("a", service_consent="Yes"), c.RULE_GENERAL))

	def test_marketing_consent_rule(self):
		self.assertEqual(c.exclusion_reason(person("a", service_consent="Yes", marketing_consent="Unknown"), c.RULE_MARKETING), c.NO_CONSENT)
		self.assertIsNone(c.exclusion_reason(person("a", marketing_consent="Yes"), c.RULE_MARKETING))


class TestBuildSet(unittest.TestCase):
	def test_splits_in_and_out_and_keeps_order(self):
		result = c.build_set(
			[
				person("a", "+919811111101"),
				person("b", None),
				person("c", "+919811111103", flag=True),
				person("d", "+919811111104"),
			]
		)
		self.assertEqual([p["party"] for p in result["included"]], ["a", "d"])
		self.assertEqual([(p["party"], p["reason"]) for p in result["excluded"]], [("b", c.NO_PHONE), ("c", c.OPTED_OUT)])
		self.assertEqual(result["counts"][c.NO_PHONE], 1)
		self.assertEqual(result["counts"][c.OPTED_OUT], 1)
		self.assertEqual(result["counts"][c.DUPLICATE], 0)

	def test_the_first_of_two_people_on_one_number_stays(self):
		result = c.build_set([person("a", "+919811111105"), person("b", "+919811111105"), person("c", "+919811111106")])
		self.assertEqual([p["party"] for p in result["included"]], ["a", "c"])
		self.assertEqual(result["excluded"][0]["reason"], c.DUPLICATE)
		self.assertEqual(result["counts"][c.DUPLICATE], 1)

	def test_an_opted_out_number_is_out_for_both_people(self):
		result = c.build_set([person("a", "+919811111105", phone_opted_out=True), person("b", "+919811111105", phone_opted_out=True)])
		self.assertEqual(result["included"], [])
		self.assertEqual([p["reason"] for p in result["excluded"]], [c.OPTED_OUT, c.OPTED_OUT])

	def test_a_person_left_out_does_not_use_up_the_number(self):
		# a is left out by the consent rule, so b on the same number is the one who stays
		result = c.build_set([person("a", "+919811111107", service_consent="Unknown"), person("b", "+919811111107", service_consent="Yes")], c.RULE_GENERAL)
		self.assertEqual([p["party"] for p in result["included"]], ["b"])

	def test_the_name_falls_back_to_the_record_id(self):
		result = c.build_set([{"party": "CUST-1", "phone": "+919811111108"}])
		self.assertEqual(result["included"][0]["name"], "CUST-1")

	def test_empty_input(self):
		result = c.build_set([])
		self.assertEqual(result["included"], [])
		self.assertEqual(result["excluded"], [])
		self.assertEqual(sum(result["counts"].values()), 0)

	def test_every_reason_has_a_label(self):
		self.assertEqual(set(c.LABELS), set(c.REASONS))


class TestHelpers(unittest.TestCase):
	def test_rule_or_default(self):
		self.assertEqual(c.rule_or_default(None), c.RULE_EVERYONE)
		self.assertEqual(c.rule_or_default(""), c.RULE_EVERYONE)
		self.assertEqual(c.rule_or_default("nonsense"), c.RULE_EVERYONE)
		self.assertEqual(c.rule_or_default(c.RULE_MARKETING), c.RULE_MARKETING)

	def test_summary(self):
		self.assertEqual(c.summary(c.build_set([person("a")])), "1 can be messaged.")
		self.assertEqual(c.summary(c.build_set([person("a"), person("b", None)])), "1 can be messaged, 1 left out.")

	def test_mask_phone_keeps_the_end_only(self):
		self.assertEqual(c.mask_phone("+919811113210"), "+91******3210")
		self.assertEqual(c.mask_phone("123"), "123")
		self.assertEqual(c.mask_phone(None), "")


if __name__ == "__main__":
	unittest.main()
