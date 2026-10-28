"""Run without a site:  python -m unittest waba.tests.test_tags"""

import unittest

from waba.rules import tags


class TestTags(unittest.TestCase):
	def test_extract(self):
		self.assertEqual(tags.extract_rep_tag("Hello, I want a quotation [R12]"), "R12")
		self.assertEqual(tags.extract_rep_tag("[north-3] hi"), "north-3")

	def test_last_tag_wins(self):
		self.assertEqual(tags.extract_rep_tag("see [old] but use [R7]"), "R7")

	def test_no_tag(self):
		for text in (None, "", "no tag here", "[]", "[has space]", "[waytoolongcodewaytoolongcode]", "[bad!chars]"):
			self.assertEqual(tags.extract_rep_tag(text), "", repr(text))

	def test_valid_codes(self):
		for code in ("R12", "a", "north_3", "A-1", "x" * 20):
			self.assertTrue(tags.is_valid_code(code), code)
		for code in ("", None, "has space", "x" * 21, "bad!", "[R1]"):
			self.assertFalse(tags.is_valid_code(code), repr(code))

	def test_prefill_fits_metas_140_characters(self):
		text = tags.make_prefill_text("Hello, I would like a quotation", "R12")
		self.assertEqual(text, "Hello, I would like a quotation [R12]")
		long_text = tags.make_prefill_text("word " * 100, "R12")
		self.assertLessEqual(len(long_text), tags.PREFILL_MAX)
		self.assertTrue(long_text.endswith("[R12]"))

	def test_prefill_round_trips_through_extract(self):
		for code in ("R12", "north-3", "x" * 20):
			self.assertEqual(tags.extract_rep_tag(tags.make_prefill_text("Hi " * 80, code)), code)

	def test_prefill_rejects_a_bad_code(self):
		with self.assertRaises(ValueError):
			tags.make_prefill_text("Hi", "bad code")


if __name__ == "__main__":
	unittest.main()
