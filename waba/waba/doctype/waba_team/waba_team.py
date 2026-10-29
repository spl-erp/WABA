"""A team in the organisation tree: Common at the top, departments, sub-teams. See waba.rules.visibility."""

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

	def on_trash(self):
		from waba import teams

		super().on_trash()
		teams.reset()
