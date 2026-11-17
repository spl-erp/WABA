"""A locked set of Customers or Leads that a campaign goes to.

Built once through waba.api.campaigns.create_set (after a review window) and never edited afterwards: the people are in
Waba Recipient Set Member rows, the people left out are kept as a short report in `excluded_json`. To change who is in a
Set, copy it as a new Set."""

import frappe
from frappe import _
from frappe.model.document import Document


class WabaRecipientSet(Document):
	def before_save(self):
		if not self.is_new():
			frappe.throw(_("A confirmed Set cannot be changed. Copy it as a new Set instead."))

	def on_trash(self):
		frappe.db.delete("Waba Recipient Set Member", {"recipient_set": self.name})
