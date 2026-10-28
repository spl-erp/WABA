"""One Meta business portfolio: the company's Meta account. Holds the system-user access token that covers
every WhatsApp account of the portfolio. The token is a Password field, visible to Waba Admin only."""

import frappe
from frappe import _
from frappe.model.document import Document

from waba.rules.config_validation import is_numeric_id


class WabaPortfolio(Document):
	def validate(self):
		if self.portfolio_id and not is_numeric_id(self.portfolio_id):
			frappe.throw(_("The portfolio ID is the long number shown in Meta Business Settings (digits only)."))
