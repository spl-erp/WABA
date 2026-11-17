"""Run without a site:  python -m unittest waba.tests.test_small_fixes

Three small fixes: the number picker lists only a person's own numbers, the floating chat opens the inbox in a new tab,
and sharing an ERP document is logged on the customer's record and in the conversation."""

import os
import re
import unittest

APP = os.path.join(os.path.dirname(__file__), "..")


def read(*parts):
	with open(os.path.join(APP, *parts), encoding="utf-8") as handle:
		return handle.read()


INBOX_JS = read("public", "js", "waba_inbox_app.js")
DOCK_JS = read("public", "js", "waba_dock.js")
SEND = read("api", "send.py")
INBOX_API = read("api", "inbox.py")


class TestNumberPicker(unittest.TestCase):
	def test_the_picker_asks_the_server_not_the_whole_doctype(self):
		body = INBOX_JS.split("load_numbers() {")[1].split("render_numbers() {")[0]
		self.assertIn("waba.api.inbox.my_numbers", body)
		self.assertNotIn('get_list("Waba Number"', body)

	def test_one_number_means_no_dropdown_and_no_all_numbers_row(self):
		body = INBOX_JS.split("render_numbers() {")[1].split("focus_search()")[0]
		self.assertIn("numbers.length === 1", body)
		self.assertIn("waba-single", body)

	def test_the_call_is_role_checked_and_filtered_by_team(self):
		body = INBOX_API.split("def my_numbers(")[1].split("\ndef _scope")[0]
		self.assertIn("only_for(SENDERS)", body)
		self.assertIn("teams.number_names()", body)

	def test_the_desk_list_of_numbers_has_a_row_rule(self):
		hooks = read("hooks.py")
		self.assertIn('"Waba Number": "waba.permissions.number_query_conditions"', hooks)
		self.assertIn('"Waba Number": "waba.permissions.number_has_permission"', hooks)

	def test_admins_and_system_managers_see_all_numbers(self):
		body = read("teams.py").split("def number_names(")[1].split("\ndef ")[0]
		self.assertIn("is_admin(user)", body)
		self.assertIn("System Manager", body)


class TestOpenInInbox(unittest.TestCase):
	def test_the_dock_opens_a_new_tab_and_stays_put(self):
		body = DOCK_JS.split("waba-dock-inbox")[2].split("waba-dock-pick")[0]
		self.assertIn("window.open(", body)
		self.assertIn('"_blank"', body)
		self.assertNotIn("set_route", body)
		self.assertNotIn("this.close()", body)

	def test_the_inbox_reads_the_conversation_from_the_address(self):
		self.assertIn('get("conversation")', INBOX_JS)
		self.assertRegex(INBOX_JS, r"\[A-Za-z0-9_-\]")  # only a plain record name is accepted


class TestSharedDocumentLog(unittest.TestCase):
	def test_a_shared_document_is_logged_only_after_a_successful_send(self):
		body = SEND.split("def send_document(")[1].split("def _log_shared_document")[0]
		self.assertIn('if result.get("ok"):', body)
		self.assertIn("_log_shared_document(", body)

	def test_it_writes_to_the_thread_and_the_customers_record(self):
		body = SEND.split("def _log_shared_document(")[1].split("\ndef ")[0]
		self.assertIn("assignment.add_event(", body)
		self.assertIn("parties.comment(", body)
		self.assertIn("PARTY_DOCTYPES", body)

	def test_logging_can_never_undo_a_sent_message(self):
		body = SEND.split("def _log_shared_document(")[1].split("\ndef ")[0]
		self.assertIn("except Exception:", body)
		self.assertIn("log_error", body)


if __name__ == "__main__":
	unittest.main()
