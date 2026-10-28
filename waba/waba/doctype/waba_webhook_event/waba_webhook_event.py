"""One delivery from Meta, kept exactly as received (the ERP is the only history Meta does not keep beyond 30 days).

Written only by waba.api.webhook; nobody edits it by hand. Named by the delivery's hash, so an unchanged re-send
cannot create a second record. Records are kept for good (the owner's retention decision); only a System Manager
may delete one."""

from frappe.model.document import Document


class WabaWebhookEvent(Document):
	pass
