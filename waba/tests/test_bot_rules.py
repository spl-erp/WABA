"""Run without a site:  python -m unittest waba.tests.test_bot_rules

The bot's decisions: what is a valid graph, who starts a bot, how a reply moves it, when it hands over."""

import copy
import datetime
import unittest

from waba.rules import bot, outbound

FACTS = {"customer_name": "Asha", "customer_phone": "+919811111111", "number_name": "Splashjet", "open_now": True, "matched": True}


def reply(text="", interactive_id=None):
	return {"text": text, "interactive_id": interactive_id}


def start(graph=None, facts=None, **kw):
	return bot.run(graph or bot.starter_graph("Sales", "Accounts"), {}, facts or FACTS, None, **kw)


def after(res, graph, text="", interactive_id=None, facts=None, **kw):
	return bot.run(graph, res.state, facts or FACTS, reply(text, interactive_id), **kw)


class TestStarter(unittest.TestCase):
	def test_the_starter_is_a_valid_bot(self):
		self.assertEqual(bot.validate_graph(bot.starter_graph("Sales", "Accounts")), [])
		self.assertEqual(bot.validate_graph(bot.starter_graph()), [])

	def test_the_starter_greets_by_name_and_shows_the_menu(self):
		res = start()
		self.assertEqual(res.actions[0], {"do": "text", "body": "Hello Asha! Thank you for contacting Splashjet."})
		self.assertEqual(res.actions[1]["do"], "buttons")
		self.assertEqual([b["title"] for b in res.actions[1]["buttons"]], ["Sales", "Accounts", "Talk to a person"])
		self.assertIsNone(res.ended)
		self.assertEqual(res.state["node"], "menu")

	def test_a_named_agent_is_carried_to_the_end(self):
		g = bot.starter_graph("Sales", "Accounts")
		next(n for n in g["nodes"] if n["id"] == "to_sales")["data"]["agent"] = "asha@example.com"
		res = after(start(), g, "Sales", "sales")
		self.assertEqual((res.team, res.agent), ("Sales", "asha@example.com"))
		res = after(start(), bot.starter_graph("Sales", "Accounts"), "Sales", "sales")
		self.assertIsNone(res.agent)  # none named: the team's least busy available agent

	def test_a_button_goes_to_its_team(self):
		g = bot.starter_graph("Sales", "Accounts")
		res = after(start(), g, "Sales", "sales")
		self.assertEqual((res.ended, res.kind, res.team), (bot.HANDED_OVER, "assign_team", "Sales"))
		self.assertIn("Sales team", res.actions[0]["body"])
		self.assertIsNone(res.state["node"])

	def test_without_teams_a_button_hands_over_to_normal_routing(self):
		g = bot.starter_graph()
		res = after(start(graph=g), g, "Sales", "sales")
		self.assertEqual((res.ended, res.kind), (bot.HANDED_OVER, "handover"))


class TestReplyMatching(unittest.TestCase):
	OPTIONS = [{"id": "a", "title": "Sales"}, {"id": "b", "title": "Accounts"}]

	def test_by_id_title_or_number(self):
		self.assertEqual(bot.match_reply(self.OPTIONS, "b")["title"], "Accounts")
		self.assertEqual(bot.match_reply(self.OPTIONS, None, "  sales ")["id"], "a")
		self.assertEqual(bot.match_reply(self.OPTIONS, None, "2")["id"], "b")

	def test_the_id_wins_over_the_text(self):
		self.assertEqual(bot.match_reply(self.OPTIONS, "a", "Accounts")["id"], "a")

	def test_nothing_matches(self):
		self.assertIsNone(bot.match_reply(self.OPTIONS, None, "hello"))
		self.assertIsNone(bot.match_reply(self.OPTIONS, None, "3"))
		self.assertIsNone(bot.match_reply(self.OPTIONS, None, "0"))
		self.assertIsNone(bot.match_reply(self.OPTIONS, "zz", ""))

	def test_a_typed_button_title_works(self):
		g = bot.starter_graph("S", "A")
		self.assertEqual(after(start(graph=g), g, "accounts").team, "A")


