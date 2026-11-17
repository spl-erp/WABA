"""Give a conversation to someone, and keep the right people told.

The choice itself is waba.rules.routing.choose_assignee (pure); this module gathers the facts from the database into
its Context, saves the answer with the reason, writes an Event note, and sends the live update only to the people who
may see that conversation (the assignee and the Team Leads above the number, plus administrators). A conversation nobody can
take waits ("waiting_since") for the department's Team Leads and is handed out by `assign_waiting` as people become free.
"""

import frappe
from frappe import _
from frappe.utils import add_to_date, now_datetime

from waba import teams
from waba.rules import purposes, routing, tags, visibility

HOOK_RECORD_OWNER = "waba_record_owner"


# ------------------------------------------------------------------------------------------------ choosing


def build_context(conversation, message_body=""):
	number = frappe.get_doc("Waba Number", conversation.waba_number)
	users = [row.user for row in number.agents]
	enabled = set(frappe.get_all("User", filters={"enabled": 1, "name": ["in", users or [""]]}, pluck="name"))
	open_counts = dict(
		frappe.db.sql(
			"""select assigned_to, count(*) from `tabWaba Conversation`
			where waba_number = %s and status = 'Open' and assigned_to is not null and assigned_to != ''
			group by assigned_to""",
			conversation.waba_number,
		)
	)
	last_assigned = dict(
		frappe.db.sql(
			"""select assigned_to, max(assigned_at) from `tabWaba Conversation`
			where waba_number = %s and assigned_to is not null and assigned_to != '' group by assigned_to""",
			conversation.waba_number,
		)
	)
	agents = [
		routing.Agent(
			user=row.user,
			role=row.role or "Agent",
			available=bool(row.available),
			max_open=row.max_open or 0,
			open_count=open_counts.get(row.user, 0),
			rep_code=row.rep_code or "",
			languages=frozenset(x.strip() for x in (row.languages or "").split(",") if x.strip()),
			last_assigned_at=last_assigned.get(row.user),
		)
		for row in number.agents
		if row.user in enabled
	]
	rules = [routing.Rule(r.rule_type, bool(r.enabled), r.parameter or "") for r in number.routing_rules]
	record_owner, language = _party_facts(conversation)
	return routing.Context(
		number_type=number.number_type or "Shared",
		owner_user=number.owner_user or "",
		default_max_open=number.default_max_open or 0,
		agents=agents,
		rules=rules,
		current_assignee=conversation.assigned_to or "",
		tag=tags.extract_rep_tag(message_body),
		record_owner=record_owner,
		language=language,
	)


def _party_facts(conversation):
	"""(the record's owner, the customer's language) from whatever the extension hooks know; blank when nobody answers.

	A hook function receives (party_doctype, party) and returns a dict with "owner" and/or "language"."""
	if not (conversation.party_doctype and conversation.party):
		return "", ""
	for path in frappe.get_hooks(HOOK_RECORD_OWNER):
		try:
			answer = frappe.get_attr(path)(conversation.party_doctype, conversation.party) or {}
		except Exception:
			frappe.log_error(title="Waba: record owner hook failed")
			continue
		if answer.get("owner") or answer.get("language"):
			return answer.get("owner") or "", answer.get("language") or ""
	return "", ""


def auto_reassign_on():
	"""Waba Settings > "Move a chat to the next available agent when its agent is Away". Off unless someone switches it on."""
	return bool(frappe.db.get_single_value("Waba Settings", "auto_reassign_away"))


def auto_assign_new_on():
	"""Waba Settings > Assign new chats automatically. Off: new chats wait for a Team Lead to assign them."""
	if not frappe.get_meta("Waba Settings").has_field("auto_assign_new_chats"):
		return True  # new code before the migrate: keep the old behaviour, never an error
	value = frappe.db.get_single_value("Waba Settings", "auto_assign_new_chats")
	return True if value is None else bool(int(value))  # a site that never saved the setting keeps the old behaviour


def _assignee_valid(conversation):
	"""The assigned person is an enabled user who still works this conversation's number."""
	user = conversation.assigned_to
	if not user or not frappe.db.get_value("User", user, "enabled"):
		return False
	return bool(frappe.db.exists("Waba Agent Access", {"parent": conversation.waba_number, "parenttype": "Waba Number", "user": user}))


def with_bot(conversation):
	"""A bot is in the middle of this conversation (an Active Waba Bot Session): nobody is assigned and no alert is raised until
	it hands the chat over, finishes or gives up, and then the number's normal routing runs at once."""
	name = conversation if isinstance(conversation, str) else conversation.name
	return bool(frappe.db.exists("Waba Bot Session", {"conversation": name, "status": "Active"}))


