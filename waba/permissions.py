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
	if scope.lead_numbers:  # nobody has it yet: the Team Leads over the number see it
		parts.append(
			"(ifnull(`tabWaba Conversation`.`assigned_to`, '') = '' and `tabWaba Conversation`.`waba_number` in ({}))".format(
				", ".join(escape(n) for n in sorted(scope.lead_numbers))
			)
		)
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


def _set_condition(user):
	"""A Set (and its people) belongs to whoever made it; Waba Admins see them all."""
	user = user or frappe.session.user
	if teams.is_admin(user):
		return ""
	return f"`tabWaba Recipient Set`.`owner` = {frappe.db.escape(user)}"


def recipient_set_query_conditions(user=None):
	return _set_condition(user)


def recipient_set_has_permission(doc, user=None, permission_type=None):
	user = user or frappe.session.user
	return teams.is_admin(user) or doc.get("owner") == user


def recipient_set_member_query_conditions(user=None):
	user = user or frappe.session.user
	if teams.is_admin(user):
		return ""
	return (
		"`tabWaba Recipient Set Member`.`recipient_set` in "
		f"(select `name` from `tabWaba Recipient Set` where `owner` = {frappe.db.escape(user)})"
	)


def recipient_set_member_has_permission(doc, user=None, permission_type=None):
	user = user or frappe.session.user
	if teams.is_admin(user):
		return True
	return bool(doc.get("recipient_set")) and frappe.db.get_value("Waba Recipient Set", doc.recipient_set, "owner") == user


def _campaign_condition(table, user, column):
	user = user or frappe.session.user
	if teams.is_admin(user):
		return ""
	return f"`tab{table}`.`{column}` = {frappe.db.escape(user)}"


def campaign_query_conditions(user=None):
	"""A campaign belongs to whoever made it; Waba Admins see them all."""
	return _campaign_condition("Waba Campaign", user, "owner")


def campaign_has_permission(doc, user=None, permission_type=None):
	user = user or frappe.session.user
	return teams.is_admin(user) or doc.get("owner") == user


def campaign_recipient_query_conditions(user=None):
	user = user or frappe.session.user
	if teams.is_admin(user):
		return ""
	return (
		"`tabWaba Campaign Recipient`.`campaign` in "
		f"(select `name` from `tabWaba Campaign` where `owner` = {frappe.db.escape(user)})"
	)


def campaign_recipient_has_permission(doc, user=None, permission_type=None):
	user = user or frappe.session.user
	if teams.is_admin(user):
		return True
	return bool(doc.get("campaign")) and frappe.db.get_value("Waba Campaign", doc.campaign, "owner") == user


def number_query_conditions(user=None):
	"""A person sees the Waba Numbers they work or oversee; administrators and System Managers see all."""
	names = teams.number_names(user or frappe.session.user)
	if names is None:
		return ""
	if not names:
		return NOTHING
	return "`tabWaba Number`.`name` in ({})".format(", ".join(frappe.db.escape(n) for n in sorted(names)))


def number_has_permission(doc, user=None, permission_type=None):
	names = teams.number_names(user or frappe.session.user)
	return names is None or doc.get("name") in names


def call_query_conditions(user=None):
	"""Waba Call: the calls of a conversation the person may see, and (for a call from a number nobody knows, which has no conversation) the
	calls of the numbers they oversee as a Team Lead."""
	scope = teams.user_scope(user or frappe.session.user)
	condition = _conversation_condition(scope)
	if not condition:
		return ""
	parts = [f"`tabWaba Call`.`conversation` in (select `name` from `tabWaba Conversation` where {condition})"]
	if scope.lead_numbers:
		parts.append(
			"(ifnull(`tabWaba Call`.`conversation`, '') = '' and `tabWaba Call`.`waba_number` in ({}))".format(", ".join(frappe.db.escape(n) for n in sorted(scope.lead_numbers)))
		)
	return "(" + " or ".join(parts) + ")"


def call_has_permission(doc, user=None, permission_type=None):
	scope = teams.user_scope(user or frappe.session.user)
	if scope.everything:
		return True
	if doc.get("conversation"):
		return _has_through_conversation(doc, user)
	return doc.get("waba_number") in scope.lead_numbers
