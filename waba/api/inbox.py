"""What the inbox page asks for: the conversation list, one conversation's messages, and the counts for the tabs.

Everything here is read-only and goes through the same permission check as sending. `_visible_filters()` is the single
place that decides WHICH conversations a person may see: today every sender role sees all of them; the per-person
rules (own conversations only, a manager's team through the Sales Person tree) replace it in the routing chunk.

The realtime message the page listens to carries only a conversation id, never any content: the page then asks these
functions, which check permission, for what it needs."""

import frappe
from frappe.utils import now_datetime

from waba.api.send import SENDERS
from waba.rules import window
from waba.rules.inbound import preview as short_text

VIEWS = ("open", "unread", "triage", "done", "all")
LIST_FIELDS = [
	"name",
	"customer_label",
	"customer_phone",
	"customer_bsuid",
	"profile_name",
	"match_state",
	"party_doctype",
	"party",
	"status",
	"unread_count",
	"waba_number",
	"last_message_at",
	"last_message_preview",
	"last_inbound_at",
	"window_expires_at",
	"assigned_to",
]
MESSAGE_FIELDS = [
	"name",
	"direction",
	"message_type",
	"body",
	"status",
	"sent_at",
	"delivered_at",
	"read_at",
	"error_code",
	"error_message",
	"waba_template",
	"sent_by",
	"message_id",
	"reply_to_message_id",
]


@frappe.whitelist()
def assets_version():
	"""A stamp that changes whenever the inbox's script or style files change. The page puts it on their URLs, so a
	changed file is fetched at once and an unchanged one stays cached. Reveals nothing but a number."""
	import os

	root = os.path.join(frappe.get_app_path("waba"), "public")
	stamp = 0
	for relative in ("js/waba_inbox_lib.js", "js/waba_inbox_app.js", "js/waba_alerts_core.js", "css/waba_inbox.css"):
		try:
			stamp = max(stamp, int(os.path.getmtime(os.path.join(root, relative))))
		except OSError:
			pass
	return str(stamp)


def _visible_filters():
	"""Filters limiting the conversations this user may see. Replaced by the per-person rules in the routing chunk."""
	frappe.only_for(SENDERS)
	return {}


def _view_filters(view):
	if view == "unread":
		return {"unread_count": [">", 0]}
	if view == "triage":
		return {"match_state": "Triage", "status": "Open"}
	if view == "done":
		return {"status": "Done"}
	if view == "all":
		return {}
	return {"status": "Open"}


@frappe.whitelist()
def conversations(view="open", number=None, search=None, start=0, limit=30):
	"""{"rows": [...], "has_more": bool}, newest message first."""
	filters = {**_visible_filters(), **_view_filters(view if view in VIEWS else "open")}
	if number:
		filters["waba_number"] = number
	or_filters = None
	text = (search or "").strip()
	if text:
		like = f"%{text}%"
		or_filters = [
			["customer_label", "like", like],
			["customer_phone", "like", like],
			["last_message_preview", "like", like],
		]
	start, limit = max(int(start or 0), 0), min(max(int(limit or 30), 1), 100)
	rows = frappe.get_all(
		"Waba Conversation",
		filters=filters,
		or_filters=or_filters,
		fields=LIST_FIELDS,
		order_by="last_message_at desc, creation desc",
		limit_start=start,
		limit_page_length=limit + 1,
	)
	has_more = len(rows) > limit
	rows = rows[:limit]
	names = {n.name: n.display_name for n in frappe.get_all("Waba Number", fields=["name", "display_name"])}
	now = now_datetime()
	for row in rows:
		row["number_name"] = names.get(row.waba_number) or row.waba_number
		row["window_open"] = window.is_window_open(row.last_inbound_at, now)
	return {"rows": rows, "has_more": has_more}


