"""What a bot may say about a customer's own Quotation, Sales Order or Sales Invoice. Pure: no database, no Frappe.

The database side (waba.bot_records) finds the customer's latest document and passes its fields here; this module only turns
them into the plain values a bot message may use. Nothing here decides WHOSE document it is: that is the lookup's job, and it
is restricted to the chat's own matched record."""

import datetime
import re

QUOTATION, SALES_ORDER, SALES_INVOICE = "Quotation", "Sales Order", "Sales Invoice"
DOC_TYPES = (QUOTATION, SALES_ORDER, SALES_INVOICE)
DOC_VARS = ("doc_name", "doc_status", "doc_date", "doc_total", "doc_outstanding", "doc_due_date")
DOC_VAR_HELP = {
	"doc_name": "the document number",
	"doc_status": "its status",
	"doc_date": "its date",
	"doc_total": "the total",
	"doc_outstanding": "the amount still to be paid (invoices)",
	"doc_due_date": "the payment due date (invoices)",
}


def _date(value):
	if not value:
		return ""
	if isinstance(value, (datetime.date, datetime.datetime)):
		return value.strftime("%d-%m-%Y")
	text = str(value)[:10]
	m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", text)
	return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else text


def variables(doctype, row, money=None):
	"""{"doc_name", "doc_status", ...} for one document. `row` has name, status, date, total, outstanding, due_date, currency.
	`money(amount, currency)` formats an amount (the glue passes the site's formatter); without it a plain number is used."""
	row = row or {}
	fmt = money or (lambda amount, currency: f"{currency + ' ' if currency else ''}{float(amount or 0):,.2f}")
	show_outstanding = doctype == SALES_INVOICE
	return {
		"doc_name": str(row.get("name") or ""),
		"doc_status": str(row.get("status") or ""),
		"doc_date": _date(row.get("date")),
		"doc_total": fmt(row.get("total"), row.get("currency")) if row.get("total") is not None else "",
		"doc_outstanding": fmt(row.get("outstanding"), row.get("currency")) if show_outstanding and row.get("outstanding") is not None else "",
		"doc_due_date": _date(row.get("due_date")) if show_outstanding else "",
	}
