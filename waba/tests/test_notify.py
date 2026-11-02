"""Run without a site:  python -m unittest waba.tests.test_notify"""

import datetime
import unittest

from waba.rules import notify as n

D = datetime.date
TODAY = D(2026, 11, 10)


def rule(kind, **k):
	base = {"message_type": kind, "waba_number": "+91", "template": "T", "days_after": 3, "repeat_every_days": 0, "max_sends": 1, "ack_within_minutes": 30}
	base.update(k)
	return base


class TestRuleProblems(unittest.TestCase):
	def test_a_blank_rule_says_what_is_missing(self):
		self.assertEqual(n.rule_problems({}), ["Choose the kind of message."])
		blank = {"message_type": n.QUOTATION}
		self.assertEqual(len(n.rule_problems(blank)), 3)

	def test_each_type_needs_its_own_timing(self):
		self.assertEqual(n.rule_problems(rule(n.QUOTATION)), [])
		self.assertIn("days after the quotation date", n.rule_problems(rule(n.QUOTATION, days_after=0))[0])
		self.assertEqual(n.rule_problems(rule(n.PAYMENT, max_sends=1)), [])
		self.assertIn("between reminders", n.rule_problems(rule(n.PAYMENT, max_sends=3, repeat_every_days=0))[0])
		self.assertEqual(n.rule_problems(rule(n.PAYMENT, max_sends=3, repeat_every_days=7)), [])
		self.assertIn("most reminders", n.rule_problems(rule(n.PAYMENT, max_sends=0))[0])
		self.assertEqual(n.rule_problems(rule(n.ENQUIRY)), [])
		self.assertIn("minutes", n.rule_problems(rule(n.ENQUIRY, ack_within_minutes=0))[0])

	def test_number_and_template_are_always_needed(self):
		out = n.rule_problems(rule(n.QUOTATION, waba_number="", template=""))
		self.assertEqual(len(out), 2)

	def test_initial_status(self):
		self.assertEqual(n.initial_status(n.AUTOMATIC), n.QUEUED)
		self.assertEqual(n.initial_status(n.MANUAL), n.PENDING_APPROVAL)
		self.assertEqual(n.initial_status(None), n.PENDING_APPROVAL)


class TestRecordProblem(unittest.TestCase):
	def test_quotation(self):
		self.assertEqual(n.record_problem(n.QUOTATION, {"docstatus": 1, "status": "Open"}), "")
		self.assertEqual(n.record_problem(n.QUOTATION, {"docstatus": 1, "status": "Replied"}), "")
		for status in ("Ordered", "Lost", "Expired", "Cancelled", "Partially Ordered", None):
			self.assertTrue(n.record_problem(n.QUOTATION, {"docstatus": 1, "status": status}), status)
		self.assertIn("not submitted", n.record_problem(n.QUOTATION, {"docstatus": 0, "status": "Open"}))

	def test_invoice(self):
		ok = {"docstatus": 1, "is_return": 0, "outstanding_amount": 500}
		self.assertEqual(n.record_problem(n.PAYMENT, ok), "")
		self.assertIn("Nothing is outstanding", n.record_problem(n.PAYMENT, dict(ok, outstanding_amount=0)))
		self.assertIn("return", n.record_problem(n.PAYMENT, dict(ok, is_return=1)))
		self.assertIn("not submitted", n.record_problem(n.PAYMENT, dict(ok, docstatus=2)))
		self.assertTrue(n.record_problem(n.PAYMENT, dict(ok, outstanding_amount=None)))

	def test_lead(self):
		self.assertEqual(n.record_problem(n.ENQUIRY, {"status": "Lead"}), "")
		for field, value in (("status", "Do Not Contact"), ("status", "Converted"), ("disabled", 1), ("unsubscribed", 1), ("customer", "C-1")):
			self.assertTrue(n.record_problem(n.ENQUIRY, {"status": "Lead", field: value}), field)


