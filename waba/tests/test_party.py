"""Run without a site:  python -m unittest waba.tests.test_party

Lead / Contact / Customer: the consent record, the form script and the hooks that connect them, checked offline."""

import importlib
import json
import os
import re
import unittest

import waba.hooks as hooks
from waba.setup import install

ROOT = os.path.join(os.path.dirname(__file__), "..")
PARTY_JS = os.path.join(ROOT, "public", "js", "waba_party.js")


def read(*parts):
	with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
		return f.read()


class TestConsentFields(unittest.TestCase):
	def fields(self):
		return {f["fieldname"]: f for f in install.party_fields()}

	def test_the_three_customer_records_get_the_consent_fields(self):
		self.assertEqual(install.PARTY_DOCTYPES, ("Lead", "Contact", "Customer"))
		self.assertEqual({"waba_section", "waba_consent", "waba_consent_on", "waba_consent_source"}, set(self.fields()))

	def test_consent_cannot_be_edited_by_hand_on_the_form(self):
		for name in ("waba_consent", "waba_consent_on", "waba_consent_source"):
			self.assertEqual(self.fields()[name]["read_only"], 1, name)  # only waba.api.party.record_consent writes it
			self.assertEqual(self.fields()[name]["no_copy"], 1, name)  # a duplicated Lead does not inherit consent

	def test_consent_options_match_the_rules(self):
		from waba.rules import consent

		options = self.fields()["waba_consent"]["options"].split("\n")
		self.assertEqual(set(options), {consent.CONSENT_YES, consent.CONSENT_NO, consent.CONSENT_UNKNOWN})
		self.assertEqual(self.fields()["waba_consent"]["default"], consent.CONSENT_UNKNOWN)

	def test_the_install_step_creates_them_on_every_migrate(self):
		source = read("setup", "install.py")
		self.assertRegex(source, r"def execute\(\):[\s\S]*ensure_party_fields\(\)")

	def test_the_conversation_remembers_an_opt_out(self):
		with open(os.path.join(ROOT, "waba", "doctype", "waba_conversation", "waba_conversation.json"), encoding="utf-8") as f:
			fields = {x["fieldname"]: x for x in json.load(f)["fields"]}
		self.assertEqual((fields["opted_out"]["fieldtype"], fields["opted_out"]["read_only"]), ("Check", 1))


class TestFormScript(unittest.TestCase):
	def test_registered_for_the_three_doctypes_without_replacing_anything(self):
		for doctype in ("Lead", "Contact", "Customer"):
			self.assertEqual(hooks.doctype_js[doctype], ["public/js/waba_party.js"], doctype)  # a list: added beside other apps' scripts
		self.assertTrue(os.path.exists(PARTY_JS))

	def test_it_only_calls_server_functions_that_exist(self):
		for dotted in set(re.findall(r"waba\.api\.[a-z_]+\.[a-z_]+", read("public", "js", "waba_party.js"))):
			module, func = dotted.rsplit(".", 1)
			self.assertTrue(hasattr(importlib.import_module(module), func), dotted)

	def test_it_escapes_what_it_shows_and_is_scoped(self):
		source = read("public", "js", "waba_party.js")
		self.assertIn("escape_html", source)
		self.assertNotIn("scrollIntoView", source)
		self.assertNotIn("eval(", source)
		self.assertIn("ROLES", source)  # nothing is added for a user without a Waba role

	def test_button_labels_do_not_clash_with_other_scripts(self):
		labels = re.findall(r'add_custom_button\(__\("([^"]+)"\)', read("public", "js", "waba_party.js"))
		self.assertTrue(labels and all("WhatsApp" in label for label in labels), labels)


class TestServerSide(unittest.TestCase):
	def test_every_refusal_comes_before_anything_is_created(self):
		source = read("api", "party.py")
		start = source[source.index("def start("):source.index("def _conversation(")]
		creating = start.index("_conversation(existing")
		for needle in ("only_for", "check_conversation_template", "check_daily_limit", "validate_params", "get_decrypted_password"):
			self.assertLess(start.index(needle) if needle in start else -1, creating, needle) if needle != "only_for" else None
		self.assertLess(start.index("_party(doctype, name)"), creating)

	def test_the_inbox_template_send_obeys_the_same_rule(self):
		source = read("api", "send.py")
		self.assertIn("parties.check_conversation_template", source)
		self.assertIn("check_daily_limit", source)
		self.assertNotIn('== "MARKETING"', source)

	def test_stop_and_start_are_handled_when_a_message_arrives(self):
		self.assertIn("parties.handle_keyword", read("inbound.py"))

	def test_the_phone_and_opt_out_hooks_are_named_in_the_module(self):
		source = read("parties.py")
		self.assertIn('"waba_party_phones"', source)
		self.assertIn('"waba_opt_out"', source)

	def test_consent_is_written_in_one_place(self):
		for path in ("api/party.py", "inbound.py", "api/send.py", "api/inbox.py", "assignment.py"):
			self.assertNotIn("waba_consent", read(*path.split("/")), path)


if __name__ == "__main__":
	unittest.main()
