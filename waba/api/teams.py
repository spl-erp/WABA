"""The Team form's Setup check and Apply button. The checking itself is pure (waba.rules.team_setup) and the database side is in
waba.teams."""

import frappe
from frappe import _

from waba import teams
from waba.rules import visibility
from waba.constants import ROLE_ADMIN


def _may_check():
	user = frappe.session.user
	if teams.is_admin(user):
		return
	parents, members, _numbers = teams.load_tree()
	if not any(m == user and role == visibility.LEAD for _t, m, role in members):
		frappe.throw(_("Only a Waba Admin or a Team Lead can run the Setup check."), frappe.PermissionError)


@frappe.whitelist()
def setup_check() -> dict:
	"""What is wrong or about to change, worst first, and whether the teams already run the Agent lists."""
	_may_check()
	teams.reset()
	problems = teams.setup_problems()
	return {"managed": teams.managed(), "problems": problems, "blocked": any(p["level"] == "error" for p in problems)}


@frappe.whitelist(methods=["POST"])
def apply() -> dict:
	"""Waba Admin only: make the teams the one source for each Number's agents and for the Waba roles."""
	frappe.only_for(ROLE_ADMIN)
	return teams.apply_setup()
