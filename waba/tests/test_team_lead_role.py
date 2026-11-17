"""Run without a site:  python -m unittest waba.tests.test_team_lead_role

The team role "Lead" is now "Team Lead" (not to be mixed up with the CRM Lead): the dropdown, the constant, every comparison, the
data patch and the words people read."""

import ast
import json
import os
import re
import unittest

APP = os.path.join(os.path.dirname(__file__), "..")


def read(*parts):
	with open(os.path.join(APP, *parts), encoding="utf-8") as handle:
		return handle.read()


def sources(*exts):
	for root, _dirs, files in os.walk(APP):
		if "tests" in root.split(os.sep) or "__pycache__" in root or "node_modules" in root:
			continue
		for name in files:
			if name.endswith(exts):
				path = os.path.join(root, name)
				yield os.path.relpath(path, APP), open(path, encoding="utf-8").read()


class TestRole(unittest.TestCase):
	def test_the_dropdown_offers_agent_and_team_lead(self):
		fields = {f["fieldname"]: f for f in json.loads(read("waba", "doctype", "waba_team_member", "waba_team_member.json"))["fields"]}
		self.assertEqual(fields["role"]["options"].split("\n"), ["Agent", "Team Lead"])
		self.assertEqual(fields["role"]["default"], "Agent")
		self.assertIn("A Team Lead sees", fields["role"]["description"])

	def test_the_constant_and_its_users_agree(self):
		from waba.rules import team_setup, visibility

		self.assertEqual(visibility.LEAD, "Team Lead")
		self.assertEqual(visibility.AGENT, "Agent")
		self.assertEqual(team_setup.ROLE_FOR[visibility.LEAD], "Supervisor")  # the number's Agent list keeps its own word
		self.assertEqual(team_setup.wanted_roles([("A", "u@x", "Agent"), ("B", "u@x", "Team Lead")])["u@x"], "Waba Supervisor")

	def test_no_code_compares_a_role_to_the_bare_word_lead(self):
		pattern = re.compile(r"""(role|a\.role|r\.role)\s*(==|===|!=|!==)\s*["']Lead["']|["']Lead["']\s*(==|===)\s*(role|a\.role)""")
		for path, text in sources(".py", ".js"):
			self.assertIsNone(pattern.search(text), path)

	def test_the_teams_api_uses_the_constant(self):
		body = read("api", "teams.py")
		self.assertIn("role == visibility.LEAD", body)
		self.assertIn("from waba.rules import visibility", body)

	def test_the_bot_builder_labels_a_team_lead(self):
		js = read("public", "js", "waba_bot_canvas.js")
		self.assertIn('a.role === "Team Lead"', js)
		self.assertNotIn('a.role === "Lead"', js)


class TestPatch(unittest.TestCase):
	PATCH = read("patches", "v0_1", "rename_lead_role.py")

	def test_it_is_registered_after_the_model_sync(self):
		text = read("patches.txt")
		self.assertIn("waba.patches.v0_1.rename_lead_role", text)
		self.assertGreater(text.index("waba.patches.v0_1.rename_lead_role"), text.index("[post_model_sync]"))

	def test_it_only_renames_the_team_member_role_and_is_safe_to_repeat(self):
		ast.parse(self.PATCH)
		self.assertIn("update `tabWaba Team Member` set role = 'Team Lead' where role = 'Lead'", self.PATCH)
		self.assertEqual(self.PATCH.count("update "), 1)
		self.assertIn("table_exists", self.PATCH)
		self.assertNotIn("Waba Agent Access", self.PATCH.split('"""')[2])


class TestWords(unittest.TestCase):
	def test_what_people_read_says_team_lead(self):
		self.assertIn("waiting for a Team Lead to assign it", read("assignment.py"))
		self.assertIn("Waiting for a Team Lead to assign it", read("assignment.py"))
		self.assertIn("ask a Team Lead", read("privacy.py"))
		self.assertIn("Add a Team Lead to the team", read("waba", "doctype", "waba_number", "waba_number.py"))
		self.assertIn("has no Team Lead", read("rules", "team_setup.py"))
		self.assertIn("Held for a Team Lead", read("waba", "doctype", "waba_conversation", "waba_conversation.json"))
		self.assertIn("until a Team Lead hands it", read("public", "js", "waba_inbox_app.js"))

	def test_the_crm_lead_is_never_renamed(self):
		party = read("api", "party.py")
		self.assertIn('"Lead": (("lead_name", "company_name", "name")', party)
		self.assertNotIn("Team Lead", party)
		self.assertIn('"Lead": ["public/js/waba_party.js", "public/js/waba_notify_doc.js"]', read("hooks.py"))
		options = [f for f in json.loads(read("waba", "doctype", "waba_recipient_set", "waba_recipient_set.json"))["fields"] if f["fieldname"] == "party_doctype"][0]["options"]
		self.assertEqual(options.split("\n"), ["Customer", "Lead"])

	def test_no_user_sentence_still_calls_the_role_a_bare_lead(self):
		bare = re.compile(r"(ask a Lead|a Lead (or admin|assigns|hands|of the number)|the Leads (of|who|above|over)|Add a Lead|no Lead\b|Held for a Lead)")
		for path, text in sources(".py", ".js", ".json"):
			self.assertIsNone(bare.search(text), path)


if __name__ == "__main__":
	unittest.main()