class TestSchedule(unittest.TestCase):
	def test_first_send_waits_for_its_day(self):
		self.assertEqual(n.schedule_due(D(2026, 11, 13), [], D(2026, 11, 12), 0, 1)[0], False)
		self.assertEqual(n.schedule_due(D(2026, 11, 13), [], D(2026, 11, 13), 0, 1)[0], True)
		self.assertEqual(n.schedule_due(D(2026, 11, 13), [], D(2026, 12, 1), 0, 1)[0], True)  # a missed day is still due

	def test_repeats_every_n_days_up_to_the_limit(self):
		h = [D(2026, 11, 1)]
		self.assertFalse(n.schedule_due(D(2026, 11, 1), h, D(2026, 11, 7), 7, 3)[0])
		self.assertTrue(n.schedule_due(D(2026, 11, 1), h, D(2026, 11, 8), 7, 3)[0])
		self.assertFalse(n.schedule_due(D(2026, 11, 1), h * 3, D(2027, 1, 1), 7, 3)[0])
		self.assertFalse(n.schedule_due(D(2026, 11, 1), h, D(2027, 1, 1), 0, 3)[0])  # no repeat set

	def test_lookback_leaves_old_records_alone_but_not_ones_already_being_chased(self):
		start = D(2026, 1, 1)
		self.assertFalse(n.schedule_due(start, [], D(2026, 11, 10), 0, 1, 30)[0])
		self.assertIn("lookback", n.schedule_due(start, [], D(2026, 11, 10), 0, 1, 30)[1])
		self.assertTrue(n.schedule_due(D(2026, 11, 1), [], D(2026, 11, 10), 0, 1, 30)[0])
		self.assertTrue(n.schedule_due(start, [], D(2026, 11, 10), 0, 1, None)[0])  # no lookback set: no limit
		self.assertTrue(n.schedule_due(start, [D(2026, 11, 1)], D(2026, 11, 10), 7, 3, 30)[0])  # a repeat is not limited by it

	def test_quotation_and_invoice_events_use_the_rules_lookback(self):
		q = {"docstatus": 1, "status": "Open", "transaction_date": D(2025, 1, 1)}
		self.assertIsNone(n.quotation_event(q, rule(n.QUOTATION, days_after=3, lookback_days=30), [], D(2026, 11, 10))[0])
		self.assertEqual(n.quotation_event(q, rule(n.QUOTATION, days_after=3), [], D(2026, 11, 10))[0], "followup-1")
		inv = {"docstatus": 1, "is_return": 0, "outstanding_amount": 5, "due_date": D(2025, 1, 1)}
		self.assertIsNone(n.invoice_event(inv, rule(n.PAYMENT, days_after=1, lookback_days=30), [], D(2026, 11, 10))[0])

	def test_quotation_event(self):
		doc = {"docstatus": 1, "status": "Open", "transaction_date": D(2026, 11, 7)}
		self.assertEqual(n.quotation_event(doc, rule(n.QUOTATION, days_after=3), [], D(2026, 11, 10))[0], "followup-1")
		self.assertIsNone(n.quotation_event(doc, rule(n.QUOTATION, days_after=3), [], D(2026, 11, 9))[0])
		self.assertIsNone(n.quotation_event(doc, rule(n.QUOTATION, days_after=3), [D(2026, 11, 10)], D(2026, 11, 20))[0])  # once
		self.assertIsNone(n.quotation_event(dict(doc, status="Ordered"), rule(n.QUOTATION), [], D(2026, 11, 20))[0])
		self.assertIsNone(n.quotation_event(dict(doc, transaction_date=None), rule(n.QUOTATION), [], D(2026, 11, 20))[0])

	def test_quotation_dates_may_be_text(self):
		doc = {"docstatus": 1, "status": "Open", "transaction_date": "2026-11-07"}
		self.assertEqual(n.quotation_event(doc, rule(n.QUOTATION, days_after=3), [], D(2026, 11, 10))[0], "followup-1")

	def test_invoice_event_numbers_the_reminders(self):
		doc = {"docstatus": 1, "is_return": 0, "outstanding_amount": 100, "due_date": D(2026, 11, 1)}
		r = rule(n.PAYMENT, days_after=1, repeat_every_days=7, max_sends=3)
		self.assertEqual(n.invoice_event(doc, r, [], D(2026, 11, 2))[0], "reminder-1")
		self.assertEqual(n.invoice_event(doc, r, [D(2026, 11, 2)], D(2026, 11, 9))[0], "reminder-2")
		self.assertIsNone(n.invoice_event(doc, r, [D(2026, 11, 2)], D(2026, 11, 8))[0])
		self.assertIsNone(n.invoice_event(dict(doc, outstanding_amount=0), r, [], D(2026, 12, 1))[0])

	def test_lead_acknowledged_once_and_only_while_fresh(self):
		now = datetime.datetime(2026, 11, 10, 12, 0)
		doc = {"status": "Lead", "creation": datetime.datetime(2026, 11, 10, 11, 45)}
		self.assertEqual(n.lead_event(doc, rule(n.ENQUIRY, ack_within_minutes=30), [], now)[0], "ack")
		self.assertIsNone(n.lead_event(doc, rule(n.ENQUIRY, ack_within_minutes=10), [], now)[0])
		self.assertIsNone(n.lead_event(doc, rule(n.ENQUIRY), [D(2026, 11, 10)], now)[0])
		self.assertEqual(n.lead_event(dict(doc, creation="2026-11-10 11:45:00"), rule(n.ENQUIRY, ack_within_minutes=30), [], now)[0], "ack")


