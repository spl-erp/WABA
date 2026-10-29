"""Run without a site:  python -m unittest waba.tests.test_doctypes

The configuration doctypes ship as JSON in the app. A wrong spelling or a bad property only shows up at
migrate time on a real site, so check the definitions offline: shape, links, secrets, permissions and
agreement with the pure rules.
"""

import importlib
import json
import os
import unittest

import frappe

from waba.rules import config_validation as cv
from waba.rules import routing

ROOT = os.path.join(os.path.dirname(__file__), "..", "waba", "doctype")
FRAPPE_DOCTYPE_DIR = os.path.join(os.path.dirname(frappe.__file__), "core", "doctype")
CORE_DOCTYPES = {"User", "DocType"}
EXPECTED = {
	"Waba Portfolio", "Waba Meta App", "Waba Account", "Waba Number", "Waba Agent Access", "Waba Routing Rule", "Waba Webhook Event",
	"Waba Identity", "Waba Conversation", "Waba Message", "Waba Template",
}
SECRET_FIELDS = {"Waba Portfolio": {"access_token"}, "Waba Meta App": {"app_secret", "verify_token"}}


def load_all():
	out = {}
	for folder in sorted(os.listdir(ROOT)):
		path = os.path.join(ROOT, folder, f"{folder}.json")
		if os.path.exists(path):
			with open(path, encoding="utf-8") as f:
				definition = json.load(f)
			out[definition["name"]] = (folder, definition)
	return out


def frappe_options(doctype_folder, fieldname):
	with open(os.path.join(FRAPPE_DOCTYPE_DIR, doctype_folder, f"{doctype_folder}.json"), encoding="utf-8") as f:
		fields = {x["fieldname"]: x for x in json.load(f)["fields"]}
	return [o for o in (fields[fieldname].get("options") or "").split("\n") if o]


DOCTYPES = load_all()


def fields_of(name):
	return {f["fieldname"]: f for f in DOCTYPES[name][1]["fields"]}


class TestDefinitions(unittest.TestCase):
	def test_exactly_the_expected_doctypes(self):
		self.assertEqual(set(DOCTYPES), EXPECTED)

	def test_controller_class_names_follow_frappes_rule(self):
		for name, (folder, _def) in DOCTYPES.items():
			module = importlib.import_module(f"waba.waba.doctype.{folder}.{folder}")
			self.assertTrue(hasattr(module, name.replace(" ", "")), f"{name}: class {name.replace(' ', '')} missing")

	def test_shape(self):
		for name, (_folder, d) in DOCTYPES.items():
			self.assertEqual(d["module"], "Waba", name)
			self.assertEqual(d["field_order"], [f["fieldname"] for f in d["fields"]], name)
			names = [f["fieldname"] for f in d["fields"]]
			self.assertEqual(len(names), len(set(names)), f"{name}: duplicate fieldname")
			self.assertNotIn("custom", d, f"{name}: shipped doctypes are standard, not Custom")

	def test_fieldtypes_and_properties_are_known_to_frappe(self):
		valid_types = set(frappe_options("docfield", "fieldtype"))
		with open(os.path.join(FRAPPE_DOCTYPE_DIR, "docfield", "docfield.json"), encoding="utf-8") as f:
			known = {x["fieldname"] for x in json.load(f)["fields"]}
		for name, (_folder, d) in DOCTYPES.items():
			for fld in d["fields"]:
				self.assertIn(fld["fieldtype"], valid_types, f"{name}.{fld['fieldname']}")
				for key in fld:
					self.assertIn(key, known, f"{name}.{fld['fieldname']}: unknown property {key}")

	def test_doctype_level_properties_are_known_to_frappe(self):
		with open(os.path.join(FRAPPE_DOCTYPE_DIR, "doctype", "doctype.json"), encoding="utf-8") as f:
			known = {x["fieldname"] for x in json.load(f)["fields"]}
		standard = {"creation", "modified", "modified_by", "owner", "doctype", "name", "fields", "field_order", "permissions"}
		for name, (_folder, d) in DOCTYPES.items():
			for key in d:
				self.assertTrue(key in known or key in standard, f"{name}: unknown doctype property {key}")
		self.assertIn("By fieldname", frappe_options("doctype", "naming_rule"))

	def test_links_and_tables_point_at_real_doctypes(self):
		for name in DOCTYPES:
			for fld in fields_of(name).values():
				if fld["fieldtype"] in ("Link", "Table"):
					self.assertTrue(
						fld["options"] in DOCTYPES or fld["options"] in CORE_DOCTYPES, f"{name}.{fld['fieldname']}"
					)

	def test_child_tables_are_child_tables_without_own_permissions(self):
		for name in ("Waba Agent Access", "Waba Routing Rule"):
			d = DOCTYPES[name][1]
			self.assertEqual(d["istable"], 1)
			self.assertEqual(d["permissions"], [])
		for name, (_folder, d) in DOCTYPES.items():
			if name not in ("Waba Agent Access", "Waba Routing Rule"):
				self.assertFalse(d.get("istable"), name)

	def test_a_table_field_exists_for_each_child_doctype(self):
		self.assertEqual(fields_of("Waba Number")["agents"]["options"], "Waba Agent Access")
		self.assertEqual(fields_of("Waba Number")["routing_rules"]["options"], "Waba Routing Rule")


