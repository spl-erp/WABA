"""What the teams imply for the numbers, and what is wrong with the setup. Pure: no database, tested offline.

The Team is the one place that says who works where. A team that owns numbers works those numbers, and only those: an
Agent of the team is an Agent on the number, a Team Lead is its Supervisor. A team that owns no number of its own works the numbers
of the nearest team above it that does (so a sub-team without a number of its own is not left with nothing). A team that
owns numbers does NOT also inherit its parent's: Marketing under IT works Marketing's number, not IT's. (The Team Lead of IT still
oversees Marketing's chats through the visibility rule.) The Agent list
on a Number is only a copy of that (see waba.teams.sync_number_agents); this module computes it and checks it.
"""

from waba.rules import visibility as v

ERROR = "error"
WARN = "warning"
INFO = "info"

ROLE_FOR = {v.AGENT: "Agent", v.LEAD: "Supervisor"}
SETTINGS = ("max_open", "rep_code", "languages", "may_send_templates", "may_take_calls", "may_make_calls")


def number_teams(team_numbers):
	return v.number_teams(team_numbers)


def team_of(user, members):
	"""The one team a person belongs to (the first when the data is wrong), or None."""
	for team, member, _role in members:
		if member == user:
			return team
	return None


def effective_team(team, parents, team_numbers):
	"""The team whose numbers `team` works: itself when it owns any, else the nearest team above it that does (None if none)."""
	for node in v.ancestors(team, parents):
		if team_numbers.get(node):
			return node
	return None


def derive_agents(number, *, parents, members, team_numbers, settings=None, existing=None):
	"""The Agent Access rows `number` should have: [{user, role, available, max_open, rep_code, languages, may_send_templates, may_take_calls, may_make_calls}].

	members   [(team, user, role)]
	settings  {user: {max_open, rep_code, languages, may_send_templates, may_take_calls, may_make_calls}} from the team members
	existing  {user: available} the runtime flags to keep (a new person is available)
	"""
	settings, existing = settings or {}, existing or {}
	using = number_teams(team_numbers).get(number, set())
	rows = {}
	for team, user, role in members:
		if effective_team(team, parents, team_numbers) not in using:
			continue
		role = ROLE_FOR.get(role, "Agent")
		if user in rows and rows[user]["role"] == "Supervisor":
			continue  # a Team Lead listed twice stays a Team Lead
		extra = settings.get(user) or {}
		rows[user] = {
			"user": user,
			"role": role,
			"available": 1 if existing.get(user, True) else 0,
			"max_open": int(extra.get("max_open") or 0),
			"rep_code": (extra.get("rep_code") or "").strip(),
			"languages": (extra.get("languages") or "").strip(),
			"may_send_templates": 1 if extra.get("may_send_templates", 1) else 0,
			"may_take_calls": 1 if extra.get("may_take_calls") else 0,
			"may_make_calls": 1 if extra.get("may_make_calls") else 0,
		}
	return sorted(rows.values(), key=lambda r: (r["role"] != "Supervisor", r["user"]))


def wanted_roles(members):
	"""{user: the Waba role their team gives them}: Team Lead -> Waba Supervisor, Agent -> Waba Agent (a Team Lead wins)."""
	roles = {}
	for _team, user, role in members:
		want = "Waba Supervisor" if role == v.LEAD else "Waba Agent"
		if roles.get(user) != "Waba Supervisor":
			roles[user] = want
	return roles


def check(*, parents, members, team_numbers, numbers, access, user_roles=None, enabled_users=None, assignments=None):
	"""A list of {level, text} for the Setup check.

	numbers        [{name, enabled}] every WhatsApp number
	access         {number: [users in its current Agent list]}
	assignments    {user: [conversation names]} open conversations by assignee (None skips the stranded check)
	user_roles     {user: set of roles} (None skips the role checks)
	enabled_users  set of enabled user ids (None skips the disabled check)
	"""
	found = []

	def add(level, text):
		found.append({"level": level, "text": text})

	by_user = {}
	for team, user, _role in members:
		by_user.setdefault(user, []).append(team)
	for user, teams in sorted(by_user.items()):
		if len(set(teams)) > 1:
			add(ERROR, f"{user} is in more than one team ({', '.join(sorted(set(teams)))}). A person belongs to one team.")
		if enabled_users is not None and user not in enabled_users:
			add(ERROR, f"{user} is in a team but is disabled or does not exist.")

	roots = [t for t, parent in parents.items() if not parent]
	for root in roots:
		if not any(role == v.LEAD and team == root for team, _u, role in members):
			add(WARN, f"The top-level team {root} has no Team Lead. A Team Lead there sees every conversation.")

	sharing = number_teams(team_numbers)
	for number in numbers:
		name = number["name"]
		if not sharing.get(name):
			add(WARN if number.get("enabled") else INFO, f"The number {name} is not used by any team, so nobody can work it.")
			continue
		branch = set()
		for team in sharing[name]:
			branch |= v.subtree(team, parents)
		if not any(role == v.LEAD and team in branch for team, _u, role in members):
			add(WARN, f"Nobody leads the teams that use {name}: unassigned conversations on it will be seen by no Team Lead.")
		if not any(team in branch for team, _u, _r in members):
			add(WARN, f"The teams that use {name} have no people.")
		derived = {row["user"] for row in derive_agents(name, parents=parents, members=members, team_numbers=team_numbers)}
		for user in sorted(set(access.get(name, [])) - derived):
			add(WARN, f"{user} is an agent on {name} but not in any team that uses it. Apply would take that away.")
		for user in sorted(derived - set(access.get(name, []))):
			add(INFO, f"{user} will become an agent on {name} when you press Apply.")

	if user_roles is not None:
		for user, want in sorted(wanted_roles(members).items()):
			if want not in user_roles.get(user, set()):
				add(INFO, f"{user} will be given the role {want} when you press Apply.")

	if user_roles is not None:
		for user, roles in sorted(user_roles.items()):
			if user not in by_user and ("Waba Agent" in roles or "Waba Supervisor" in roles) and "Waba Admin" not in roles:
				add(WARN, f"{user} has a Waba role but is in no team. Apply would take the role away.")

	if assignments and user_roles is not None:
		for user, names in sorted(assignments.items()):
			roles = user_roles.get(user, set())
			if not ({"Waba Agent", "Waba Supervisor", "Waba Admin"} & roles) or user not in by_user and "Waba Admin" not in roles:
				shown = ", ".join(names[:3]) + (" ..." if len(names) > 3 else "")
				add(WARN, f"{user} has open conversations ({shown}) but is not in a team with a Waba role. Return them to the waiting list or transfer them.")

	order = {ERROR: 0, WARN: 1, INFO: 2}
	return sorted(found, key=lambda f: order[f["level"]])


def blocking(problems):
	return [p for p in problems if p["level"] == ERROR]
