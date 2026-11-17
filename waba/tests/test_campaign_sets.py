"""Run without a site:  python -m unittest waba.tests.test_campaign_sets

W4a wiring: the Set doctypes, who may build and see a Set, the list-view action and the review window. The decisions
(who is in and out) are tested in test_campaign_rules; the database side is checked on a site by verify_w4a."""

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


SET = load("waba", "doctype", "waba_recipient_set", "waba_recipient_set.json")
MEMBER = load("waba", "doctype", "waba_recipient_set_member", "waba_recipient_set_member.json")
API = read("api", "campaigns.py")
GLUE = read("campaigns.py")
HOOKS = read("hooks.py")
LIST_JS = read("public", "js", "waba_create_set.js")
UI_JS = read("public", "js", "waba_sets_ui.js")
FORM_JS = read("waba", "doctype", "waba_recipient_set", "waba_recipient_set.js")


def perms(definition):
	return {p["role"]: p for p in definition["permissions"]}


class TestRole(unittest.TestCase):
	def test_the_campaign_role_is_created_on_install(self):
		self.assertIn('ROLE_CAMPAIGN = "Waba Campaign Manager"', read("constants.py"))
		self.assertIn("ROLE_CAMPAIGN", read("setup", "install.py").split("ROLES =")[1].split("\n")[0])

	def test_a_campaign_manager_is_not_an_inbox_sender(self):
		# creating Sets does not give access to chats: SENDERS stays Admin / Supervisor / Agent
		senders = re.search(r"SENDERS\s*=\s*\(([^)]*)\)", read("api", "send.py")).group(1)
		self.assertNotIn("Campaign", senders)


class TestDoctypes(unittest.TestCase):
	def test_nobody_may_edit_or_delete_a_set_except_admin_delete(self):
		p = perms(SET)
		for role, rights in p.items():
			self.assertFalse(rights.get("write"), role)
		self.assertTrue(p["Waba Admin"].get("delete"))
		self.assertFalse(p["Waba Campaign Manager"].get("delete"))
		self.assertTrue(p["Waba Campaign Manager"].get("create"))

	def test_members_are_read_only_for_everyone(self):
		for role, rights in perms(MEMBER).items():
			self.assertFalse(rights.get("write") or rights.get("create"), role)

	def test_system_manager_alone_does_not_see_sets(self):
		self.assertNotIn("System Manager", perms(SET))
		self.assertNotIn("System Manager", perms(MEMBER))

	def test_a_set_is_made_from_customers_or_leads_only(self):
		field = {f["fieldname"]: f for f in SET["fields"]}["party_doctype"]
		self.assertEqual(field["options"].split("\n"), ["Customer", "Lead"])

	def test_the_set_controller_refuses_edits(self):
		source = read("waba", "doctype", "waba_recipient_set", "waba_recipient_set.py")
		self.assertIn("before_save", source)
		self.assertIn("is_new()", source)

	def test_deleting_a_set_deletes_its_people(self):
		self.assertIn('frappe.db.delete("Waba Recipient Set Member"', read("waba", "doctype", "waba_recipient_set", "waba_recipient_set.py"))

	def test_members_have_the_fields_the_bulk_insert_writes(self):
		have = {f["fieldname"] for f in MEMBER["fields"]}
		columns = re.search(r'bulk_insert\(\s*"Waba Recipient Set Member",\s*\[([^\]]*)\]', GLUE).group(1)
		written = {c.strip().strip('"') for c in columns.split(",")}
		standard = {"name", "creation", "modified", "owner", "modified_by", "docstatus", "idx"}
		self.assertEqual(written - standard, have)

	def test_the_audience_rule_setting_exists_with_the_rules_choices(self):
		from waba.rules import campaign

		fields = {f["fieldname"]: f for f in load("waba", "doctype", "waba_settings", "waba_settings.json")["fields"]}
		self.assertEqual(fields["campaign_audience_rule"]["options"].split("\n"), list(campaign.RULES))