class TestHandover(unittest.TestCase):
	def test_asking_for_a_person_hands_over(self):
		g = bot.starter_graph("S", "A")
		for text in ("agent", "I want to talk to someone", "Human please", "PERSON"):
			res = after(start(graph=g), g, text)
			self.assertEqual((res.ended, res.kind), (bot.HANDED_OVER, "asked"), text)

	def test_a_long_sentence_with_the_word_is_not_a_request(self):
		self.assertFalse(bot.matches_human("I am the person who called you yesterday about the invoice for the ink order", bot.DEFAULT_HUMAN_WORDS))

	def test_the_word_must_be_whole(self):
		self.assertFalse(bot.matches_human("agenda", bot.DEFAULT_HUMAN_WORDS))
		self.assertTrue(bot.matches_human("agent!", bot.DEFAULT_HUMAN_WORDS))

	def test_an_unrecognised_reply_repeats_the_menu_then_hands_over(self):
		g = bot.starter_graph("S", "A")
		first = after(start(graph=g), g, "blah")
		self.assertIsNone(first.ended)
		self.assertEqual(first.state["retries"], 1)
		self.assertEqual(first.actions[0]["do"], "buttons")
		self.assertIn("choose one of the options", first.actions[0]["body"])
		second = after(first, g, "still blah")
		self.assertEqual((second.ended, second.kind), (bot.HANDED_OVER, "stuck"))

	def test_a_valid_reply_resets_the_retries(self):
		g = bot.starter_graph("S", "A")
		first = after(start(graph=g), g, "blah")
		self.assertEqual(first.state["retries"], 1)
		self.assertEqual(after(first, g, "1").team, "S")

	def test_the_stuck_limit_is_the_owners_to_set(self):
		g = bot.starter_graph("S", "A")
		res = after(start(graph=g), g, "blah", stuck_limit=1)
		self.assertEqual(res.kind, "stuck")
		res = start(graph=g)
		for _ in range(3):
			res = after(res, g, "blah", stuck_limit=4)
			self.assertIsNone(res.ended)
		self.assertEqual(after(res, g, "blah", stuck_limit=4).kind, "stuck")


def ask_graph(validate="text", var="city"):
	return {
		"nodes": [
			{"id": "t", "type": "trigger", "data": {"mode": "any_unassigned"}},
			{"id": "q", "type": "ask", "data": {"text": "Which city, {{customer_name}}?", "var": var, "validate": validate}},
			{"id": "c", "type": "condition", "data": {"kind": "var_equals", "var": var, "value": "Delhi"}},
			{"id": "d", "type": "message", "data": {"text": "Delhi has a showroom."}},
			{"id": "n", "type": "note", "data": {"text": "City is {{" + var + "}}"}},
			{"id": "e", "type": "end", "data": {}},
			{"id": "h", "type": "handover", "data": {}},
		],
		"edges": [
			{"id": "1", "source": "t", "sourceHandle": "out", "target": "q"},
			{"id": "2", "source": "q", "sourceHandle": "out", "target": "n"},
			{"id": "3", "source": "n", "sourceHandle": "out", "target": "c"},
			{"id": "4", "source": "c", "sourceHandle": "yes", "target": "d"},
			{"id": "5", "source": "c", "sourceHandle": "no", "target": "h"},
			{"id": "6", "source": "d", "sourceHandle": "out", "target": "e"},
		],
	}