def assign(conversation, message_body=""):
	"""Choose and save the assignee when the conversation needs one. Returns the Decision, or None when nothing changed.

	An open conversation whose agent is still available keeps them without any work (Stickiness)."""
	if isinstance(conversation, str):
		conversation = frappe.get_doc("Waba Conversation", conversation)
	if conversation.status == "Done":
		return None
	if not conversation.assigned_to and with_bot(conversation):
		return None  # a bot is talking to the customer; the chat is routed when it ends
	if conversation.held and not conversation.assigned_to:
		return None  # returned to the waiting list on purpose: only a Team Lead hands it on
	if conversation.assigned_to and routing.keep_with_current(conversation.assigned_to, _assignee_valid(conversation), auto_reassign_on()):
		return None  # automatic re-assignment is paused: the chat stays with its agent, Away or not
	if routing.needs_lead(conversation.assigned_to, _assignee_valid(conversation), auto_assign_new_on()):
		# automatic assignment of new chats is off: the chat waits, once, for a Team Lead of the number to hand it on
		if conversation.waiting_since and not conversation.assigned_to:
			return None
		decision = routing.Decision(None, "lead_assign", ("automatic assignment is off",))
		_save(conversation, decision)
		return decision
	number = frappe.db.get_value("Waba Number", conversation.waba_number, [f"purpose_{p}" for p in purposes.PURPOSES] + ["reply_policy"], as_dict=True) or {}
	if not conversation.assigned_to and purposes.replies_go_to_pool({p: number.get(f"purpose_{p}") for p in purposes.PURPOSES}, number.get("reply_policy")):
		# a number kept for notifications or campaigns: a customer's reply waits for a supervisor, not a rep picked by the rules
		decision = routing.Decision(None, "pool", ("reply policy",))
	else:
		decision = routing.choose_assignee(build_context(conversation, message_body))
	if decision.assignee and decision.assignee == conversation.assigned_to:
		return None
	if not decision.assignee and conversation.assigned_to:
		return None  # nobody better is free: it stays with its agent even while they are away
	if not decision.assignee and conversation.waiting_since:
		return None  # still waiting, already recorded
	_save(conversation, decision)
	return decision


def assign_to_team(conversation, team, agent=None):
	"""Give the conversation to a person of `team` (and its sub-teams) who works this number. With `agent` named, that person gets
	it even while Away or full (the admin chose them on purpose); if they can no longer take it (disabled, left the team, not on
	this number) it falls back to the least busy AVAILABLE agent and says why in the chat. Without one, the least busy available
	agent. When nobody is free it waits for a Team Lead, like any chat nobody could take. Returns the Decision. Used by a bot's Assign block."""
	if isinstance(conversation, str):
		conversation = frappe.get_doc("Waba Conversation", conversation)
	parents, members, _numbers = teams.load_tree()
	users = {user for (t, user, _role) in members if t in visibility.subtree(team, parents)} if team in parents else set()
	ctx = build_context(conversation)
	ctx.agents = [a for a in ctx.agents if a.user in users]
	ctx.rules = [routing.Rule(routing.LEAST_BUSY, True)]
	ctx.number_type = "Shared"
	ctx.current_assignee = ""
	if agent and any(a.user == agent for a in ctx.agents):
		decision = routing.Decision(agent, "bot_choice", ("chosen in the bot",))
	else:
		if agent:
			add_event(conversation.name, _("The bot chose {0}, who cannot take this chat now (not active in team {1} on this number). It went to the team instead.").format(_name(agent), team))
		decision = routing.choose_assignee(ctx)
	_save(conversation, decision)
	return decision


REASONS = {
	"sticky": "stayed with the same agent",
	"number_owner": "the number's owner",
	"owner_away_supervisor": "the owner is away, so a supervisor",
	"rep_tag": "the rep code in the message",
	"record_owner": "the owner of the customer's record",
	"language": "speaks the customer's language",
	"least_busy": "the least busy agent",
	"pool": "waiting for an agent",
	"lead_assign": "waiting for a Team Lead to assign it",
	"bot_choice": "chosen in the bot",
}


def reason_text(code):
	return REASONS.get(code, code)


def _save(conversation, decision):
	now = now_datetime()
	if decision.assignee:
		values = {
			"assigned_to": decision.assignee,
			"assigned_at": now,
			"assigned_reason": reason_text(decision.reason),
			"assigned_trail": ", ".join(decision.trail),
			"waiting_since": None,
			"held": 0,
		}
		text = _("Assigned to {0}: {1}.").format(_name(decision.assignee), reason_text(decision.reason))
	else:
		values = {
			"assigned_to": None,
			"assigned_at": None,
			"assigned_reason": reason_text(decision.reason if decision.reason == "lead_assign" else "pool"),
			"assigned_trail": ", ".join(decision.trail),
			"waiting_since": conversation.waiting_since or now,
		}
		if decision.reason == "lead_assign":
			text = _("Waiting for a Team Lead to assign it: automatic assignment of new chats is off.")
		else:
			text = _("Waiting for an agent: nobody was available.")
	frappe.db.set_value("Waba Conversation", conversation.name, values, update_modified=False)
	conversation.update(values)
	add_event(conversation.name, text)



