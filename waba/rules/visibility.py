"""Who may see which conversation. Pure rules: no database, fully testable offline.

The organisation is a tree of teams ("Common" at the top, departments under it, sub-teams under those). A team owns
the WhatsApp numbers its people work on and has members, each an Agent or a Lead. The rule is "each level sees itself
and everything below it, never sideways":

  Everyone                 System Manager and Waba Admin; a Lead of a top-level team ("Common")
  Lead of a team           conversations assigned to anyone in that team or below it, and every conversation
                           (assigned or not) on the numbers owned by that team or below it
  Agent                    only the conversations assigned to them
  A number set to "All conversations on this number" also shows all of it to the agents who work that number

An unassigned conversation is therefore seen by the Leads above its number and nobody else.
"""

from dataclasses import dataclass, field

LEAD = "Lead"
AGENT = "Agent"
SHOW_ALL_ON_NUMBER = "All conversations on this number"


@dataclass(frozen=True)
class Scope:
	"""What one user may see. `users` and `numbers` are alternatives: a conversation is visible if it matches either."""

	me: str
	everything: bool = False
	users: frozenset = field(default_factory=frozenset)
	numbers: frozenset = field(default_factory=frozenset)
	lead_numbers: frozenset = field(default_factory=frozenset)  # the numbers the person oversees as a Lead (shows Unassigned)

	@property
	def is_lead(self):
		return self.everything or bool(self.lead_numbers) or len(self.users) > 1


def subtree(root, parents):
	"""`root` and every team below it. `parents` maps team -> parent team (or None). Safe against a loop."""
	children = {}
	for team, parent in parents.items():
		children.setdefault(parent, []).append(team)
	found, stack = set(), [root]
	while stack:
		team = stack.pop()
		if team in found:
			continue
		found.add(team)
		stack.extend(children.get(team, []))
	return found


def ancestors(team, parents):
	"""`team` and the teams above it, nearest first. Safe against a loop."""
	chain, seen = [], set()
	while team and team not in seen:
		seen.add(team)
		chain.append(team)
		team = parents.get(team)
	return chain


def is_root(team, parents):
	return not parents.get(team)


def visible_scope(user, *, everyone=False, parents=None, members=None, team_numbers=None, agent_numbers=None, number_visibility=None):
	"""The Scope of `user`.

	everyone          True for System Manager / Waba Admin
	parents           {team: parent team or None}
	members           [(team, user, role)] with role "Lead" or "Agent"
	team_numbers      {team: [number, ...]}
	agent_numbers     the numbers `user` works as an agent (their Agent Access rows)
	number_visibility {number: "Own conversations only" | "All conversations on this number"}
	"""
	parents, members = parents or {}, members or []
	team_numbers, number_visibility = team_numbers or {}, number_visibility or {}
	if everyone:
		return Scope(me=user, everything=True)

	users, numbers, lead_numbers = {user}, set(), set()
	for team, member, role in members:
		if member != user or role != LEAD:
			continue
		if is_root(team, parents):
			return Scope(me=user, everything=True)
		for node in subtree(team, parents):
			users.update(m for t, m, _ in members if t == node)
			lead_numbers.update(team_numbers.get(node, []))
	numbers.update(lead_numbers)
	for number in agent_numbers or []:
		if number_visibility.get(number) == SHOW_ALL_ON_NUMBER:
			numbers.add(number)
	return Scope(me=user, users=frozenset(users), numbers=frozenset(numbers), lead_numbers=frozenset(lead_numbers))


def can_see(scope, assigned_to, number):
	if scope.everything:
		return True
	return (bool(assigned_to) and assigned_to in scope.users) or number in scope.numbers


def can_see_unassigned(scope, number):
	"""Only the people who oversee the number (and everyone) see a conversation nobody has."""
	return scope.everything or number in scope.lead_numbers


def overseers(assigned_to, number, *, parents, members, team_numbers):
	"""Users (other than the assignee) who may see a conversation, so a live update can be sent to just them.

	A Lead sees it if it is on a number owned by their team or below, or assigned to someone in their team or below.
	Top-level Leads see everything. (Administrators are added by the caller: they are not in the tree.)
	"""
	owner_teams = {t for t, nums in team_numbers.items() if number in nums}
	assignee_teams = {t for t, m, _ in members if m == assigned_to} if assigned_to else set()
	related = set(owner_teams) | assignee_teams
	above = set()
	for team in related:
		above.update(ancestors(team, parents))
	roots = {t for t in parents if is_root(t, parents)}
	return {m for t, m, role in members if role == LEAD and (t in above or t in roots)} - {assigned_to}
