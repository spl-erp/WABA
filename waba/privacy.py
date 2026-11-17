"""The server side of the sensitive-details block: reads the settings, decides who may override, writes the log and the
conversation note, and builds the answer `api.send._deliver` returns when a message is stopped. The detection itself is in
waba.rules.sensitive (pure, tested offline).

Only a message written by a person (origin Person) is checked. Notifications, reminders and campaigns take their values from ERP
records and are not scanned. Nothing here ever stores or logs the raw value: the log and the note hold masked samples only.
"""

import frappe
from frappe import _

from waba import assignment, teams
from waba.rules import purposes
from waba.rules import sensitive as rules

SKIP_FIELD = {code: f"privacy_skip_{code}" for code in rules.ALL}
SUPERVISOR_ROLES = ("Waba Supervisor", "Waba Admin")


def settings():
	"""(enabled types, allowed identifiers), or None when the check is switched off. A missing value means ON."""
	if frappe.db.get_single_value("Waba Settings", "privacy_disabled"):
		return None
	enabled = tuple(code for code in rules.ALL if not frappe.db.get_single_value("Waba Settings", SKIP_FIELD[code]))
	if not enabled:
		return None
	return enabled, rules.parse_allow_list(frappe.db.get_single_value("Waba Settings", "privacy_allow_list"))


def may_override(user=None):
	"""A Team Lead, a Waba Supervisor or a Waba Admin may send a flagged message anyway, with a reason."""
	user = user or frappe.session.user
	scope = teams.user_scope(user)
	return bool(scope.everything or scope.is_lead or set(SUPERVISOR_ROLES) & set(frappe.get_roles(user)))


def _log(ctx, hits, action, reason):
	codes = ", ".join(sorted({h["code"] for h in hits}))
	frappe.get_doc(
		{
			"doctype": "Waba Privacy Log",
			"user": frappe.session.user,
			"action": action,
			"waba_number": ctx.number.name,
			"conversation": ctx.conversation.name,
			"codes": codes,
			"samples": "\n".join(f"{h['label']}: {h['sample']}" for h in hits),
			"reason": reason or None,
		}
	).insert(ignore_permissions=True)
	who = frappe.db.get_value("User", frappe.session.user, "full_name") or frappe.session.user
	text = (
		_("{0} sent a message with {1} anyway. Reason: {2}").format(who, rules.describe(hits), reason)
		if action == "Overridden"
		else _("A message from {0} with {1} was not sent.").format(who, rules.describe(hits))
	)
	assignment.add_event(ctx.conversation.name, text)


def check(ctx, text, origin, override_reason=None):
	"""None when the message may go; otherwise the dict `_deliver` returns instead of sending anything.

	An override (a Team Lead or admin with a non-empty reason) lets it through and is logged."""
	if origin != purposes.PERSON or getattr(ctx, "skip_privacy", False):
		return None
	config = settings()
	if not config:
		return None
	hits = rules.scan(text, *config)
	if not hits:
		return None
	reason = (override_reason or "").strip()
	can_override = may_override()
	if can_override and reason:
		_log(ctx, hits, "Overridden", reason)
		return None
	_log(ctx, hits, "Blocked", None)
	found = rules.describe(hits)
	if can_override:
		error = _("This message looks like it contains {0}. It was not sent. You may send it anyway if you give a reason.").format(found)
	else:
		error = _("Not sent: this message looks like it contains {0}. Please do not share these details on WhatsApp. If they really must be sent, ask a Team Lead.").format(found)
	return {"ok": False, "blocked": True, "can_override": can_override, "found": [{"label": h["label"], "sample": h["sample"]} for h in hits], "error": error}
