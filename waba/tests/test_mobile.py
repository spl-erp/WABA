"""The phone inbox: its one bootstrap call and the switch that keeps it hidden until released."""

import ast
import json
import os
import unittest

BASE = os.path.join(os.path.dirname(__file__), "..")


def read(*parts):
	with open(os.path.join(BASE, *parts), encoding="utf-8") as f:
		return f.read()


def function(source, name):
	for node in ast.walk(ast.parse(source)):
		if isinstance(node, ast.FunctionDef) and node.name == name:
			return node
	raise AssertionError(name)


class TestMe(unittest.TestCase):
	def setUp(self):
		self.src = read("api", "mobile.py")
		self.fn = function(self.src, "me")

	def test_it_is_whitelisted_and_checks_the_role_first(self):
		self.assertTrue(any("whitelist" in ast.unparse(d) for d in self.fn.decorator_list))
		body = ast.get_source_segment(self.src, self.fn)
		self.assertLess(body.index("frappe.only_for(SENDERS)"), body.index("inbox.summary()"))

	def test_it_reuses_the_inbox_calls_so_the_phone_sees_what_the_browser_sees(self):
		body = ast.get_source_segment(self.src, self.fn)
		for call in ("inbox.summary()", "inbox.my_numbers()", "inbox.unread_total()", "teams.user_scope()"):
			self.assertIn(call, body)

	def test_the_version_is_an_int_the_app_can_compare(self):
		self.assertIn("API_VERSION = 1", self.src)
		self.assertIn('"api_version": API_VERSION', self.src)

	def test_no_customer_content_is_returned(self):
		body = ast.get_source_segment(self.src, self.fn)
		for word in ("body", "customer_phone", "profile_name"):
			self.assertNotIn(word, body)


class TestTheSwitch(unittest.TestCase):
	def test_phone_inbox_is_a_setting_that_is_off_by_default(self):
		doc = json.loads(read("waba", "doctype", "waba_settings", "waba_settings.json"))
		field = next(f for f in doc["fields"] if f["fieldname"] == "mobile_inbox_enabled")
		self.assertEqual((field["fieldtype"], str(field["default"])), ("Check", "0"))
		self.assertIn("mobile_inbox_enabled", doc["field_order"])
		self.assertEqual(len(doc["field_order"]), len(doc["fields"]))


from waba.rules import mobile as rules  # noqa: E402


class TestArrangeDocuments(unittest.TestCase):
	def row(self, name, doctype="Quotation"):
		return {"doctype": doctype, "name": name}

	def test_the_chats_own_customer_comes_first_and_each_document_once(self):
		out = rules.arrange_documents([self.row("A"), self.row("B")], [self.row("B"), self.row("C")])
		self.assertEqual([(r["name"], r["own"]) for r in out], [("A", True), ("B", True), ("C", False)])

	def test_the_same_name_in_another_document_type_is_a_different_document(self):
		out = rules.arrange_documents([self.row("X", "Quotation")], [self.row("X", "Sales Order")])
		self.assertEqual(len(out), 2)

	def test_the_list_is_cut_and_inputs_are_not_changed(self):
		own = [self.row(str(i)) for i in range(30)]
		self.assertEqual(len(rules.arrange_documents(own, [])), rules.MAX_DOCUMENTS)
		self.assertNotIn("own", own[0])
		self.assertEqual(rules.arrange_documents(None, None), [])

	def test_the_search_text_is_trimmed_and_cut(self):
		self.assertEqual(rules.clean_query("  abc  "), "abc")
		self.assertEqual(len(rules.clean_query("x" * 500)), 100)
		self.assertEqual(rules.clean_query(None), "")


class TestSendDeviceFile(unittest.TestCase):
	def setUp(self):
		self.src = read("api", "mobile.py")
		self.fn = function(self.src, "send_device_file")
		self.body = ast.get_source_segment(self.src, self.fn)
		self.work = ast.get_source_segment(self.src, function(self.src, "_send_upload"))  # the part that reads and sends the file

	def test_it_is_a_post_with_a_role_check_before_the_file_is_read(self):
		self.assertIn('whitelist(methods=["POST"])', ast.unparse(self.fn.decorator_list[0]).replace("'", '"'))
		self.assertLess(self.body.index("frappe.only_for(SENDERS)"), self.body.index("_uploaded_file()"))

	def test_it_never_reads_more_than_whatsapp_allows(self):
		self.assertIn("upload.stream.read(limit + 1)", self.work)
		self.assertIn("max(media_rules.LIMITS.values())", self.work)

	def test_it_uses_the_one_file_sender_as_a_person(self):
		self.assertIn("send._send_media(conversation, content, name, mime, caption, reply_to, purposes.PERSON, override_reason)", self.work)

	def test_it_stores_nothing_itself(self):
		for word in ("insert(", "File", "save("):
			self.assertNotIn(word, self.body + self.work)


