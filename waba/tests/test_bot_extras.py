"""Run without a site:  python -m unittest waba.tests.test_bot_extras

The preview blocks (Status lookup, Send document, Link button), the 'no answer' path, the starter bots, the document values and
the switch that hides all of it. The database side is checked on a site by verify_bot_extras."""

import copy
import unittest

from waba.rules import bot, bot_docs, bot_starters, outbound

FACTS = {"customer_name": "Asha", "customer_phone": "+919811111111", "number_name": "Splashjet", "open_now": True, "matched": True}
DOC = {"doc_name": "SO-0007", "doc_status": "To Deliver and Bill", "doc_date": "05-11-2026", "doc_total": "Rs 12,345.00", "doc_outstanding": "", "doc_due_date": ""}


def n(node_id, kind, **data):
	return {"id": node_id, "type": kind, "position": {"x": 0, "y": 0}, "data": data}


def e(i, source, target, handle="out"):
	return {"id": f"e{i}", "source": source, "sourceHandle": handle, "target": target}


def trigger():
	return n("t", "trigger", mode="any_unassigned")


def start(graph, facts=None, **kw):
	return bot.run(graph, {}, {**FACTS, **(facts or {})}, None, **kw)


class TestLinkButton(unittest.TestCase):
	def graph(self, **over):
		data = {"text": "More on our site.", "button_text": "Open", "url": "https://www.example.com/ink"}
		data.update(over)
		return {"nodes": [trigger(), n("l", "link_button", **data), n("end", "end")], "edges": [e(1, "t", "l"), e(2, "l", "end")]}

	def test_it_sends_a_link_and_goes_on(self):
		res = start(self.graph())
		self.assertEqual(res.actions, [{"do": "cta", "body": "More on our site.", "button": "Open", "url": "https://www.example.com/ink"}])
		self.assertEqual(res.kind, "finished")

	def test_only_https_complete_addresses(self):
		for bad in ("", "http://example.com", "example.com", "https://", "https://exa mple.com", "https://localhost", "javascript:alert(1)", "https://x.com/" + "a" * 2000):
			self.assertTrue(bot.validate_graph(self.graph(url=bad)), bad)
		for good in ("https://example.com", "https://www.example.co.in/a/b?x=1&y=2", "https://example.com:8443/path"):
			self.assertEqual(bot.validate_graph(self.graph(url=good)), [], good)

	def test_button_text_limit(self):
		self.assertTrue(bot.validate_graph(self.graph(button_text="x" * 21)))
		self.assertTrue(bot.validate_graph(self.graph(button_text="")))
		self.assertEqual(bot.validate_graph(self.graph(button_text="x" * 20)), [])

	def test_payload_is_a_cta_url_message(self):
		p = outbound.cta_payload("+91 98111 11111", " Hello ", " Open ", " https://example.com ")
		self.assertEqual(p["to"], "919811111111")
		self.assertEqual(p["interactive"]["type"], "cta_url")
		self.assertEqual(p["interactive"]["action"], {"name": "cta_url", "parameters": {"display_text": "Open", "url": "https://example.com"}})
		self.assertEqual(p["interactive"]["body"], {"text": "Hello"})

	def test_the_message_limits(self):
		self.assertEqual(outbound.check_cta("Hi", "Open", "https://example.com"), [])
		self.assertTrue(outbound.check_cta("", "Open", "https://example.com"))
		self.assertTrue(outbound.check_cta("x" * 1025, "Open", "https://example.com"))


