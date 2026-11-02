"""One automatic WhatsApp message and when it goes: the number, the template, the timing, Manual or Automatic."""

import frappe
from frappe import _
from frappe.model.document import Document

from waba.rules import notify


class WabaNotificationRule(Document):
	def validate(self):
		problems = notify.rule_problems(self.as_dict())
		self.still_needed = "\n".join(problems) or None
		if self.waba_number:
			number = frappe.db.get_value("Waba Number", self.waba_number, ["account", "enabled", "purpose_notifications"], as_dict=True)
			if not number or not number.enabled:
				problems.append("The number is switched off.")
			elif not number.purpose_notifications:
				problems.append("The number is not switched on for notifications (tick it on the Number).")
			if self.template and number:
				tpl = frappe.db.get_value("Waba Template", self.template, ["account", "status", "category", "unsendable_reason"], as_dict=True)
				if not tpl:
					problems.append("That template does not exist.")
				elif tpl.account != number.account:
					problems.append("The template belongs to a different WhatsApp account than the number.")
				elif tpl.status != "APPROVED":
					problems.append(f"The template is {tpl.status}, not approved.")
				elif tpl.category != "UTILITY":
					problems.append("Only Utility templates can be used (Marketing is not allowed yet).")
				elif tpl.unsendable_reason:
					problems.append(tpl.unsendable_reason)
		self.still_needed = "\n".join(problems) or None
		if self.enabled and problems:
			frappe.throw(_("This rule cannot be switched on yet:") + "<br>" + "<br>".join(_(p) for p in problems))
