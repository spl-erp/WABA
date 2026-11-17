"""Run without a site:  python -m unittest waba.tests.test_privacy

Source and structure checks for the sensitive-details block (the behaviour is in the UAT check script verify_w3)."""

import ast
import json
import os
import unittest

BASE = os.path.join(os.path.dirname(__file__), "..")


def read(*parts):
	with open(os.path.join(BASE, *parts), encoding="utf-8") as handle:
		return handle.read()


class TestSendPath(unittest.TestCase):
	def setUp(self):
		self.send = read("api", "send.py")
		self.tree = ast.parse(self.send)

	def function(self, name):
		return next(n for n in self.tree.body if isinstance(n, ast.FunctionDef) and n.name == name)

	def test_every_whitelisted_sender_of_content_accepts_a_reason(self):
		for name in ("send_text", "send_template", "send_file", "send_document", "send_library_file"):
			args = [a.arg for a in self.function(name).args.args]
			self.assertIn("override_reason", args, name)

	def test_the_check_runs_in_the_one_choke_point_before_anything_is_stored(self):
		body = self.send[self.send.index("def _deliver("):]
		check = body.index("privacy.check(")
		self.assertLess(check, body.index('"doctype": "Waba Message"'))
		self.assertLess(check, body.index("graph.send_message("))

	def test_a_message_sent_again_is_not_scanned_twice(self):
		retry = self.send[self.send.index("def retry_message("):]
		self.assertEqual(retry.count("skip_privacy=True"), 2)

	def test_a_blocked_upload_is_kept_so_it_can_be_sent_again(self):
		self.assertIn('if result.get("blocked"):', self.send)

	def test_the_browser_cannot_pick_an_origin_so_only_person_messages_are_scanned(self):
		privacy = read("privacy.py")
		self.assertIn("if origin != purposes.PERSON", privacy)


class TestPrivacyModule(unittest.TestCase):
	def setUp(self):
		self.src = read("privacy.py")

	def test_a_missing_setting_means_the_check_is_on(self):
		self.assertIn('get_single_value("Waba Settings", "privacy_disabled")', self.src)
		self.assertIn("not frappe.db.get_single_value", self.src)  # the per-type tick means "do not check"

	def test_only_leads_supervisors_and_admins_may_override_and_a_reason_is_required(self):
		self.assertIn("scope.everything or scope.is_lead", self.src)
		self.assertIn('SUPERVISOR_ROLES = ("Waba Supervisor", "Waba Admin")', self.src)
		self.assertIn("if can_override and reason:", self.src)

	def test_the_log_and_the_note_hold_masked_samples_never_the_text(self):
		log = self.src[self.src.index("def _log("):self.src.index("def check(")]
		self.assertIn("h['sample']", log)
		self.assertNotIn("text)", log.split("assignment.add_event")[0].replace("text = (", ""))  # the message text is not passed in
		self.assertNotIn("ctx.values", log)

	def test_the_log_is_written_before_the_answer_is_returned(self):
		check = self.src[self.src.index("def check("):]
		self.assertLess(check.index('_log(ctx, hits, "Blocked", None)'), check.index("return {"))


class TestDoctypes(unittest.TestCase):
	def test_the_log_is_read_only_and_never_has_a_raw_value_field(self):
		doc = json.loads(read("waba", "doctype", "waba_privacy_log", "waba_privacy_log.json"))
		fields = {f["fieldname"]: f for f in doc["fields"]}
		self.assertEqual(set(fields), {"user", "action", "waba_number", "conversation", "column_break_pl1", "codes", "samples", "reason"})
		for name, f in fields.items():
			if f["fieldtype"] != "Column Break":
				self.assertEqual(f.get("read_only"), 1, name)
		roles = {p["role"] for p in doc["permissions"]}
		self.assertEqual(roles, {"System Manager", "Waba Admin"})
		for p in doc["permissions"]:
			self.assertNotIn("write", p)
			self.assertNotIn("create", p)

	def test_the_settings_have_the_privacy_section_and_default_to_on(self):
		doc = json.loads(read("waba", "doctype", "waba_settings", "waba_settings.json"))
		fields = {f["fieldname"]: f for f in doc["fields"]}
		for name in ("privacy_disabled", "privacy_skip_aadhaar", "privacy_skip_pan", "privacy_skip_card", "privacy_skip_bank", "privacy_skip_upi", "privacy_skip_otp", "privacy_allow_list"):
			self.assertIn(name, fields, name)
		for name in [n for n in fields if n.startswith("privacy_skip") or n == "privacy_disabled"]:
			self.assertEqual(str(fields[name]["default"]), "0", name)  # unticked: the check is on


class TestBrowser(unittest.TestCase):
	def setUp(self):
		self.js = read("public", "js", "waba_inbox_app.js")

	def test_every_send_path_goes_through_the_one_handler(self):
		self.assertIn("if (out.blocked) return this.privacy_dialog(out, method, args);", self.js)
		for call in ('this.send("send_file"', 'this.send("send_document"', 'this.send("send_library_file"'):
			self.assertIn(call, self.js, call)

	def test_an_agent_cannot_override_and_a_lead_must_give_a_reason(self):
		body = self.js[self.js.index("privacy_dialog(out, method, args) {"):]
		self.assertIn("if (!out.can_override)", body)
		self.assertIn('fieldname: "reason"', body)
		self.assertIn("reqd: 1", body)
		self.assertIn("override_reason: v.reason", body)