class TestHolding(unittest.TestCase):
	OK = dict(enabled=True, rule_enabled=True, mode=n.AUTOMATIC, receive_only=False, number_ok=True, quiet_ok=True, phone="+919000000001", test_list="", sent_last_hour=0, max_per_hour=60, sent_today=0, max_per_day=1)

	def hold(self, **k):
		return n.hold_reason(**{**self.OK, **k})

	def test_nothing_holds_a_clean_send(self):
		self.assertIsNone(self.hold())

	def test_hard_reasons_in_order(self):
		self.assertEqual(self.hold(enabled=False)[0], "switch_off")
		self.assertEqual(self.hold(rule_enabled=False)[0], "rule_off")
		self.assertEqual(self.hold(receive_only=True)[0], "receive_only")
		self.assertEqual(self.hold(number_ok=False)[0], "number")
		self.assertEqual(self.hold(test_list="+91 90000 00002")[0], "test_mode")
		self.assertIsNone(self.hold(test_list="+91 90000 00001\n+91 1"))

	def test_soft_reasons_apply_only_to_automatic_sends(self):
		self.assertEqual(self.hold(quiet_ok=False)[0], "quiet_hours")
		self.assertEqual(self.hold(sent_last_hour=60)[0], "hourly_cap")
		self.assertEqual(self.hold(sent_today=1)[0], "customer_cap")
		self.assertIsNone(self.hold(mode=n.MANUAL, quiet_ok=False, sent_last_hour=99, sent_today=5))

	def test_which_holds_clear_by_themselves(self):
		self.assertTrue(n.retry_later("quiet_hours"))
		self.assertTrue(n.retry_later("hourly_cap"))
		self.assertFalse(n.retry_later("customer_cap"))
		self.assertFalse(n.retry_later("test_mode"))

	def test_caps(self):
		self.assertFalse(n.hourly_cap_reached(10, 0))  # 0 means no limit
		self.assertTrue(n.hourly_cap_reached(60, 60))
		self.assertTrue(n.customer_cap_reached(1, 0))  # blank means 1