class TestAsk(unittest.TestCase):
	def test_the_question_uses_the_name_and_waits(self):
		res = start(ask_graph())
		self.assertEqual(res.actions, [{"do": "text", "body": "Which city, Asha?"}])
		self.assertEqual(res.state["node"], "q")

	def test_the_answer_is_kept_and_the_note_uses_it(self):
		g = ask_graph()
		res = after(start(g), g, "Delhi")
		self.assertEqual(res.state["vars"], {"city": "Delhi"})  # state is reset when it ended, but the vars stay
		self.assertEqual(res.actions[0], {"do": "note", "text": "City is Delhi"})
		self.assertEqual(res.actions[1], {"do": "text", "body": "Delhi has a showroom."})
		self.assertEqual((res.ended, res.kind), (bot.FINISHED, "finished"))

	def test_the_condition_takes_the_no_line(self):
		g = ask_graph()
		res = after(start(g), g, "Pune")
		self.assertEqual((res.ended, res.kind), (bot.HANDED_OVER, "handover"))

	def test_the_comparison_ignores_case_and_spaces(self):
		g = ask_graph()
		self.assertEqual(after(start(g), g, "  dELHI ").kind, "finished")

	def test_a_bad_number_is_asked_again(self):
		g = ask_graph("number", "qty")
		res = after(start(g), g, "many")
		self.assertIsNone(res.ended)
		self.assertTrue(res.actions[0]["body"].startswith("Sorry, that does not look right."))

	def test_validation_kinds(self):
		self.assertEqual(bot.validate_value("number", "12,5"), (True, "12,5"))
		self.assertFalse(bot.validate_value("number", "12 pcs")[0])
		self.assertTrue(bot.validate_value("phone", "+91 98111 11111")[0])
		self.assertFalse(bot.validate_value("phone", "12345")[0])
		self.assertFalse(bot.validate_value("phone", "call me")[0])
		self.assertTrue(bot.validate_value("email", "a@b.co")[0])
		self.assertFalse(bot.validate_value("email", "a@b")[0])
		self.assertFalse(bot.validate_value("text", "   ")[0])
		self.assertFalse(bot.validate_value("text", "x" * 501)[0])

	def test_asking_for_a_person_while_asked_a_question(self):
		g = ask_graph()
		self.assertEqual(after(start(g), g, "agent").kind, "asked")

	def test_last_choice_is_remembered(self):
		g = bot.starter_graph("S", "A")
		self.assertEqual(after(start(graph=g), g, "Sales", "sales").state["vars"]["last_choice"], "Sales")


class TestConditions(unittest.TestCase):
	def graph(self, kind):
		return {
			"nodes": [
				{"id": "t", "type": "trigger", "data": {"mode": "new_conversation"}},
				{"id": "c", "type": "condition", "data": {"kind": kind}},
				{"id": "y", "type": "message", "data": {"text": "yes"}},
				{"id": "n", "type": "message", "data": {"text": "no"}},
				{"id": "e", "type": "end", "data": {}},
			],
			"edges": [
				{"id": "1", "source": "t", "sourceHandle": "out", "target": "c"},
				{"id": "2", "source": "c", "sourceHandle": "yes", "target": "y"},
				{"id": "3", "source": "c", "sourceHandle": "no", "target": "n"},
				{"id": "4", "source": "y", "sourceHandle": "out", "target": "e"},
				{"id": "5", "source": "n", "sourceHandle": "out", "target": "e"},
			],
		}

	def test_working_hours(self):
		g = self.graph("working_hours")
		self.assertEqual(start(g, {**FACTS, "open_now": True}).actions[0]["body"], "yes")
		self.assertEqual(start(g, {**FACTS, "open_now": False}).actions[0]["body"], "no")

	def test_known_record(self):
		g = self.graph("matched")
		self.assertEqual(start(g, {**FACTS, "matched": False}).actions[0]["body"], "no")


