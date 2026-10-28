"""Run without a site:  python -m unittest waba.tests.test_config_validation"""

import datetime
import unittest

from waba.rules import config_validation as cv
from waba.rules.hours import as_time, is_within_hours


def row(user, role="Agent", **kw):
	return {"user": user, "role": role, **kw}


class TestIds(unittest.TestCase):
	def test_meta_ids_are_digit_strings(self):
		for good in ("123456789012345", "1234567890", " 12345 "):
			self.assertTrue(cv.is_numeric_id(good), good)
		for bad in ("", None, "abc", "12 34", "1234", "12-3456"):
			self.assertFalse(cv.is_numeric_id(bad), repr(bad))


class TestAgents(unittest.TestCase):
	def test_a_valid_shared_number(self):
		rows = [row("a", rep_code="R1"), row("b", "Supervisor", rep_code="R2")]
		self.assertEqual(cv.validate_agents(rows, "Shared", ""), [])

	def test_duplicate_user_and_duplicate_code(self):
		errs = cv.validate_agents([row("a", rep_code="R1"), row("a", rep_code="r1")], "Shared", "")
		self.assertEqual(len(errs), 2)
		self.assertTrue(any("twice" in e for e in errs))
		self.assertTrue(any("already used" in e for e in errs))

	def test_codes_are_case_insensitive_for_duplicates(self):
		errs = cv.validate_agents([row("a", rep_code="R1"), row("b", rep_code="r1")], "Shared", "")
		self.assertEqual(len(errs), 1)

	def test_bad_role_negative_capacity_and_bad_code(self):
		errs = cv.validate_agents(
			[row("a", "Boss"), row("b", max_open=-1), row("c", rep_code="bad code!")], "Shared", ""
		)
		self.assertEqual(len(errs), 3)

	def test_blank_user_row(self):
		self.assertEqual(len(cv.validate_agents([{"user": ""}], "Shared", "")), 1)

	def test_personal_number_needs_its_owner_as_an_agent(self):
		self.assertEqual(len(cv.validate_agents([row("a")], "Personal", "")), 1)  # no owner set
		errs = cv.validate_agents([row("a")], "Personal", "rahul")
		self.assertEqual(len(errs), 1)
		self.assertIn("rahul", errs[0])
		self.assertEqual(cv.validate_agents([row("rahul"), row("s", "Supervisor")], "Personal", "rahul"), [])

	def test_the_owner_must_be_an_agent_not_a_supervisor(self):
		errs = cv.validate_agents([row("rahul", "Supervisor")], "Personal", "rahul")
		self.assertEqual(len(errs), 1)


class TestRules(unittest.TestCase):
	def test_valid_and_duplicate(self):
		self.assertEqual(cv.validate_rules([{"rule_type": "Rep Tag"}, {"rule_type": "Least Busy"}]), [])
		errs = cv.validate_rules([{"rule_type": "Rep Tag"}, {"rule_type": "Rep Tag"}])
		self.assertEqual(len(errs), 1)

	def test_unknown_type(self):
		self.assertEqual(len(cv.validate_rules([{"rule_type": "Nope"}])), 1)

	def test_empty_is_fine(self):
		self.assertEqual(cv.validate_rules([]), [])


class TestHours(unittest.TestCase):
	T = datetime.time

	def test_off_means_no_checks(self):
		self.assertEqual(cv.validate_hours(False, None, None, "garbage"), [])

	def test_on_needs_times_and_days(self):
		self.assertEqual(cv.validate_hours(True, self.T(9), self.T(18), "Mon,Tue"), [])
		self.assertEqual(len(cv.validate_hours(True, None, self.T(18), "Mon")), 1)
		self.assertEqual(len(cv.validate_hours(True, self.T(18), self.T(9), "Mon")), 1)
		self.assertEqual(len(cv.validate_hours(True, self.T(9), self.T(18), "Funday")), 1)

	def test_parse_days(self):
		self.assertEqual(cv.parse_days("Mon, tue ;WED,Mon"), ["Mon", "Tue", "Wed"])
		self.assertEqual(cv.parse_days("Monday,Tuesday"), ["Mon", "Tue"])
		self.assertIsNone(cv.parse_days(""))
		self.assertIsNone(cv.parse_days("Mon,Xyz"))

	def test_number_checks(self):
		self.assertEqual(cv.validate_number("Shared", 7, 0), [])
		self.assertEqual(len(cv.validate_number("Weird", -1, -2)), 3)


class TestWithinHours(unittest.TestCase):
	T = datetime.time
	WED_10 = datetime.datetime(2026, 10, 28, 10, 0)  # a Wednesday

	def test_inside_and_outside(self):
		args = (self.T(9), self.T(18), "Mon,Tue,Wed,Thu,Fri")
		self.assertTrue(is_within_hours(self.WED_10, *args))
		self.assertFalse(is_within_hours(datetime.datetime(2026, 10, 28, 8, 59), *args))
		self.assertFalse(is_within_hours(datetime.datetime(2026, 10, 28, 18, 0), *args))  # end is exclusive
		self.assertTrue(is_within_hours(datetime.datetime(2026, 10, 28, 9, 0), *args))  # start is inclusive

	def test_non_working_day(self):
		sunday = datetime.datetime(2026, 11, 1, 10, 0)
		self.assertFalse(is_within_hours(sunday, self.T(9), self.T(18), "Mon,Tue,Wed,Thu,Fri,Sat"))

	def test_switched_off_or_misconfigured_never_blocks(self):
		self.assertTrue(is_within_hours(self.WED_10, None, None, "", hours_enabled=False))
		self.assertTrue(is_within_hours(self.WED_10, None, None, "Mon"))
		self.assertTrue(is_within_hours(self.WED_10, self.T(9), self.T(18), "garbage"))

	def test_as_time(self):
		self.assertEqual(as_time(datetime.timedelta(hours=9, minutes=30)), datetime.time(9, 30))
		self.assertEqual(as_time("09:30:00"), datetime.time(9, 30))
		self.assertEqual(as_time("9:5"), datetime.time(9, 5))
		self.assertEqual(as_time(datetime.time(7, 1)), datetime.time(7, 1))
		self.assertIsNone(as_time(None))
		self.assertIsNone(as_time(""))
		self.assertIsNone(as_time("xx"))
		self.assertIsNone(as_time("25:00:00"))


if __name__ == "__main__":
	unittest.main()
