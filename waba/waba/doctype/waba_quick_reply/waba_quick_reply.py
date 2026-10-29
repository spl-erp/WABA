"""A saved answer an agent inserts from the composer."""

import frappe
from frappe import _
from frappe.model.document import Document

MANAGERS = {"System Manager", "Waba Admin", "Waba Supervisor"}


class WabaQuickReply(Document):
	def validate(self):
		if self.scope != "Team":
			self.team = None
		if self.scope != "Me" and not (MANAGERS & set(frappe.get_roles())):
			frappe.throw(_("Agents can save quick replies for themselves only. Ask a supervisor to share one with a team."))
