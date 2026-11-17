"""Run without a site:  python -m unittest waba.tests.test_bot_engine

How the bot is wired in: where the hook sits, that it never calls Meta from the webhook, that routing leaves a bot's chat alone,
who may build bots, and that no code is ever evaluated. The decisions are in test_bot_rules; the database side is checked on a
site by verify_bot."""

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


def load(*parts):
	return json.loads(read(*parts))


INBOUND = read("inbound.py")
BOT = read("bot.py")
RULES = read("rules", "bot.py")
API = read("api", "bots.py")
SEND = read("api", "send.py")
ASSIGNMENT = read("assignment.py")
HOOKS = read("hooks.py")
INBOX = read("api", "inbox.py")
BOT_DOCTYPE = load("waba", "doctype", "waba_bot", "waba_bot.json")
SESSION_DOCTYPE = load("waba", "doctype", "waba_bot_session", "waba_bot_session.json")
LOG_DOCTYPE = load("waba", "doctype", "waba_bot_log", "waba_bot_log.json")
SETTINGS = load("waba", "doctype", "waba_settings", "waba_settings.json")
MESSAGE = load("waba", "doctype", "waba_message", "waba_message.json")


def function(source, name):
	for node in ast.walk(ast.parse(source)):
		if isinstance(node, ast.FunctionDef) and node.name == name:
			return ast.get_source_segment(source, node)
	raise AssertionError(name)


def fields(definition):
	return {f["fieldname"]: f for f in definition["fields"]}


class TestHookPosition(unittest.TestCase):
	def test_the_bot_runs_after_stop_and_before_routing(self):
		block = INBOUND.split("with locks.conversation(conversation.name):")[1].split("assignment.notify(conversation")[0]
		order = [block.index(x) for x in ("_keyword(", "_campaign_reply(", "_bot(", "_route(")]
		self.assertEqual(order, sorted(order))

	def test_a_failing_bot_never_loses_the_stored_message(self):
		body = function(INBOUND, "_bot")
		self.assertIn("try:", body)
		self.assertIn("frappe.log_error", body)

	def test_the_hook_decides_but_never_sends(self):
		body = function(BOT, "on_inbound")
		for word in ("send.", "graph.", "_perform(", "advance("):
			self.assertNotIn(word, body)
		self.assertIn("_enqueue(", body)
		self.assertIn("enqueue_after_commit=True", function(BOT, "_enqueue"))

	def test_a_bot_held_back_by_a_guard_says_why_in_the_chat(self):
		body = function(BOT, "on_inbound")
		self.assertIn("skipped.append((b.name, held[1]))", body)
		self.assertIn('did not answer: {1}', body)
		self.assertLess(body.index("if skipped:"), body.index("return", body.index("if skipped:")))

	def test_the_session_exists_before_routing_runs(self):
		# the session is inserted inside on_inbound, in the webhook transaction, so assignment.assign sees it
		self.assertIn('"doctype": SESSION', function(BOT, "on_inbound"))


class TestTheJob(unittest.TestCase):
	def test_it_runs_as_the_system_under_the_conversation_lock(self):
		body = function(BOT, "advance")
		self.assertIn("notify.as_system()", body)
		self.assertIn("locks.conversation(conversation)", body)

	def test_every_guard_is_checked_again_when_the_job_runs(self):
		body = function(BOT, "_advance") + function(BOT, "_step")
		for needle in ("if conv.assigned_to:", "conv.opted_out", "switched_on()", "bot.enabled", "frappe.db.exists(LOG"):
			self.assertIn(needle, body, needle)

	def test_the_decision_is_logged_before_anything_is_sent(self):
		body = function(BOT, "_step")
		self.assertLess(body.index("frappe.get_doc({\"doctype\": LOG"), body.index("_perform("))

	def test_a_message_cap_stops_a_runaway_bot(self):
		self.assertIn("rules.over_cap(", function(BOT, "_step"))

	def test_a_failed_send_hands_the_chat_over(self):
		body = function(BOT, "_step")
		self.assertIn("send_failed", body)
		self.assertIn("finish(", body)

	def test_the_bot_speaks_as_an_automatic_reply_with_nobody_as_sender(self):
		body = function(BOT, "_perform")
		self.assertIn("purposes.AUTO_REPLY", body)
		self.assertIn("send.send_automatic_text(", body)
		self.assertIn("send.send_automatic_interactive(", body)

	def test_a_chat_is_never_stranded(self):
		body = function(BOT, "finish")
		self.assertIn("assignment.assign(conv)", body)
		self.assertIn("assignment.assign_to_team(conv, team, agent)", body)
		self.assertIn('"active_key": None', body)

	def test_stopping_for_a_person_routes_nothing(self):
		self.assertNotIn("assignment.assign(", function(BOT, "stop"))

	def test_a_silent_customer_is_released(self):
		self.assertIn("waba.bot.expire_sessions", HOOKS)
		self.assertIn("rules.EXPIRED", function(BOT, "expire_sessions"))


