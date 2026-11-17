"""Run without a site:  python -m unittest waba.tests.test_sensitive

Every number used here is built from a check digit or is obviously fake; none is a real person's identifier."""

import unittest

from waba.rules import sensitive as s


def aadhaar(prefix="23456789012"):
	return prefix + str(s.verhoeff_check_digit(prefix))


def card(prefix="453201511283036"):
	return prefix + str(s.luhn_check_digit(prefix))


def codes(text, **kw):
	return [h["code"] for h in s.scan(text, **kw)]


class TestChecksums(unittest.TestCase):
	def test_verhoeff(self):
		self.assertTrue(s.verhoeff_valid("2363"))  # the textbook example
		self.assertFalse(s.verhoeff_valid("2364"))
		n = aadhaar()
		self.assertTrue(s.verhoeff_valid(n))
		self.assertFalse(s.verhoeff_valid(n[:-1] + str((int(n[-1]) + 1) % 10)))

	def test_luhn(self):
		self.assertTrue(s.luhn_valid("4539578763621486"))  # a well known test number
		self.assertFalse(s.luhn_valid("4539578763621487"))
		self.assertTrue(s.luhn_valid(card()))


class TestAadhaar(unittest.TestCase):
	def test_grouped_and_plain(self):
		n = aadhaar()
		self.assertEqual(codes(f"my aadhaar {n[:4]} {n[4:8]} {n[8:]}"), ["aadhaar"])
		self.assertEqual(codes(f"uid {n}"), ["aadhaar"])
		self.assertEqual(codes(f"{n[:4]}-{n[4:8]}-{n[8:]}"), ["aadhaar"])

	def test_a_wrong_checksum_is_not_flagged(self):
		n = aadhaar()
		self.assertEqual(codes(n[:-1] + str((int(n[-1]) + 1) % 10)), [])

	def test_a_phone_number_with_its_country_code_is_not_an_aadhaar(self):
		self.assertEqual(codes("call +919876543210"), [])
		self.assertEqual(codes("call 919876543210"), [])

	def test_the_sample_is_masked(self):
		n = aadhaar()
		hit = s.scan(n)[0]
		self.assertEqual(hit["sample"], f"XXXX XXXX {n[-4:]}")
		self.assertNotIn(n[:8], hit["sample"])

	def test_a_longer_number_is_not_cut_up(self):
		self.assertEqual(codes("ref " + aadhaar() + "9"), [])


class TestPan(unittest.TestCase):
	def test_valid_shape(self):
		self.assertEqual(codes("PAN is ABCPE1234F"), ["pan"])
		self.assertEqual(codes("pan abcpe1234f"), ["pan"])

	def test_wrong_entity_letter_or_shape(self):
		self.assertEqual(codes("ABCXE1234F"), [])  # X is not a PAN entity type
		self.assertEqual(codes("ABCPE12345"), [])
		self.assertEqual(codes("SAL-INV-2026-00312"), [])

	def test_masked(self):
		self.assertEqual(s.scan("ABCPE1234F")[0]["sample"], "ABC******F")


class TestCard(unittest.TestCase):
	def test_grouped_and_plain(self):
		c = card()
		self.assertEqual(codes(f"card {c[:4]} {c[4:8]} {c[8:12]} {c[12:]}"), ["card"])
		self.assertEqual(codes(c), ["card"])

	def test_a_wrong_checksum_is_not_a_card(self):
		c = card()
		self.assertEqual(codes(c[:-1] + str((int(c[-1]) + 1) % 10)), [])

	def test_a_long_number_that_only_passes_the_checksum_is_not_a_card(self):
		self.assertEqual(codes("order 50100123456789 shipped"), [])  # 14 digits, no card network starts like this
		self.assertEqual(codes("ref 12345678903"), [])

	def test_known_networks(self):
		self.assertEqual(codes(card("411111111111111")), ["card"])  # Visa, 16
		self.assertEqual(codes(card("555555555555444")), ["card"])  # Mastercard, 16
		self.assertEqual(codes(card("37828224631000")), ["card"])  # Amex, 15
		self.assertEqual(codes(card("608100000000000")), ["card"])  # RuPay style, 16

	def test_the_last_four_only(self):
		c = card()
		self.assertEqual(s.scan(c)[0]["sample"], f"XXXX XXXX XXXX {c[-4:]}")