class TestValidation(unittest.TestCase):
	def problems(self, mutate):
		g = copy.deepcopy(bot.starter_graph("S", "A"))
		mutate(g)
		return bot.validate_graph(g)

	def node(self, g, node_id):
		return next(n for n in g["nodes"] if n["id"] == node_id)

	def test_empty_and_malformed(self):
		self.assertTrue(bot.validate_graph({}))
		self.assertTrue(bot.validate_graph({"nodes": []}))
		self.assertTrue(bot.validate_graph(None))

	def test_exactly_one_trigger(self):
		self.assertTrue(self.problems(lambda g: g["nodes"].append({"id": "t2", "type": "trigger", "data": {"mode": "any_unassigned"}})))
		self.assertTrue(self.problems(lambda g: g.update(nodes=[n for n in g["nodes"] if n["id"] != "trigger"])))

	def test_meta_limits_on_buttons(self):
		def four(g):
			self.node(g, "menu")["data"]["buttons"].append({"id": "x", "title": "More"})

		self.assertTrue(any("1 to 3 buttons" in p for p in self.problems(four)))

		def long_title(g):
			self.node(g, "menu")["data"]["buttons"][0]["title"] = "A title much longer than twenty"

		self.assertTrue(any("longer than 20" in p for p in self.problems(long_title)))

		def same_id(g):
			self.node(g, "menu")["data"]["buttons"][1]["id"] = "sales"

		self.assertTrue(any("share the id" in p for p in self.problems(same_id)))

	def test_a_button_without_a_line_is_reported(self):
		def cut(g):
			g["edges"] = [e for e in g["edges"] if e["sourceHandle"] != "accounts"]

		self.assertTrue(any("Accounts" in p and "not joined" in p for p in self.problems(cut)))

	def test_a_block_that_cannot_be_reached(self):
		def orphan(g):
			g["nodes"].append({"id": "lost", "type": "end", "data": {}})

		self.assertTrue(any("not reachable" in p for p in self.problems(orphan)))

	def test_nothing_may_follow_an_ending_block(self):
		def follow(g):
			g["edges"].append({"id": "x", "source": "to_sales", "sourceHandle": "out", "target": "welcome"})

		self.assertTrue(any("ends the bot" in p for p in self.problems(follow)))

	def test_a_line_into_the_trigger_is_refused(self):
		def into(g):
			g["edges"].append({"id": "x", "source": "welcome", "sourceHandle": "out", "target": "trigger"})

		self.assertTrue(self.problems(into))

	def test_an_unknown_value_in_the_text(self):
		def unknown(g):
			self.node(g, "welcome")["data"]["text"] = "Hi {{secret}}"

		self.assertTrue(any("not a known value" in p for p in self.problems(unknown)))

	def test_a_loop_that_never_waits_is_refused(self):
		g = {
			"nodes": [
				{"id": "t", "type": "trigger", "data": {"mode": "any_unassigned"}},
				{"id": "a", "type": "message", "data": {"text": "a"}},
				{"id": "b", "type": "message", "data": {"text": "b"}},
			],
			"edges": [
				{"id": "1", "source": "t", "sourceHandle": "out", "target": "a"},
				{"id": "2", "source": "a", "sourceHandle": "out", "target": "b"},
				{"id": "3", "source": "b", "sourceHandle": "out", "target": "a"},
			],
		}
		self.assertTrue(any("loop" in p for p in bot.validate_graph(g)))

	def test_a_loop_through_a_question_is_fine(self):
		g = ask_graph()
		g["edges"][-1] = {"id": "6", "source": "d", "sourceHandle": "out", "target": "q"}
		self.assertEqual([p for p in bot.validate_graph(g) if "loop" in p], [])

	def test_ask_needs_a_good_variable_name(self):
		self.assertTrue(any("name of lower-case" in p for p in bot.validate_graph(ask_graph(var="City Name"))))
		self.assertTrue(any("already used" in p for p in bot.validate_graph(ask_graph(var="customer_name"))))

	def test_condition_needs_a_question_answer(self):
		g = ask_graph()
		g["nodes"][2]["data"]["var"] = "customer_name"
		self.assertTrue(any("Question block" in p for p in bot.validate_graph(g)))

	def test_the_keyword_trigger_needs_words(self):
		def kw(g):
			self.node(g, "trigger")["data"] = {"mode": "keyword", "keywords": " ", "match": "exact"}

		self.assertTrue(any("keyword" in p.lower() for p in self.problems(kw)))

	def test_the_team_must_be_chosen(self):
		def no_team(g):
			self.node(g, "to_sales")["data"]["team"] = ""

		self.assertTrue(any("Choose the team" in p for p in self.problems(no_team)))

	def test_a_list_follows_metas_limits(self):
		g = {
			"nodes": [
				{"id": "t", "type": "trigger", "data": {"mode": "new_conversation"}},
				{"id": "l", "type": "list", "data": {"text": "Pick", "button_text": "Choose", "rows": [{"id": str(i), "title": f"Row {i}"} for i in range(11)]}},
			],
			"edges": [{"id": "1", "source": "t", "sourceHandle": "out", "target": "l"}],
		}
		self.assertTrue(any("1 to 10 choices" in p for p in bot.validate_graph(g)))