class TestKeysAndPhones(unittest.TestCase):
	def test_dedupe_key_is_stable_and_specific(self):
		a = n.dedupe_key("R", "Quotation", "Q-1", "followup-1", "+91", "2026-11-10")
		self.assertEqual(a, n.dedupe_key("R", "Quotation", "Q-1", "followup-1", "+91", "2026-11-10"))
		self.assertEqual(len(a), 40)
		for other in (("R2", "Quotation", "Q-1", "followup-1", "+91", "2026-11-10"), ("R", "Quotation", "Q-2", "followup-1", "+91", "2026-11-10"), ("R", "Quotation", "Q-1", "followup-2", "+91", "2026-11-10"), ("R", "Quotation", "Q-1", "followup-1", "+92", "2026-11-10"), ("R", "Quotation", "Q-1", "followup-1", "+91", "2026-11-11")):
			self.assertNotEqual(a, n.dedupe_key(*other))

	def test_test_list_compares_digits(self):
		self.assertTrue(n.in_test_list("+919000000001", ""))
		self.assertTrue(n.in_test_list("+919000000001", "9000000001, +91 90000 00001"))
		self.assertFalse(n.in_test_list("+919000000009", "+91 90000 00001"))
		self.assertFalse(n.in_test_list("", "+91 90000 00001"))

	def test_pick_phone(self):
		self.assertEqual(n.pick_phone([{"raw": "x", "key": None}, {"raw": "y", "key": "+919"}]), "+919")
		self.assertIsNone(n.pick_phone([]))
		self.assertIsNone(n.pick_phone(None))


if __name__ == "__main__":
	unittest.main()


class TestAutomaticSendSeam(unittest.TestCase):
	"""The system may send a template, but only through a narrow, server-side door."""

	def setUp(self):
		import ast, os

		base = os.path.join(os.path.dirname(__file__), "..")
		with open(os.path.join(base, "api", "send.py"), encoding="utf-8") as handle:
			self.src = handle.read()
		self.tree = ast.parse(self.src)

	def fn(self, name):
		import ast

		return next(n for n in self.tree.body if isinstance(n, ast.FunctionDef) and n.name == name)

	def test_send_automatic_is_not_whitelisted_and_takes_only_system_origins(self):
		import ast

		node = self.fn("send_automatic")
		self.assertFalse(any("whitelist" in ast.dump(d) for d in node.decorator_list))
		text = ast.get_source_segment(self.src, node)
		self.assertIn("AUTOMATIC_ORIGINS", text)
		self.assertIn("person=False", text)
		self.assertIn("AUTOMATIC_ORIGINS = (purposes.NOTIFICATION, purposes.REMINDER, purposes.SYSTEM)", self.src)

	def test_the_person_bound_parts_are_the_only_ones_replaced(self):
		import ast

		text = ast.get_source_segment(self.src, self.fn("_send_template"))
		for needle in ("refuse_if_receive_only()", "check_conversation_template(", "templating.prepare(", "sent_by=False if person else None", "if person else None"):
			self.assertIn(needle, text, needle)

	def test_nobody_is_recorded_as_the_sender_of_an_automatic_message(self):
		self.assertIn('"sent_by": frappe.session.user if sent_by is False else sent_by', self.src)

	def test_the_whitelisted_senders_still_cannot_choose_an_origin_or_a_person_mode(self):
		import ast

		for node in self.tree.body:
			if isinstance(node, ast.FunctionDef) and any("whitelist" in ast.dump(d) for d in node.decorator_list):
				names = [a.arg for a in node.args.args]
				for forbidden in ("origin", "person", "sender_label", "sent_by"):
					self.assertNotIn(forbidden, names, node.name)