class TestSenders(unittest.TestCase):
	def test_automatic_senders_are_not_whitelisted(self):
		tree = ast.parse(SEND)
		for node in ast.walk(tree):
			if isinstance(node, ast.FunctionDef) and node.name in ("send_automatic_text", "send_automatic_interactive"):
				self.assertFalse(any("whitelist" in ast.dump(d) for d in node.decorator_list), node.name)

	def test_auto_reply_is_an_automatic_origin(self):
		self.assertIn("purposes.AUTO_REPLY", SEND.split("AUTOMATIC_ORIGINS =")[1].split("\n")[0])

	def test_the_interactive_sender_keeps_every_text_check(self):
		body = function(SEND, "send_automatic_interactive")
		for needle in ("refuse_if_receive_only()", "check_free_text(", "check_recipient(", "check_buttons(", "check_list(", "sent_by=None"):
			self.assertIn(needle, body, needle)

	def test_a_text_the_system_sends_records_no_person(self):
		self.assertIn("sent_by=False if person else None", function(SEND, "_send_text"))

	def test_a_person_typing_stops_the_bot_but_never_blocks_the_send(self):
		self.assertIn("origin == purposes.PERSON and sent_by is False", function(SEND, "_deliver"))
		body = function(SEND, "_person_takes_over")
		self.assertIn("bot.on_agent_reply(conversation)", body)
		self.assertIn("except Exception", body)

	def test_a_transfer_ends_the_bot(self):
		self.assertIn("bot.on_person_assigned(conv)", function(INBOX, "transfer"))


class TestRoutingLeavesABotsChatAlone(unittest.TestCase):
	def test_assign_skips_a_chat_with_a_bot(self):
		self.assertIn("with_bot(conversation)", function(ASSIGNMENT, "assign"))

	def test_the_waiting_list_hand_out_skips_it(self):
		self.assertIn("with_bot(conversation)", function(ASSIGNMENT, "assign_waiting"))

	def test_the_unanswered_alert_skips_it(self):
		self.assertIn("with_bot(c.name)", function(ASSIGNMENT, "alert_unanswered"))

	def test_a_team_assignment_uses_the_least_busy_available_agent_of_the_team(self):
		body = function(ASSIGNMENT, "assign_to_team")
		self.assertIn("visibility.subtree(team, parents)", body)
		self.assertIn("routing.LEAST_BUSY", body)
		self.assertIn('ctx.number_type = "Shared"', body)


	def test_a_named_agent_gets_the_chat_without_an_availability_check(self):
		body = function(ASSIGNMENT, "assign_to_team")
		self.assertIn('routing.Decision(agent, "bot_choice"', body)
		self.assertIn("any(a.user == agent for a in ctx.agents)", body)  # enabled and works this number
		self.assertIn("add_event(", body)  # a refused choice is explained in the chat
		self.assertIn("bot_choice", ASSIGNMENT.split("REASONS = {")[1].split("}")[0])
		self.assertIn("result.agent", function(BOT, "_step"))


class TestTheMatchedStartIsKept(unittest.TestCase):
	def test_the_hook_stores_the_start_the_customer_hit(self):
		body = function(BOT, "on_inbound")
		self.assertIn("rules.match_start(", body)
		self.assertIn('"_start": start_of[chosen]', body)

	def test_one_bot_per_kind_of_start_compares_every_start(self):
		src = read("waba", "doctype", "waba_bot", "waba_bot.py")
		self.assertIn("trigger_modes(", src)


