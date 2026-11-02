"""Template sending glue: the database side of rules/templates.py and rules/template_vars.py.

It builds a template's structure from what is stored, gathers what the ERP knows about the customer, fills the values
the template's variable map can fill, and turns a header file choice into the bytes to upload. Nothing here talks to Meta."""

import json

import frappe
from frappe import _

from waba.rules import media as media_rules
from waba.rules import template_vars, templates

HOOK_VALUES = "waba_template_values"
HEADER_KINDS = {"image": "image", "video": "video", "document": "document"}


def structure_of(tpl):
	"""The parsed structure of a Waba Template (from its stored components, or its older fields)."""
	components = None
	if tpl.get("components_json"):
		try:
			components = json.loads(tpl.components_json)
		except ValueError:
			components = None
	if not components:
		components = templates.from_fields(tpl.header_format, tpl.header_text, tpl.body_text, tpl.footer_text)
	return templates.parse(components, tpl.get("parameter_format"))


def map_rows(tpl):
	return [
		{"slot": r.slot, "source_type": r.source_type, "source": r.source, "label": r.label, "active": r.active, "example": r.example}
		for r in (tpl.get("variables") or [])
	]


def context_for(party_doctype, party, customer_label="", profile_name="", sender=None, reference=None):
	"""What the variable map may draw on: the matched record's plain fields (only if this person may read it), the sender,
	today and the customer's name. Splashjet-specific fields arrive through the `waba_template_values` hook."""
	record = {}
	if party_doctype and party and frappe.db.exists(party_doctype, party) and frappe.has_permission(party_doctype, "read", party):
		doc = frappe.get_doc(party_doctype, party)
		record = template_vars.public_record(doc.as_dict())
		for path in frappe.get_hooks(HOOK_VALUES):
			try:
				extra = frappe.get_attr(path)(party_doctype, party) or {}
			except Exception:
				frappe.log_error(title="Waba: template values hook failed")
				continue
			record.update(template_vars.public_record(extra))
	if reference:  # a notification is about a document (a quotation, an invoice): its fields are `doc.<field>` in the variable map
		record["doc"] = template_vars.public_record(reference)
	name = ""
	for key in ("customer_name", "lead_name", "full_name"):
		if record.get(key):
			name = str(record[key]).strip()
			break
	if not name and (record.get("first_name") or record.get("last_name")):
		name = " ".join(x for x in (record.get("first_name"), record.get("last_name")) if x)
	if not name:
		name = (profile_name or customer_label or "").split(" · ")[0].strip()
	return {
		"record": record,
		"sender": sender or frappe.utils.get_fullname(frappe.session.user),  # an automatic message has no person: the caller passes a label
		"today": frappe.utils.formatdate(frappe.utils.today(), "dd-mm-yyyy"),
		"customer_name": name,
	}


def prepare(tpl, party_doctype, party, customer_label="", profile_name="", typed=None, sender=None, reference=None):
	"""(structure, values, missing slots, problems) for a template and what the person typed or chose."""
	structure = structure_of(tpl)
	filled, _missing = template_vars.resolve(map_rows(tpl), context_for(party_doctype, party, customer_label, profile_name, sender, reference))
	values = template_vars.merge(filled, templates.typed_values(structure, typed))
	problems = templates.validate(structure, values)
	missing = [s for s in templates.slot_ids(structure) if not _has(values.get(s))]
	return structure, values, missing, problems


def _has(value):
	return bool(value) and (not isinstance(value, str) or bool(value.strip()))


def header_file(structure, values, library_rows, user):
	"""(content, filename, mime, cleanup) for a template with a media header, or None. `library_rows` are the Shared Files this
	person may use. Raises in plain words when the file is missing, not allowed or the wrong kind."""
	slot = next((s for s in structure["slots"] if s["id"] == "header.media"), None)
	if not slot:
		return None
	choice = values.get("header.media")
	if isinstance(choice, str):
		choice = {"file_url": choice}
	if not isinstance(choice, dict) or not (choice.get("shared_file") or choice.get("file_url")):
		frappe.throw(_("Choose the {0} for the header.").format(slot["kind"]))
	cleanup = None
	if user is None and not choice.get("shared_file"):
		frappe.throw(_("An automatic message can use only a file from the shared library for its header."))
	if choice.get("shared_file"):
		row = next((r for r in library_rows if r.name == choice["shared_file"]), None)
		if not row:
			frappe.throw(_("That header file is not available to you."), frappe.PermissionError)
		record = frappe.get_doc("File", {"file_url": row.file})
	else:
		found = frappe.db.get_value("File", {"file_url": choice["file_url"], "is_private": 1, "owner": user}, ["name", "attached_to_doctype"], as_dict=True)
		if not found or found.attached_to_doctype:
			frappe.throw(_("That upload was not found. Choose the file again."))
		record = frappe.get_doc("File", found.name)
		cleanup = found.name
	with open(record.get_full_path(), "rb") as handle:
		content = handle.read()
	import mimetypes

	mime = media_rules.clean_mime(mimetypes.guess_type(record.file_name or "")[0])
	ok, kind, why = media_rules.check_upload(mime, len(content))
	if not ok:
		frappe.throw(_(why))
	if kind != slot["kind"]:
		frappe.throw(_("This template's header is a {0}, but the file chosen is a {1}.").format(slot["kind"], kind))
	ok, why = media_rules.check_content(mime, content)
	if not ok:
		frappe.throw(_(why))
	return content, media_rules.safe_filename(record.file_name, mime, fallback=kind), mime, cleanup
