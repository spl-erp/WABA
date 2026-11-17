"""Run without a site:  python -m unittest waba.tests.test_template_draft"""

import ast
import os
import types
import unittest

from waba.rules import template_author as author

BASE = os.path.join(os.path.dirname(__file__), "..")


def read(*parts):
	with open(os.path.join(BASE, *parts), encoding="utf-8") as handle:
		return handle.read()


def fake_doc(**k):
	row = lambda **r: types.SimpleNamespace(**r)
	doc = types.SimpleNamespace(
		template_name=" order_update ", language=" en ", category="UTILITY", header_format="", header_text="", header_handle=None,
		body_text="Hello {{1}}, your order {{2}} has been dispatched and will reach you soon.", footer_text="",
		buttons=[row(type="QUICK_REPLY", text="Thanks", url=None, phone_number=None, example=None)],
		variables=[row(slot="body.1", example="Rahul"), row(slot="body.2", example=""), row(slot="", example="x")],
	)
	doc.get = lambda name, default=None: getattr(doc, name, default)
	for key, value in k.items():
		setattr(doc, key, value)
	return doc


class TestDraftDict(unittest.TestCase):
	def setUp(self):
		import importlib.util

		spec = importlib.util.spec_from_file_location("waba_template_ctrl", os.path.join(BASE, "waba", "doctype", "waba_template", "waba_template.py"))
		try:
			self.mod = importlib.util.module_from_spec(spec)
			spec.loader.exec_module(self.mod)
		except Exception as e:  # frappe is not importable here
			self.skipTest(f"controller not importable offline: {e}")

	def test_draft_is_read_from_the_fields_and_the_example_rows(self):
		d = self.mod.draft_dict(fake_doc())
		self.assertEqual((d["template_name"], d["language"]), ("order_update", "en"))
		self.assertEqual(d["examples"], {"body.1": "Rahul"})
		self.assertEqual(d["buttons"], [{"type": "QUICK_REPLY", "text": "Thanks", "url": None, "phone_number": None, "example": None}])

	def test_an_incomplete_draft_lists_what_is_missing(self):
		problems = author.check(self.mod.draft_dict(fake_doc()))
		self.assertTrue(any("body value {{2}}" in p for p in problems), problems)


class TestSource(unittest.TestCase):
	def setUp(self):
		self.src = read("waba", "doctype", "waba_template", "waba_template.py")

	def test_a_draft_names_itself_before_naming_and_synced_templates_keep_their_key(self):
		self.assertIn("def before_naming", self.src)
		self.assertIn('if self.status == "DRAFT" and not self.template_key', self.src)

	def test_only_drafts_and_rejected_templates_are_validated_as_drafts(self):
		self.assertIn('EDITABLE = ("DRAFT", "REJECTED")', self.src)
		self.assertIn("if self.status in EDITABLE", self.src)

	def test_saving_a_draft_never_talks_to_meta(self):
		for forbidden in ("graph.", "requests", "send."):
			self.assertNotIn(forbidden, self.src)

	def test_sync_leaves_unsent_drafts_alone(self):
		src = read("meta", "actions.py")
		self.assertIn('"status": ["not in", ["DELETED", "DRAFT"]]', src)


if __name__ == "__main__":
	unittest.main()
