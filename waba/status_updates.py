"""Apply Meta's delivery reports (sent, delivered, read, failed) to the outgoing messages they are about.

A report can arrive before the ERP has saved the message id Meta just returned (the webhook and the send race each
other). Such reports are returned as `waiting` and retried by waba.api.webhook.retry_waiting; a report about a message
the ERP never sent is dropped after an hour."""

import datetime

import frappe
from frappe.utils import convert_utc_to_system_timezone

from waba.rules import statuses


def apply_statuses(value):
	"""{"updated": n, "unchanged": n, "waiting": [ids]} for a `messages` change value."""
	result = {"updated": 0, "unchanged": 0, "waiting": []}
	for item in value.get("statuses") or []:
		if not isinstance(item, dict) or not item.get("id"):
			continue
		name = frappe.db.get_value("Waba Message", {"message_id": str(item["id"]), "direction": "Out"}, "name")
		if not name:
			result["waiting"].append(str(item["id"]))
			continue
		current = frappe.db.get_value("Waba Message", name, "status")
		new = statuses.next_status(current, item.get("status"))
		if not new:
			result["unchanged"] += 1
			continue
		values = {"status": new}
		when = _when(item.get("timestamp"))
		if new == "Delivered":
			values["delivered_at"] = when
		elif new == "Read":
			values["read_at"] = when
			values["delivered_at"] = frappe.db.get_value("Waba Message", name, "delivered_at") or when
		elif new == "Failed":
			code, text = statuses.failure(item)
			values.update({"error_code": str(code or ""), "error_message": text})
		frappe.db.set_value("Waba Message", name, values, update_modified=False)
		result["updated"] += 1
		frappe.publish_realtime(
			"waba_inbox",
			{"conversation": frappe.db.get_value("Waba Message", name, "conversation"), "kind": "status"},
			after_commit=True,
		)
	return result


def _when(epoch):
	try:
		return convert_utc_to_system_timezone(
			datetime.datetime.fromtimestamp(int(epoch), tz=datetime.timezone.utc)
		).replace(tzinfo=None)
	except (TypeError, ValueError):
		return frappe.utils.now_datetime()