# ------------------------------------------------------------------------------------------------ notes and events


def add_event(conversation, text, user=None):
	_add("Event", conversation, text, user)


def add_note(conversation, text, user=None):
	return _add("Note", conversation, text, user or frappe.session.user)


def _add(kind, conversation, text, user):
	return frappe.get_doc(
		{"doctype": "Waba Note", "conversation": conversation, "kind": kind, "body": text, "user": user}
	).insert(ignore_permissions=True)


def _name(user):
	return frappe.db.get_value("User", user, "full_name") or user


# ------------------------------------------------------------------------------------------------ telling people


def recipients(conversation):
	"""Users who may see this conversation right now: the assignee and everyone who oversees its number."""
	if isinstance(conversation, str):
		conversation = frappe.get_doc("Waba Conversation", conversation)
	people = teams.number_overseers(conversation.waba_number, conversation.assigned_to)
	if conversation.assigned_to:
		people.add(conversation.assigned_to)
	return people


def notify(conversation, kind):
	"""The live update the inbox and the alerts listen to. Content-free (an id and a kind), sent only to people who may
	see the conversation, so someone else's chat never rings in your browser."""
	if isinstance(conversation, str):
		conversation = frappe.get_doc("Waba Conversation", conversation)
	for user in recipients(conversation):
		frappe.publish_realtime(
			"waba_inbox", {"conversation": conversation.name, "kind": kind}, user=user, after_commit=True
		)


# ------------------------------------------------------------------------------------------------ scheduled


def assign_waiting():
	"""Every two minutes: give waiting conversations to whoever has become available or has room again.
	Paused (does nothing) while automatic re-assignment, or automatic assignment of new chats, is switched off in Waba Settings."""
	if not auto_reassign_on() or not auto_assign_new_on():
		return 0
	waiting = frappe.get_all(
		"Waba Conversation",
		filters={"status": "Open", "waiting_since": ["is", "set"], "held": 0},
		fields=["name"],
		order_by="waiting_since asc",
		limit_page_length=200,
	)
	done = 0
	for row in waiting:
		conversation = frappe.get_doc("Waba Conversation", row.name)
		if conversation.assigned_to:
			frappe.db.set_value("Waba Conversation", row.name, "waiting_since", None, update_modified=False)
			continue
		if with_bot(conversation):
			continue
		decision = assign(conversation)
		if decision and decision.assignee:
			notify(conversation, "message")
			done += 1
	if done:
		_commit()
	return done


def alert_unanswered():
	"""Every two minutes: tell the Team Leads who oversee a number about a customer message still waiting for an answer.

	Once per message: `alerted_at` records when the alert for the latest customer message was sent."""
	now = now_datetime()
	sent = 0
	for number in frappe.get_all("Waba Number", filters={"enabled": 1, "unanswered_alert_minutes": [">", 0]}, fields=["name", "unanswered_alert_minutes"]):
		cutoff = add_to_date(now, minutes=-number.unanswered_alert_minutes)
		for c in frappe.get_all(
			"Waba Conversation",
			filters={"waba_number": number.name, "status": "Open", "last_inbound_at": ["<", cutoff]},
			fields=["name", "customer_label", "assigned_to", "last_inbound_at", "alerted_at", "waba_number"],
			limit_page_length=200,
		):
			if c.alerted_at and c.alerted_at >= c.last_inbound_at:
				continue
			if with_bot(c.name):
				continue  # the bot is answering; the alert can come later if nobody has replied once it hands over
			if frappe.db.exists("Waba Message", {"conversation": c.name, "direction": "Out", "sent_at": [">=", c.last_inbound_at]}):
				continue
			for user in teams.number_overseers(c.waba_number, None):
				_notification_log(user, c)
			frappe.db.set_value("Waba Conversation", c.name, "alerted_at", now, update_modified=False)
			sent += 1
	if sent:
		_commit()
	return sent


def _notification_log(user, c):
	who = _name(c.assigned_to) if c.assigned_to else _("nobody yet")
	frappe.get_doc(
		{
			"doctype": "Notification Log",
			"for_user": user,
			"type": "Alert",
			"subject": _("WhatsApp: {0} has waited for an answer (assigned to {1})").format(c.customer_label or c.name, who),
			"document_type": "Waba Conversation",
			"document_name": c.name,
		}
	).insert(ignore_permissions=True)


def _commit():
	"""The scheduled jobs commit their own work (they run outside a request). A check script that wraps them in a savepoint
	sets frappe.flags.waba_no_commit so nothing it creates is kept."""
	if not frappe.flags.get("waba_no_commit"):
		frappe.db.commit()  # nosemgrep