class TestEngineSource(unittest.TestCase):
	"""The engine runs unattended, so its safety is pinned from the source."""

	def setUp(self):
		import ast, os

		base = os.path.join(os.path.dirname(__file__), "..")
		with open(os.path.join(base, "notify.py"), encoding="utf-8") as handle:
			self.src = handle.read()
		self.tree = ast.parse(self.src)

	def fn(self, name):
		import ast

		return next(n for n in self.tree.body if isinstance(n, ast.FunctionDef) and n.name == name)

	def text(self, name):
		import ast

		return ast.get_source_segment(self.src, self.fn(name))

	def test_it_reaches_customers_only_through_send_automatic(self):
		for forbidden in ("graph.send_message", "graph.upload_media", "send._deliver", "send._send_template", "send._send_text", "requests."):
			self.assertNotIn(forbidden, self.src, forbidden)
		self.assertIn("send.send_automatic(", self.src)
		self.assertIn("purposes.NOTIFICATION", self.text("deliver"))

	def test_deliver_rechecks_everything_before_sending(self):
		text = self.text("deliver")
		for needle in ("rule_problems(", "record_problem(", "_evaluate(", "send.send_automatic("):
			self.assertIn(needle, text, needle)
		order = [text.index(x) for x in ("rule_problems(", "record_problem(", "_evaluate(", "send.send_automatic(")]
		self.assertEqual(order, sorted(order))

	def test_every_hold_is_evaluated_from_the_switches_and_the_number(self):
		text = self.text("_evaluate")
		for needle in ("notifications_enabled", "receive_only", "purpose_notifications", "test_phones", "max_sends_per_hour", "is_within_hours"):
			self.assertIn(needle, text, needle)

	def test_nothing_runs_while_the_master_switch_is_off(self):
		for name in ("_scan", "dispatch"):
			self.assertIn("switched_on()", self.text(name), name)

	def test_automatic_sends_are_claimed_once_before_the_job(self):
		text = self.text("dispatch")
		self.assertIn("claims.claim_and_enqueue(", text)
		self.assertIn("from_status=rules.QUEUED", text)
		self.assertIn("to_status=rules.SENDING", text)

	def test_the_manual_screens_need_an_approver_role_and_no_function_takes_an_origin(self):
		import ast

		self.assertIn('APPROVERS = ("System Manager", ROLE_ADMIN, ROLE_SUPERVISOR)', self.src)
		for node in self.tree.body:
			if isinstance(node, ast.FunctionDef) and any("whitelist" in ast.dump(d) for d in node.decorator_list):
				self.assertIn("_only_approvers()", ast.get_source_segment(self.src, node), node.name)
				names = [a.arg for a in node.args.args]
				for forbidden in ("origin", "person", "sender_label", "sent_by"):
					self.assertNotIn(forbidden, names, node.name)
				for a in node.args.args:
					self.assertIsNotNone(a.annotation, f"{node.name}({a.arg})")

	def test_the_scheduler_runs_the_scans_and_dispatch(self):
		import os

		with open(os.path.join(os.path.dirname(__file__), "..", "hooks.py"), encoding="utf-8") as handle:
			hooks = handle.read()
		for job in ("waba.notify.scan_leads", "waba.notify.dispatch", "waba.notify.scan_dates"):
			self.assertIn(job, hooks, job)


