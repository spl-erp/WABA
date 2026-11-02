"""'Remind me' on a conversation: a date and time that wakes the chat for its person.

A reminder belongs to the person who set it. When it falls due (the two-minute job) it is claimed exactly once, an Event is
written in the chat, the person (and the chat's current assignee, if someone else) get a notification, the chat is reopened if
it was done, and the open inbox refreshes. It never sends anything to a customer.
"""

import frappe
from frappe import _
from frappe.utils import get_datetime, now_datetime

from waba import assignment, claims, permissions
from waba.api.send import SENDERS
from waba.rules import reminders as rules

DOCTYPE = "Waba Reminder"


def _commit():
	if not frappe.flags.get("waba_no_commit"):
		frappe.db.commit()  # nosemgrep


def _conversation(name):
	frappe.only_for(SENDERS)
	conv = frappe.get_doc("Waba Conversation", name)
	if not permissions.conversation_has_permission(conv):
		frappe.throw(_("You may not open this conversation."), frappe.PermissionError)
	return conv


def _mine(name):
	row = frappe.get_doc(DOCTYPE, name)
	if row.user != frappe.session.user and not frappe.db.exists("Has Role", {"parent": frappe.session.user, "role": ["in", ["System Manager", "Waba Admin"]]}):
		frappe.throw(_("This is not your reminder."), frappe.PermissionError)
	return row


@frappe.whitelist(methods=["POST"])
def remind(conversation: str, remind_at: str, note: str = ""):
	"""Set a reminder for yourself on a conversation you may open."""
	conv = _conversation(conversation)
	when = get_datetime(remind_at) if remind_at else None
	ok, message = rules.check_remind_at(when, now_datetime())
	if not ok:
		frappe.throw(_(message))
	row = frappe.get_doc({"doctype": DOCTYPE, "conversation": conv.name, "user": frappe.session.user, "remind_at": when, "note": rules.clean_note(note), "status": rules.PENDING}).insert(ignore_permissions=True)
	_commit()
	return {"ok": True, "reminder": row.name}


@frappe.whitelist()
def my_reminders(view: str = "open"):
	"""Your reminders: 'open' (waiting or fired but not done), or 'done'."""
	frappe.only_for(SENDERS)
	states = [rules.DONE, rules.CANCELLED] if view == "done" else [rules.PENDING, rules.FIRED]
	rows = frappe.get_all(DOCTYPE, filters={"user": frappe.session.user, "status": ["in", states]}, fields=["name", "conversation", "status", "remind_at", "note", "fired_at"], order_by="remind_at asc", limit_page_length=100)
	out = []
	for r in rows:
		conv = frappe.db.get_value("Waba Conversation", r.conversation, ["customer_label", "waba_number", "assigned_to", "party_doctype", "party"], as_dict=True)
		if not conv or not permissions.conversation_has_permission(frappe._dict(conv, name=r.conversation)):
			continue
		r["customer"] = conv.customer_label
		r["due"] = r.status == rules.FIRED or (r.remind_at <= now_datetime())
		out.append(r)
	return out


@frappe.whitelist(methods=["POST"])
def done_reminder(reminder: str):
	frappe.only_for(SENDERS)
	row = _mine(reminder)
	new = rules.status_after("done", row.status)
	if not new:
		frappe.throw(_("This reminder is already finished."))
	frappe.db.set_value(DOCTYPE, row.name, "status", new, update_modified=False)
	_commit()
	return {"ok": True}


@frappe.whitelist(methods=["POST"])
def cancel_reminder(reminder: str):
	frappe.only_for(SENDERS)
	row = _mine(reminder)
	new = rules.status_after("cancel", row.status)
	if not new:
		frappe.throw(_("Only a waiting reminder can be cancelled."))
	frappe.db.set_value(DOCTYPE, row.name, "status", new, update_modified=False)
	_commit()
	return {"ok": True}


def fire_due():
	"""Every two minutes: fire each due reminder exactly once. Returns how many fired."""
	now = now_datetime()
	fired = 0
	for row in frappe.get_all(DOCTYPE, filters={"status": rules.PENDING, "remind_at": ["<=", now]}, fields=["name", "conversation", "user", "note"], order_by="remind_at asc", limit_page_length=200):
		if not claims.claim(DOCTYPE, row.name, "status", rules.PENDING, rules.FIRED):
			continue
		frappe.db.set_value(DOCTYPE, row.name, "fired_at", now, update_modified=False)
		conv = frappe.db.get_value("Waba Conversation", row.conversation, ["name", "customer_label", "assigned_to", "status"], as_dict=True)
		if not conv:
			continue
		if conv.status == "Done":
			frappe.db.set_value("Waba Conversation", conv.name, "status", "Open", update_modified=False)
		text = rules.subject(conv.customer_label, row.note)
		assignment.add_event(conv.name, _("Reminder from {0}: {1}").format(frappe.utils.get_fullname(row.user), row.note or _("look at this chat")))
		enabled = set(frappe.get_all("User", filters={"enabled": 1, "name": ["in", [u for u in (row.user, conv.assigned_to) if u] or [""]]}, pluck="name"))
		for user in rules.recipients(row.user, conv.assigned_to, enabled):
			frappe.get_doc({"doctype": "Notification Log", "for_user": user, "type": "Alert", "subject": text, "document_type": "Waba Conversation", "document_name": conv.name}).insert(ignore_permissions=True)
		assignment.notify(conv.name, "reminder")
		fired += 1
	if fired:
		_commit()
	return fired
