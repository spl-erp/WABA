"""Run without a site:  python -m unittest waba.tests.test_registration

Registering a number with Meta: the checks, the Graph calls (fake Meta) and the wiring of the API and the form."""

import ast
import os
import re
import unittest

from waba.meta import graph
from waba.rules import registration as r

BASE = os.path.join(os.path.dirname(__file__), "..")


def read(*parts):
	with open(os.path.join(BASE, *parts), encoding="utf-8") as handle:
		return handle.read()


class Resp:
	def __init__(self, body, status=200):
		self._body, self.status_code = body, status

	def json(self):
		return self._body


class Fake:
	def __init__(self, *responses):
		self.responses, self.calls = list(responses), []

	def __call__(self, method, url, params=None, data=None, json=None, headers=None, timeout=None, files=None, stream=None):
		self.calls.append({"method": method, "url": url, "params": params, "json": json, "headers": headers})
		return self.responses.pop(0)


class TestChecks(unittest.TestCase):
	def test_pin_is_exactly_six_digits(self):
		self.assertEqual(r.clean_pin(" 123456 ")[0], "123456")
		for bad in ("12345", "1234567", "12345a", "", None, "123 456"):
			self.assertIsNone(r.clean_pin(bad)[0], bad)

	def test_code_accepts_the_dash_meta_prints(self):
		self.assertEqual(r.clean_code("123-456")[0], "123456")
		self.assertEqual(r.clean_code("123 456")[0], "123456")
		self.assertIsNone(r.clean_code("12-3456-7")[0])

	def test_method_and_language(self):
		self.assertEqual(r.clean_method("sms")[0], "SMS")
		self.assertEqual(r.clean_method("voice")[0], "VOICE")
		self.assertIsNone(r.clean_method("email")[0])
		self.assertEqual(r.clean_language(None)[0], "en_US")
		self.assertIsNone(r.clean_language("English")[0])


class TestState(unittest.TestCase):
	def test_unverified_number_needs_a_code(self):
		s = r.state({"status": "PENDING", "code_verification_status": "UNVERIFIED"})
		self.assertEqual(s["next"], r.REQUEST_CODE)

	def test_verified_but_pending_needs_registration(self):
		s = r.state({"status": "PENDING", "code_verification_status": "VERIFIED"})
		self.assertEqual(s["next"], r.REGISTER)

	def test_connected_is_done(self):
		self.assertEqual(r.state({"status": "CONNECTED", "code_verification_status": "VERIFIED"})["next"], r.DONE)

	def test_a_flagged_number_needs_attention_first(self):
		self.assertEqual(r.state({"status": "FLAGGED", "code_verification_status": "VERIFIED"})["next"], r.ATTENTION)

	def test_the_name_review_is_mentioned_but_does_not_change_the_step(self):
		s = r.state({"status": "PENDING", "code_verification_status": "VERIFIED", "name_status": "PENDING_REVIEW"})
		self.assertEqual(s["next"], r.REGISTER)
		self.assertIn("waiting for Meta's review", s["text"])

	def test_an_empty_answer_is_treated_as_unverified(self):
		self.assertEqual(r.state(None)["next"], r.REQUEST_CODE)