class TestLists(unittest.TestCase):
	def test_a_list_walks_like_buttons(self):
		rows = [{"id": "r1", "title": "Price list"}, {"id": "r2", "title": "Brochure"}]
		g = {
			"nodes": [
				{"id": "t", "type": "trigger", "data": {"mode": "new_conversation"}},
				{"id": "l", "type": "list", "data": {"text": "What do you need?", "button_text": "Choose", "rows": rows}},
				{"id": "a", "type": "message", "data": {"text": "Price list coming"}},
				{"id": "b", "type": "message", "data": {"text": "Brochure coming"}},
				{"id": "e", "type": "end", "data": {}},
			],
			"edges": [
				{"id": "1", "source": "t", "sourceHandle": "out", "target": "l"},
				{"id": "2", "source": "l", "sourceHandle": "r1", "target": "a"},
				{"id": "3", "source": "l", "sourceHandle": "r2", "target": "b"},
				{"id": "4", "source": "a", "sourceHandle": "out", "target": "e"},
				{"id": "5", "source": "b", "sourceHandle": "out", "target": "e"},
			],
		}
		self.assertEqual(bot.validate_graph(g), [])
		res = start(g)
		self.assertEqual(res.actions[0]["do"], "list")
		self.assertEqual(res.actions[0]["button"], "Choose")
		self.assertEqual(after(res, g, "Brochure", "r2").actions[0]["body"], "Brochure coming")


class TestSafety(unittest.TestCase):
	def test_a_bot_that_changed_while_the_customer_was_in_it_hands_over(self):
		g = bot.starter_graph("S", "A")
		res = bot.run(g, {"node": "gone", "vars": {}}, FACTS, reply("hi"))
		self.assertEqual((res.ended, res.kind), (bot.HANDED_OVER, "missing"))

	def test_a_long_chain_is_stopped_by_the_step_limit(self):
		nodes = [{"id": "t", "type": "trigger", "data": {"mode": "any_unassigned"}}]
		edges = [{"id": "e0", "source": "t", "sourceHandle": "out", "target": "m0"}]
		for i in range(30):
			nodes.append({"id": f"m{i}", "type": "message", "data": {"text": "x"}})
			if i:
				edges.append({"id": f"e{i}", "source": f"m{i - 1}", "sourceHandle": "out", "target": f"m{i}"})
		res = bot.run({"nodes": nodes, "edges": edges}, {}, FACTS)
		self.assertEqual(res.kind, "loop")
		self.assertLessEqual(len(res.actions), bot.MAX_STEPS)

	def test_a_line_that_leads_nowhere_simply_ends(self):
		g = {"nodes": [{"id": "t", "type": "trigger", "data": {"mode": "any_unassigned"}}], "edges": []}
		self.assertEqual(bot.run(g, {}, FACTS).kind, "finished")

	def test_rendering_never_runs_code(self):
		# only a plain name is replaced; anything else is left as written and never evaluated
		self.assertEqual(bot.render("{{customer_name}} {{__import__('os')}} {{nope}}!", {"customer_name": "A"}), "A {{__import__('os')}} !")

	def test_unknown_values_become_empty(self):
		self.assertEqual(bot.render("Hi {{nope}}", {}), "Hi")


class TestStarting(unittest.TestCase):
	def test_triggers(self):
		self.assertTrue(bot.should_start({"mode": "new_conversation"}, first_message=True, text="hi"))
		self.assertFalse(bot.should_start({"mode": "new_conversation"}, first_message=False, text="hi"))
		self.assertTrue(bot.should_start({"mode": "any_unassigned"}, first_message=False, text="hi"))
		self.assertFalse(bot.should_start({"mode": "nonsense"}, first_message=True, text="hi"))

	def test_keywords(self):
		t = {"mode": "keyword", "keywords": "price, rate card", "match": "exact"}
		self.assertTrue(bot.should_start(t, first_message=False, text=" Price "))
		self.assertFalse(bot.should_start(t, first_message=False, text="what is the price"))
		t["match"] = "contains"
		self.assertTrue(bot.should_start(t, first_message=False, text="What is the PRICE?"))
		self.assertFalse(bot.should_start(t, first_message=False, text="priceless"))
		self.assertFalse(bot.should_start(t, first_message=False, text=""))

	def test_a_keyword_bot_beats_a_new_chat_bot(self):
		self.assertEqual(bot.pick_bot([("a", "any_unassigned"), ("b", "new_conversation"), ("c", "keyword")]), "c")
		self.assertEqual(bot.pick_bot([("a", "any_unassigned"), ("b", "new_conversation")]), "b")
		self.assertIsNone(bot.pick_bot([]))


