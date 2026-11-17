"""What a bot may look up or send from the ERP, for ONE chat. The database side of rules/bot_docs.py.

The bot runs as the system, so ERP permissions do not protect anything here: the protection is that every query is filtered to
the chat's OWN matched record (a Customer, or the Customer of a Contact, or a Lead and the Customer it became). A document
number is never taken from what the customer typed, and a chat with no matched record gets nothing."""

import frappe
from frappe.utils import fmt_money, getdate

from waba.rules import bot_docs


def customer_scope(conv):
	"""(customers, leads): the records whose documents belong to this chat. Empty when the chat is not matched to a record."""
	doctype, name = conv.party_doctype, conv.party
	if not doctype or not name or not frappe.db.exists(doctype, name):
		return [], []
	if doctype == "Customer":
		return [name], []
	if doctype == "Contact":
		links = frappe.get_all("Dynamic Link", filters={"parent": name, "parenttype": "Contact", "link_doctype": ["in", ["Customer", "Lead"]]}, fields=["link_doctype", "link_name"])
		return [x.link_name for x in links if x.link_doctype == "Customer"], [x.link_name for x in links if x.link_doctype == "Lead"]
	if doctype == "Lead":
		customers = frappe.get_all("Customer", filters={"lead_name": name}, pluck="name") if frappe.get_meta("Customer").has_field("lead_name") else []
		return customers, [name]
	return [], []


def _money(amount, currency):
	try:
		return fmt_money(amount, currency=currency)
	except Exception:
		return f"{currency + ' ' if currency else ''}{float(amount or 0):,.2f}"


def _latest(rows):
	rows = [r for r in rows if r]
	return max(rows, key=lambda r: (str(r.get("date") or ""), str(r.get("creation") or ""))) if rows else None


def _quotation(customers, leads):
	rows = []
	for party_type, names in (("Customer", customers), ("Lead", leads)):
		if names:
			rows += frappe.get_all(
				"Quotation",
				filters={"docstatus": 1, "quotation_to": party_type, "party_name": ["in", names]},
				fields=["name", "status", "transaction_date as date", "grand_total as total", "currency", "creation"],
				order_by="transaction_date desc, creation desc",
				limit_page_length=1,
			)
	return _latest(rows)


def _sales_order(customers, _leads):
	if not customers:
		return None
	rows = frappe.get_all(
		"Sales Order",
		filters={"docstatus": 1, "customer": ["in", customers]},
		fields=["name", "status", "transaction_date as date", "grand_total as total", "currency", "creation"],
		order_by="transaction_date desc, creation desc",
		limit_page_length=1,
	)
	return _latest(rows)


def _sales_invoice(customers, _leads):
	if not customers:
		return None
	rows = frappe.get_all(
		"Sales Invoice",
		filters={"docstatus": 1, "is_return": 0, "customer": ["in", customers]},
		fields=["name", "status", "posting_date as date", "grand_total as total", "outstanding_amount as outstanding", "due_date", "currency", "creation"],
		order_by="posting_date desc, creation desc",
		limit_page_length=1,
	)
	return _latest(rows)


_FIND = {bot_docs.QUOTATION: _quotation, bot_docs.SALES_ORDER: _sales_order, bot_docs.SALES_INVOICE: _sales_invoice}


def latest_documents(conv, doctypes):
	"""{document type: the values a bot message may use, or None} for the chat's OWN latest submitted document of each type asked for."""
	customers, leads = customer_scope(conv)
	out = {}
	for doctype in doctypes:
		finder = _FIND.get(doctype)
		row = finder(customers, leads) if finder else None
		out[doctype] = bot_docs.variables(doctype, row, _money) if row else None
	return out


def files_status(names):
	"""{library file name: may a bot send it now}. The administrator who built the bot chose the file, so its team scope is not
	applied; it must be enabled, not expired and still have its file."""
	today = getdate()
	out = {}
	for name in names:
		row = frappe.db.get_value("Waba Shared File", name, ["enabled", "valid_until", "file"], as_dict=True) if name else None
		out[name] = bool(row and row.enabled and row.file and (not row.valid_until or getdate(row.valid_until) >= today))
	return out


def library_file(name):
	"""(content, filename) of a library file, or None."""
	url = frappe.db.get_value("Waba Shared File", name, "file")
	record = frappe.get_doc("File", {"file_url": url}) if url else None
	if not record:
		return None
	with open(record.get_full_path(), "rb") as handle:
		return handle.read(), record.file_name


def pdf_of(doctype, name):
	"""The PDF of an ERP document, or None. The caller has already taken `name` from latest_documents, never from the customer."""
	if doctype not in bot_docs.DOC_TYPES or not name or not frappe.db.exists(doctype, name):
		return None
	return frappe.get_print(doctype, name, as_pdf=True)
