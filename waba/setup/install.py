"""Created on install and on every migrate, never by hand in the Desk: the three roles and the Waba workspace.
Idempotent: each step creates only what is missing and never edits what a site has changed."""

import json

import frappe

from waba.constants import ROLE_ADMIN, ROLE_AGENT, ROLE_SUPERVISOR
from waba.setup import workspace_spec as spec

ROLES = (ROLE_ADMIN, ROLE_SUPERVISOR, ROLE_AGENT)


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
	if new_shortcuts or links_changed or blocks:
		doc.save(ignore_permissions=True)


def execute():
	ensure_roles()
	ensure_workspace()