class TestStatusLookup(unittest.TestCase):
	def graph(self):
		return {
			"nodes": [
				trigger(),
				n("s", "status_lookup", doctype="Sales Order", text="Order {{doc_name}} is {{doc_status}} ({{doc_total}})."),
				n("done", "end", text="Anything else?"),
				n("miss", "message", text="No order found."),
				n("h", "handover"),
			],
			"edges": [e(1, "t", "s"), e(2, "s", "done", "found"), e(3, "s", "miss", "none"), e(4, "miss", "h")],
		}

	def test_valid_with_both_lines(self):
		self.assertEqual(bot.validate_graph(self.graph()), [])

	def test_found_tells_the_customer_their_own_document(self):
		res = start(self.graph(), {"docs": {"Sales Order": DOC}})
		self.assertEqual(res.actions[0], {"do": "text", "body": "Order SO-0007 is To Deliver and Bill (Rs 12,345.00)."})
		self.assertEqual(res.actions[1]["body"], "Anything else?")
		self.assertEqual(res.log[1]["result"], "found SO-0007")

	def test_nothing_found_takes_the_other_line(self):
		for docs in ({"docs": {"Sales Order": None}}, {"docs": {}}, {}):
			res = start(self.graph(), docs)
			self.assertEqual(res.actions[0]["body"], "No order found.", docs)
			self.assertEqual(res.kind, "handover")

	def test_the_document_values_are_known_only_when_the_block_is_there(self):
		g = self.graph()
		g["nodes"][1]["data"]["text"] = "Order {{doc_name}}"
		self.assertEqual(bot.validate_graph(g), [])
		plain = {"nodes": [trigger(), n("m", "message", text="Order {{doc_name}}"), n("e", "end")], "edges": [e(1, "t", "m"), e(2, "m", "e")]}
		self.assertTrue(any("not a known value" in p for p in bot.validate_graph(plain)))

	def test_a_document_type_is_required_and_known(self):
		for bad in ("", "Purchase Order", None):
			g = self.graph()
			g["nodes"][1]["data"]["doctype"] = bad
			self.assertTrue(any("Choose which document" in p for p in bot.validate_graph(g)), bad)

	def test_the_two_lines_must_both_be_joined(self):
		g = self.graph()
		g["edges"] = [x for x in g["edges"] if x["sourceHandle"] != "none"]
		self.assertTrue(any("Not found" in p or "none" in p.lower() for p in bot.validate_graph(g)))

	def test_a_question_cannot_take_a_document_value_as_its_name(self):
		g = {"nodes": [trigger(), n("q", "ask", text="x", var="doc_name", validate="text"), n("e", "end")], "edges": [e(1, "t", "q"), e(2, "q", "e")]}
		self.assertTrue(any("already used" in p for p in bot.validate_graph(g)))


class TestDocValues(unittest.TestCase):
	def test_a_sales_order(self):
		v = bot_docs.variables("Sales Order", {"name": "SO-1", "status": "To Deliver", "date": "2026-11-05", "total": 1500, "currency": "INR"})
		self.assertEqual((v["doc_name"], v["doc_status"], v["doc_date"]), ("SO-1", "To Deliver", "05-11-2026"))
		self.assertEqual(v["doc_total"], "INR 1,500.00")
		self.assertEqual((v["doc_outstanding"], v["doc_due_date"]), ("", ""))  # only an invoice has these

	def test_an_invoice_shows_what_is_still_to_pay(self):
		v = bot_docs.variables("Sales Invoice", {"name": "INV-1", "status": "Unpaid", "date": "2026-11-01", "total": 1000, "outstanding": 400, "due_date": "2026-11-30", "currency": "INR"}, lambda a, c: f"{c}{a}")
		self.assertEqual((v["doc_outstanding"], v["doc_due_date"], v["doc_total"]), ("INR400", "30-11-2026", "INR1000"))

	def test_every_value_always_exists(self):
		self.assertEqual(set(bot_docs.variables("Quotation", {})), set(bot_docs.DOC_VARS))
		self.assertEqual(set(bot_docs.variables("Quotation", None)), set(bot_docs.DOC_VARS))


