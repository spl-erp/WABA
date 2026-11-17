"""Run without a site:  python -m unittest waba.tests.test_bot_ui

The bot screens' wiring: the builder only calls real server methods, escapes what people typed, saves a draft (never the live
version), is admin only, and the inbox shows the Bot chip, the banner and Take over."""

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


CANVAS = read("public", "js", "waba_bot_canvas.js")
GRAPH = read("public", "js", "waba_bot_graph.js")
FORM = read("waba", "doctype", "waba_bot", "waba_bot.js")
API = read("api", "bots.py")
INBOX_API = read("api", "inbox.py")
INBOX_JS = read("public", "js", "waba_inbox_app.js")
LIB = read("public", "js", "waba_inbox_lib.js")
CSS = read("public", "css", "waba_inbox.css")
BOT = read("bot.py")
SPEC = read("setup", "workspace_spec.py")
SIDEBAR = json.loads(read("waba", "sidebar", "waba", "waba.json"))


def function(source, name):
	for node in ast.walk(ast.parse(source)):
		if isinstance(node, ast.FunctionDef) and node.name == name:
			return ast.get_source_segment(source, node)
	raise AssertionError(name)


def whitelisted(source):
	return {name for _d, name in re.findall(r"@frappe\.whitelist\(([^)]*)\)\s*\ndef (\w+)\(", source)}


class TestBuilderCallsRealMethods(unittest.TestCase):
	def test_every_bots_call_exists(self):
		called = set(re.findall(r"waba\.api\.bots\.(\w+)", CANVAS + FORM))
		self.assertTrue(called)
		self.assertFalse(called - whitelisted(API), called - whitelisted(API))

	def test_every_inbox_call_exists(self):
		called = set(re.findall(r"waba\.api\.inbox\.(\w+)", FORM + INBOX_JS))
		self.assertFalse(called - whitelisted(INBOX_API), called - whitelisted(INBOX_API))
		self.assertIn("take_over_from_bot", called)

	def test_the_writes_are_posts(self):
		for name in ("save_draft", "publish", "use_starter", "simulate"):
			self.assertRegex(CANVAS + FORM, re.compile(rf'method: "waba\.api\.bots\.{name}".{{0,300}}?type: "POST"', re.S))
		self.assertIn("POST", re.search(r"whitelist\(([^)]*)\)\s*\ndef save_draft", API).group(1))

	def test_assets_are_in_the_cache_stamp(self):
		stamp = function(INBOX_API, "assets_version")
		self.assertIn("js/waba_bot_graph.js", stamp)
		self.assertIn("js/waba_bot_canvas.js", stamp)

	def test_the_form_loads_the_graph_helpers_before_the_canvas(self):
		self.assertLess(FORM.index('load("waba_bot_graph.js")'), FORM.index('load("waba_bot_canvas.js")'))


class TestBuilderSafety(unittest.TestCase):
	def test_what_people_type_is_escaped_before_it_is_drawn(self):
		self.assertIn("frappe.utils.escape_html", CANVAS)
		# the preview of a block is plain text; it is only ever drawn through esc()
		self.assertGreater(CANVAS.count("this.preview("), 0)
		self.assertEqual(CANVAS.count("this.preview("), CANVAS.count("esc(this.preview("))
		# values that go straight into markup (not through a helper that escapes) would be an XSS
		for raw in re.findall(r"<[a-z]+[^>`]*\$\{(?:d|b|r|m|p|node)\.(?:text|title|description|team|var|value|keywords|button_text|retry_text|id)\}", CANVAS):
			self.fail(f"unescaped value in the canvas: {raw}")
		self.assertNotRegex(CANVAS, r">\$\{[a-z.]*\.(text|title|body)\}<")

	def test_jquery_is_never_shadowed(self):
		# a local named $ hides jQuery inside every handler written after it ("$ is not a function")
		for source in (CANVAS, FORM):
			self.assertIsNone(re.search(r"\b(const|let|var)\s+\$\s*=", source))

	def test_no_code_is_evaluated_in_the_browser(self):
		for source in (CANVAS, GRAPH, FORM):
			self.assertIsNone(re.search(r"\beval\(|new Function\(|document\.write\(", source))

	def test_saving_the_draft_never_publishes(self):
		self.assertNotIn("published_json", function(API, "save_draft").split('"""')[2].replace("doc.published_json", "") if False else function(API, "save_draft"))
		self.assertIn("doc.graph_json = text", function(API, "save_draft"))

	def test_the_server_limits_what_a_save_may_hold(self):
		body = function(API, "save_draft")
		for needle in ("MAX_GRAPH_BYTES", "MAX_NODES", "json.loads(graph)"):
			self.assertIn(needle, body)

	def test_only_a_waba_admin_may_save_or_check(self):
		for name in ("save_draft", "check", "publish", "simulate", "use_starter"):
			self.assertIn("_bot(", function(API, name), name)


