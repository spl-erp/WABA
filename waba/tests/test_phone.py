"""Run without a site:  python -m unittest waba.tests.test_phone"""

import unittest

from waba.rules.phone import e164, wa_digits


class TestE164(unittest.TestCase):
	def test_formats_whatsapp_uses(self):
		cases = {
			"+91 98765 43210": "+919876543210",  # display_phone_number
			"919876543210": "+919876543210",  # webhook `from` / wa_id
			"+919876543210": "+919876543210",
			" +1 (770) 664-4877 ": "+17706644877",
			"0091 98765 43210": "+919876543210",  # 00 international prefix
			"+971-50-791-0025": "+971507910025",
		}
		for raw, want in cases.items():
			self.assertEqual(e164(raw), want, raw)

	def test_idempotent(self):
		self.assertEqual(e164(e164("919876543210")), "+919876543210")

	def test_unusable_input(self):
		for raw in (None, "", "   ", "abc", "12345", "+1234567890123456", "98765"):
			self.assertIsNone(e164(raw), repr(raw))

	def test_no_default_country_is_ever_added(self):
		# e164 is for numbers that come from Meta, whose digits are always international. It never adds +91:
		# a person-typed bare 10-digit number must get its country explicitly elsewhere, not be guessed here.
		self.assertEqual(e164("9876543210"), "+9876543210")  # kept as given; documented as unsuitable for typed input
		self.assertNotEqual(e164("9876543210"), "+919876543210")

	def test_wa_digits(self):
		self.assertEqual(wa_digits("+91 98765 43210"), "919876543210")
		self.assertIsNone(wa_digits("nope"))


if __name__ == "__main__":
	unittest.main()
