"""One WhatsApp business number of an account. Named by its E.164 form (+<digits>). Type Shared (a team or
region) or Personal (a company number assigned to one agent). Agents and routing rules are child tables.

All the checking lives in waba.rules.config_validation (pure, tested offline); this class only gathers the
values and turns a list of problems into one readable error."""

import frappe
from frappe import _
from frappe.model.document import Document

from waba.constants import NUMBER_TYPE_PERSONAL
from waba.rules import config_validation as cv
from waba.rules.hours import as_time
from waba.rules.phone import e164


class WabaNumber(Document):
	def autoname(self):
		self.name = self._key()

	def _key(self):
		key = e164(self.display_number)
		if not key:
			frappe.throw(_("{0} is not a valid international phone number.").format(self.display_number))
		return key

	def validate(self):
		self.display_number = self._key()
		self.phone_number_id = (self.phone_number_id or "").strip()
		if not cv.is_numeric_id(self.phone_number_id):
			frappe.throw(_("The phone number ID is the long number Meta shows for this number (digits only)."))

		if self.number_type != NUMBER_TYPE_PERSONAL:
			self.owner_user = None

		errors = [
			*cv.validate_number(self.number_type, self.sticky_days, self.default_max_open),
			*cv.validate_hours(
				self.hours_enabled, as_time(self.hours_start), as_time(self.hours_end), self.working_days
			),
			*cv.validate_agents([row.as_dict() for row in self.agents], self.number_type, self.owner_user),
			*cv.validate_rules([row.as_dict() for row in self.routing_rules]),
		]
		if errors:
			frappe.throw("<br>".join(_(e) for e in errors), title=_("Please fix the number's settings"))

		if self.enabled and self.number_type != NUMBER_TYPE_PERSONAL and not any(
			row.role == "Supervisor" for row in self.agents
		):
			frappe.msgprint(
				_("A shared number should have at least one supervisor, who receives unassigned conversations."),
				indicator="orange",
				alert=True,
			)
