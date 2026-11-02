"""What the inbox page asks for: the conversation list, one conversation's messages, and the counts for the tabs.

`_scope()` is the single place that decides WHICH conversations a person may see: the team tree (waba.teams and
waba.rules.visibility), the same rule the Desk lists use (waba.permissions). The write actions at the end (transfer,
done, notes, away) check it too.

The realtime message the page listens to carries only a conversation id, never any content: the page then asks these
functions, which check permission, for what it needs."""

import frappe
from frappe import _
from frappe.query_builder import Criterion, Order
from frappe.query_builder.functions import Count
from frappe.utils import now_datetime

from waba import assignment, permissions, teams
from waba.api.send import SENDERS
from waba.rules import window
from waba.rules.inbound import preview as short_text

VIEWS = ("open", "unread", "triage", "unassigned", "done", "all")
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
	"media_mime",
	"media_filename",
	"media_size",
	"media_status",
	"media_error",
	"voice",
	"latitude",
	"longitude",
	"contacts_json",
	"customer_reaction",
	"our_reaction",
	"retried",
]


@frappe.whitelist()
def assets_version() -> str:
	"""A stamp that changes whenever the inbox's script or style files change. The page puts it on their URLs, so a
	changed file is fetched at once and an unchanged one stays cached. Reveals nothing but a number."""
	import os

	root = os.path.join(frappe.get_app_path("waba"), "public")
	stamp = 0
	for relative in ("js/waba_inbox_lib.js", "js/waba_inbox_app.js", "js/waba_template_dialog.js", "js/waba_notify_ui.js", "js/waba_alerts_core.js", "css/waba_inbox.css"):
		try:
			stamp = max(stamp, int(os.path.getmtime(os.path.join(root, relative))))
		except OSError:
			pass
	return str(stamp)


def _scope():
	"""What the person may see (waba.teams reads the tree). The single place that decides it for the inbox."""
	frappe.only_for(SENDERS)
	return teams.user_scope()


def _visible_term(scope, C):
	"""A query-builder condition for what `scope` may see, or None for everything."""
	if scope.everything:
		return None
	parts = []
	if scope.users:
		parts.append(C.assigned_to.isin(list(scope.users)))
	if scope.numbers:
		parts.append(C.waba_number.isin(list(scope.numbers)))
	return Criterion.any(parts) if parts else (C.name == "")


def _unassigned_term(C):
	return (C.assigned_to.isnull()) | (C.assigned_to == "")


def _view_terms(view, scope, C):
	terms = []
	if view == "unread":
		terms += [C.unread_count > 0]
	elif view == "triage":
		terms += [C.match_state == "Triage", C.status == "Open"]
	elif view == "done":
		terms += [C.status == "Done"]
	elif view == "unassigned":
		terms += [C.status == "Open", _unassigned_term(C)]
		if not scope.everything:
			terms += [C.waba_number.isin(list(scope.lead_numbers) or [""])]
	elif view != "all":
		terms += [C.status == "Open"]
	return terms


def _scope_terms(which, scope, C):
	"""Mine / My team: narrows what the person may see to their own, or to everyone else's."""
	if which == "mine":
		return [C.assigned_to == scope.me]
	if which == "team":
		return [~(C.assigned_to == scope.me) | C.assigned_to.isnull()]
	return []


def _conversation_query(view, scope_name, number=None, search=None):
	scope = _scope()
	C = frappe.qb.DocType("Waba Conversation")
	query = frappe.qb.from_(C)
	for term in [_visible_term(scope, C)] + _view_terms(view if view in VIEWS else "open", scope, C) + _scope_terms(scope_name, scope, C):
		if term is not None:
			query = query.where(term)
	if number:
		query = query.where(C.waba_number == number)
	text = (search or "").strip()
	if text:
		like = f"%{text}%"
		query = query.where(Criterion.any([C.customer_label.like(like), C.customer_phone.like(like), C.last_message_preview.like(like)]))
	return query, C, scope


@frappe.whitelist()
def conversations(view: str = "open", number: str | None = None, search: str | None = None, start: int = 0, limit: int = 30, scope: str = "all"):
	"""{"rows": [...], "has_more": bool}, newest message first."""
	query, C, who = _conversation_query(view, scope, number, search)
	start, limit = max(int(start or 0), 0), min(max(int(limit or 30), 1), 100)
	rows = (
		query.select(*[C[f] for f in LIST_FIELDS])
		.orderby(C.last_message_at, order=Order.desc)
		.orderby(C.creation, order=Order.desc)
		.limit(limit + 1)
		.offset(start)
		.run(as_dict=True)
	)
	rows = [frappe._dict(r) for r in rows]
	has_more = len(rows) > limit
	rows = rows[:limit]
	names = {n.name: n.display_name for n in frappe.get_all("Waba Number", fields=["name", "display_name"])}
	people = {}
	now = now_datetime()
	for row in rows:
		row["number_name"] = names.get(row.waba_number) or row.waba_number
		row["window_open"] = window.is_window_open(row.last_inbound_at, now)
		if row.assigned_to and row.assigned_to not in people:
			people[row.assigned_to] = frappe.db.get_value("User", row.assigned_to, "full_name") or row.assigned_to
		row["assigned_name"] = people.get(row.assigned_to)
	return {"rows": rows, "has_more": has_more}