class TestGuards(unittest.TestCase):
	OK = dict(switch_on=True, published=True, opted_out=False, assigned=False, receive_only=False, number_ok=True, test_ok=True, cooling_down=False)

	def reason(self, **over):
		r = bot.hold_reason(**{**self.OK, **over})
		return r[0] if r else None

	def test_clear_to_go(self):
		self.assertIsNone(self.reason())

	def test_each_guard(self):
		for key, value, code in (
			("switch_on", False, "switch_off"),
			("published", False, "not_published"),
			("receive_only", True, "receive_only"),
			("number_ok", False, "number"),
			("opted_out", True, "opted_out"),
			("assigned", True, "assigned"),
			("test_ok", False, "test_mode"),
			("cooling_down", True, "cooldown"),
		):
			self.assertEqual(self.reason(**{key: value}), code, key)

	def test_the_master_switch_wins(self):
		self.assertEqual(self.reason(switch_on=False, assigned=True, opted_out=True), "switch_off")

	def test_cooldown(self):
		now = datetime.datetime(2026, 11, 6, 12, 0)
		self.assertTrue(bot.is_cooling_down(now - datetime.timedelta(hours=11), now, 12))
		self.assertFalse(bot.is_cooling_down(now - datetime.timedelta(hours=13), now, 12))
		self.assertFalse(bot.is_cooling_down(None, now, 12))
		self.assertFalse(bot.is_cooling_down(now, now, 0))

	def test_session_expiry(self):
		now = datetime.datetime(2026, 11, 6, 12, 0)
		self.assertTrue(bot.session_expired(now - datetime.timedelta(minutes=1440), now, 1440))
		self.assertFalse(bot.session_expired(now - datetime.timedelta(minutes=10), now, 1440))
		self.assertFalse(bot.session_expired(now - datetime.timedelta(days=9), now, 0))

	def test_the_message_cap(self):
		self.assertFalse(bot.over_cap(28, 2))
		self.assertTrue(bot.over_cap(29, 2))


class TestInteractivePayloads(unittest.TestCase):
	def test_buttons_payload(self):
		p = outbound.buttons_payload("+91 98111 11111", " Pick one ", [{"id": "a", "title": " Sales "}, {"id": "b", "title": "Accounts"}])
		self.assertEqual(p["to"], "919811111111")
		self.assertEqual(p["type"], "interactive")
		self.assertEqual(p["interactive"]["type"], "button")
		self.assertEqual(p["interactive"]["body"], {"text": "Pick one"})
		self.assertEqual(p["interactive"]["action"]["buttons"][0], {"type": "reply", "reply": {"id": "a", "title": "Sales"}})

	def test_list_payload(self):
		p = outbound.list_payload("919811111111", "Choose", "Open", [{"id": "1", "title": "Price list", "description": " all "}, {"id": "2", "title": "Brochure"}])
		action = p["interactive"]["action"]
		self.assertEqual(action["button"], "Open")
		self.assertEqual(action["sections"][0]["rows"][0], {"id": "1", "title": "Price list", "description": "all"})
		self.assertNotIn("description", action["sections"][0]["rows"][1])

	def test_the_limits(self):
		ok = [{"id": "a", "title": "One"}]
		self.assertEqual(outbound.check_buttons("Hi", ok), [])
		self.assertTrue(outbound.check_buttons("", ok))
		self.assertTrue(outbound.check_buttons("x" * 1025, ok))
		self.assertTrue(outbound.check_buttons("Hi", []))
		self.assertTrue(outbound.check_buttons("Hi", ok * 4))
		self.assertTrue(outbound.check_buttons("Hi", [{"id": "a", "title": "x" * 21}]))
		self.assertTrue(outbound.check_buttons("Hi", [{"id": "", "title": "One"}]))
		self.assertTrue(outbound.check_list("Hi", "", [{"id": "1", "title": "A"}]))
		self.assertTrue(outbound.check_list("Hi", "x" * 21, [{"id": "1", "title": "A"}]))
		self.assertTrue(outbound.check_list("Hi", "Open", [{"id": "1", "title": "x" * 25}]))
		self.assertTrue(outbound.check_list("Hi", "Open", [{"id": "1", "title": "A", "description": "x" * 73}]))
		self.assertEqual(outbound.check_list("Hi", "Open", [{"id": "1", "title": "A", "description": "x" * 72}]), [])


if __name__ == "__main__":
	unittest.main()