class TestBuilderBehaviour(unittest.TestCase):
	def test_it_autosaves_a_draft_shortly_after_a_change(self):
		self.assertIn("SAVE_DELAY", CANVAS)
		self.assertIn('method: "waba.api.bots.save_draft"', CANVAS)
		self.assertIn("this.timer = setTimeout(() => this.save(false), SAVE_DELAY)", CANVAS)

	def test_publish_saves_first_and_asks_before_going_live(self):
		body = CANVAS.split("publish() {")[1].split("close() {")[0]
		self.assertLess(body.index("this.save(false)"), body.index("frappe.confirm("))
		self.assertIn("this.problems.length", body)

	def test_closing_saves_pending_work(self):
		self.assertIn("this.dirty ? this.save(false)", CANVAS.split("close() {")[1])

	def test_keyboard_shortcuts(self):
		for key in ('"Delete"', '"Escape"', 'key.toLowerCase() === "s"', 'key.toLowerCase() === "z"'):
			self.assertIn(key, CANVAS)

	def test_typing_in_a_field_never_deletes_a_block(self):
		self.assertIn("/^(INPUT|TEXTAREA|SELECT)$/.test(ev.target.tagName)", CANVAS)

	def test_the_trigger_cannot_be_deleted_or_copied_from_the_ui(self):
		self.assertIn('node.type === "trigger"', function_js("remove_node"))
		self.assertIn('n.type === "trigger" ? ""', CANVAS)  # no menu on the Trigger card

	def test_editing_is_off_on_a_phone_but_the_simulator_stays(self):
		self.assertIn("window.innerWidth < 700", CANVAS)
		self.assertIn("wbb-compact", CANVAS)
		self.assertIn("if (this.compact) this.tab = \"try\"", CANVAS)
		self.assertIn("if (this.compact) return;", CANVAS)

	def test_the_simulator_sends_nothing_and_tries_the_draft_or_the_live_version(self):
		body = CANVAS.split("sim_call(text, id, event) {")[1].split("mark_active(id) {")[0]
		self.assertIn("waba.api.bots.simulate", body)
		self.assertNotIn("send_", body)
		self.assertIn("published: s.published", body)
		self.assertIn("this.save(false)", body)  # the draft on the server is what is tried

	def test_choices_respect_metas_limits_in_the_form(self):
		for needle in ("G.MAX_BUTTONS", "G.MAX_ROWS", "this.counter(", ", 20)", ", 24)"):
			self.assertIn(needle, CANVAS)

	def test_problems_are_listed_and_mark_the_block(self):
		self.assertIn("wbb-flag", CANVAS)
		self.assertIn("waba.api.bots.check", CANVAS)
		self.assertIn("p.node", CANVAS)

	def test_dark_and_light_follow_the_desk_theme(self):
		self.assertIn("var(--card-bg", CANVAS)
		self.assertIn('[data-theme="dark"]', CANVAS)

	def test_reduced_motion_is_respected(self):
		self.assertIn("prefers-reduced-motion", CANVAS)


def function_js(name):
	"""The text of a method in the canvas class, up to the next method at the same indent."""
	start = CANVAS.index(f"\t\t{name}(")
	end = CANVAS.index("\n\t\t}\n", start)
	return CANVAS[start:end]


