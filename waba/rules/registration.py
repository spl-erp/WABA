"""Registering a phone number for the Cloud API: what to check before calling Meta, and what a number's state means in plain
words. Pure: no database, no network, tested offline.

Meta's order for a new number: (1) it must be verified with a one-time code (SMS or voice), (2) it is registered with a
6-digit two-step PIN the owner chooses. Status CONNECTED means that is done; PENDING means registration is still missing.
The display-name review (name_status) runs on its own.
"""

import re

METHODS = ("SMS", "VOICE")
_PIN = re.compile(r"^\d{6}$")
_LANG = re.compile(r"^[a-z]{2,3}(_[A-Z]{2})?$")

REQUEST_CODE = "request_code"
REGISTER = "register"
DONE = "done"
ATTENTION = "attention"


def clean_pin(value):
	"""(pin, problem): exactly six digits."""
	pin = str(value or "").strip()
	if not _PIN.match(pin):
		return None, "The PIN must be exactly 6 digits."
	return pin, None


def clean_code(value):
	"""(code, problem): the one-time code, as Meta sends it (123456 or 123-456)."""
	code = re.sub(r"[\s-]", "", str(value or ""))
	if not _PIN.match(code):
		return None, "The code is 6 digits."
	return code, None


def clean_method(value):
	method = str(value or "SMS").strip().upper()
	return (method, None) if method in METHODS else (None, "Choose SMS or voice.")


def clean_language(value):
	language = str(value or "en_US").strip()
	return (language, None) if _LANG.match(language) else (None, "The language must look like en_US.")


def state(info):
	"""{next, text, verified, status, name_status} from Meta's phone-number fields.

	next is request_code (not verified yet), register (verified, not registered), done (connected) or attention
	(restricted, flagged or disconnected for another reason)."""
	info = info or {}
	status = str(info.get("status") or "").upper()
	name_status = str(info.get("name_status") or "").upper()
	verified = str(info.get("code_verification_status") or "").upper() == "VERIFIED"
	if status in ("RESTRICTED", "FLAGGED", "RATE_LIMITED"):
		step, text = ATTENTION, f"Meta shows this number as {status.lower().replace('_', ' ')}. Look at it in WhatsApp Manager before anything else."
	elif status == "CONNECTED":
		step, text = DONE, "This number is registered and connected."
	elif not verified:
		step, text = REQUEST_CODE, "The number is not verified yet. Ask Meta to send a code to it, then enter the code."
	else:
		step, text = REGISTER, "The number is verified but not registered. Register it with a 6-digit PIN you choose."
	if name_status in ("PENDING_REVIEW", "NONE", "EXPIRED"):
		text += " Its display name is still waiting for Meta's review."
	elif name_status == "DECLINED":
		text += " Meta declined its display name; fix that in WhatsApp Manager."
	return {"next": step, "text": text, "verified": verified, "status": status, "name_status": name_status}