@frappe.whitelist()
def summary(number: str | None = None, scope: str = "all"):
	"""Counts for the tabs, and what this person's view offers (the Unassigned tab and the Mine / My team switch)."""
	who = _scope()
	counts = {}
	for key, view in (("open", "open"), ("unread", "unread"), ("triage", "triage"), ("unassigned", "unassigned")):
		query, C, _w = _conversation_query(view, scope, number)
		counts[key] = query.select(Count("*")).run()[0][0]
	counts["can_oversee"] = who.is_lead
	counts["available"] = _my_availability(who.me)
	return counts


def _my_availability(user):
	"""True when the person is available on every number they work, None when they work none."""
	rows = frappe.get_all("Waba Agent Access", filters={"user": user}, fields=["available"], parent_doctype="Waba Number")
	return None if not rows else all(r.available for r in rows)


@frappe.whitelist()
def thread(conversation: str, limit: int = 60, before: str | None = None):
	"""One conversation: its header details and the latest `limit` messages (oldest first); `before` (a time) loads older ones."""
	conv = _open(conversation)
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
	notes = _notes(conv.name, rows, before, has_more)

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
			"assigned_to": conv.assigned_to,
			"assigned_name": _full_name(conv.assigned_to),
			"assigned_reason": conv.assigned_reason,
			"waiting": bool(conv.waiting_since) and not conv.assigned_to,
			"can_transfer": _may_manage(conv),
		},
		"messages": rows,
		"notes": notes,
		"has_more": has_more,
	}


def _full_name(user):
	return (frappe.db.get_value("User", user, "full_name") or user) if user else None


def _open(conversation):
	"""The conversation, if this person may see it."""
	frappe.only_for(SENDERS)
	conv = frappe.get_doc("Waba Conversation", conversation)
	if not permissions.conversation_has_permission(conv):
		frappe.throw(_("You may not open this conversation."), frappe.PermissionError)
	return conv


def _may_manage(conv):
	"""May this person hand the conversation to someone else or close it: its assignee, or anyone who oversees it."""
	scope = teams.user_scope()
	if scope.everything or conv.assigned_to == scope.me:
		return True
	return conv.waba_number in scope.lead_numbers or (bool(conv.assigned_to) and conv.assigned_to in scope.users and scope.is_lead)


def _notes(conversation, messages, before, has_more):
	"""Notes and events inside the time span of the messages being shown, so a note never appears without its neighbours."""
	filters = [["Waba Note", "conversation", "=", conversation]]
	if messages and has_more:
		filters.append(["Waba Note", "creation", ">=", messages[0].sent_at])
	if before:
		filters.append(["Waba Note", "creation", "<", before])
	rows = frappe.get_all(
		"Waba Note", filters=filters, fields=["name", "kind", "body", "user", "creation"], order_by="creation asc", limit_page_length=200
	)
	for r in rows:
		r["user_name"] = _full_name(r.user)
	return rows


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


# ------------------------------------------------------------------------------------------------ teamwork


@frappe.whitelist()
def transfer_targets(conversation: str):
	"""The people the conversation may be handed to: the agents of its number (enabled users), with how busy they are."""
	conv = _open(conversation)
	number = frappe.get_doc("Waba Number", conv.waba_number)
	users = [row.user for row in number.agents]
	enabled = set(frappe.get_all("User", filters={"enabled": 1, "name": ["in", users or [""]]}, pluck="name"))
	counts = dict(
		frappe.db.sql(
			"""select assigned_to, count(*) from `tabWaba Conversation`
			where waba_number = %s and status = 'Open' and assigned_to is not null and assigned_to != '' group by assigned_to""",
			conv.waba_number,
		)
	)
	return [
		{
			"user": row.user,
			"full_name": _full_name(row.user),
			"available": bool(row.available),
			"open": counts.get(row.user, 0),
			"is_current": row.user == conv.assigned_to,
		}
		for row in number.agents
		if row.user in enabled
	]


