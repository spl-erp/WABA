"""Delivery ticks. Meta reports each outbound message as sent, delivered, read or failed, possibly out of order and
possibly more than once. A message only ever moves forward (Sent -> Delivered -> Read); a failure applies only
while the message has not been delivered. No Frappe import."""

from waba.rules import errors

RANK = {"Queued": 0, "Sent": 1, "Delivered": 2, "Read": 3}
FROM_META = {"sent": "Sent", "delivered": "Delivered", "read": "Read", "failed": "Failed"}


def next_status(current, meta_status):
	"""The status to store after a Meta report, or None when nothing should change."""
	new = FROM_META.get(str(meta_status or "").lower())
	if not new:
		return None
	current = current or "Queued"
	if new == "Failed":
		return "Failed" if current in ("Queued", "Sent") else None
	if current == "Failed":
		return None
	return new if RANK[new] > RANK.get(current, 0) else None


def failure(item):
	"""(code, readable text) from a Meta status item, or (None, None)."""
	items = item.get("errors") if isinstance(item, dict) else None
	if not isinstance(items, list) or not items or not isinstance(items[0], dict):
		return None, None
	first = items[0]
	code = first.get("code")
	detail = (first.get("error_data") or {}).get("details") if isinstance(first.get("error_data"), dict) else None
	meaning = errors.classify(code)[1]
	said = detail or first.get("message") or first.get("title") or ""
	return code, f"{meaning}. Meta said: {said}".strip() if said else meaning
