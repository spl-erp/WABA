"""A message template: what Meta has (synced) or what we are writing (a draft, not yet sent to Meta).

A DRAFT or REJECTED template can be edited; everything else is read-only and follows Meta. Saving a draft never sends anything:
the Submit to Meta button (waba.api.templates.submit) does that, after the checks in waba.rules.template_author.
"""

import frappe
from frappe import _
from frappe.model.document import Document

from waba.rules import template_author as author

EDITABLE = ("DRAFT", "REJECTED")


def draft_dict(doc):
	"""The plain draft (see rules/template_author.py) of a template record."""
	return {
		"template_name": (doc.template_name or "").strip(),
		"language": (doc.language or "").strip(),
		"category": doc.category,
		"header_format": doc.header_format or "",
		"header_text": doc.header_text or "",
		"header_handle": doc.get("header_handle"),
		"body_text": doc.body_text or "",
		"footer_text": doc.footer_text or "",
		"buttons": [
			{"type": b.type, "text": b.text, "url": b.url, "phone_number": b.phone_number, "example": b.example}
			for b in (doc.get("buttons") or [])
		],
		"examples": {r.slot: r.example for r in (doc.get("variables") or []) if r.slot and r.example},
	}


class WabaTemplate(Document):
	def before_naming(self):
		if not self.status:
			self.status = "DRAFT"
		if self.status == "DRAFT" and not self.template_key:
			self.template_key = f"{self.account}|{(self.template_name or '').strip()}|{(self.language or '').strip()}"
			self.title = f"{(self.template_name or '').strip()} ({(self.language or '').strip()})"

	LOCKED_WHEN_SENT = ("template_name", "language", "header_format", "header_text", "body_text", "footer_text")

	def validate(self):
		if self.status in EDITABLE:
			self.validate_draft()
		else:
			self.refuse_edits_once_sent()

	def refuse_edits_once_sent(self):
		"""Meta owns a template once it is submitted: its text cannot change here (Copy as new draft instead). The sync from Meta
		writes straight to the database, so it is not stopped by this."""
		before = self.get_doc_before_save()
		if not before or before.status in EDITABLE:
			return
		changed = [f for f in self.LOCKED_WHEN_SENT if (before.get(f) or "") != (self.get(f) or "")]
		if changed or len(before.get("buttons") or []) != len(self.get("buttons") or []):
			frappe.throw(_("This template is with Meta ({0}). Its text cannot be changed here; use Copy as new draft.").format(self.status))

	def validate_draft(self):
		if not (self.template_name or "").strip() or not (self.language or "").strip():
			frappe.throw(_("Give the template a name and a language first."))
		if self.is_new():
			key = f"{self.account}|{self.template_name.strip()}|{self.language.strip()}"
			if frappe.db.exists("Waba Template", key):
				frappe.throw(_("This account already has a template called {0} in {1}.").format(self.template_name, self.language))
		self.sync_example_rows()
		problems = author.check(draft_dict(self))
		self.draft_problems = "\n".join(problems) or None
		body_slots = [s for s in author.slots(draft_dict(self)) if s["id"].startswith("body.")]
		self.variable_count = len(body_slots)
		self.button_count = len([b for b in (self.buttons or []) if b.type])
		self.parameter_format = author.request(draft_dict(self))["parameter_format"]

	def sync_example_rows(self):
		"""One row per value the text defines, so the writer can give each an example. Rows already there keep what was typed."""
		slots = {s["id"]: s for s in author.slots(draft_dict(self))}
		have = {r.slot: r for r in (self.variables or [])}
		for slot_id, slot in slots.items():
			row = have.get(slot_id)
			if row is None:
				self.append("variables", {"slot": slot_id, "label": slot["label"], "source_type": "Ask each time", "active": 1})
			else:
				row.active = 1
		for slot_id, row in have.items():
			if slot_id not in slots:
				row.active = 0
