"""Run without a site:  python -m unittest waba.tests.test_template_api"""

import ast
import os
import unittest

BASE = os.path.join(os.path.dirname(__file__), "..")


def read(*parts):
	with open(os.path.join(BASE, *parts), encoding="utf-8") as handle:
		return handle.read()


class TestTemplateApiSource(unittest.TestCase):
	def setUp(self):
		self.src = read("api", "templates.py")
		self.tree = ast.parse(self.src)

	def fn(self, name):
		return next(n for n in self.tree.body if isinstance(n, ast.FunctionDef) and n.name == name)

	def text(self, name):
		return ast.get_source_segment(self.src, self.fn(name))

	def test_every_whitelisted_function_is_admin_only_post_and_annotated(self):
		found = 0
		for node in self.tree.body:
			if isinstance(node, ast.FunctionDef) and any("whitelist" in ast.dump(d) for d in node.decorator_list):
				found += 1
				self.assertIn("_only_admins()", ast.get_source_segment(self.src, node), node.name)
				self.assertTrue(any("POST" in ast.dump(d) for d in node.decorator_list), node.name)
				for a in node.args.args:
					self.assertIsNotNone(a.annotation, f"{node.name}({a.arg})")
		self.assertEqual(found, 3)

	def test_submit_checks_before_it_talks_to_meta_and_only_for_drafts(self):
		text = self.text("submit")
		self.assertIn("if doc.status not in EDITABLE", text)
		self.assertLess(text.index("author.check(draft)"), text.index("_context(doc)"))
		self.assertLess(text.index("_context(doc)"), text.index("graph.create_template("))
		self.assertIn("for_submit=True", text)

	def test_the_sample_is_uploaded_before_the_create_call_and_only_for_media_headers(self):
		text = self.text("submit")
		self.assertIn('if draft["header_format"] in MEDIA_HEADERS', text)
		self.assertLess(text.index("_upload_sample("), text.index("graph.create_template("))

	def test_a_refusal_is_shown_in_metas_words_and_noted_on_the_template(self):
		text = self.text("submit")
		self.assertIn("graph.explain(e)", text)
		self.assertIn('"submit_note": text', text)
		self.assertIn("_note_account_problem", text)

	def test_delete_removes_a_draft_locally_and_a_meta_template_only_by_its_id(self):
		text = self.text("delete")
		self.assertIn('if doc.status == "DRAFT"', text)
		self.assertIn("doc.meta_template_id", text)
		self.assertIn("graph.delete_template(token, account.waba_id, doc.template_name, doc.meta_template_id, version)", text)
		self.assertLess(text.index("if not doc.meta_template_id"), text.index("graph.delete_template("))

	def test_nothing_here_sends_a_message(self):
		for forbidden in ("send_message", "send_automatic", "_deliver", "send._send"):
			self.assertNotIn(forbidden, self.src)

	def test_the_draft_form_never_calls_meta_on_save(self):
		self.assertNotIn("graph.", read("waba", "doctype", "waba_template", "waba_template.py"))


if __name__ == "__main__":
	unittest.main()


class TestTemplateFormScreen(unittest.TestCase):
	def setUp(self):
		self.js = read("waba", "doctype", "waba_template", "waba_template.js")

	def test_every_server_method_the_form_calls_exists_and_is_whitelisted(self):
		import re

		tree = ast.parse(read("api", "templates.py"))
		whitelisted = {n.name for n in tree.body if isinstance(n, ast.FunctionDef) and any("whitelist" in ast.dump(d) for d in n.decorator_list)}
		calls = set(re.findall(r"waba\.api\.templates\.(\w+)", self.js))
		self.assertEqual(calls, {"submit", "delete", "duplicate"})
		self.assertTrue(calls <= whitelisted)

	def test_submitting_needs_a_saved_draft_and_a_confirmation(self):
		self.assertIn("frm.is_dirty()", self.js)
		self.assertIn("frappe.confirm(", self.js)

	def test_deleting_at_meta_needs_the_name_typed(self):
		self.assertIn("v.confirm !== frm.doc.template_name", self.js)

	def test_what_the_form_shows_is_escaped(self):
		for fragment in ("e(fill(frm.doc.body_text", "e(b.text || names[b.type]", "e(frm.doc.footer_text)", "frappe.utils.escape_html(out.error"):
			self.assertIn(fragment, self.js, fragment)

	def test_only_drafts_and_rejected_templates_get_the_submit_button(self):
		self.assertIn('["DRAFT", "REJECTED"].includes(frm.doc.status)', self.js)
