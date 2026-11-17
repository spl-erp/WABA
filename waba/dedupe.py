"""Stops one send being made twice. A phone on a bad network may time out and the person taps Send again; if the app gives both
attempts the same `client_key`, the second one gets the first one's answer and nothing more is sent. Only a send that worked is
remembered, so a refused or failed one can be tried again."""

import frappe
from frappe import _

from waba import locks
from waba.rules import mobile as rules


def once(conversation, client_key, send):
	"""Run `send()` unless this person already sent with this key in the last few minutes; then return the earlier answer."""
	ok, key = rules.clean_client_key(client_key)
	if not ok:
		frappe.throw(_("The send key must be 8 to 64 letters, digits or - _ . :"))
	if not key:
		return send()
	cache = frappe.cache() if callable(frappe.cache) else frappe.cache
	cache_key = rules.duplicate_cache_key(frappe.session.user, conversation, key)
	with locks.conversation(f"send|{conversation}|{key}"):
		earlier = cache.get_value(cache_key)
		if earlier:
			return {**earlier, "duplicate": True}
		result = send()
		if isinstance(result, dict) and result.get("ok"):
			cache.set_value(cache_key, {"ok": True, "message": result.get("message"), "message_id": result.get("message_id")}, expires_in_sec=rules.DUPLICATE_SECONDS)
		return result