class TestFormScript(unittest.TestCase):
	def test_buttons(self):
		for label in ("Open builder", "Use starter", "Publish", "See sessions", "See log"):
			self.assertIn(label, FORM)

	def test_the_design_json_is_not_shown_for_hand_editing(self):
		self.assertIn('set_df_property("graph_json", "hidden", 1)', FORM)

	def test_the_form_is_saved_before_the_builder_opens(self):
		self.assertIn("frm.is_dirty()", FORM)


class TestInboxPieces(unittest.TestCase):
	def test_rows_get_a_bot_flag_from_one_query(self):
		body = function(INBOX_API, "conversations")
		self.assertEqual(body.count("Waba Bot Session"), 1)
		self.assertIn('row["bot"] = with_bots.get(row.name)', body)

	def test_the_thread_says_which_bot_is_talking(self):
		self.assertIn('"bot": frappe.db.get_value("Waba Bot Session"', function(INBOX_API, "thread"))

	def test_messages_carry_the_bot_name(self):
		self.assertIn('"bot",', INBOX_API.split("MESSAGE_FIELDS = [")[1].split("]")[0])
		self.assertIn("Auto-reply \\u00b7 ${m.bot}", LIB)

	def test_take_over_checks_visibility_and_that_a_bot_is_there(self):
		body = function(INBOX_API, "take_over_from_bot")
		self.assertIn("_open(conversation)", body)
		self.assertIn("bot.active_session(conv.name)", body)
		self.assertIn("bot.take_over(conv)", body)
		self.assertIn("POST", re.search(r"whitelist\(([^)]*)\)\s*\ndef take_over_from_bot", INBOX_API).group(1))

	def test_chip_banner_and_button(self):
		self.assertIn("waba-chip bot", INBOX_JS)
		self.assertIn("waba-bot-line", INBOX_JS)
		self.assertIn("waba-takeover", INBOX_JS)
		self.assertIn("onTakeOver", INBOX_JS)
		self.assertIn("waba.api.inbox.take_over_from_bot", INBOX_JS)
		self.assertIn(".waba-chip.bot", CSS)

	def test_the_bot_banner_text_is_escaped(self):
		self.assertIn("waba_e(c.bot)", INBOX_JS)

	def test_the_chip_updates_live(self):
		self.assertIn('assignment.notify(conversation, "bot")', BOT)


class TestSidebar(unittest.TestCase):
	def test_the_automation_entries_are_in_the_sidebar_and_the_workspace(self):
		labels = {i.get("link_to") for i in SIDEBAR["items"]}
		for doctype in ("Waba Bot", "Waba Bot Session", "Waba Bot Log"):
			self.assertIn(doctype, labels)
			self.assertIn(doctype, SPEC)


if __name__ == "__main__":
	unittest.main()


class TestAssignAgentPicker(unittest.TestCase):
	def test_the_form_asks_the_server_for_the_team_agents_and_escapes_them(self):
		canvas = CANVAS
		self.assertIn("waba.api.bots.team_agents", canvas)
		self.assertIn("esc(a.full_name)", canvas)
		self.assertIn("G.setTeam(self.graph, id, value)", canvas)

	def test_the_endpoint_is_admin_only(self):
		body = function(read("api", "bots.py"), "team_agents")
		self.assertIn("_admin_only()", body)


class TestStartsPanel(unittest.TestCase):
	def test_the_panel_edits_starts_through_the_helpers_and_escapes(self):
		self.assertIn("G.addStart(this.graph)", CANVAS)
		self.assertIn("G.removeStart(this.graph", CANVAS)
		self.assertIn("G.setStart(self.graph", CANVAS)
		self.assertIn("G.normalizeTrigger(this.graph)", CANVAS)
		self.assertIn('esc(x.keywords || "")', CANVAS)

	def test_the_simulator_can_pick_a_start_and_the_endpoint_takes_it(self):
		self.assertIn("start: s.start", CANVAS)
		self.assertIn("start: str | None", read("api", "bots.py"))

