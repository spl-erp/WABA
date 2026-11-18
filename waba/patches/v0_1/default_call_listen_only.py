"""Waba Settings > Allow calls without a microphone (listen only) is ON by default. A new Check on a Single doctype has no stored row until
someone saves the form, so it reads as off: store the default once (only when nobody has chosen yet)."""

import frappe


def execute():
	if not frappe.get_meta("Waba Settings").has_field("call_listen_only"):
		return
	if not frappe.db.sql("select 1 from `tabSingles` where `doctype` = 'Waba Settings' and `field` = 'call_listen_only'"):
		frappe.db.set_single_value("Waba Settings", "call_listen_only", 1)
