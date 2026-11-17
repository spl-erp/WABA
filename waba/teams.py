"""The team tree and who may see what, read from the database. The decisions themselves are in waba.rules.visibility."""

import frappe
from frappe import _

from waba.rules import team_setup, visibility
from waba.rules.tags import is_valid_code

ADMIN_ROLES = {"Waba Admin"}  # may see every conversation and does the whole setup; System Manager alone no longer reads chats
TOLD_ROLES = {"Waba Admin"}  # these are also sent the live updates and alerts
WABA_ROLES = ("Waba Agent", "Waba Supervisor")  # given and taken away by the teams once "Apply" has been pressed


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


def has_waba_role(user):
	"""Does this person hold a Waba role (the one thing that lets them use the inbox)?"""
	return user == "Administrator" or bool({"Waba Agent", "Waba Supervisor", "Waba Admin"} & set(frappe.get_roles(user)))


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


def number_names(user=None):
	"""The Waba Number names this person may see, or None for every number (an administrator or System Manager)."""
	user = user or frappe.session.user
	if is_admin(user) or "System Manager" in frappe.get_roles(user):
		return None
	scope = user_scope(user)
	agent_numbers = frappe.get_all("Waba Agent Access", filters={"user": user}, pluck="parent", parent_doctype="Waba Number")
	every = frappe.get_all("Waba Number", pluck="name")
	return set(visibility.visible_numbers(scope, agent_numbers, every))


def team_ids_for_quick_replies(user):
	"""Teams whose "Team" quick replies this person may use: their own teams and every team above them."""
	parents, members, _numbers = load_tree()
	found = set()
	for team, member, _role in members:
		if member == user:
			found.update(visibility.ancestors(team, parents))
	return found


def number_overseers(number, assigned_to=None):
	"""Users to tell about a conversation on `number` (besides its assignee): the Team Leads above it, and Waba Admins."""
	parents, members, team_numbers = load_tree()
	people = visibility.overseers(assigned_to, number, parents=parents, members=members, team_numbers=team_numbers)
	admins = {
		u
		for u in frappe.get_all("Has Role", filters={"role": ["in", list(TOLD_ROLES)], "parenttype": "User"}, pluck="parent")
		if u != "Administrator"
	}
	enabled = set(frappe.get_all("User", filters={"enabled": 1, "name": ["in", list(people | admins) or [""]]}, pluck="name"))
	return (people | admins) & (enabled - {assigned_to})


def managed():
	"""True once the teams run the Agent lists and the Waba roles (the admin pressed Apply on a clean Setup check)."""
	return bool(frappe.db.get_single_value("Waba Settings", "teams_manage_agents"))


def _lead_of(user, team, parents, members):
	"""May `user` edit `team`: a Team Lead of it or of a team above it."""
	chain = set(visibility.ancestors(team, parents))
	return any(m == user and role == visibility.LEAD and t in chain for t, m, role in members)


def may_edit_team(team, user=None):
	user = user or frappe.session.user
	if is_admin(user):
		return True
	parents, members, _numbers = load_tree()
	return _lead_of(user, team, parents, members)


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
		elsewhere = frappe.db.get_value("Waba Team Member", {"user": member.user, "parenttype": "Waba Team", "parent": ["!=", team.name]}, "parent")
		if elsewhere:
			frappe.throw(_("{0} is already in the team {1}. A person belongs to one team.").format(member.user, elsewhere))
		if int(member.max_open or 0) < 0:
			frappe.throw(_("{0}: maximum open conversations cannot be negative.").format(member.user))
	codes = {}
	for member in team.members:
		code = (member.rep_code or "").strip()
		if not code:
			continue
		if not is_valid_code(code):
			frappe.throw(_("{0}: a rep code is 1 to 20 letters, digits, _ or -.").format(member.user))
		taken = codes.get(code.lower()) or frappe.db.get_value(
			"Waba Team Member", {"rep_code": code, "parenttype": "Waba Team", "user": ["!=", member.user]}, "user"
		)
		if taken:
			frappe.throw(_("The rep code {0} is already used by {1}.").format(code, taken))
		codes[code.lower()] = member.user
	own = [n.waba_number for n in team.numbers]
	if len(own) != len(set(own)):
		frappe.throw(_("A number is listed twice in {0}.").format(team.team_name))

	if not is_admin(frappe.session.user) and frappe.session.user != "Administrator":
		before = team.get_doc_before_save()
		if not before:
			frappe.throw(_("Only a Waba Admin creates teams."), frappe.PermissionError)
		if (before.parent_waba_team or None) != (team.parent_waba_team or None) or sorted(n.waba_number for n in before.numbers) != sorted(own):
			frappe.throw(_("Only a Waba Admin changes a team's numbers or where it sits in the tree."), frappe.PermissionError)
		if not may_edit_team(team.name):
			frappe.throw(_("You can change only the teams you lead."), frappe.PermissionError)


def has_team_permission(doc, ptype=None, user=None):
	"""Waba Team: everyone with a Waba role reads; a Team Lead writes the teams of their own branch (Waba Admin everything)."""
	user = user or frappe.session.user
	if ptype in ("create", "delete"):
		return is_admin(user)
	if ptype in ("write", "submit", "cancel"):
		return may_edit_team(doc if isinstance(doc, str) else doc.name, user)
	return True


