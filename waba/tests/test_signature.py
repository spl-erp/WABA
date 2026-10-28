"""Run without a site:  python -m unittest waba.tests.test_signature"""

import json
import unittest

from waba.rules.signature import PREFIX, sign, verify_signature

SECRET = "app-secret-123"
BODY = json.dumps({"object": "whatsapp_business_account", "entry": [{"id": "1"}]}).encode()


class TestSignature(unittest.TestCase):
	def test_round_trip(self):
		self.assertTrue(verify_signature(BODY, sign(BODY, SECRET), SECRET))

	def test_header_has_the_documented_shape(self):
		header = sign(BODY, SECRET)
		self.assertTrue(header.startswith(PREFIX))
		self.assertEqual(len(header), len(PREFIX) + 64)

	def test_known_vector(self):
		# HMAC-SHA256("secret", "hello") - fixed so a change in the algorithm is caught
		self.assertEqual(
			sign(b"hello", "secret"),
			"sha256=88aab3ede8d3adf94d26ab90d3bafd4a2083070c3bcce9c014ee04a443847c0b",
		)

	def test_wrong_secret_or_tampered_body_fails(self):
		header = sign(BODY, SECRET)
		self.assertFalse(verify_signature(BODY, header, "other-secret"))
		self.assertFalse(verify_signature(BODY + b" ", header, SECRET))

	def test_reserialised_json_is_not_the_same_body(self):
		header = sign(BODY, SECRET)
		reserialised = json.dumps(json.loads(BODY), indent=2).encode()
		self.assertFalse(verify_signature(reserialised, header, SECRET))  # raw bytes are what is signed

	def test_missing_or_malformed_input_is_simply_invalid(self):
		header = sign(BODY, SECRET)
		self.assertFalse(verify_signature(BODY, None, SECRET))
		self.assertFalse(verify_signature(BODY, "", SECRET))
		self.assertFalse(verify_signature(BODY, header, ""))
		self.assertFalse(verify_signature(BODY, header, None))
		self.assertFalse(verify_signature(None, header, SECRET))
		self.assertFalse(verify_signature(BODY, header[len(PREFIX) :], SECRET))  # no "sha256=" prefix
		self.assertFalse(verify_signature(BODY, "sha1=" + header[len(PREFIX) :], SECRET))

	def test_hex_case_does_not_matter(self):
		header = sign(BODY, SECRET)
		self.assertTrue(verify_signature(BODY, PREFIX + header[len(PREFIX) :].upper(), SECRET))

	def test_string_body_and_bytes_body_agree(self):
		self.assertEqual(sign("héllo", SECRET), sign("héllo".encode(), SECRET))


if __name__ == "__main__":
	unittest.main()
