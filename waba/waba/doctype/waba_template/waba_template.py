"""A message template as Meta has it (a read-only mirror, filled by Sync templates on the account). Only APPROVED templates can be sent."""

from frappe.model.document import Document


class WabaTemplate(Document):
	pass