class TestScreensWiring(unittest.TestCase):
	"""The notification and reminder screens call the server by name; check those names exist and are whitelisted."""

	FILES = (
		("public", "js", "waba_notify_ui.js"),
		("public", "js", "waba_notify_doc.js"),
		("public", "js", "waba_inbox_app.js"),
		("waba", "doctype", "waba_notification_log", "waba_notification_log.js"),
		("waba", "doctype", "waba_notification_rule", "waba_notification_rule.js"),
	)

	def setUp(self):
		import os

		self.base = os.path.join(os.path.dirname(__file__), "..")
		self.src = {}
		for parts in self.FILES:
			with open(os.path.join(self.base, *parts), encoding="utf-8") as handle:
				self.src[parts[-1]] = handle.read()

	def whitelisted(self, module_path):
		import ast, os

		path = os.path.join(self.base, *module_path.split("."), "") [:-1] + ".py"
		with open(path, encoding="utf-8") as handle:
			tree = ast.parse(handle.read())
		return {n.name for n in tree.body if isinstance(n, ast.FunctionDef) and any("whitelist" in ast.dump(d) for d in n.decorator_list)}

	def test_every_server_method_called_exists_and_is_whitelisted(self):
		import re

		for name, text in self.src.items():
			for module, fn in set(re.findall(r"waba\.((?:api\.)?\w+)\.(\w+)", text)):
				if module in ("notify", "reminders") or module.startswith("api."):
					self.assertIn(fn, self.whitelisted(module), f"{name}: waba.{module}.{fn}")

	def test_what_the_dialogs_show_is_escaped(self):
		ui = self.src["waba_notify_ui.js"]
		for fragment in ("e(f.rule_name)", "e(p.body)", "e(b.text || b.type)", "e(out.error"):
			self.assertIn(fragment, ui, fragment)
		inbox = self.src["waba_inbox_app.js"]
		for fragment in ("waba_e(x.customer", "waba_e(x.note)", "waba_e(x.conversation)"):
			self.assertIn(fragment, inbox, fragment)

	def test_the_buttons_on_documents_are_for_approvers_only(self):
		doc = self.src["waba_notify_doc.js"]
		self.assertIn('"Waba Supervisor"', doc)
		self.assertIn("allowed()", doc)

	def test_the_loader_stamp_knows_the_new_file(self):
		import os

		with open(os.path.join(self.base, "api", "inbox.py"), encoding="utf-8") as handle:
			self.assertIn("js/waba_notify_ui.js", handle.read())


class TestModuleReferences(unittest.TestCase):
	"""A call to a function that is not where the code looks for it only shows up at run time; check the names here."""

	def test_every_module_attribute_notify_uses_exists_where_it_is_looked_for(self):
		import ast, os

		base = os.path.join(os.path.dirname(__file__), "..")

		def names_in(path):
			with open(path, encoding="utf-8") as handle:
				tree = ast.parse(handle.read())
			found = set()
			for node in tree.body:
				if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
					found.add(node.name)
				elif isinstance(node, ast.Assign):
					found |= {t.id for t in node.targets if isinstance(t, ast.Name)}
				elif isinstance(node, (ast.Import, ast.ImportFrom)):
					found |= {(a.asname or a.name).split(".")[0] for a in node.names}
			return found

		with open(os.path.join(base, "notify.py"), encoding="utf-8") as handle:
			tree = ast.parse(handle.read())
		aliases = {}
		for node in tree.body:
			if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("waba"):
				for a in node.names:
					module = node.module.replace(".", os.sep) + os.sep + a.name if node.module in ("waba", "waba.rules", "waba.api") else None
					if module and os.path.exists(os.path.join(base, "..", module + ".py")):
						aliases[a.asname or a.name] = os.path.join(base, "..", module + ".py")
		self.assertTrue({"inbound", "parties", "send", "claims", "assignment", "rules_inbound", "rules", "purposes"} <= set(aliases), sorted(aliases))
		missing = []
		for node in ast.walk(tree):
			if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id in aliases:
				if node.attr not in names_in(aliases[node.value.id]):
					missing.append(f"{node.value.id}.{node.attr}")
		self.assertEqual(missing, [])


class TestFormScriptsSurviveConcatenation(unittest.TestCase):
	"""Frappe joins every app's script for a doctype into one file. If the script before ours does not end in a semicolon,
	our `(function () {` would be read as a call on it ("... is not a function") and the whole form script would die."""

	def test_scripts_added_to_other_apps_forms_start_with_a_semicolon(self):
		import os, re

		import waba.hooks as hooks

		base = os.path.join(os.path.dirname(__file__), "..")
		files = {path for paths in hooks.doctype_js.values() for path in paths}
		self.assertTrue(files)
		for path in files:
			with open(os.path.join(base, path), encoding="utf-8") as handle:
				text = handle.read()
			code = re.sub(r"/\*.*?\*/", "", text, flags=re.S).lstrip()
			code = re.sub(r"^(//[^\n]*\n\s*)+", "", code)
			self.assertTrue(code.startswith(";(function") or not code.startswith("("), f"{path} starts with a bare '(' and could break when joined to another app's script")
