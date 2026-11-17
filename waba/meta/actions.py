"""The buttons on the WhatsApp Account form: Test connection, Subscribe webhook, Sync numbers.
Admin only. Each button calls Meta with the portfolio's token, records what it learned on the account and says
in plain words what happened."""

import json

import frappe
from frappe import _
from frappe.utils import now_datetime
from frappe.utils.password import get_decrypted_password

from waba.constants import DEFAULT_API_VERSION, NUMBER_TYPE_SHARED, ROLE_ADMIN
from waba.meta import graph
from waba.rules import templates
from waba.rules.phone import e164


def _context(account):
	frappe.only_for((ROLE_ADMIN, "System Manager"))
	doc = frappe.get_doc("Waba Account", account)
	token = get_decrypted_password("Waba Portfolio", doc.portfolio, "access_token", raise_exception=False)
	if not token:
		frappe.throw(_("Save the access token on the portfolio {0} first.").format(doc.portfolio))
	return doc, token, doc.api_version or DEFAULT_API_VERSION


def _failed(doc, error):
	message = graph.explain(error)
	values = {"last_error": message, "last_checked": now_datetime()}
	if error.code == 190:
		values["token_valid"] = 0
	doc.db_set(values, update_modified=False)
	frappe.db.commit()
	frappe.throw(message, title=_("Meta said no"))


@frappe.whitelist(methods=["POST"])
def test_connection(account):
	doc, token, version = _context(account)
	try:
		info = graph.account_info(token, doc.waba_id, version)
	except graph.GraphError as e:
		_failed(doc, e)
	doc.db_set(
		{
			"token_valid": 1,
			"currency": info.get("currency"),
			"timezone": info.get("timezone_id"),
			"verification_status": info.get("business_verification_status"),
			"review_status": info.get("account_review_status"),
			"last_checked": now_datetime(),
			"last_error": None,
		},
		update_modified=False,
	)
	return _("Connected to {0}. Verification: {1}. Review: {2}.").format(
		info.get("name") or doc.waba_id, info.get("business_verification_status") or "?", info.get("account_review_status") or "?"
	)


@frappe.whitelist(methods=["POST"])
def subscribe_webhook(account):
	doc, token, version = _context(account)
	try:
		graph.subscribe_app(token, doc.waba_id, version)
		apps = graph.subscribed_apps(token, doc.waba_id, version)
	except graph.GraphError as e:
		_failed(doc, e)
	return _("Subscribed. Meta now lists {0} app(s) for this account.").format(len(apps))


@frappe.whitelist(methods=["POST"])
def sync_numbers(account):
	doc, token, version = _context(account)
	try:
		items = graph.list_numbers(token, doc.waba_id, version)
	except graph.GraphError as e:
		_failed(doc, e)

	created, updated, skipped = [], [], []
	for item in items:
		values = graph.number_values(item)
		existing = frappe.db.get_value("Waba Number", {"phone_number_id": values["phone_number_id"]}, "name")
		if existing:
			meta_fields = {k: v for k, v in values.items() if k in ("display_name", "name_status", "status", "quality_rating")}
			if meta_fields:
				frappe.db.set_value("Waba Number", existing, meta_fields, update_modified=False)
			updated.append(existing)
		elif e164(values.get("display_number")):
			# New numbers start OFF: the admin sets type, agents and routing first, then switches them on.
			frappe.get_doc(
				{"doctype": "Waba Number", "account": doc.name, "enabled": 0, "number_type": NUMBER_TYPE_SHARED, **values}
			).insert()
			created.append(values["display_number"])
		else:
			skipped.append(values["phone_number_id"])
	doc.db_set({"last_checked": now_datetime(), "last_error": None}, update_modified=False)
	return _("{0} new (switched off until you set them up), {1} updated, {2} skipped.").format(
		len(created), len(updated), len(skipped)
	)


def _sync_variable_rows(key, structure):
	"""One editable row per value the template needs. New slots get a row; rows already there (and what an admin set in them)
	are never touched; a slot the template no longer has is only switched off, so the choice survives if it comes back."""
	doc = frappe.get_doc("Waba Template", key)
	have = {row.slot: row for row in doc.variables}
	wanted = {slot["id"]: slot for slot in structure["slots"]}
	changed = False
	for slot_id, slot in wanted.items():
		row = have.get(slot_id)
		if row is None:
			doc.append("variables", {"slot": slot_id, "label": slot["label"], "source_type": "Ask each time", "active": 1})
			changed = True
		elif not row.active:
			row.active = 1
			changed = True
	for slot_id, row in have.items():
		if slot_id not in wanted and row.active:
			row.active = 0
			changed = True
	if changed:
		doc.flags.ignore_permissions = True
		doc.save()


@frappe.whitelist(methods=["POST"])
def sync_templates(account):
	from waba.rules.outbound import variable_count

	doc, token, version = _context(account)
	try:
		items = graph.list_templates(token, doc.waba_id, version)
	except graph.GraphError as e:
		_failed(doc, e)

	created = updated = 0
	seen = set()
	for item in items:
		values = graph.template_values(item)
		if not values["template_name"] or not values["language"]:
			continue
		key = f"{doc.name}|{values['template_name']}|{values['language']}"
		seen.add(key)
		structure = templates.parse(json.loads(values["components_json"]), values["parameter_format"])
		values.update(
			{
				"title": f"{values['template_name']} ({values['language']})",
				"account": doc.name,
				"variable_count": len(structure["body"]["slots"]) or variable_count(values["body_text"]),
				"last_synced": now_datetime(),
			}
		)
		if frappe.db.exists("Waba Template", key):
			frappe.db.set_value("Waba Template", key, values, update_modified=False)
			updated += 1
		else:
			frappe.get_doc({"doctype": "Waba Template", "template_key": key, **values}).insert(ignore_permissions=True)
			created += 1
		_sync_variable_rows(key, structure)

	removed = 0
	for name in frappe.get_all("Waba Template", filters={"account": doc.name, "status": ["not in", ["DELETED", "DRAFT"]]}, pluck="name"):  # a draft was never at Meta
		if name not in seen:
			frappe.db.set_value("Waba Template", name, {"status": "DELETED", "last_synced": now_datetime()}, update_modified=False)
			removed += 1
	doc.db_set({"last_checked": now_datetime(), "last_error": None}, update_modified=False)
	return _("{0} new, {1} updated, {2} no longer at Meta.").format(created, updated, removed)