@frappe.whitelist()
def summary():
	"""Counts for the tabs."""
	base = _visible_filters()
	count = lambda extra: frappe.db.count("Waba Conversation", {**base, **extra})  # noqa: E731
	return {
		"open": count({"status": "Open"}),
		"unread": count({"unread_count": [">", 0]}),
		"triage": count({"match_state": "Triage", "status": "Open"}),
	}


@frappe.whitelist()
def thread(conversation, limit=60, before=None):
	"""One conversation: its header details and the latest `limit` messages (oldest first); `before` (a time) loads older ones."""
	_visible_filters()
	conv = frappe.get_doc("Waba Conversation", conversation)
	if not frappe.db.exists("Waba Conversation", {"name": conv.name, **_visible_filters()}):
		frappe.throw(frappe._("You may not open this conversation."), frappe.PermissionError)
	limit = min(max(int(limit or 60), 1), 200)
	filters = {"conversation": conv.name}
	if before:
		filters["sent_at"] = ["<", before]
	rows = frappe.get_all(
		"Waba Message",
		filters=filters,
		fields=MESSAGE_FIELDS,
		order_by="sent_at desc, creation desc",
		limit_page_length=limit + 1,
	)
	has_more = len(rows) > limit
	rows = list(reversed(rows[:limit]))
	senders = {}
	template_titles = {}
	for row in rows:
		if row.sent_by:
			if row.sent_by not in senders:
				senders[row.sent_by] = frappe.db.get_value("User", row.sent_by, "full_name") or row.sent_by
			row["sent_by_name"] = senders[row.sent_by]
		if row.waba_template:
			if row.waba_template not in template_titles:
				template_titles[row.waba_template] = frappe.db.get_value("Waba Template", row.waba_template, "title")
			row["template_title"] = template_titles[row.waba_template]

	_add_quoted(rows, conv.name, senders)

	now = now_datetime()
	number = frappe.db.get_value("Waba Number", conv.waba_number, ["display_name", "account"], as_dict=True) or {}
	environment = frappe.db.get_value("Waba Account", number.get("account"), "environment") if number.get("account") else None
	return {
		"conversation": {
			"name": conv.name,
			"customer_label": conv.customer_label,
			"customer_phone": conv.customer_phone,
			"customer_bsuid": conv.customer_bsuid,
			"profile_name": conv.profile_name,
			"match_state": conv.match_state,
			"party_doctype": conv.party_doctype,
			"party": conv.party,
			"status": conv.status,
			"unread_count": conv.unread_count,
			"waba_number": conv.waba_number,
			"number_name": number.get("display_name") or conv.waba_number,
			"environment": environment,
			"last_inbound_at": conv.last_inbound_at,
			"window_expires_at": conv.window_expires_at,
			"window_open": window.is_window_open(conv.last_inbound_at, now),
			"seconds_left": window.seconds_left(conv.last_inbound_at, now),
			"can_reply_by_phone": bool(conv.customer_phone),
		},
		"messages": rows,
		"has_more": has_more,
	}


def _add_quoted(rows, conversation, senders):
	"""For a message that answers another one, say what it answers: the quoted text, its direction and who sent it.
	Only messages of the same conversation are looked up; a quoted message we do not hold simply has no preview."""
	wanted = {row.reply_to_message_id for row in rows if row.get("reply_to_message_id")}
	if not wanted:
		return
	quoted = {
		q.message_id: q
		for q in frappe.get_all(
			"Waba Message",
			filters={"conversation": conversation, "message_id": ["in", list(wanted)]},
			fields=["message_id", "body", "direction", "sent_by"],
		)
	}
	for row in rows:
		q = quoted.get(row.get("reply_to_message_id"))
		if not q:
			continue
		row["reply_to_body"] = short_text(q.body)
		row["reply_to_direction"] = q.direction
		if q.sent_by:
			if q.sent_by not in senders:
				senders[q.sent_by] = frappe.db.get_value("User", q.sent_by, "full_name") or q.sent_by
			row["reply_to_sender"] = senders[q.sent_by]