class TestNoCodeIsEvaluated(unittest.TestCase):
	def test_no_eval_exec_or_dynamic_calls(self):
		for name, source in (("bot.py", BOT), ("rules/bot.py", RULES), ("api/bots.py", API)):
			code = re.sub(r'""".*?"""', "", source, flags=re.S)
			for word in ("eval(", "exec(", "safe_eval", "get_attr(", "__import__"):
				self.assertNotIn(word, code, f"{name}: {word}")
			self.assertIsNone(re.search(r"(?<!re\.)\bcompile\(", code), name)  # re.compile is fine; compiling code is not


class TestWhoMayBuild(unittest.TestCase):
	def test_only_a_waba_admin_builds_bots(self):
		perms = {p["role"]: p for p in BOT_DOCTYPE["permissions"]}
		self.assertEqual(set(perms), {"Waba Admin"})
		self.assertTrue(perms["Waba Admin"].get("write"))

	def test_sessions_and_logs_are_read_only_even_for_the_admin(self):
		for definition in (SESSION_DOCTYPE, LOG_DOCTYPE):
			for p in definition["permissions"]:
				self.assertEqual(p["role"], "Waba Admin")
				self.assertFalse(p.get("write") or p.get("create"))

	def test_every_call_is_admin_only(self):
		for decorator, name in re.findall(r"@frappe\.whitelist\(([^)]*)\)\s*\ndef (\w+)\(", API):
			body = function(API, name)
			self.assertTrue("_bot(" in body or "_admin_only()" in body, name)
		self.assertIn("is_admin", function(API, "_admin_only"))

	def test_the_writes_are_post_only(self):
		decorators = dict((name, d) for d, name in re.findall(r"@frappe\.whitelist\(([^)]*)\)\s*\ndef (\w+)\(", API))
		for name in ("publish", "use_starter", "simulate"):
			self.assertIn("POST", decorators[name])

	def test_simulate_cannot_send(self):
		body = function(API, "simulate")
		for word in ("send.", "graph.", "frappe.enqueue", "insert("):
			self.assertNotIn(word, body)


class TestDoctypes(unittest.TestCase):
	def test_one_active_session_per_conversation_is_a_database_rule(self):
		f = fields(SESSION_DOCTYPE)["active_key"]
		self.assertTrue(f.get("unique"))
		self.assertIn("active_key", BOT.split("def on_inbound")[1].split("def _enqueue")[0])

	def test_the_master_switch_is_off_by_default(self):
		f = fields(SETTINGS)["bots_enabled"]
		self.assertEqual(f["fieldtype"], "Check")
		self.assertEqual(str(f.get("default")), "0")

	def test_messages_know_which_bot_sent_them(self):
		f = fields(MESSAGE)["bot"]
		self.assertEqual((f["fieldtype"], f["options"]), ("Link", "Waba Bot"))

	def test_a_bot_is_named_by_its_name_and_cannot_be_switched_on_unpublished(self):
		self.assertEqual(BOT_DOCTYPE["autoname"], "field:bot_name")
		self.assertIn("Publish the bot before switching it on", read("waba", "doctype", "waba_bot", "waba_bot.py"))

	def test_the_trigger_choices_match_the_rules(self):
		from waba.rules import bot

		options = [o for o in fields(BOT_DOCTYPE)["trigger"]["options"].split("\n") if o]
		self.assertEqual(options, list(bot.TRIGGERS))

	def test_the_session_statuses_match_the_rules(self):
		from waba.rules import bot

		self.assertEqual(fields(SESSION_DOCTYPE)["status"]["options"].split("\n"), list(bot.STATUSES))

	def test_the_defaults_match_the_rules(self):
		from waba.rules import bot

		f = fields(BOT_DOCTYPE)
		self.assertEqual(int(f["stuck_limit"]["default"]), bot.DEFAULT_STUCK_LIMIT)
		self.assertEqual(int(f["session_timeout_minutes"]["default"]), bot.DEFAULT_TIMEOUT_MINUTES)
		self.assertEqual(int(f["cooldown_hours"]["default"]), bot.DEFAULT_COOLDOWN_HOURS)
		self.assertEqual(f["handover_words"]["default"], bot.DEFAULT_HUMAN_WORDS)


if __name__ == "__main__":
	unittest.main()
