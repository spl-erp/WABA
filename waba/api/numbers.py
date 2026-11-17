"""Register a WhatsApp number with Meta from the ERP: check its state, ask for the one-time code, enter the code, register with a
6-digit PIN. Waba Admin and System Manager only. Each call contacts Meta once; no message is sent and nothing is charged.

The PIN and the code go straight to Meta. They are never logged, never put in a note, and the PIN is stored (encrypted) only
when the person ticks "Save the PIN". Meta's own refusal is shown in plain words. The real calls are UNVERIFIED until Meta's
API block is lifted; every path is covered by tests with a fake Meta.
"""

import frappe
from frappe import _
from frappe.utils import now_datetime
from frappe.utils.password import get_decrypted_password, set_encrypted_password

from waba.api import send
from waba.constants import DEFAULT_API_VERSION, ROLE_ADMIN
from waba.meta import graph
from waba.rules import registration as rules

ADMINS = ("System Manager", ROLE_ADMIN)
DOCTYPE = "Waba Number"


def _context(number):
	frappe.only_for(ADMINS)
	doc = frappe.get_doc(DOCTYPE, number)
	if not doc.phone_number_id:
		frappe.throw(_("This number has no phone number ID yet. Run Sync numbers on its account first."))
	account = frappe.get_doc("Waba Account", doc.account)
	if not account.enabled:
		frappe.throw(_("The WhatsApp account {0} is switched off.").format(account.name))
	token = get_decrypted_password("Waba Portfolio", account.portfolio, "access_token", raise_exception=False)
	if not token:
		frappe.throw(_("Save the access token on the portfolio {0} first.").format(account.portfolio))
	return doc, account, token, account.api_version or DEFAULT_API_VERSION


def _not_coexistence(doc):
	"""A number that is also in the WhatsApp Business app (coexistence) must never go through these steps: registering or
	verifying it again would cut the phone app link."""
	if doc.get("coexistence"):
		frappe.throw(_("This number is used in the WhatsApp Business app as well (coexistence). It is already registered; do not register or verify it again."))


def _problem(text):
	frappe.throw(_(text))


def _failed(account, error):
	text = graph.explain(error)
	send._note_account_problem(account, error, text)
	return {"ok": False, "error": text}


def _remember(doc, info):
	"""Write what Meta says about the number's state onto the record (a refresh of the read-only fields)."""
	verification = str(info.get("code_verification_status") or "").upper()
	values = {"code_verification_status": verification or None}
	for field in ("status", "name_status", "quality_rating"):
		if info.get(field):
			values[field] = str(info[field]).upper()
	frappe.db.set_value(DOCTYPE, doc.name, values, update_modified=False)


@frappe.whitelist()
def check(number: str):
	"""Ask Meta for the number's state and say what the next step is."""
	doc, account, token, version = _context(number)
	try:
		info = graph.number_state(token, doc.phone_number_id, version)
	except graph.GraphError as e:
		return _failed(account, e)
	_remember(doc, info)
	return {"ok": True, **rules.state(info)}


@frappe.whitelist(methods=["POST"])
def request_code(number: str, method: str = "SMS", language: str = "en_US"):
	"""Meta sends a one-time code to the number itself by SMS or voice call."""
	doc, account, token, version = _context(number)
	_not_coexistence(doc)
	method, problem = rules.clean_method(method)
	if problem:
		_problem(problem)
	language, problem = rules.clean_language(language)
	if problem:
		_problem(problem)
	try:
		graph.request_code(token, doc.phone_number_id, method, language, version)
	except graph.GraphError as e:
		return _failed(account, e)
	return {"ok": True, "note": _("Meta is sending a code to {0} by {1}. Enter it next.").format(doc.display_number, "SMS" if method == "SMS" else _("voice call"))}


@frappe.whitelist(methods=["POST"])
def verify_code(number: str, code: str):
	"""Enter the one-time code Meta sent to the number."""
	doc, account, token, version = _context(number)
	_not_coexistence(doc)
	code, problem = rules.clean_code(code)
	if problem:
		_problem(problem)
	try:
		graph.verify_code(token, doc.phone_number_id, code, version)
	except graph.GraphError as e:
		return _failed(account, e)
	frappe.db.set_value(DOCTYPE, doc.name, "code_verification_status", "VERIFIED", update_modified=False)
	return {"ok": True, "note": _("The number is verified. The next step is to register it with a 6-digit PIN.")}


@frappe.whitelist(methods=["POST"])
def register(number: str, pin: str, remember: int = 0, confirm: int = 0):
	"""Register the number for the Cloud API with a 6-digit two-step PIN. From then on it runs on the API, not in the WhatsApp app."""
	if not int(confirm or 0):
		frappe.only_for(ADMINS)
		frappe.throw(_("Confirm the registration first."))
	doc, account, token, version = _context(number)
	_not_coexistence(doc)
	pin, problem = rules.clean_pin(pin)
	if problem:
		_problem(problem)
	try:
		graph.register_number(token, doc.phone_number_id, pin, version)
	except graph.GraphError as e:
		return _failed(account, e)
	if int(remember or 0):
		set_encrypted_password(DOCTYPE, doc.name, pin, "registration_pin")
	frappe.db.set_value(
		DOCTYPE,
		doc.name,
		{"registered_at": now_datetime(), "registration_note": _("Registered with Meta from the ERP. Run Sync numbers to refresh its status.")},
		update_modified=False,
	)
	state = None
	try:  # a fresh read, so the form shows what Meta now says
		info = graph.number_state(token, doc.phone_number_id, version)
		_remember(doc, info)
		state = rules.state(info)
	except graph.GraphError:
		pass
	return {"ok": True, "note": _("Registered. It can take a moment for Meta to show it as connected."), "state": state}