# --- the teams run the Agent lists and the roles (after Apply) ------------------------------------------------------


def member_settings():
	return {
		m.user: {"max_open": m.max_open, "rep_code": m.rep_code, "languages": m.languages, "may_send_templates": m.may_send_templates}
		for m in frappe.get_all("Waba Team Member", fields=["user", "max_open", "rep_code", "languages", "may_send_templates"], parent_doctype="Waba Team")
	}


def used_numbers():
	_parents, _members, team_numbers = load_tree()
	return sorted({n for numbers in team_numbers.values() for n in numbers if frappe.db.exists("Waba Number", n)})


def derived_agents(number):
	"""The Agent list the teams give `number` (the runtime Available flags are kept)."""
	reset()
	parents, members, team_numbers = load_tree()
	existing = {
		r.user: bool(r.available)
		for r in frappe.get_all("Waba Agent Access", filters={"parent": number}, fields=["user", "available"], parent_doctype="Waba Number")
	}
	return team_setup.derive_agents(number, parents=parents, members=members, team_numbers=team_numbers, settings=member_settings(), existing=existing)


def sync_number_agents(number):
	"""Rewrite the Agent list of `number` from the teams. Returns the number of people. Written straight to the table, so the
	Number's own checks do not run (they would refuse a half-finished setup)."""
	rows = derived_agents(number)
	frappe.db.delete("Waba Agent Access", {"parent": number, "parenttype": "Waba Number"})
	for idx, row in enumerate(rows, start=1):
		frappe.get_doc(
			{"doctype": "Waba Agent Access", "parent": number, "parenttype": "Waba Number", "parentfield": "agents", "idx": idx, **row}
		).db_insert()
	return len(rows)


def sync_roles():
	"""Give every team member the Waba role their team role implies; take Waba Agent / Supervisor from people who are in no
	team (never touches Waba Admin holders). Returns (added, removed)."""
	reset()
	_parents, members, _numbers = load_tree()
	wanted = team_setup.wanted_roles(members)
	added = removed = 0
	for user, role in wanted.items():
		have = set(frappe.get_all("Has Role", filters={"parent": user, "parenttype": "User"}, pluck="role"))
		for need in (role,):
			if need not in have:
				frappe.get_doc({"doctype": "Has Role", "parent": user, "parenttype": "User", "parentfield": "roles", "role": need}).insert(ignore_permissions=True)
				added += 1
		frappe.clear_cache(user=user)
	holders = set(frappe.get_all("Has Role", filters={"role": ["in", list(WABA_ROLES)], "parenttype": "User"}, pluck="parent"))
	for user in holders - set(wanted):
		if user == "Administrator" or "Waba Admin" in frappe.get_roles(user):
			continue
		frappe.db.delete("Has Role", {"parent": user, "parenttype": "User", "role": ["in", list(WABA_ROLES)]})
		frappe.clear_cache(user=user)
		removed += 1
	return added, removed


def sync_all():
	"""Roles and every used number's Agent list. Called when a team changes, once the teams run things."""
	roles = sync_roles()
	people = {n: sync_number_agents(n) for n in used_numbers()}
	return {"roles_added": roles[0], "roles_removed": roles[1], "numbers": people}


def setup_problems():
	reset()
	parents, members, team_numbers = load_tree()
	numbers = frappe.get_all("Waba Number", fields=["name", "enabled"])
	access = {}
	for r in frappe.get_all("Waba Agent Access", fields=["parent", "user"], parent_doctype="Waba Number"):
		access.setdefault(r.parent, []).append(r.user)
	holders = set(frappe.get_all("Has Role", filters={"role": ["in", list(WABA_ROLES)], "parenttype": "User"}, pluck="parent"))
	users = {m[1] for m in members} | {u for rows in access.values() for u in rows} | holders
	roles = {}
	for r in frappe.get_all("Has Role", filters={"parenttype": "User", "parent": ["in", list(users) or [""]]}, fields=["parent", "role"]):
		roles.setdefault(r.parent, set()).add(r.role)
	enabled = set(frappe.get_all("User", filters={"enabled": 1, "name": ["in", list(users) or [""]]}, pluck="name"))
	assignments = {}
	for c in frappe.get_all("Waba Conversation", filters={"status": "Open", "assigned_to": ["is", "set"]}, fields=["name", "assigned_to"]):
		assignments.setdefault(c.assigned_to, []).append(c.name)
	for user in assignments:
		if user not in roles:
			roles[user] = set(frappe.get_all("Has Role", filters={"parent": user, "parenttype": "User"}, pluck="role"))
	return team_setup.check(
		parents=parents, members=members, team_numbers=team_numbers, numbers=[{"name": n.name, "enabled": n.enabled} for n in numbers],
		access=access, user_roles=roles, enabled_users=enabled, assignments=assignments,
	)


def apply_setup():
	"""Turn the teams on as the one source of truth: refused while the Setup check shows an error."""
	problems = setup_problems()
	errors = team_setup.blocking(problems)
	if errors:
		frappe.throw("<br>".join(e["text"] for e in errors), title=_("Fix these first"))
	frappe.db.set_single_value("Waba Settings", "teams_manage_agents", 1)
	return sync_all()
