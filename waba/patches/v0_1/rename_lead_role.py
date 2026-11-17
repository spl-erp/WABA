"""The team role "Lead" is now called "Team Lead" (so it is not mixed up with the CRM Lead). Teams that already hold the old value
are updated; the dropdown no longer offers it. Only Waba Team Member.role changes (the number's Agent list keeps "Supervisor")."""

import frappe


def execute():
	if not frappe.db.table_exists("Waba Team Member"):
		return
	frappe.db.sql("update `tabWaba Team Member` set role = 'Team Lead' where role = 'Lead'")
