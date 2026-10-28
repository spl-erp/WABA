"""The buttons on the WhatsApp Account form: Test connection, Subscribe webhook, Sync numbers.
Admin only. Each button calls Meta with the portfolio's token, records what it learned on the account and says
in plain words what happened."""

import frappe
from frappe import _
from frappe.utils import now_datetime
from frappe.utils.password import get_decrypted_password

from waba.constants import DEFAULT_API_VERSION, NUMBER_TYPE_SHARED, ROLE_ADMIN
from waba.meta import graph
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
