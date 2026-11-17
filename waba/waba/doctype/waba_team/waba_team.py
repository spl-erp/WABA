"""A team in the organisation tree: Common at the top, departments, sub-teams. See waba.rules.visibility."""

import frappe
from frappe.utils.nestedset import NestedSet


class WabaTeam(NestedSet):
	nsm_parent_field = "parent_waba_team"

	def validate(self):
		from waba import teams

		teams.validate_team(self)

	def on_update(self):
		from waba import teams

		super().on_update()
		teams.reset()
		if teams.managed():
			teams.sync_all()

	def on_trash(self):
		from waba import teams

		super().on_trash()
		teams.reset()
		if teams.managed():
			frappe.enqueue("waba.teams.sync_all", enqueue_after_commit=True)
