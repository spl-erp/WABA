"""Who gets a new or returning conversation on a number. Pure rules: no database, fully testable offline.

The caller (the webhook job) gathers the facts into a Context and calls choose_assignee(). Order of the
rules, first match wins (the admin can reorder, disable or leave them to the default):

  Stickiness     an open conversation stays with its agent while that agent is available on the number
  Number Owner   a Personal number goes to its owner; if the owner is away, to an available supervisor
  Rep Tag        the [CODE] a QR code or link put in the first message picks that rep
  Record Owner   the Lead owner / customer's sales person, if they work this number
  Language       an available agent who speaks the customer's language (least busy)
  Least Busy     the available agent with the fewest open conversations
  Unassigned Pool  nobody: supervisors are alerted by the caller after N minutes

A Personal number only ever uses Stickiness and Number Owner (its other rules would let a conversation leave
the owner for no reason). An agent who is away, or at capacity, is skipped by every rule except Stickiness
(a conversation already theirs does not move because they are busy).
"""

from dataclasses import dataclass, field

STICKY = "Stickiness"
NUMBER_OWNER = "Number Owner"
REP_TAG = "Rep Tag"
RECORD_OWNER = "Record Owner"
LANGUAGE = "Language"
LEAST_BUSY = "Least Busy"
RULE_TYPES = (STICKY, NUMBER_OWNER, REP_TAG, RECORD_OWNER, LANGUAGE, LEAST_BUSY)
DEFAULT_ORDER = RULE_TYPES
POOL = "Unassigned Pool"

PERSONAL = "Personal"
SUPERVISOR = "Supervisor"


@dataclass(frozen=True)
class Agent:
	user: str
	role: str = "Agent"  # "Agent" or "Supervisor"
	available: bool = True
	max_open: int = 0  # 0 = use the number's default
	open_count: int = 0
	rep_code: str = ""
	languages: frozenset = frozenset()
	last_assigned_at: object = None  # anything sortable (a datetime); None = never assigned


@dataclass(frozen=True)
class Rule:
	rule_type: str
	enabled: bool = True
	parameter: str = ""


@dataclass
class Context:
	number_type: str = "Shared"
	owner_user: str = ""
	default_max_open: int = 0  # 0 = unlimited
	agents: list = field(default_factory=list)
	rules: list = field(default_factory=list)
	current_assignee: str = ""
	tag: str = ""
	record_owner: str = ""
	language: str = ""


@dataclass(frozen=True)
class Decision:
	assignee: str | None
	reason: str
	trail: tuple = ()  # the rules that were tried and passed, for the inbox's "why this agent"


def choose_assignee(ctx):
	by_user = {agent.user: agent for agent in ctx.agents}
	trail = []
	for rule_type in _steps(ctx):
		decision = _HANDLERS[rule_type](ctx, by_user)
		if decision:
			return Decision(decision[0], decision[1], tuple(trail))
		trail.append(rule_type)
	return Decision(None, POOL, tuple(trail))


# ----------------------------------------------------------------------------------------- helpers


def _steps(ctx):
	if ctx.number_type == PERSONAL:
		return [STICKY, NUMBER_OWNER]
	if not ctx.rules:
		return list(DEFAULT_ORDER)
	return [r.rule_type for r in ctx.rules if r.enabled and r.rule_type in _HANDLERS]


def keep_with_current(current_assignee, assignee_valid, auto_reassign_away):
	"""True when a conversation must stay with its present agent. While automatic re-assignment is switched off (Waba Settings),
	a chat stays with its agent even if they are Away. A broken assignment (the person is disabled or no longer works the
	number) is not "Away" and is still moved."""
	return bool(current_assignee) and bool(assignee_valid) and not auto_reassign_away


def needs_lead(current_assignee, assignee_valid, auto_assign_new):
	"""True when a chat must wait for a Team Lead to assign it: automatic assignment of new chats is switched off (Waba Settings) and the
	chat has nobody who can take it (no assignee, or one who is disabled or no longer works the number)."""
	return not auto_assign_new and not (bool(current_assignee) and bool(assignee_valid))


def _has_capacity(agent, default_max_open):
	limit = agent.max_open or default_max_open
	return limit <= 0 or agent.open_count < limit


def _usable(agent, ctx):
	"""Available and below capacity: may receive a NEW assignment."""
	return agent is not None and agent.available and _has_capacity(agent, ctx.default_max_open)


def _least_busy_key(agent):
	return (
		agent.open_count,
		agent.last_assigned_at is not None,
		agent.last_assigned_at if agent.last_assigned_at is not None else "",
		agent.user,
	)


def _least_busy(agents):
	return min(agents, key=_least_busy_key) if agents else None


# ----------------------------------------------------------------------------------------- rules


def _sticky(ctx, by_user):
	agent = by_user.get(ctx.current_assignee)
	if agent and agent.available:  # capacity is NOT checked: the conversation is already theirs
		return agent.user, "sticky"
	return None


def _number_owner(ctx, by_user):
	if ctx.number_type != PERSONAL or not ctx.owner_user:
		return None
	owner = by_user.get(ctx.owner_user)
	if owner and owner.available:
		return owner.user, "number_owner"
	supervisors = [a for a in ctx.agents if a.role == SUPERVISOR and a.available and a.user != ctx.owner_user]
	chosen = _least_busy(supervisors)
	if chosen:
		return chosen.user, "owner_away_supervisor"
	return None


def _rep_tag(ctx, by_user):
	if not ctx.tag:
		return None
	wanted = ctx.tag.strip().lower()
	for agent in ctx.agents:
		if agent.rep_code and agent.rep_code.strip().lower() == wanted and _usable(agent, ctx):
			return agent.user, "rep_tag"
	return None


def _record_owner(ctx, by_user):
	if not ctx.record_owner:
		return None
	agent = by_user.get(ctx.record_owner)
	if _usable(agent, ctx):
		return agent.user, "record_owner"
	return None


def _language(ctx, by_user):
	if not ctx.language:
		return None
	wanted = ctx.language.strip().lower()
	speakers = [
		a
		for a in ctx.agents
		if a.role != SUPERVISOR and _usable(a, ctx) and wanted in {x.strip().lower() for x in a.languages}
	]
	chosen = _least_busy(speakers)
	return (chosen.user, "language") if chosen else None


def _least_busy_rule(ctx, by_user):
	pool = [a for a in ctx.agents if a.role != SUPERVISOR and _usable(a, ctx)]
	chosen = _least_busy(pool)
	return (chosen.user, "least_busy") if chosen else None


_HANDLERS = {
	STICKY: _sticky,
	NUMBER_OWNER: _number_owner,
	REP_TAG: _rep_tag,
	RECORD_OWNER: _record_owner,
	LANGUAGE: _language,
	LEAST_BUSY: _least_busy_rule,
}
