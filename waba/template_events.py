"""Apply Meta's template events (approved, rejected, paused, quality, category) to our template records and tell the admins
when one needs attention. The parsing is in waba.rules.template_events."""

import frappe

from waba.constants import ROLE_ADMIN
from waba.rules import template_events as rules


def _template_for(account, parsed):
	if parsed["id"]:
		name = frappe.db.get_value("Waba Template", {"account": account, "meta_template_id": parsed["id"]}, "name")
		if name:
			return name
	if parsed["name"] and parsed["language"]:
		key = f"{account}|{parsed['name']}|{parsed['language']}"
		if frappe.db.exists("Waba Template", key):
			return key
	return None


def _tell_admins(text, template):
	admins = set(frappe.get_all("Has Role", filters={"role": ROLE_ADMIN, "parenttype": "User"}, pluck="parent"))
	enabled = frappe.get_all("User", filters={"enabled": 1, "name": ["in", list(admins) or [""]]}, pluck="name")
	for user in enabled:
		frappe.get_doc(
			{"doctype": "Notification Log", "for_user": user, "type": "Alert", "subject": text, "document_type": "Waba Template", "document_name": template}
		).insert(ignore_permissions=True)


def apply_changes(payload, account):
	"""Apply every template event of a delivery. Returns a list of plain notes for the event log."""
	notes = []
	for entry in payload.get("entry") or []:
		for change in (entry or {}).get("changes") or []:
			parsed = rules.parse((change or {}).get("field"), (change or {}).get("value"))
			if not parsed:
				continue
			template = _template_for(account, parsed)
			if not template:
				notes.append(f"Template event for {parsed['name'] or parsed['id']} is not in the ERP yet (press Sync templates).")
				continue
			if parsed["updates"]:
				frappe.db.set_value("Waba Template", template, parsed["updates"], update_modified=False)
			if parsed["alert"]:
				_tell_admins(parsed["alert"], template)
			notes.append(f"{parsed['field']}: {template} updated.")
	return notes