class TestSendDocument(unittest.TestCase):
	def graph(self, **data):
		base = {"source": "library", "shared_file": "Price list", "caption": "Our prices"}
		base.update(data)
		return {"nodes": [trigger(), n("f", "send_file", **base), n("ok", "end", text="Sent."), n("no", "handover")], "edges": [e(1, "t", "f"), e(2, "f", "ok"), e(3, "f", "no", "none")]}

	def test_a_library_file_is_sent_when_it_is_usable(self):
		res = start(self.graph(), {"files": {"Price list": True}})
		self.assertEqual(res.actions[0], {"do": "file", "file": "Price list", "caption": "Our prices"})
		self.assertEqual(res.actions[1]["body"], "Sent.")

	def test_an_unusable_library_file_takes_the_none_line(self):
		for files in ({"files": {"Price list": False}}, {"files": {}}, {}):
			res = start(self.graph(), files)
			self.assertEqual(res.kind, "handover", files)
			self.assertEqual([a["do"] for a in res.actions], [])

	def test_a_pdf_of_the_customers_own_latest_document(self):
		g = self.graph(source="erp_pdf", doctype="Quotation", shared_file="")
		res = start(g, {"docs": {"Quotation": {**DOC, "doc_name": "QTN-9"}}})
		self.assertEqual(res.actions[0], {"do": "pdf", "doctype": "Quotation", "name": "QTN-9", "caption": "Our prices"})
		self.assertEqual(start(g, {"docs": {"Quotation": None}}).kind, "handover")

	def test_the_pdf_name_comes_from_the_lookup_never_from_the_graph_or_the_customer(self):
		g = self.graph(source="erp_pdf", doctype="Sales Order", shared_file="", name="SO-OTHER-CUSTOMER")
		res = start(g, {"docs": {"Sales Order": {**DOC, "doc_name": "SO-MINE"}}}, )
		self.assertEqual(res.actions[0]["name"], "SO-MINE")

	def test_validation(self):
		self.assertEqual(bot.validate_graph(self.graph()), [])
		self.assertTrue(bot.validate_graph(self.graph(source="")))
		self.assertTrue(bot.validate_graph(self.graph(shared_file="")))
		self.assertTrue(bot.validate_graph(self.graph(source="erp_pdf", doctype="Purchase Order")))
		self.assertTrue(bot.validate_graph(self.graph(caption="x" * 1100)))
		self.assertEqual(bot.validate_graph(self.graph(caption="")), [])

	def test_the_caption_may_use_values(self):
		res = start(self.graph(caption="For {{customer_name}}"), {"files": {"Price list": True}})
		self.assertEqual(res.actions[0]["caption"], "For Asha")