class TestApi(unittest.TestCase):
	def methods(self):
		return re.findall(r"@frappe\.whitelist\(([^)]*)\)\s*\ndef (\w+)\(", API)

	def test_every_call_is_role_checked(self):
		for _decorator, name in self.methods():
			body = API.split(f"def {name}(")[1].split("\n@frappe.whitelist")[0]
			self.assertTrue(any(x in body for x in ("only_managers()", "_set(", "_campaign(", "_admin_only(")) or name == "can_create_set", name)

	def test_the_write_is_post_only(self):
		decorators = dict((name, deco) for deco, name in self.methods())
		self.assertIn("POST", decorators["create_set"])

	def test_create_applies_the_rules_again_on_the_server(self):
		body = GLUE.split("def create_set(")[1].split("\ndef ")[0]
		self.assertIn("review(doctype, names)", body)
		self.assertIn('result["included"]', body)

	def test_the_review_limits_the_size_of_a_set(self):
		self.assertIn("MAX_SET_SIZE", GLUE.split("def review(")[1].split("\ndef ")[0])

	def test_people_come_from_a_permission_checked_read(self):
		self.assertIn("frappe.get_list(", GLUE.split("def chosen_names(")[1].split("\ndef ")[0])

	def test_phone_order_is_the_records_own(self):
		self.assertIn("parties.phones(", GLUE)


class TestVisibility(unittest.TestCase):
	def test_hooks_register_set_permissions(self):
		for name in ("recipient_set_query_conditions", "recipient_set_member_query_conditions", "recipient_set_has_permission", "recipient_set_member_has_permission"):
			self.assertIn(f"waba.permissions.{name}", HOOKS)
			self.assertIn(f"def {name}(", read("permissions.py"))

	def test_a_set_belongs_to_its_creator_and_waba_admins(self):
		source = read("permissions.py")
		self.assertIn("teams.is_admin(user)", source.split("def _set_condition(")[1])
		self.assertIn("`owner`", source.split("def _set_condition(")[1])


class TestScreens(unittest.TestCase):
	def test_the_list_hook_covers_customer_and_lead(self):
		block = HOOKS.split("doctype_list_js")[-1]
		self.assertIn('"Customer": "public/js/waba_create_set.js"', block)
		self.assertIn('"Lead": "public/js/waba_create_set.js"', block)

	def test_the_list_script_wraps_an_existing_onload(self):
		self.assertIn("const previous = settings.onload", LIST_JS)
		self.assertIn("previous.apply(this, arguments)", LIST_JS)

	def test_the_action_shows_only_to_campaign_roles(self):
		self.assertIn('"Waba Campaign Manager"', LIST_JS)
		self.assertIn("add_actions_menu_item", LIST_JS)

	def test_all_matching_the_filter_is_offered(self):
		self.assertIn("get_filters_for_args", LIST_JS)
		self.assertIn("total_count", LIST_JS)

	def test_screens_call_only_real_methods(self):
		from_js = set(re.findall(r"waba\.api\.campaigns\.(\w+)", LIST_JS + UI_JS + FORM_JS))
		defined = {name for _d, name in re.findall(r"@frappe\.whitelist\(([^)]*)\)\s*\ndef (\w+)\(", API)}
		self.assertTrue(from_js)
		self.assertFalse(from_js - defined, from_js - defined)

	def test_the_dialog_escapes_what_it_draws(self):
		self.assertIn("escape_html", UI_JS)
		# a person's text is never put between tags unescaped (the search string is not drawn, so it is exempt)
		self.assertNotRegex(UI_JS, r">\$\{p\.(name|party|phone|label)\}")

	def test_confirm_asks_before_locking(self):
		self.assertIn("frappe.confirm(", UI_JS)
		self.assertIn("create_set", UI_JS)

	def test_the_set_form_has_copy_and_no_save(self):
		self.assertIn("Copy as new Set", FORM_JS)
		self.assertIn("disable_save", FORM_JS)

	def test_the_ui_file_is_in_the_cache_stamp_and_the_workspace(self):
		self.assertIn("js/waba_sets_ui.js", read("api", "inbox.py"))
		self.assertIn("Waba Recipient Set", read("setup", "workspace_spec.py"))
		self.assertIn("Waba Recipient Set", read("waba", "sidebar", "waba", "waba.json"))


if __name__ == "__main__":
	unittest.main()
