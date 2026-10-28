"""One WhatsApp Business Account (Meta now calls it a "Messaging account"): the owner of templates, billing,
payment method and spend limit. It belongs to a portfolio (token) and is served by a Meta app (webhook)."""

import frappe
from frappe import _
from frappe.model.document import Document

from waba.rules.config_validation import is_numeric_id


class WabaAccount(Document):
	def validate(self):
		self.waba_id = (self.waba_id or "").strip()
		if not is_numeric_id(self.waba_id):
			frappe.throw(_("The WABA ID is the long number shown in WhatsApp Manager (digits only)."))
		if self.enabled:
			for doctype, name in (("Waba Portfolio", self.portfolio), ("Waba Meta App", self.meta_app)):
				if name and not frappe.db.get_value(doctype, name, "enabled"):
					frappe.msgprint(
						_("{0} {1} is disabled, so this account cannot connect until it is enabled.").format(
							_(doctype), name
						),
						indicator="orange",
						alert=True,
					)
