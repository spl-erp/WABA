"""The team tree and who may see what, read from the database. The decisions themselves are in waba.rules.visibility."""

import frappe
from frappe import _

from waba.rules import visibility

ADMIN_ROLES = {"System Manager", "Waba Admin"}  # may see every conversation
TOLD_ROLES = {"Waba Admin"}  # ...but only these are also sent the live updates and alerts (every System Manager would be too many)


def reset():
	frappe.local.waba_tree = None


def load_tree():
	"""(parents, members, team_numbers) for the whole tree, read once per request."""
	cached = getattr(frappe.local, "waba_tree", None)
	if cached:
		return cached
	parents = {t.name: t.parent_waba_team or None for t in frappe.get_all("Waba Team", fields=["name", "parent_waba_team"])}
	members = [
		(m.parent, m.user, m.role or visibility.AGENT)
		for m in frappe.get_all("Waba Team Member", fields=["parent", "user", "role"], parent_doctype="Waba Team", order_by="idx")
		if m.parent in parents
	]
	team_numbers = {}
	for n in frappe.get_all("Waba Team Number", fields=["parent", "waba_number"], parent_doctype="Waba Team", order_by="idx"):
		if n.parent in parents:
			team_numbers.setdefault(n.parent, []).append(n.waba_number)
	frappe.local.waba_tree = (parents, members, team_numbers)
	return frappe.local.waba_tree


def is_admin(user):
	return user == "Administrator" or bool(ADMIN_ROLES & set(frappe.get_roles(user)))


def user_scope(user=None):
	user = user or frappe.session.user
	parents, members, team_numbers = load_tree()
	agent_numbers = frappe.get_all("Waba Agent Access", filters={"user": user}, pluck="parent", parent_doctype="Waba Number")
	number_visibility = {}
	if agent_numbers:
		number_visibility = dict(
			frappe.get_all("Waba Number", filters={"name": ["in", agent_numbers]}, fields=["name", "visibility_mode"], as_list=True)
		)
	return visibility.visible_scope(
		user,
		everyone=is_admin(user),
		parents=parents,
		members=members,
		team_numbers=team_numbers,
		agent_numbers=agent_numbers,
		number_visibility=number_visibility,
	)


def team_ids_for_quick_replies(user):
	"""Teams whose "Team" quick replies this person may use: their own teams and every team above them."""
	parents, members, _numbers = load_tree()
	found = set()
	for team, member, _role in members:
		if member == user:
			found.update(visibility.ancestors(team, parents))
	return found


def number_overseers(number, assigned_to=None):
	"""Users to tell about a conversation on `number` (besides its assignee): the Leads above it, and Waba Admins."""
	parents, members, team_numbers = load_tree()
	people = visibility.overseers(assigned_to, number, parents=parents, members=members, team_numbers=team_numbers)
	admins = {
		u
		for u in frappe.get_all("Has Role", filters={"role": ["in", list(TOLD_ROLES)], "parenttype": "User"}, pluck="parent")
		if u != "Administrator"
	}
	enabled = set(frappe.get_all("User", filters={"enabled": 1, "name": ["in", list(people | admins) or [""]]}, pluck="name"))
	return (people | admins) & (enabled - {assigned_to})


def validate_team(team):
	parents = {t.name: t.parent_waba_team for t in frappe.get_all("Waba Team", fields=["name", "parent_waba_team"])}
	if not team.parent_waba_team:
		others = [name for name, parent in parents.items() if not parent and name != team.name]
		if others:
			frappe.throw(_("{0} is already the top level. Choose a parent team for {1}.").format(others[0], team.team_name))
	elif team.parent_waba_team == team.name:
		frappe.throw(_("A team cannot be its own parent."))
	seen_users = set()
	for member in team.members:
		if member.user in seen_users:
			frappe.throw(_("{0} is listed twice in {1}.").format(member.user, team.team_name))
		seen_users.add(member.user)
	own = [n.waba_number for n in team.numbers]
	if len(own) != len(set(own)):
		frappe.throw(_("A number is listed twice in {0}.").format(team.team_name))
	for number in own:
		taken = frappe.db.get_value(
			"Waba Team Number", {"waba_number": number, "parenttype": "Waba Team", "parent": ["!=", team.name]}, "parent"
		)
		if taken:
			frappe.throw(_("{0} already belongs to the team {1}. A number is owned by one team.").format(number, taken))
