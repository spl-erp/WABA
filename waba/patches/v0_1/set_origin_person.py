"""Messages sent before the origin tag existed were all typed or clicked by a person: mark them so."""

import frappe


def execute():
	if not frappe.db.has_column("Waba Message", "origin"):
		return
	frappe.db.sql("update `tabWaba Message` set origin = 'Person' where direction = 'Out' and (origin is null or origin = '')")
