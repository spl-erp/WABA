"""Run without a site:  python -m unittest waba.tests.test_receive_only

A live customer number connected to a test system must be listenable-to but never writable-to (owner decision, 2 Nov)."""

import ast
import json
import os
import unittest

from waba.rules import purposes

BASE = os.path.join(os.path.dirname(__file__), "..")


def read(*parts):
	with open(os.path.join(BASE, *parts), encoding="utf-8") as handle:
		return handle.read()


class TestRule(unittest.TestCase):
	def test_receive_only_blocks_with_a_plain_message(self):
		ok, code, message = purposes.check_send_allowed(True)
		self.assertFalse(ok)
		self.assertEqual(code, purposes.RECEIVE_ONLY)
		self.assertIn("receive only", message)
		self.assertIn("Waba Admin", message)

	def test_normal_numbers_are_unaffected(self):
		self.assertEqual(purposes.check_send_allowed(False), (True, None, None))
		self.assertEqual(purposes.check_send_allowed(None), (True, None, None))
		self.assertEqual(purposes.check_send_allowed(0), (True, None, None))


class TestEverySenderIsGuarded(unittest.TestCase):
	def setUp(self):
		self.src = read("api", "send.py")
		self.tree = ast.parse(self.src)

	def function(self, name):
		return next(n for n in self.tree.body if isinstance(n, ast.FunctionDef) and n.name == name)

	def test_text_template_file_and_reaction_check_before_anything_is_created(self):
		for name in ("_send_text", "_send_template", "_send_media", "send_reaction"):
			self.assertIn("ctx.refuse_if_receive_only()", ast.get_source_segment(self.src, self.function(name)), name)

	def test_deliver_has_a_backstop(self):
		self.assertIn('getattr(ctx, "receive_only", False)', ast.get_source_segment(self.src, self.function("_deliver")))

	def test_read_receipts_are_not_sent(self):
		self.assertIn("not ctx.receive_only", ast.get_source_segment(self.src, self.function("mark_read")))

	def test_starting_from_a_record_refuses_before_creating_a_conversation(self):
		start = ast.get_source_segment(read("api", "party.py"), next(n for n in ast.parse(read("api", "party.py")).body if isinstance(n, ast.FunctionDef) and n.name == "start"))
		self.assertIn('"receive_only"', start)
		self.assertLess(start.index('"receive_only"'), start.index("_conversation("))

	def test_every_call_that_reaches_meta_is_in_a_guarded_path(self):
		# graph.send_message / upload_media may appear only in these functions
		allowed = {"mark_read", "_deliver", "build", "send_reaction"}
		for node in ast.walk(self.tree):
			if isinstance(node, ast.FunctionDef):
				text = ast.get_source_segment(self.src, node)
				calls = "graph.send_message(" in text or "graph.upload_media(" in text
				inner = [c for c in ast.walk(node) if isinstance(c, ast.FunctionDef) and c is not node]
				own = text
				for c in inner:
					own = own.replace(ast.get_source_segment(self.src, c), "")
				if "graph.send_message(" in own or "graph.upload_media(" in own:
					self.assertIn(node.name, allowed, f"{node.name} calls Meta directly")


class TestField(unittest.TestCase):
	def test_field_exists_unticked_by_default_and_in_the_right_place(self):
		d = json.loads(read("waba", "doctype", "waba_number", "waba_number.json"))
		field = next(f for f in d["fields"] if f["fieldname"] == "receive_only")
		self.assertEqual(field["fieldtype"], "Check")
		self.assertEqual(str(field.get("default")), "0")
		self.assertIn("receive_only", d["field_order"])
		self.assertEqual(d["field_order"], [f["fieldname"] for f in d["fields"]])


if __name__ == "__main__":
	unittest.main()
