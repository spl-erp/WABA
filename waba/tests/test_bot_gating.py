"""Run without a site:  python -m unittest waba.tests.test_bot_gating

The preview bot features are hidden behind Waba Settings > "Bot builder: preview blocks" (off by default). These tests pin that the
switch is enforced on the SERVER (publishing, running, the scan, the gallery, the counts), not only drawn in the screen, and that the
lookups can only ever reach the chat's own records."""

import ast
import json
import os
import re
import unittest

HERE = os.path.dirname(__file__)
APP = os.path.join(HERE, "..")


def read(*parts):
	with open(os.path.join(APP, *parts), encoding="utf-8") as handle:
		return handle.read()


def function(source, name):
	for node in ast.walk(ast.parse(source)):
		if isinstance(node, ast.FunctionDef) and node.name == name:
			return ast.get_source_segment(source, node)
	raise AssertionError(name)


BOT = read("bot.py")
API = read("api", "bots.py")
SEND = read("api", "send.py")
RECORDS = read("bot_records.py")
BOOT = read("boot.py")
DOCTYPE_PY = read("waba", "doctype", "waba_bot", "waba_bot.py")
FORM_JS = read("waba", "doctype", "waba_bot", "waba_bot.js")
CANVAS = read("public", "js", "waba_bot_canvas.js")
SETTINGS = json.loads(read("waba", "doctype", "waba_settings", "waba_settings.json"))
SESSION = json.loads(read("waba", "doctype", "waba_bot_session", "waba_bot_session.json"))


def fields(d):
	return {f["fieldname"]: f for f in d["fields"]}


class TestTheSwitchExists(unittest.TestCase):
	def test_it_is_off_by_default(self):
		f = fields(SETTINGS)["bot_extra_blocks"]
		self.assertEqual((f["fieldtype"], str(f.get("default"))), ("Check", "0"))

	def test_the_session_has_the_timeout_fields(self):
		f = fields(SESSION)
		self.assertEqual(f["timeout_at"]["fieldtype"], "Datetime")
		self.assertTrue(f["timeout_at"].get("search_index"))
		self.assertEqual(f["timeouts"]["fieldtype"], "Int")

	def test_the_builder_learns_the_flag_at_login_and_only_for_waba_users(self):
		self.assertIn("waba_extra_blocks", BOOT)
		self.assertIn("bot_extra_blocks", BOOT)
		self.assertIn("if bootinfo.waba_alerts else 0", BOOT)


class TestTheServerEnforcesIt(unittest.TestCase):
	def test_publish_refuses_preview_blocks_while_off(self):
		self.assertIn("rules.validate_graph(graph, engine.extras_on())", DOCTYPE_PY)

	def test_check_save_and_simulate_use_the_same_rule(self):
		for name in ("check", "save_draft", "simulate", "use_starter"):
			self.assertIn("engine.extras_on()", function(API, name), name)

	def test_a_published_bot_is_not_run_once_the_switch_goes_off(self):
		body = function(BOT, "_step")
		self.assertIn("rules.uses_extras(graph) and not extras_on()", body)
		self.assertIn("finish(session, conv, rules.HANDED_OVER", body.split("rules.uses_extras(graph) and not extras_on()")[1].split("\n")[1])  # the chat is handed on, never stranded

	def test_the_timeout_scan_does_nothing_while_off(self):
		body = function(BOT, "fire_timeouts")
		self.assertLess(body.index("not extras_on()"), body.index("notify.as_system()"))  # checked before anything is read or run

	def test_the_gallery_and_the_counts_are_empty_while_off(self):
		self.assertIn("bot_starters.catalog(engine.extras_on())", function(API, "starters"))
		self.assertIn("not engine.extras_on()", function(API, "block_counts"))
		self.assertIn('{"enabled": False', function(API, "block_counts"))

	def test_an_unavailable_starter_cannot_be_used_by_calling_the_api_directly(self):
		self.assertIn("not in {s[\"key\"] for s in bot_starters.catalog(engine.extras_on())}", function(API, "use_starter"))

	def test_a_draft_may_hold_preview_blocks_but_never_goes_live(self):
		self.assertNotIn("published_json", function(API, "save_draft").replace("published_json", "published_json", 0).split('"""')[-1])