class TestGraph(unittest.TestCase):
	def test_request_code_calls_the_right_endpoint(self):
		http = Fake(Resp({"success": True}))
		graph.request_code("T", "555", "VOICE", "hi_IN", "v25.0", http=http)
		c = http.calls[0]
		self.assertEqual((c["method"], c["url"]), ("POST", "https://graph.facebook.com/v25.0/555/request_code"))
		self.assertEqual(c["json"], {"code_method": "VOICE", "language": "hi_IN"})

	def test_verify_and_register_payloads(self):
		http = Fake(Resp({"success": True}), Resp({"success": True}))
		graph.verify_code("T", "555", "123456", http=http)
		graph.register_number("T", "555", "654321", http=http)
		self.assertEqual(http.calls[0]["json"], {"code": "123456"})
		self.assertEqual(http.calls[1]["json"], {"messaging_product": "whatsapp", "pin": "654321"})
		self.assertTrue(http.calls[1]["url"].endswith("/555/register"))

	def test_the_token_is_in_the_header_and_the_pin_never_in_the_url(self):
		http = Fake(Resp({"success": True}))
		graph.register_number("SECRET-TOKEN", "555", "654321", http=http)
		c = http.calls[0]
		self.assertEqual(c["headers"], {"Authorization": "Bearer SECRET-TOKEN"})
		self.assertNotIn("654321", c["url"] + str(c["params"]))

	def test_state_read_retries_with_fewer_fields_when_meta_rejects_one(self):
		http = Fake(Resp({"error": {"message": "bad field", "code": 100}}, 400), Resp({"id": "555", "status": "PENDING"}))
		self.assertEqual(graph.number_state("T", "555", http=http)["status"], "PENDING")
		self.assertEqual(http.calls[1]["params"]["fields"], graph.NUMBER_STATE_MINIMAL)

	def test_a_meta_refusal_surfaces_as_a_graph_error_with_its_words(self):
		http = Fake(Resp({"error": {"message": "x", "code": 136024, "error_user_msg": "Already verified."}}, 400))
		with self.assertRaises(graph.GraphError) as ctx:
			graph.request_code("T", "555", http=http)
		self.assertEqual(graph.explain(ctx.exception), "Already verified.")


class TestWiring(unittest.TestCase):
	def setUp(self):
		self.api = read("api", "numbers.py")
		self.js = read("waba", "doctype", "waba_number", "waba_number.js")
		tree = ast.parse(self.api)
		self.whitelisted = {n.name for n in tree.body if isinstance(n, ast.FunctionDef) and any("whitelist" in ast.dump(d) for d in n.decorator_list)}

	def test_every_method_the_form_calls_exists_and_is_whitelisted(self):
		calls = set(re.findall(r'call\("(\w+)"', self.js))
		self.assertEqual(calls, {"check", "request_code", "verify_code", "register"})
		self.assertTrue(calls <= self.whitelisted)

	def test_writes_are_post_only_and_admin_only(self):
		for name in ("request_code", "verify_code", "register"):
			self.assertIn(f'@frappe.whitelist(methods=["POST"])\ndef {name}(', self.api, name)
		self.assertIn("frappe.only_for(ADMINS)", self.api)
		self.assertIn('ADMINS = ("System Manager", ROLE_ADMIN)', self.api)

	def test_registering_needs_an_explicit_confirmation(self):
		self.assertIn("if not int(confirm or 0):", self.api)
		self.assertIn("confirm: 1", self.js)

	def test_the_pin_and_code_are_never_logged_or_written_into_a_note(self):
		for forbidden in ("log_error", "logger", "print(", "msgprint", "registration_note\": pin", "note\": pin", "format(pin", "format(code"):
			self.assertNotIn(forbidden, self.api, forbidden)

	def test_the_pin_is_stored_only_when_asked_and_encrypted(self):
		self.assertIn("if int(remember or 0):", self.api)
		self.assertIn('set_encrypted_password(DOCTYPE, doc.name, pin, "registration_pin")', self.api)

	def test_the_form_buttons_are_for_admins_and_the_dialog_uses_a_password_field(self):
		self.assertIn('["System Manager", "Waba Admin"]', self.js)
		self.assertIn('fieldtype: "Password"', self.js)
		self.assertIn("The two PINs are not the same.", self.js)

	def test_the_number_has_the_registration_fields(self):
		import json

		fields = {f["fieldname"]: f for f in json.loads(read("waba", "doctype", "waba_number", "waba_number.json"))["fields"]}
		for name in ("code_verification_status", "registered_at", "registration_pin", "registration_note"):
			self.assertIn(name, fields, name)
		self.assertEqual(fields["registration_pin"]["fieldtype"], "Password")
		self.assertEqual(fields["code_verification_status"]["read_only"], 1)