class TestSecretsAndPermissions(unittest.TestCase):
	def test_secrets_are_password_fields(self):
		for name, secrets_ in SECRET_FIELDS.items():
			for field in secrets_:
				self.assertEqual(fields_of(name)[field]["fieldtype"], "Password", f"{name}.{field}")

	def test_no_other_field_looks_like_a_secret(self):
		for name in DOCTYPES:
			for fld in fields_of(name).values():
				if fld["fieldtype"] != "Password":
					self.assertFalse(
						any(w in fld["fieldname"] for w in ("secret", "token")) and fld["fieldname"] not in ("verify_token_notes", "token_notes", "token_valid"),
						f"{name}.{fld['fieldname']}",
					)

	def test_secrets_are_only_readable_by_admins(self):
		for name in SECRET_FIELDS:
			roles = {p["role"] for p in DOCTYPES[name][1]["permissions"]}
			self.assertEqual(roles, {"System Manager", "Waba Admin"}, name)

	def test_agents_and_supervisors_cannot_write_configuration(self):
		for name in ("Waba Account", "Waba Number"):
			for perm in DOCTYPES[name][1]["permissions"]:
				if perm["role"] in ("Waba Agent", "Waba Supervisor"):
					self.assertEqual(perm.get("write", 0), 0, f"{name}: {perm['role']}")
					self.assertEqual(perm.get("create", 0), 0)
					self.assertEqual(perm.get("delete", 0), 0)


class TestAgreementWithTheRules(unittest.TestCase):
	def test_routing_rule_options_are_the_engines_rule_types(self):
		options = fields_of("Waba Routing Rule")["rule_type"]["options"].split("\n")
		self.assertEqual(tuple(options), routing.RULE_TYPES)

	def test_agent_role_and_number_type_options(self):
		self.assertEqual(tuple(fields_of("Waba Agent Access")["role"]["options"].split("\n")), cv.AGENT_ROLES)
		self.assertEqual(tuple(fields_of("Waba Number")["number_type"]["options"].split("\n")), cv.NUMBER_TYPES)

	def test_defaults_are_valid_options(self):
		for name in DOCTYPES:
			for fld in fields_of(name).values():
				if fld["fieldtype"] == "Select" and fld.get("default"):
					self.assertIn(fld["default"], fld["options"].split("\n"), f"{name}.{fld['fieldname']}")

	def test_personal_owner_field_only_applies_to_personal_numbers(self):
		owner = fields_of("Waba Number")["owner_user"]
		self.assertIn("Personal", owner["depends_on"])
		self.assertIn("Personal", owner["mandatory_depends_on"])

	def test_the_account_links_the_three_levels(self):
		account = fields_of("Waba Account")
		self.assertEqual(account["portfolio"]["options"], "Waba Portfolio")
		self.assertEqual(account["meta_app"]["options"], "Waba Meta App")
		self.assertEqual(account["waba_id"].get("unique"), 1)
		self.assertEqual(fields_of("Waba Number")["account"]["options"], "Waba Account")
		self.assertEqual(fields_of("Waba Number")["phone_number_id"].get("unique"), 1)

	def test_the_webhook_key_is_unique_and_generated_not_typed(self):
		key = fields_of("Waba Meta App")["webhook_key"]
		self.assertEqual((key.get("unique"), key.get("read_only")), (1, 1))


if __name__ == "__main__":
	unittest.main()
