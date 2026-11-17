"""Created on install and on every migrate, never by hand in the Desk: the three roles and the Waba workspace.
Idempotent: each step creates only what is missing and never edits what a site has changed."""

import json

import frappe

from waba.constants import ROLE_ADMIN, ROLE_AGENT, ROLE_CAMPAIGN, ROLE_SUPERVISOR
from waba.setup import workspace_spec as spec

ROLES = (ROLE_ADMIN, ROLE_SUPERVISOR, ROLE_AGENT, ROLE_CAMPAIGN)


def ensure_roles():
	for role in ROLES:
		if not frappe.db.exists("Role", role):
			frappe.get_doc({"doctype": "Role", "role_name": role, "desk_access": 1}).insert(ignore_permissions=True)


def ensure_workspace():
	if not frappe.db.exists("Module Def", spec.MODULE):
		return
	if frappe.db.exists("Workspace", spec.WORKSPACE):
		return _add_missing_to_workspace()
	frappe.get_doc(
		{
			"doctype": "Workspace",
			"name": spec.WORKSPACE,
			"label": spec.WORKSPACE,
			"title": spec.WORKSPACE,
			"module": spec.MODULE,
			"public": 1,
			"is_hidden": 0,
			"icon": "chat",
			"sequence_id": 90,
			"content": spec.content(),
			"links": spec.link_rows(),
			"shortcuts": spec.shortcut_rows(),
			"roles": [{"role": r} for r in spec.VIEWER_ROLES],
		}
	).insert(ignore_permissions=True)


def _add_missing_to_workspace():
	"""A later chunk adds a doctype to the spec; add its shortcut and card to the existing workspace without
	touching anything a site has changed there."""
	doc = frappe.get_doc("Workspace", spec.WORKSPACE)
	have_shortcuts = {r.label for r in doc.shortcuts}
	new_shortcuts = [r for r in spec.shortcut_rows() if r["label"] not in have_shortcuts]
	fields = ("type", "label", "link_type", "link_to", "description", "hidden", "onboard")
	merged = spec.merge_links([{f: r.get(f) for f in fields} for r in doc.links], spec.link_rows())
	links_changed = len(merged) != len(doc.links)
	for row in new_shortcuts:
		doc.append("shortcuts", row)
	if links_changed:
		doc.set("links", merged)
	shortcut_labels = {r.label for r in doc.shortcuts}
	card_labels = {r["label"] for r in merged if r["type"] == "Card Break"}
	blocks = spec.missing_blocks(doc.content, shortcut_labels, card_labels)
	if blocks:
		body = json.loads(doc.content)
		doc.content = json.dumps(body + blocks)
	have_roles = {r.role for r in doc.roles}
	new_roles = [role for role in spec.VIEWER_ROLES if role not in have_roles and frappe.db.exists("Role", role)]
	for role in new_roles:
		doc.append("roles", {"role": role})
	if new_shortcuts or links_changed or blocks or new_roles:
		doc.save(ignore_permissions=True)


PARTY_DOCTYPES = ("Lead", "Contact", "Customer")


def party_fields():
	"""The consent record Waba keeps on a Lead, Contact and Customer. Read-only on the form: it changes only through
	waba.api.party.record_consent (which checks permission and leaves a comment) and the customer's own STOP / START."""
	return [
		{"fieldname": "waba_section", "fieldtype": "Section Break", "label": "WhatsApp", "collapsible": 1},
		{"fieldname": "waba_consent", "fieldtype": "Select", "label": "WhatsApp Consent", "options": "Unknown\nYes\nNo", "default": "Unknown", "read_only": 1, "no_copy": 1,
		 "description": "May the business start a WhatsApp conversation with this person?"},
		{"fieldname": "waba_consent_on", "fieldtype": "Date", "label": "Consent Date", "read_only": 1, "no_copy": 1},
		{"fieldname": "waba_consent_source", "fieldtype": "Data", "label": "Consent Source", "read_only": 1, "no_copy": 1,
		 "description": "Where the agreement came from, for example an IndiaMART enquiry or a verbal yes."},
		{"fieldname": "waba_marketing_consent", "fieldtype": "Select", "label": "WhatsApp Marketing Consent", "options": "Unknown\nYes\nNo", "default": "Unknown", "read_only": 1, "no_copy": 1,
		 "description": "A separate agreement for promotions and offers. Service and order messages do not need it."},
		{"fieldname": "waba_marketing_consent_on", "fieldtype": "Date", "label": "Marketing Consent Date", "read_only": 1, "no_copy": 1},
		{"fieldname": "waba_marketing_consent_source", "fieldtype": "Data", "label": "Marketing Consent Source", "read_only": 1, "no_copy": 1},
	]


def ensure_party_fields():
	"""Custom fields on the customer records. Only for doctypes this site has; idempotent."""
	from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

	fields = {dt: party_fields() for dt in PARTY_DOCTYPES if frappe.db.exists("DocType", dt)}
	if fields:
		create_custom_fields(fields, ignore_validate=True)


def execute():
	ensure_roles()
	ensure_workspace()
	ensure_party_fields()