class TestNoAnswerPath(unittest.TestCase):
	def graph(self, minutes=30):
		return {
			"nodes": [
				trigger(),
				n("b", "buttons", text="Pick one.", buttons=[{"id": "a", "title": "Yes"}], timeout_minutes=minutes),
				n("yes", "end", text="Great."),
				n("remind", "message", text="Are you still there?"),
				n("h", "handover"),
			],
			"edges": [e(1, "t", "b"), e(2, "b", "yes", "a"), e(3, "b", "remind", "timeout"), e(4, "remind", "h")],
		}

	def test_a_waiting_block_with_a_timeout_reports_it(self):
		res = start(self.graph(45))
		self.assertEqual(res.timeout_minutes, 45)
		self.assertIsNone(res.ended)
		self.assertEqual(start(self.graph(0)).timeout_minutes, 0)

	def test_the_no_answer_line_must_be_joined_when_a_time_is_set(self):
		g = self.graph()
		g["edges"] = [x for x in g["edges"] if x["sourceHandle"] != "timeout"]
		self.assertTrue(any("not joined" in p for p in bot.validate_graph(g)))
		self.assertTrue(bot.handles(g["nodes"][1])[-1] == "timeout")

	def test_no_time_means_no_line(self):
		g = self.graph(0)
		self.assertNotIn("timeout", bot.handles(g["nodes"][1]))

	def test_silence_runs_the_timeout_line(self):
		g = self.graph()
		first = start(g)
		res = bot.run(g, first.state, FACTS, None, event="timeout")
		self.assertEqual(res.actions[0]["body"], "Are you still there?")
		self.assertEqual(res.kind, "handover")
		self.assertEqual(res.log[0]["result"], "no answer in time")

	def test_silence_without_a_timeout_line_hands_over(self):
		g = self.graph()
		g["edges"] = [x for x in g["edges"] if x["sourceHandle"] != "timeout"]
		first = start(g)
		res = bot.run(g, first.state, FACTS, None, event="timeout")
		self.assertEqual((res.ended, res.kind), (bot.HANDED_OVER, "handover"))

	def test_a_timeout_path_can_wait_again(self):
		g = self.graph()
		g["nodes"][3] = n("remind", "buttons", text="Still there?", buttons=[{"id": "x", "title": "Yes"}], timeout_minutes=10)
		g["edges"] = [x for x in g["edges"] if x["id"] != "e4"] + [e(5, "remind", "h", "x"), e(6, "remind", "h", "timeout")]
		first = start(g)
		res = bot.run(g, first.state, FACTS, None, event="timeout")
		self.assertIsNone(res.ended)
		self.assertEqual((res.state["node"], res.timeout_minutes), ("remind", 10))

	def test_the_time_is_limited(self):
		for bad in (721, -5, "abc"):
			g = self.graph()
			g["nodes"][1]["data"]["timeout_minutes"] = bad
			self.assertTrue(bot.validate_graph(g) or bot.timeout_of(g["nodes"][1]) == 0, bad)
		g = self.graph(720)
		self.assertEqual(bot.validate_graph(g), [])

	def test_questions_can_time_out_too(self):
		g = {"nodes": [trigger(), n("q", "ask", text="Name?", var="name", validate="text", timeout_minutes=15), n("h", "handover"), n("h2", "handover")],
			"edges": [e(1, "t", "q"), e(2, "q", "h"), e(3, "q", "h2", "timeout")]}
		self.assertEqual(bot.validate_graph(g), [])
		self.assertEqual(bot.handles(g["nodes"][1]), ["out", "timeout"])
		self.assertEqual(start(g).timeout_minutes, 15)

	def test_the_per_session_cap_is_three(self):
		self.assertEqual(bot.MAX_TIMEOUTS, 3)


class TestTheSwitch(unittest.TestCase):
	def test_every_preview_block_is_refused_while_off_and_allowed_while_on(self):
		cases = {
			"status_lookup": TestStatusLookup().graph(),
			"send_file": TestSendDocument().graph(),
			"link_button": TestLinkButton().graph(),
		}
		for kind, graph in cases.items():
			self.assertEqual(bot.validate_graph(graph, extras=True), [], kind)
			off = bot.problems_for(graph, extras=False)
			self.assertTrue(any("preview" in p["text"] for p in off), kind)
			self.assertTrue(any(p["node"] for p in off), kind)  # the problem names its block

	def test_a_timeout_is_refused_while_off(self):
		g = TestNoAnswerPath().graph()
		self.assertEqual(bot.validate_graph(g, extras=True), [])
		self.assertTrue(any("timeout" in p and "preview" in p for p in bot.validate_graph(g, extras=False)))

	def test_a_bot_that_uses_none_of_it_is_unaffected(self):
		g = bot.starter_graph("Sales", "Accounts")
		self.assertEqual(bot.validate_graph(g, extras=False), [])
		self.assertFalse(bot.uses_extras(g))

	def test_uses_extras_sees_blocks_and_timeouts(self):
		self.assertTrue(bot.uses_extras(TestLinkButton().graph()))
		self.assertTrue(bot.uses_extras(TestNoAnswerPath().graph()))
		self.assertFalse(bot.uses_extras(TestNoAnswerPath().graph(0)))
		self.assertFalse(bot.uses_extras({}))
		self.assertFalse(bot.uses_extras(None))

	def test_the_gated_types_are_exactly_the_preview_blocks(self):
		self.assertEqual(set(bot.GATED_TYPES), {"status_lookup", "send_file", "link_button"})
		self.assertTrue(set(bot.GATED_TYPES) <= set(bot.NODE_TYPES))


