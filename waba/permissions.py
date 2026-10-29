"""Row-level permissions: Desk lists, reports, links and the inbox all see the same conversations.

Registered in hooks.py as permission_query_conditions (lists) and has_permission (one document). The decision is
waba.rules.visibility; waba.teams reads the people and the tree from the database.
"""

import frappe

from waba import teams
from waba.rules import visibility

NOTHING = "1=0"


def _conversation_condition(scope):
	"""SQL on tabWaba Conversation for what `scope` may see, or "" for everything."""
	if scope.everything:
		return ""
	escape = frappe.db.escape
	parts = []
	if scope.users:
		parts.append("`tabWaba Conversation`.`assigned_to` in ({})".format(", ".join(escape(u) for u in sorted(scope.users))))
	if scope.numbers:
		parts.append("`tabWaba Conversation`.`waba_number` in ({})".format(", ".join(escape(n) for n in sorted(scope.numbers))))
	return "(" + " or ".join(parts) + ")" if parts else NOTHING


def conversation_query_conditions(user=None):
	return _conversation_condition(teams.user_scope(user))


def conversation_has_permission(doc, user=None, permission_type=None):
	scope = teams.user_scope(user)
	return visibility.can_see(scope, doc.get("assigned_to"), doc.get("waba_number"))


def _through_conversation(table, user):
	condition = _conversation_condition(teams.user_scope(user))
	if not condition:
		return ""
	return (
		f"`tab{table}`.`conversation` in (select `name` from `tabWaba Conversation` where {condition})"
	)


def message_query_conditions(user=None):
	return _through_conversation("Waba Message", user or frappe.session.user)


def note_query_conditions(user=None):
	return _through_conversation("Waba Note", user or frappe.session.user)


def message_has_permission(doc, user=None, permission_type=None):
	return _has_through_conversation(doc, user)


def note_has_permission(doc, user=None, permission_type=None):
	return _has_through_conversation(doc, user)


def _has_through_conversation(doc, user):
	if not doc.get("conversation"):
		return True
	row = frappe.db.get_value("Waba Conversation", doc.get("conversation"), ["assigned_to", "waba_number"], as_dict=True)
	if not row:
		return False
	return visibility.can_see(teams.user_scope(user), row.assigned_to, row.waba_number)


def quick_reply_query_conditions(user=None):
	user = user or frappe.session.user
	if teams.is_admin(user):
		return ""
	escape = frappe.db.escape
	mine = [f"`tabWaba Quick Reply`.`scope` = 'Everyone'", f"`tabWaba Quick Reply`.`owner` = {escape(user)}"]
	team_ids = sorted(teams.team_ids_for_quick_replies(user))
	if team_ids:
		mine.append(
			"(`tabWaba Quick Reply`.`scope` = 'Team' and `tabWaba Quick Reply`.`team` in ({}))".format(", ".join(escape(t) for t in team_ids))
		)
	return "(" + " or ".join(mine) + ")"
