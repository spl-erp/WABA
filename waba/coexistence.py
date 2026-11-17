"""WhatsApp Business app coexistence, the Frappe side: apply Meta's `account_update` (the phone-app link changed) to the numbers
of that WhatsApp account that are marked as coexistence numbers, and tell the people who oversee them.

The pure decisions are in waba.rules.coexistence (tested offline). Nothing here sends a message to a customer."""

import frappe
from frappe import _
from frappe.utils import now_datetime

from waba import teams
from waba.rules import coexistence as rules


def has_fields():
	"""False until the migrate that adds the coexistence fields to Waba Number has run (new code before the migrate: do nothing)."""
	return frappe.get_meta("Waba Number").has_field("coexistence")


def apply_account_updates(payload, account):
	"""Handle every `account_update` change of a delivery. Returns the notes for the stored event."""
	notes = []
	for entry in payload.get("entry") or []:
		for change in (entry.get("changes") or []) if isinstance(entry, dict) else []:
			if not isinstance(change, dict) or change.get("field") != rules.ACCOUNT_FIELD:
				continue
			value = change.get("value") if isinstance(change.get("value"), dict) else {}
			event, state, reason = rules.account_event(value)
			numbers = frappe.get_all("Waba Number", filters={"account": account, "coexistence": 1}, pluck="name") if has_fields() else []
			if not numbers:
				notes.append(f"{event or 'account_update'}: no coexistence number on this account, nothing changed.")
				continue
			sentence = rules.state_sentence(event, state, reason)
			for number in numbers:
				if state:
					frappe.db.set_value("Waba Number", number, {"coexistence_state": state, "coexistence_at": now_datetime()}, update_modified=False)
				_tell(number, sentence)
			notes.append(f"{event or 'account_update'}: {len(numbers)} number(s) {'set to ' + state if state else 'noted'}.")
	return notes


def _tell(number, sentence):
	"""One Notification Log alert per person who oversees the number."""
	for user in teams.number_overseers(number, None):
		frappe.get_doc(
			{
				"doctype": "Notification Log",
				"for_user": user,
				"type": "Alert",
				"subject": _("WhatsApp number {0}: {1}").format(number, _(sentence)),
				"document_type": "Waba Number",
				"document_name": number,
			}
		).insert(ignore_permissions=True)