class TestStarters(unittest.TestCase):
	def test_every_starter_is_a_valid_bot(self):
		for key in bot_starters.STARTERS:
			graph = bot_starters.build(key, "Sales", "Accounts")
			self.assertEqual(bot.validate_graph(graph), [], key)

	def test_only_welcome_and_menu_is_offered_while_the_switch_is_off(self):
		self.assertEqual([s["key"] for s in bot_starters.catalog(False)], ["welcome_menu"])
		self.assertEqual({s["key"] for s in bot_starters.catalog(True)}, set(bot_starters.STARTERS))

	def test_an_unknown_starter_builds_nothing(self):
		self.assertIsNone(bot_starters.build("nope"))

	def test_after_hours_branches_on_business_hours(self):
		g = bot_starters.build("after_hours")
		closed = start(g, {"open_now": False})
		self.assertEqual(closed.state["node"], "ask")
		self.assertIn("closed", closed.actions[0]["body"])
		self.assertEqual(closed.actions[1]["do"], "text")
		again = bot.run(g, closed.state, {**FACTS, "open_now": False}, {"text": "Please call me tomorrow", "interactive_id": None})
		self.assertEqual(again.actions[0]["do"], "note")
		self.assertIn("Please call me tomorrow", again.actions[0]["text"])
		self.assertEqual(again.kind, "finished")
		open_ = start(g, {"open_now": True})
		self.assertEqual(open_.kind, "handover")

	def test_enquiry_keeps_the_three_answers_in_one_note(self):
		g = bot_starters.build("enquiry")
		res = start(g)
		for answer in ("Asha", "Printer inks", "Pune"):
			res = bot.run(g, res.state, FACTS, {"text": answer, "interactive_id": None})
		notes = [a for a in res.actions if a["do"] == "note"]
		self.assertEqual(len(notes), 1)
		for part in ("Asha", "Printer inks", "Pune"):
			self.assertIn(part, notes[0]["text"])
		self.assertEqual(res.kind, "handover")

	def test_menu_faq_starts_on_its_keywords_and_answers(self):
		g = bot_starters.build("menu_faq")
		trig = bot.trigger_of(g)
		self.assertTrue(bot.should_start(trig, first_message=False, text="Menu please"))
		self.assertFalse(bot.should_start(trig, first_message=False, text="hello"))
		res = bot.run(g, start(g).state, FACTS, {"text": "Payment terms", "interactive_id": "payment"})
		self.assertIn("payment", res.actions[0]["body"])

	def test_order_status_uses_a_preview_block(self):
		g = bot_starters.build("order_status")
		self.assertTrue(bot.uses_extras(g))
		self.assertTrue(bot.validate_graph(g, extras=False))
		res = start(g, {"docs": {"Sales Order": DOC}})
		self.assertIn("SO-0007", res.actions[0]["body"])


class TestExistingBehaviourIsUnchanged(unittest.TestCase):
	def test_the_welcome_starter_still_works_exactly_as_before(self):
		g = bot.starter_graph("Sales", "Accounts")
		res = bot.run(g, {}, FACTS, None)
		self.assertEqual([a["do"] for a in res.actions], ["text", "buttons"])
		self.assertEqual(res.timeout_minutes, 0)
		done = bot.run(g, res.state, FACTS, {"text": "Sales", "interactive_id": "sales"})
		self.assertEqual((done.kind, done.team), ("assign_team", "Sales"))

	def test_the_original_blocks_have_the_original_handles(self):
		g = copy.deepcopy(bot.starter_graph())
		by = {x["id"]: x for x in g["nodes"]}
		self.assertEqual(bot.handles(by["welcome"]), ["out"])
		self.assertEqual(bot.handles(by["menu"]), ["sales", "accounts", "person"])
		self.assertEqual(bot.handles(by["to_person"]), [])


if __name__ == "__main__":
	unittest.main()
