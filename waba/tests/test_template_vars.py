"""Run without a site:  python -m unittest waba.tests.test_template_vars"""

import unittest

from waba.rules import template_vars as v

CTX = {"record": {"customer_name": "Rahul Traders", "mobile_no": " 98 ", "address": {"city": "Nagpur"}, "empty": " ", "items": [1], "none": None}, "sender": "Asha Verma", "today": "02-11-2026", "customer_name": "Rahul"}


def row(slot, kind, source="", active=1):
	return {"slot": slot, "source_type": kind, "source": source, "active": active}


class TestResolve(unittest.TestCase):
	def test_each_source(self):
		values, missing = v.resolve(
			[row("body.1", v.RECORD, "customer_name"), row("body.2", v.LITERAL, " Splashjet "), row("body.3", v.SENDER), row("body.4", v.TODAY), row("body.5", v.CUSTOMER), row("header.media", v.SHARED, "WSF-00001")],
			CTX,
		)
		self.assertEqual(values, {"body.1": "Rahul Traders", "body.2": "Splashjet", "body.3": "Asha Verma", "body.4": "02-11-2026", "body.5": "Rahul", "header.media": {"shared_file": "WSF-00001"}})
		self.assertEqual(missing, [])

	def test_what_cannot_be_filled_is_reported_missing(self):
		values, missing = v.resolve(
			[row("body.1", v.ASK), row("body.2", v.RECORD, "nope"), row("body.3", v.RECORD, "empty"), row("body.4", v.RECORD, "items"), row("body.5", v.RECORD, "none"), row("body.6", v.SHARED, ""), row("body.7", v.LITERAL, "  ")],
			CTX,
		)
		self.assertEqual(values, {})
		self.assertEqual(missing, ["body.1", "body.2", "body.3", "body.4", "body.5", "body.6", "body.7"])

	def test_nested_fields_and_trimming(self):
		values, _ = v.resolve([row("body.1", v.RECORD, "address.city"), row("body.2", v.RECORD, "mobile_no")], CTX)
		self.assertEqual(values, {"body.1": "Nagpur", "body.2": "98"})

	def test_inactive_rows_and_odd_input(self):
		self.assertEqual(v.resolve([row("body.1", v.LITERAL, "x", active=0)], CTX), ({}, []))
		self.assertEqual(v.resolve(None, None), ({}, []))
		self.assertEqual(v.resolve([{"slot": ""}, {"slot": "body.1"}], {}), ({}, ["body.1"]))
		self.assertEqual(v.resolve([{"slot": "body.1", "source_type": "Something new"}], {}), ({}, ["body.1"]))

	def test_missing_context_never_raises(self):
		for kind in v.SOURCE_TYPES:
			v.resolve([row("body.1", kind, "x")], {})


class TestMerge(unittest.TestCase):
	def test_typed_wins_and_blank_does_not_erase(self):
		self.assertEqual(v.merge({"body.1": "A", "body.2": "B"}, {"body.1": "Z", "body.2": "  ", "body.3": "C"}), {"body.1": "Z", "body.2": "B", "body.3": "C"})
		self.assertEqual(v.merge(None, None), {})


class TestPublicRecord(unittest.TestCase):
	def test_only_plain_non_secret_fields(self):
		out = v.public_record({"name": "L-1", "_comments": "x", "api_key": "k", "password_hash": "p", "tags": ["a"], "n": 3, "none": None, "mobile_no": "9"})
		self.assertEqual(out, {"name": "L-1", "n": 3, "none": None, "mobile_no": "9"})

	def test_an_allow_list_narrows_it_further(self):
		self.assertEqual(v.public_record({"name": "L-1", "mobile_no": "9"}, exposed={"mobile_no"}), {"mobile_no": "9"})


if __name__ == "__main__":
	unittest.main()