class TestSeveralStarts(unittest.TestCase):
	def _graph(self, starts):
		return {
			"nodes": [
				{"id": "trigger_1", "type": "trigger", "position": {"x": 0, "y": 0}, "data": {"starts": starts}},
				{"id": "a", "type": "message", "position": {"x": 0, "y": 0}, "data": {"text": "Price list: ..."}},
				{"id": "b", "type": "message", "position": {"x": 0, "y": 0}, "data": {"text": "Our services: ..."}},
				{"id": "end", "type": "end", "position": {"x": 0, "y": 0}, "data": {"text": "Bye"}},
			],
			"edges": [
				{"id": "e1", "source": "trigger_1", "sourceHandle": "s1", "target": "a"},
				{"id": "e2", "source": "trigger_1", "sourceHandle": "s2", "target": "b"},
				{"id": "e3", "source": "a", "sourceHandle": "out", "target": "end"},
				{"id": "e4", "source": "b", "sourceHandle": "out", "target": "end"},
			],
		}

	STARTS = [
		{"id": "s1", "label": "Price", "mode": "keyword", "keywords": "price, rate", "match": "exact"},
		{"id": "s2", "label": "Services", "mode": "keyword", "keywords": "service", "match": "contains"},
	]

	def test_an_older_trigger_is_one_start_called_out(self):
		starts = bot.starts_of({"mode": "keyword", "keywords": "hi", "match": "exact"})
		self.assertEqual([(s["id"], s["mode"]) for s in starts], [("out", "keyword")])

	def test_the_message_picks_its_own_start(self):
		g = self._graph(self.STARTS)
		trigger = bot.trigger_of(g)
		self.assertEqual(bot.match_start(trigger, first_message=False, text="Price")["id"], "s1")
		self.assertEqual(bot.match_start(trigger, first_message=False, text="need a service quote")["id"], "s2")
		self.assertIsNone(bot.match_start(trigger, first_message=False, text="hello"))
		self.assertTrue(bot.should_start(trigger, first_message=False, text="rate"))

	def test_a_keyword_start_beats_a_new_conversation_start(self):
		g = self._graph(self.STARTS + [{"id": "s3", "label": "", "mode": "new_conversation"}])
		trigger = bot.trigger_of(g)
		self.assertEqual(bot.match_start(trigger, first_message=True, text="price")["id"], "s1")
		self.assertEqual(bot.match_start(trigger, first_message=True, text="hello")["id"], "s3")

	def test_each_start_walks_its_own_branch(self):
		g = self._graph(self.STARTS)
		facts = {"customer_name": "Asha"}
		first = bot.run(g, {"node": None, "vars": {"_start": "s1"}, "retries": 0}, facts, None)
		self.assertEqual(first.actions[0]["body"], "Price list: ...")
		self.assertEqual(first.log[0]["result"], "started: Price")
		second = bot.run(g, {"node": None, "vars": {"_start": "s2"}, "retries": 0}, facts, None)
		self.assertEqual(second.actions[0]["body"], "Our services: ...")

	def test_the_handles_are_the_start_ids(self):
		g = self._graph(self.STARTS)
		self.assertEqual(bot.handles(g["nodes"][0]), ["s1", "s2"])
		self.assertEqual(bot.validate_graph(g), [])

	def test_mistakes_are_named(self):
		dup = self._graph([dict(self.STARTS[0]), {"id": "s2", "label": "", "mode": "keyword", "keywords": "Rate", "match": "exact"}])
		self.assertTrue(any('"rate"' in p and "Start 1 and Start 2" in p for p in bot.validate_graph(dup)))
		two_new = self._graph([{"id": "s1", "mode": "new_conversation"}, {"id": "s2", "mode": "new_conversation"}])
		self.assertTrue(any("Only one start can begin with a new conversation" in p for p in bot.validate_graph(two_new)))
		empty = self._graph([{"id": "s1", "mode": "keyword", "keywords": "", "match": "exact"}, {"id": "s2", "mode": ""}])
		texts = " | ".join(bot.validate_graph(empty))
		self.assertIn("Start 1: Write at least one keyword", texts)
		self.assertIn("Start 2: Choose what starts the bot", texts)
		unjoined = self._graph(self.STARTS)
		unjoined["edges"] = [e for e in unjoined["edges"] if e["id"] != "e2"]
		self.assertTrue(any("Services" in p and "not joined" in p for p in bot.validate_graph(unjoined)))

