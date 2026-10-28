"""Who is this customer? Waba itself knows only what it has stored: the WhatsApp user ID (BSUID) -> record pairs of
the Identity store. Finding a Lead, Contact or Customer BY PHONE NUMBER is company-specific (Splashjet has an indexed
Phone Lookup), so Waba asks the apps that care through the hook

    waba_party_matchers = ["myapp.module.function"]      # in an app's hooks.py

Each function takes an E.164 phone ("+919876543210") and returns {"doctype": ..., "name": ...} or None. The first
hit wins. With no matcher installed every sender simply stays in the triage list.
"""

import frappe


def find_party(phone, bsuid, portfolio):
	"""(doctype, name) of the customer's record, or None."""
	if bsuid:
		known = frappe.db.get_value(
			"Waba Identity", {"identity_key": identity_key(portfolio, bsuid)}, ["party_doctype", "party"], as_dict=True
		)
		if known and known.party_doctype and known.party and frappe.db.exists(known.party_doctype, known.party):
			return known.party_doctype, known.party
	if phone:
		for path in frappe.get_hooks("waba_party_matchers"):
			try:
				hit = frappe.get_attr(path)(phone)
			except Exception:
				frappe.log_error(title=f"Waba: matcher {path} failed")
				continue
			if hit and hit.get("doctype") and hit.get("name"):
				return hit["doctype"], hit["name"]
	return None


def identity_key(portfolio, bsuid):
	return f"{portfolio}|{bsuid}"


def remember_identity(portfolio, bsuid, phone=None, profile_name=None, party=None):
	"""Keep the BSUID -> phone / record pair. Only fills what is known; never erases."""
	if not bsuid:
		return
	key = identity_key(portfolio, bsuid)
	values = {"phone": phone, "profile_name": profile_name}
	if party:
		values["party_doctype"], values["party"] = party
	values = {k: v for k, v in values.items() if v}
	name = frappe.db.get_value("Waba Identity", {"identity_key": key}, "name")
	if name:
		if values:
			frappe.db.set_value("Waba Identity", name, values, update_modified=False)
		return
	try:
		frappe.get_doc(
			{"doctype": "Waba Identity", "identity_key": key, "portfolio": portfolio, "bsuid": bsuid, **values}
		).insert(ignore_permissions=True)
	except frappe.DuplicateEntryError:
		pass
