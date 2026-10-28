"""Checks for the configuration records (numbers, agents, routing rules, hours). Pure: they take plain dicts
or values and return a list of problems (empty = fine), so the doctype controllers stay thin and the rules
are testable offline. A controller turns a non-empty list into one readable error."""

import re

from waba.constants import (
	AGENT_ROLE_AGENT,
	AGENT_ROLE_SUPERVISOR,
	NUMBER_TYPE_PERSONAL,
	NUMBER_TYPE_SHARED,
)
from waba.rules import routing, tags

AGENT_ROLES = (AGENT_ROLE_AGENT, AGENT_ROLE_SUPERVISOR)
NUMBER_TYPES = (NUMBER_TYPE_SHARED, NUMBER_TYPE_PERSONAL)
DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
# Rules that mean something only when a parameter is given (none today; kept explicit for the next rule that does)
RULES_NEEDING_PARAMETER = frozenset()


def is_numeric_id(value):
	"""Meta ids (portfolio, app, WABA, phone number) are plain digit strings."""
	return bool(value) and re.fullmatch(r"\d{5,25}", str(value).strip()) is not None


def validate_agents(rows, number_type, owner_user):
	errors = []
	seen_users, seen_codes = set(), {}
	for index, row in enumerate(rows, start=1):
		user = (row.get("user") or "").strip()
		if not user:
			errors.append(f"Agents row {index}: a user is required.")
			continue
		if user in seen_users:
			errors.append(f"Agents row {index}: {user} is listed twice on this number.")
		seen_users.add(user)
		if row.get("role") not in AGENT_ROLES:
			errors.append(f"Agents row {index}: role must be Agent or Supervisor.")
		if int(row.get("max_open") or 0) < 0:
			errors.append(f"Agents row {index}: maximum open conversations cannot be negative.")
		code = (row.get("rep_code") or "").strip()
		if code:
			if not tags.is_valid_code(code):
				errors.append(f"Agents row {index}: rep code must be 1 to 20 letters, digits, _ or -.")
			elif code.lower() in seen_codes:
				errors.append(f"Agents row {index}: rep code {code} is already used by {seen_codes[code.lower()]}.")
			else:
				seen_codes[code.lower()] = user
	if number_type == NUMBER_TYPE_PERSONAL:
		if not owner_user:
			errors.append("A personal number needs an owner.")
		elif owner_user not in seen_users:
			errors.append(f"The owner {owner_user} must also be listed as an agent on this number.")
		else:
			owner_rows = [r for r in rows if (r.get("user") or "").strip() == owner_user]
			if owner_rows and owner_rows[0].get("role") != AGENT_ROLE_AGENT:
				errors.append("The owner of a personal number must have the Agent role on it.")
	return errors


def validate_rules(rows):
	errors, seen = [], set()
	for index, row in enumerate(rows, start=1):
		rule_type = row.get("rule_type")
		if rule_type not in routing.RULE_TYPES:
			errors.append(f"Routing rule {index}: unknown rule type {rule_type!r}.")
			continue
		if rule_type in seen:
			errors.append(f"Routing rule {index}: {rule_type} is listed twice.")
		seen.add(rule_type)
		if rule_type in RULES_NEEDING_PARAMETER and not (row.get("parameter") or "").strip():
			errors.append(f"Routing rule {index}: {rule_type} needs a parameter.")
	return errors


def parse_days(text):
	"""["Mon", ...] from "Mon, Tue,Wed"; None if any token is not a day name."""
	days = [d.strip().title()[:3] for d in (text or "").replace(";", ",").split(",") if d.strip()]
	if not days or any(d not in DAYS for d in days):
		return None
	return list(dict.fromkeys(days))  # de-duplicated, order kept


def validate_hours(hours_enabled, start, end, working_days):
	"""Business hours only matter when switched on; then both times and valid days are required."""
	if not hours_enabled:
		return []
	errors = []
	if start is None or end is None:
		errors.append("Business hours need a start and an end time.")
	elif start >= end:
		errors.append("Business hours must start before they end.")
	if parse_days(working_days) is None:
		errors.append("Working days must be a comma-separated list such as Mon,Tue,Wed,Thu,Fri,Sat.")
	return errors


def validate_number(number_type, sticky_days, default_max_open):
	errors = []
	if number_type not in NUMBER_TYPES:
		errors.append("Number type must be Shared or Personal.")
	if int(sticky_days or 0) < 0:
		errors.append("Sticky days cannot be negative.")
	if int(default_max_open or 0) < 0:
		errors.append("The default maximum open conversations cannot be negative.")
	return errors
