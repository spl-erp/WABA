"""Run without a site:  python -m unittest waba.tests.test_start_chat

The inbox's New conversation: wiring of the button, the dialog and the server calls. The rules (consent, opt-out, daily limit)
are `start`'s and are tested with it; the database side is checked on a site by verify_start_chat."""

import os
import re
import unittest

APP = os.path.join(os.path.dirname(__file__), "..")


def read(*parts):
	with open(os.path.join(APP, *parts), encoding="utf-8") as handle:
		return handle.read()


PARTY = read("api", "party.py")
DIALOG = read("public", "js", "waba_start_chat.js")
INBOX = read("public", "js", "waba_inbox_app.js")


class TestServer(unittest.TestCase):
	def test_search_is_role_checked_and_permission_filtered(self):
		body = PARTY.split("def search_people(")[1].split("\n@frappe")[0]
		self.assertIn("only_for(SENDERS)", body)
		self.assertIn("frappe.get_list(", body)
		self.assertNotIn("frappe.get_all(", body)

	def test_search_covers_the_three_record_types_and_masks_the_phone(self):
		self.assertIn('"Lead"', PARTY)
		self.assertIn('"Customer"', PARTY)
		self.assertIn('"Contact"', PARTY)
		self.assertIn("mask_phone(", PARTY.split("def search_people(")[1])

	def test_start_chat_is_post_and_utility_only(self):
		deco = re.search(r"@frappe\.whitelist\(([^)]*)\)\s*\ndef start_chat\(", PARTY)
		self.assertIn("POST", deco.group(1))
		body = PARTY.split("def start_chat(")[1]
		self.assertIn('!= "UTILITY"', body)

	def test_an_existing_chat_is_returned_not_duplicated(self):
		body = PARTY.split("def start_chat(")[1]
		self.assertIn("conversation_has_permission(", body)
		self.assertIn('"existing": existing', body)

	def test_everything_else_is_the_one_start(self):
		self.assertIn("return start(doctype, name, number, phone, template, params)", PARTY.split("def start_chat(")[1])

	def test_context_can_leave_marketing_out(self):
		body = PARTY.split("def context(")[1].split("\n@frappe")[0]
		self.assertIn("utility_only", body)
		self.assertIn('["UTILITY"]', body)


class TestClient(unittest.TestCase):
	def test_the_inbox_has_no_new_conversation_button_for_now(self):
		for needle in ("waba-newchat", "onNewChat", "new_chat()", "waba_start_chat.js"):
			self.assertNotIn(needle, INBOX)

	def test_the_dialog_calls_only_real_methods(self):
		used = set(re.findall(r"waba\.api\.(?:party|inbox)\.(\w+)", DIALOG))
		defined = set(re.findall(r"\ndef (\w+)\(", PARTY + read("api", "inbox.py")))
		self.assertTrue(used)
		self.assertFalse(used - defined, used - defined)

	def test_utility_only_and_existing_chat_handling(self):
		self.assertIn("utility_only: 1", DIALOG)
		self.assertIn("out.existing", DIALOG)
		self.assertIn("Open chat", DIALOG)

	def test_people_text_is_escaped(self):
		self.assertIn("frappe.utils.escape_html", DIALOG)
		self.assertNotRegex(DIALOG, r">\$\{r\.(title|name|doctype)\}")

	def test_the_file_is_in_the_cache_stamp_and_the_icon_exists(self):
		self.assertIn("js/waba_start_chat.js", read("api", "inbox.py"))
		self.assertIn("compose:", read("public", "js", "waba_inbox_lib.js"))


if __name__ == "__main__":
	unittest.main()