class TestBank(unittest.TestCase):
	def test_needs_a_bank_word_nearby(self):
		self.assertEqual(codes("a/c no 50100123456789 IFSC HDFC0001234"), ["bank"])
		self.assertEqual(codes("account number: 123456789012345"), ["bank"])
		self.assertEqual(codes("order 50100123456789 shipped"), [])

	def test_a_mobile_number_beside_a_bank_word_is_not_an_account(self):
		self.assertEqual(codes("call the bank on 9876543210"), [])

	def test_a_bank_word_wins_over_a_lucky_card_checksum(self):
		lucky = card("511234567890123")
		self.assertEqual(codes(f"bank account {lucky}"), ["bank"])
		self.assertEqual(codes(f"here: {lucky}"), ["card"])


class TestUpi(unittest.TestCase):
	def test_upi_ids(self):
		self.assertEqual(codes("pay to ravi@oksbi"), ["upi"])
		self.assertEqual(codes("ravi.k-12@ybl please"), ["upi"])

	def test_emails_are_not_blocked(self):
		self.assertEqual(codes("write to ravi@gmail.com"), [])
		self.assertEqual(codes("accounts@company.co.in"), [])

	def test_masked(self):
		self.assertEqual(s.scan("ravi@oksbi")[0]["sample"], "r***@oksbi")


class TestOtpAndPin(unittest.TestCase):
	def test_codes_next_to_their_words(self):
		for text in ("your OTP is 482913", "482913 is your OTP", "One time password 5821", "verification code: 123456", "CVV 123", "ATM PIN 4821", "password is 8841"):
			self.assertEqual(codes(text), ["otp"], text)

	def test_the_code_is_masked(self):
		self.assertEqual(s.scan("OTP 482913")[0]["sample"], "XXXXXX")

	def test_a_postal_pin_code_is_not_a_secret(self):
		for text in ("Nagpur PIN 440001", "PIN code 440001", "pincode 440001", "Pin - code: 440001"):
			self.assertEqual(codes(text), [], text)

	def test_a_word_alone_or_far_from_the_digits_is_fine(self):
		self.assertEqual(codes("please share the OTP you received"), [])
		self.assertEqual(codes("OTP was sent. " + "x" * 40 + " 123456"), [])

	def test_a_wrong_length_for_that_word(self):
		self.assertEqual(codes("OTP 12"), [])
		self.assertEqual(codes("cvv 12345"), [])


class TestOrdinaryText(unittest.TestCase):
	def test_things_that_must_never_trigger(self):
		for text in (
			"Invoice SAL-INV-2026-00312 for Rs 45,000 is due on 10/11/2026.",
			"Your order SO-2026-0042 has shipped. Track at https://splashjetink.com/t/9f3a",
			"Call me on +91 98765 43210 or 9876543210.",
			"Mail accounts@splashjetink.com for help",
			"Quantity 5000 pieces at 12.50 each, GST 18%",
			"Meeting at 4:30 pm, 2026-11-04",
			"Reply YES to confirm",
			"",
			None,
		):
			self.assertEqual(codes(text), [], text)


class TestSettings(unittest.TestCase):
	def test_only_enabled_types_are_checked(self):
		self.assertEqual(codes("ABCPE1234F ravi@oksbi", enabled=(s.PAN,)), ["pan"])
		self.assertEqual(codes("ABCPE1234F", enabled=()), [])

	def test_the_allow_list_lets_the_companys_own_identifiers_through(self):
		allow = s.parse_allow_list("50100123456789\nABCPE1234F, accounts@oksbi")
		self.assertEqual(codes("a/c no 50100123456789", allow=allow), [])
		self.assertEqual(codes("our PAN ABCPE1234F", allow=allow), [])
		self.assertEqual(codes("pay accounts@oksbi", allow=allow), [])
		self.assertEqual(codes("a/c no 50100123456780", allow=allow), ["bank"])  # a different number still blocked

	def test_the_allow_list_ignores_spacing_in_numbers(self):
		allow = s.parse_allow_list("5010 0123 4567 89")
		self.assertEqual(codes("account 50100123456789", allow=allow), [])

	def test_hits_come_in_order_and_describe_reads_well(self):
		n = aadhaar()
		hits = s.scan(f"PAN ABCPE1234F then aadhaar {n}")
		self.assertEqual([h["code"] for h in hits], ["pan", "aadhaar"])
		text = s.describe(hits)
		self.assertIn("a PAN (ABC******F)", text)
		self.assertIn(" and an Aadhaar number (", text)
		self.assertEqual(s.describe([]), "")

	def test_a_raw_value_never_appears_in_a_hit(self):
		n = aadhaar()
		c = card()
		for text, raw in ((f"aadhaar {n}", n), (f"card {c}", c), ("PAN ABCPE1234F", "ABCPE1234F"), ("pay ravi@oksbi", "ravi@oksbi"), ("OTP 482913", "482913")):
			self.assertNotIn(raw, str(s.scan(text)))