class TestDocumentsForChat(unittest.TestCase):
	def setUp(self):
		self.src = read("api", "mobile.py")
		self.body = ast.get_source_segment(self.src, function(self.src, "documents_for_chat"))

	def test_it_opens_the_chat_with_the_visibility_check_and_limits_the_types(self):
		self.assertIn("inbox._open(conversation)", self.body)
		self.assertIn("doctype not in PRINTABLE", self.body)

	def test_permissions_apply_to_every_list(self):
		self.assertIn("frappe.get_list(", self.body)
		self.assertNotIn("frappe.get_all(", self.body)
		self.assertNotIn("ignore_permissions", self.body)

	def test_cancelled_documents_are_never_offered_and_the_own_customer_uses_the_shared_scope(self):
		self.assertIn('"docstatus": ["<", 2]', self.body)
		self.assertIn("bot_records.customer_scope(conv)", self.body)

	def test_the_phone_allowlist_carries_both_new_calls(self):
		path = os.path.join(BASE, "..", "..", "splinh", "splinh", "custom", "call_tracker_auth.py")
		if not os.path.exists(path):
			self.skipTest("splinh is not next to waba")
		with open(path, encoding="utf-8") as f:
			text = f.read()
		self.assertIn('"waba.api.mobile.send_device_file"', text)
		self.assertIn('"waba.api.mobile.documents_for_chat"', text)


import shutil  # noqa: E402
import subprocess  # noqa: E402

NODE = shutil.which("node")
VECTORS = os.path.join(BASE, "..", "docs", "mobile_vectors")


@unittest.skipUnless(NODE, "node is not installed")
class TestVectorsForThePhoneApp(unittest.TestCase):
	"""The shared test cases for the app team come straight from the browser's helpers, so they cannot drift."""

	def test_the_committed_vectors_match_what_the_browser_helpers_give_now(self):
		now = subprocess.check_output([NODE, os.path.join(VECTORS, "generate.js")], text=True)
		with open(os.path.join(VECTORS, "vectors.json"), encoding="utf-8") as f:
			committed = f.read()
		self.assertEqual(json.loads(now), json.loads(committed), "Rules in waba_inbox_lib.js changed: regenerate vectors.json and tell the app team")

	def test_every_group_has_cases(self):
		with open(os.path.join(VECTORS, "vectors.json"), encoding="utf-8") as f:
			data = json.load(f)
		for key in ("time_left", "wa_format", "quick_replies_filter", "fill_template", "missing_slots", "first_unread", "reminder_choices", "check_upload", "human_size", "tick_for"):
			self.assertTrue(data[key], key)

	def test_the_browser_and_the_server_accept_and_refuse_the_same_files(self):
		from waba.rules import media as media_rules

		with open(os.path.join(VECTORS, "vectors.json"), encoding="utf-8") as f:
			data = json.load(f)
		# the app is told the limits by `me`; if the browser's table and the server's ever disagreed they would refuse different files
		for case in data["check_upload"]:
			ok, kind, _why = media_rules.check_upload(case["mime"].split(";")[0], case["size"])
			self.assertEqual((ok, kind), (case["expected"]["ok"], case["expected"]["kind"]), case)


class TestClientKey(unittest.TestCase):
	"""A repeated send (the phone timed out and the person tapped again) must not reach the customer twice."""

	def test_key_shape(self):
		from waba.rules import mobile as rules

		self.assertEqual(rules.clean_client_key(None), (True, None))
		self.assertEqual(rules.clean_client_key("  "), (True, None))
		self.assertEqual(rules.clean_client_key(" 3f2b9c1e-7a54-4d1e-9b0a-1c2d3e4f5a6b "), (True, "3f2b9c1e-7a54-4d1e-9b0a-1c2d3e4f5a6b"))
		for bad in ("short", "x" * 65, "has space in it", "semi;colon;key", "quote'key'abc"):
			self.assertFalse(rules.clean_client_key(bad)[0], bad)

	def test_cache_key_is_per_person_and_conversation(self):
		from waba.rules import mobile as rules

		a = rules.duplicate_cache_key("a@x.com", "WCONV-1", "key-12345678")
		self.assertNotEqual(a, rules.duplicate_cache_key("b@x.com", "WCONV-1", "key-12345678"))
		self.assertNotEqual(a, rules.duplicate_cache_key("a@x.com", "WCONV-2", "key-12345678"))
		self.assertNotEqual(a, rules.duplicate_cache_key("a@x.com", "WCONV-1", "key-87654321"))

	def test_every_phone_send_takes_the_key_and_uses_the_guard(self):
		send, mobile = read("api", "send.py"), read("api", "mobile.py")
		for src, name in ((send, "send_text"), (send, "send_template"), (send, "send_document"), (send, "send_library_file"), (mobile, "send_device_file")):
			fn = function(src, name)
			self.assertIn("client_key", [a.arg for a in fn.args.args], name)
			self.assertIn("dedupe.once(", ast.get_source_segment(src, fn), name)

	def test_only_a_send_that_worked_is_remembered(self):
		src = read("dedupe.py")
		self.assertIn('result.get("ok")', src)
		self.assertIn("locks.conversation", src)
		self.assertIn('"duplicate": True', src)
