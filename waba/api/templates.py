"""Write a template here, send it to Meta, copy it, delete it. Waba Admin and System Manager only.

Nothing is sent to Meta until a person presses Submit to Meta (a template is never submitted by saving it). Meta decides
(PENDING, then APPROVED or REJECTED with a reason); the answer arrives through the webhook (waba.template_events) or Sync
templates. A refusal is shown in Meta's own words. Everything the check script covers runs against a fake Meta; the real
calls are UNVERIFIED until Meta's API block is lifted.
"""

import json

import frappe
from frappe import _
from frappe.utils import now_datetime
from frappe.utils.password import get_decrypted_password

from waba.api import send
from waba.constants import DEFAULT_API_VERSION, ROLE_ADMIN
from waba.meta import graph
from waba.rules import media as media_rules
from waba.rules import template_author as author
from waba.waba.doctype.waba_template.waba_template import EDITABLE, draft_dict

ADMINS = ("System Manager", ROLE_ADMIN)
MEDIA_HEADERS = ("IMAGE", "VIDEO", "DOCUMENT")
DOCTYPE = "Waba Template"


def _only_admins():
	frappe.only_for(ADMINS)


def _context(doc):
	account = frappe.get_doc("Waba Account", doc.account)
	if not account.enabled:
		frappe.throw(_("The WhatsApp account {0} is switched off.").format(account.name))
	token = get_decrypted_password("Waba Portfolio", account.portfolio, "access_token", raise_exception=False)
	if not token:
		frappe.throw(_("Save the access token on the portfolio {0} first.").format(account.portfolio))
	app_id = frappe.db.get_value("Waba Meta App", account.meta_app, "app_id")
	return account, token, account.api_version or DEFAULT_API_VERSION, app_id


def _list(problems):
	return "<br>".join(_(p) for p in problems)


def _upload_sample(doc, token, app_id, version):
	"""Send the chosen Shared File to Meta as the header's sample; returns the handle."""
	if not doc.header_sample:
		frappe.throw(_("Choose a sample file for the {0} header first.").format(doc.header_format.lower()))
	row = frappe.db.get_value("Waba Shared File", doc.header_sample, ["file", "enabled"], as_dict=True)
	if not row or not row.file:
		frappe.throw(_("The sample file is not available."))
	record = frappe.get_doc("File", {"file_url": row.file})
	with open(record.get_full_path(), "rb") as handle:
		content = handle.read()
	import mimetypes

	mime = media_rules.clean_mime(mimetypes.guess_type(record.file_name or "")[0])
	ok, kind, why = media_rules.check_upload(mime, len(content))
	if not ok:
		frappe.throw(_(why))
	if kind.upper() != doc.header_format:
		frappe.throw(_("The header is a {0}, but the sample file is a {1}.").format(doc.header_format.lower(), kind))
	ok, why = media_rules.check_content(mime, content)
	if not ok:
		frappe.throw(_(why))
	return graph.upload_sample(token, app_id, media_rules.safe_filename(record.file_name, mime, fallback=kind), content, mime, version)


@frappe.whitelist(methods=["POST"])
def submit(template: str):
	"""Send a DRAFT (or a REJECTED one, corrected) to Meta for review."""
	_only_admins()
	doc = frappe.get_doc(DOCTYPE, template)
	if doc.status not in EDITABLE:
		frappe.throw(_("Only a draft or a rejected template can be submitted; this one is {0}.").format(doc.status))
	draft = draft_dict(doc)
	problems = author.check(draft)
	if problems:
		frappe.throw(_list(problems), title=_("Not ready to submit"))
	account, token, version, app_id = _context(doc)
	try:
		if draft["header_format"] in MEDIA_HEADERS:
			draft["header_handle"] = _upload_sample(doc, token, app_id, version)
			doc.db_set("header_handle", draft["header_handle"], update_modified=False)
			problems = author.check(draft, for_submit=True)
			if problems:
				frappe.throw(_list(problems), title=_("Not ready to submit"))
		payload = author.request(draft)
		answer = graph.create_template(token, account.waba_id, payload, version)
	except graph.GraphError as e:
		text = graph.explain(e)
		send._note_account_problem(account, e, text)
		doc.db_set({"submit_note": text}, update_modified=False)
		return {"ok": False, "error": text}
	status = str((answer or {}).get("status") or "PENDING").upper()
	category = str((answer or {}).get("category") or doc.category).upper()
	note = _("Sent to Meta for review.")
	if category != doc.category:
		note += " " + _("Meta set the category to {0} (you chose {1}).").format(category, doc.category)
	doc.db_set(
		{
			"meta_template_id": str((answer or {}).get("id") or ""),
			"status": status,
			"category": category,
			"submitted_at": now_datetime(),
			"submit_note": note,
			"rejected_reason": None,
			"draft_problems": None,
			"components_json": json.dumps(payload["components"], ensure_ascii=False),
			"parameter_format": payload["parameter_format"],
			"last_synced": now_datetime(),
		}
	)
	return {"ok": True, "status": status, "note": note}


@frappe.whitelist(methods=["POST"])
def delete(template: str):
	"""Delete a template: a draft only here; a template Meta knows is deleted at Meta (that one language) and marked DELETED."""
	_only_admins()
	doc = frappe.get_doc(DOCTYPE, template)
	if doc.status == "DRAFT":
		frappe.delete_doc(DOCTYPE, doc.name, ignore_permissions=True)
		return {"ok": True, "deleted": "draft"}
	if not doc.meta_template_id:
		frappe.throw(_("The ERP does not know this template's id at Meta yet. Press Sync templates first, then delete it."))
	account, token, version, _app = _context(doc)
	try:
		graph.delete_template(token, account.waba_id, doc.template_name, doc.meta_template_id, version)
	except graph.GraphError as e:
		text = graph.explain(e)
		doc.db_set({"submit_note": text}, update_modified=False)
		return {"ok": False, "error": text}
	doc.db_set({"status": "DELETED", "submit_note": _("Deleted at Meta."), "last_synced": now_datetime()})
	return {"ok": True, "deleted": "meta"}


def _free_name(account, base, language):
	n = 2
	while frappe.db.exists(DOCTYPE, f"{account}|{base}_v{n}|{language}"):
		n += 1
	return f"{base}_v{n}"


@frappe.whitelist(methods=["POST"])
def duplicate(template: str):
	"""Copy a template as a new draft (Meta's advised way to change an approved template). Returns the new draft's name."""
	_only_admins()
	source = frappe.get_doc(DOCTYPE, template)
	try:
		components = json.loads(source.components_json) if source.components_json else None
	except ValueError:
		components = None
	if not components:
		frappe.throw(_("This template's content is not stored yet. Press Sync templates, then copy it."))
	copy = author.from_components(components)
	name = _free_name(source.account, source.template_name, source.language)
	rows = [{"slot": slot, "example": value, "source_type": "Ask each time", "active": 1} for slot, value in copy["examples"].items()]
	new = frappe.get_doc(
		{
			"doctype": DOCTYPE,
			"account": source.account,
			"template_name": name,
			"language": source.language,
			"category": source.category if source.category in author.ALLOWED_CATEGORIES else "UTILITY",
			"status": "DRAFT",
			"header_format": copy["header_format"],
			"header_text": copy["header_text"],
			"body_text": copy["body_text"],
			"footer_text": copy["footer_text"],
			"buttons": [{"type": b["type"], "text": b["text"], "url": b["url"], "phone_number": b["phone_number"], "example": b["example"]} for b in copy["buttons"]],
			"variables": rows,
		}
	).insert(ignore_permissions=True)
	return {"ok": True, "draft": new.name}
