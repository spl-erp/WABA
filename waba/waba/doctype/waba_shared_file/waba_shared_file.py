import frappe
from frappe import _
from frappe.model.document import Document

from waba.rules import media as rules


class WabaSharedFile(Document):
	def validate(self):
		if self.scope == "Team" and not self.team:
			frappe.throw(_("Choose the team that may send this file."))
		if not self.file:
			return
		record = frappe.db.get_value("File", {"file_url": self.file}, ["file_name", "file_size", "is_private"], as_dict=True)
		if record:
			ok, _kind, why = rules.check_upload(_guess_mime(record.file_name), record.file_size)
			if not ok:
				frappe.throw(_(why))


def _guess_mime(name):
	import mimetypes

	return mimetypes.guess_type(name or "")[0] or ""
