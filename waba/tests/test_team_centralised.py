"""Run without a site:  python -m unittest waba.tests.test_team_centralised

Source-level checks for the pieces that need a site to run (the live behaviour is in the UAT check script)."""

import ast
import os
import re
import unittest

BASE = os.path.join(os.path.dirname(__file__), "..")


def read(*parts):
	with open(os.path.join(BASE, *parts), encoding="utf-8") as handle:
		return handle.read()


def whitelisted(path):
	tree = ast.parse(read(*path))
	return {n.name for n in tree.body if isinstance(n, ast.FunctionDef) and any("whitelist" in ast.dump(d) for d in n.decorator_list)}


class TestTeamForm(unittest.TestCase):
	def test_every_method_the_team_form_calls_exists(self):
		js = read("waba", "doctype", "waba_team", "waba_team.js")
		calls = set(re.findall(r"waba\.api\.teams\.(\w+)", js))
		self.assertEqual(calls, {"setup_check", "apply"})
		self.assertTrue(calls <= whitelisted(("api", "teams.py")))

	def test_apply_is_for_waba_admin_only_and_posts(self):
		source = read("api", "teams.py")
		self.assertIn("frappe.only_for(ROLE_ADMIN)", source)
		self.assertIn('@frappe.whitelist(methods=["POST"])\ndef apply', source)

	def test_system_manager_alone_no_longer_reads_chats(self):
		self.assertIn('ADMIN_ROLES = {"Waba Admin"}', read("teams.py"))

	def test_the_number_form_only_locks_the_agents_when_the_teams_run_them(self):
		js = read("waba", "doctype", "waba_number", "waba_number.js")
		self.assertIn("teams_manage_agents", js)
		self.assertIn("read_only", js)


class TestUnassign(unittest.TestCase):
	def setUp(self):
		self.source = read("api", "inbox.py")

	def test_it_needs_a_note_and_the_right_to_manage(self):
		body = self.source[self.source.index("def unassign("):self.source.index("def set_status(")]
		self.assertIn("if not note:", body)
		self.assertIn("_may_manage(conv)", body)
		self.assertIn('"held": 1', body)

	def test_routing_leaves_a_held_conversation_alone(self):
		source = read("assignment.py")
		self.assertIn("conversation.held and not conversation.assigned_to", source)
		self.assertIn('"held": 0,', source)  # a real assignment clears the hold

	def test_the_waiting_scan_skips_held_ones(self):
		self.assertIn('"waiting_since": ["is", "set"], "held": 0}', read("assignment.py"))

	def test_a_transfer_clears_the_hold(self):
		body = self.source[self.source.index("def transfer("):self.source.index("def unassign(")]
		self.assertIn('"held": 0', body)

	def test_the_inbox_menu_offers_it_and_calls_a_real_method(self):
		js = read("public", "js", "waba_inbox_app.js")
		self.assertIn("waba.api.inbox.unassign", js)
		self.assertIn("unassign", whitelisted(("api", "inbox.py")))
		self.assertIn("can_unassign", js)


class TestTeamCode(unittest.TestCase):
	def test_a_person_belongs_to_one_team_and_numbers_may_be_shared(self):
		source = read("teams.py")
		self.assertIn("A person belongs to one team.", source)
		self.assertNotIn("A number is owned by one team.", source)

	def test_only_a_lead_of_the_branch_edits_a_team(self):
		source = read("teams.py")
		self.assertIn("def has_team_permission", source)
		self.assertIn("Only a Waba Admin changes a team's numbers or where it sits in the tree.", source)


class TestInboxNeedsAWabaRole(unittest.TestCase):
	def test_system_manager_alone_does_not_open_the_inbox(self):
		self.assertIn('SENDERS = (ROLE_ADMIN, ROLE_SUPERVISOR, ROLE_AGENT)', read("api", "send.py"))

	def test_transfer_refuses_and_lists_only_people_with_a_waba_role(self):
		source = read("api", "inbox.py")
		self.assertIn("teams.has_waba_role(u)", source)
		self.assertIn("has no Waba role. Add them to a team first.", source)
