"""Give a conversation to someone, and keep the right people told.

The choice itself is waba.rules.routing.choose_assignee (pure); this module gathers the facts from the database into
its Context, saves the answer with the reason, writes an Event note, and sends the live update only to the people who
may see that conversation (the assignee and the Leads above the number, plus administrators). A conversation nobody can
take waits ("waiting_since") for the department's Leads and is handed out by `assign_waiting` as people become free.
"""

import frappe
from frappe import _
from frappe.utils import add_to_date, now_datetime

from waba import teams
from waba.rules import purposes, routing, tags

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


def assign(conversation, message_body=""):
	"""Choose and save the assignee when the conversation needs one. Returns the Decision, or None when nothing changed.

	An open conversation whose agent is still available keeps them without any work (Stickiness)."""
	if isinstance(conversation, str):
		conversation = frappe.get_doc("Waba Conversation", conversation)
	if conversation.status == "Done":
		return None
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


REASONS = {
	"sticky": "stayed with the same agent",
	"number_owner": "the number's owner",
	"owner_away_supervisor": "the owner is away, so a supervisor",
	"rep_tag": "the rep code in the message",
	"record_owner": "the owner of the customer's record",
	"language": "speaks the customer's language",
	"least_busy": "the least busy agent",
	"pool": "waiting for an agent",
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
		}
		text = _("Assigned to {0}: {1}.").format(_name(decision.assignee), reason_text(decision.reason))
	else:
		values = {
			"assigned_to": None,
			"assigned_at": None,
			"assigned_reason": reason_text("pool"),
			"assigned_trail": ", ".join(decision.trail),
			"waiting_since": conversation.waiting_since or now,
		}
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
	"""Every two minutes: give waiting conversations to whoever has become available or has room again."""
	waiting = frappe.get_all(
		"Waba Conversation",
		filters={"status": "Open", "waiting_since": ["is", "set"]},
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
		decision = assign(conversation)
		if decision and decision.assignee:
			notify(conversation, "message")
			done += 1
	if done:
		_commit()
	return done


def alert_unanswered():
	"""Every two minutes: tell the Leads who oversee a number about a customer message still waiting for an answer.

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