@frappe.whitelist(methods=["POST"])
def transfer(conversation: str, to_user: str, note: str):
	"""Hand the conversation to another agent of the same number, with a note the new person reads."""
	conv = _open(conversation)
	note = (note or "").strip()
	if not note:
		frappe.throw(_("Write a short note for the person who takes over."))
	scope = teams.user_scope()
	if not _may_manage(conv):
		frappe.throw(_("Only the person it is assigned to, or someone who oversees this number, can transfer it."), frappe.PermissionError)
	number = frappe.get_doc("Waba Number", conv.waba_number)
	if number.number_type == "Personal" and not (scope.everything or scope.me == number.owner_user or conv.waba_number in scope.lead_numbers):
		frappe.throw(_("A personal number's conversations are moved only by its owner or a supervisor."), frappe.PermissionError)
	if to_user not in {row.user for row in number.agents} or not frappe.db.get_value("User", to_user, "enabled"):
		frappe.throw(_("{0} does not work this number.").format(_full_name(to_user)))
	if to_user == conv.assigned_to:
		frappe.throw(_("It is already assigned to {0}.").format(_full_name(to_user)))
	before = conv.assigned_to
	now = now_datetime()
	frappe.db.set_value(
		"Waba Conversation",
		conv.name,
		{
			"assigned_to": to_user,
			"assigned_at": now,
			"assigned_reason": _("transferred by {0}").format(_full_name(scope.me)),
			"assigned_trail": "",
			"waiting_since": None,
		},
		update_modified=False,
	)
	conv.reload()
	assignment.add_event(
		conv.name,
		_("Transferred from {0} to {1} by {2}. Note: {3}").format(_full_name(before) or _("nobody"), _full_name(to_user), _full_name(scope.me), note),
	)
	assignment.add_note(conv.name, note)
	assignment.notify(conv, "assigned")
	if before and before != to_user:  # the old assignee's list drops the row
		frappe.publish_realtime("waba_inbox", {"conversation": conv.name, "kind": "assigned"}, user=before, after_commit=True)
	if to_user != scope.me:  # the new person is told (tone and notice), unless they did it themself
		frappe.publish_realtime("waba_inbox", {"conversation": conv.name, "kind": "handed_over"}, user=to_user, after_commit=True)
	return {"ok": True, "assigned_to": to_user, "assigned_name": _full_name(to_user)}


@frappe.whitelist(methods=["POST"])
def set_status(conversation: str, status: str):
	"""Mark a conversation Done, or reopen it. A new customer message reopens it by itself."""
	if status not in ("Open", "Done"):
		frappe.throw(_("Status must be Open or Done."))
	conv = _open(conversation)
	if not _may_manage(conv):
		frappe.throw(_("Only the person it is assigned to, or someone who oversees this number, can do this."), frappe.PermissionError)
	if conv.status == status:
		return {"ok": True, "status": status}
	frappe.db.set_value("Waba Conversation", conv.name, "status", status, update_modified=False)
	who = _full_name(frappe.session.user)
	assignment.add_event(conv.name, (_("Marked done by {0}.") if status == "Done" else _("Reopened by {0}.")).format(who))
	conv.reload()
	assignment.notify(conv, "assigned")
	return {"ok": True, "status": status}


@frappe.whitelist(methods=["POST"])
def add_note(conversation: str, body: str):
	"""An internal note inside the conversation. It is never sent to the customer."""
	conv = _open(conversation)
	body = (body or "").strip()
	if not body:
		frappe.throw(_("Write the note first."))
	if len(body) > 2000:
		frappe.throw(_("A note can be at most 2000 characters."))
	note = assignment.add_note(conv.name, body)
	assignment.notify(conv, "note")
	return {"name": note.name, "kind": "Note", "body": note.body, "user": note.user, "user_name": _full_name(note.user), "creation": note.creation}


@frappe.whitelist()
def quick_replies():
	"""The saved answers this person may use: Everyone's, their team's (and the teams above), and their own."""
	frappe.only_for(SENDERS)
	user = frappe.session.user
	allowed_teams = teams.team_ids_for_quick_replies(user)
	rows = frappe.get_all("Waba Quick Reply", fields=["name", "title", "body", "scope", "team", "language", "owner"], order_by="title asc")
	admin = teams.is_admin(user)
	out = []
	for r in rows:
		if admin or r.scope == "Everyone" or r.owner == user or (r.scope == "Team" and r.team in allowed_teams):
			out.append({k: r[k] for k in ("name", "title", "body", "scope", "language")})
	return out


@frappe.whitelist(methods=["POST"])
def set_available(available: int | str | bool):
	"""Away / available for the person themself, on every number they work. Away people get no new conversations."""
	frappe.only_for(SENDERS)
	flag = 1 if str(available).lower() in ("1", "true", "yes") else 0
	rows = frappe.get_all("Waba Agent Access", filters={"user": frappe.session.user}, pluck="name", parent_doctype="Waba Number")
	for name in rows:
		frappe.db.set_value("Waba Agent Access", name, "available", flag, update_modified=False)
	if flag:
		assignment.assign_waiting()
	return {"available": bool(flag) if rows else None}
