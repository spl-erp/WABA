"""Send each thing once: "claim" it, then queue it.

A scheduled or automatic send must never go out twice, even if a worker retries or the server restarts. The pattern:

  1. claim(): one UPDATE that moves the record from "Pending" to "Queued" only if it is still "Pending"; the one worker
     whose update changed a row owns it.
  2. commit, so the claim survives a rollback.
  3. enqueue the job.

Used by notifications and reminders (later chunks) and campaigns."""

import frappe


def claim(doctype, name, status_field="status", from_status="Pending", to_status="Queued"):
	"""True for exactly one caller: the one that moved `name` from `from_status` to `to_status`."""
	table = f"`tab{doctype}`"
	column = f"`{status_field}`"
	frappe.db.sql(f"update {table} set {column} = %s where name = %s and {column} = %s", (to_status, name, from_status))
	return int(frappe.db.sql("select row_count()")[0][0]) == 1


def claim_and_enqueue(doctype, name, method, queue="short", status_field="status", from_status="Pending", to_status="Queued", **kwargs):
	"""Claim, commit, then enqueue `method(doctype=..., name=..., **kwargs)`. Returns False when someone else holds it."""
	if not claim(doctype, name, status_field, from_status, to_status):
		return False
	if not frappe.flags.get("waba_no_commit"):
		frappe.db.commit()  # nosemgrep: the claim must outlive any later rollback
	frappe.enqueue(method, queue=queue, doctype=doctype, name=name, **kwargs)
	return True