class TestOwnRecordsOnly(unittest.TestCase):
	def test_every_query_is_filtered_to_the_chats_own_customer_or_lead(self):
		self.assertIn('"party_name": ["in", names]', RECORDS)
		self.assertIn('"quotation_to": party_type', RECORDS)
		self.assertEqual(RECORDS.count('"customer": ["in", customers]'), 2)  # Sales Order and Sales Invoice
		self.assertIn('"docstatus": 1', RECORDS)

	def test_an_unmatched_chat_gets_nothing(self):
		body = function(RECORDS, "customer_scope")
		self.assertIn("if not doctype or not name or not frappe.db.exists(doctype, name):", body)
		self.assertIn("return [], []", body)
		for finder in ("_sales_order", "_sales_invoice"):
			self.assertIn("if not customers:", function(RECORDS, finder))

	def test_what_the_customer_types_never_picks_a_document(self):
		# the lookup takes document TYPES from the bot's design and the chat's own record; there is no text argument
		self.assertEqual(re.findall(r"def latest_documents\((.*?)\):", RECORDS), ["conv, doctypes"])
		self.assertNotIn("body", function(RECORDS, "latest_documents"))

	def test_the_pdf_name_comes_from_the_lookup(self):
		body = function(BOT, "_send_document")
		self.assertIn('action["name"]', body)
		self.assertIn("bot_records.pdf_of(doctype, name)", body)
		facts = function(BOT, "_facts")
		self.assertIn("bot_records.latest_documents(conv, docs)", facts)

	def test_only_known_document_types_can_be_printed(self):
		self.assertIn("doctype not in bot_docs.DOC_TYPES", function(RECORDS, "pdf_of"))

	def test_the_library_file_must_be_enabled_and_unexpired(self):
		body = function(RECORDS, "files_status")
		for needle in ("row.enabled", "row.file", "valid_until"):
			self.assertIn(needle, body)

	def test_nothing_is_evaluated(self):
		for source in (RECORDS, BOT):
			code = re.sub(r'""".*?"""', "", source, flags=re.S)
			for word in ("eval(", "exec(", "safe_eval", "__import__"):
				self.assertNotIn(word, code)


class TestSending(unittest.TestCase):
	def test_the_link_sender_is_not_whitelisted_and_keeps_every_text_check(self):
		node = next(n for n in ast.walk(ast.parse(SEND)) if isinstance(n, ast.FunctionDef) and n.name == "send_automatic_cta")
		self.assertFalse(any("whitelist" in ast.dump(d) for d in node.decorator_list))
		body = ast.get_source_segment(SEND, node)
		for needle in ("refuse_if_receive_only()", "check_free_text(", "check_recipient(", "check_cta(", "sent_by=None"):
			self.assertIn(needle, body, needle)

	def test_a_file_the_bot_sends_records_no_person(self):
		self.assertIn("person=False", function(BOT, "_send_document"))
		self.assertIn("sent_by=False if person else None", function(SEND, "_send_media"))

	def test_the_activity_log_names_the_bot_not_a_person(self):
		self.assertIn("who=_(", function(BOT, "_send_document"))
		self.assertIn("who = who or", function(SEND, "_log_shared_document"))

	def test_a_failed_document_hands_the_chat_over_like_any_failed_send(self):
		self.assertIn("send_failed", function(BOT, "_step"))


class TestTimeouts(unittest.TestCase):
	def test_the_scan_is_the_existing_two_minute_job(self):
		self.assertIn("fire_timeouts()", function(BOT, "expire_sessions"))
		self.assertIn("waba.bot.expire_sessions", read("hooks.py"))

	def test_it_runs_once_per_wait_under_the_conversation_lock(self):
		body = function(BOT, "_timeout_one")
		self.assertIn('"timeout_at", None', body)  # claimed first
		self.assertIn("rules.MAX_TIMEOUTS", body)
		self.assertIn("f\"timeout-{name}-{(session.timeouts or 0) + 1}\"", body)  # the log key makes a retried step a no-op
		self.assertIn("locks.conversation(s.conversation)", function(BOT, "fire_timeouts"))

	def test_a_person_or_an_opt_out_ends_it_instead(self):
		body = function(BOT, "_timeout_one")
		self.assertIn("conv.assigned_to", body)
		self.assertIn("conv.opted_out", body)

	def test_the_next_deadline_is_set_only_while_waiting(self):
		self.assertIn("waiting_again = bool(result.timeout_minutes) and not result.ended", function(BOT, "_step"))


class TestScreens(unittest.TestCase):
	def test_the_builder_reads_the_flag_and_hides_the_group_and_extras(self):
		self.assertIn("frappe.boot.waba_extra_blocks", CANVAS)
		self.assertIn('key !== "more" || this.extras', CANVAS)
		self.assertIn("this.extras && !this.compact", CANVAS)  # the numbers toggle
		self.assertIn('if (this.extras && ["buttons", "list", "ask"]', CANVAS)  # the timeout field

	def test_the_gallery_only_opens_while_the_flag_is_on(self):
		self.assertIn("if (!(frappe.boot && frappe.boot.waba_extra_blocks)) return welcome_starter(frm);", FORM_JS)

	def test_the_simulator_never_sends(self):
		self.assertNotIn("send_automatic", CANVAS)

	def test_real_methods_only(self):
		defined = {name for _d, name in re.findall(r"@frappe\.whitelist\(([^)]*)\)\s*\ndef (\w+)\(", API)}
		called = set(re.findall(r"waba\.api\.bots\.(\w+)", CANVAS + FORM_JS))
		self.assertFalse(called - defined, called - defined)
		self.assertTrue({"block_counts", "starters", "use_starter", "simulate"} <= called)


if __name__ == "__main__":
	unittest.main()
