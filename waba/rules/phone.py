"""Phone numbers as WhatsApp gives them, turned into one canonical key.

Meta shows a number as "+91 98765 43210" (display_phone_number) but delivers it as plain digits
("919876543210") in webhooks and expects plain digits when sending. Both mean the same international
number, so the canonical form here is "+" followed by the digits. Text in, text out: no database, no
Frappe, so the log, the matcher and the sender can never disagree on the key.

**For numbers that come from Meta only** (webhooks, the Graph API): their digits are always international.
A number typed by a person (a Lead's phone) must be given its country explicitly before it is turned into a
key; it must never be passed here bare, because 10 plain digits would become a wrong "+<digits>". The typed-
number helper arrives with the send action. None means "not a usable international number".
"""

import re

MIN_DIGITS = 7
MAX_DIGITS = 15  # E.164's limit


def e164(raw):
	"""Return "+<digits>" for an international number, or None if `raw` is not usable."""
	if raw is None:
		return None
	text = str(raw).strip()
	if not text:
		return None
	digits = re.sub(r"\D", "", text)
	if text.startswith("00"):  # international call prefix written instead of "+"
		digits = digits[2:]
	if not MIN_DIGITS <= len(digits) <= MAX_DIGITS:
		return None
	return "+" + digits


def wa_digits(raw):
	"""The plain-digit form Meta expects in the `to` field of a send request, or None."""
	key = e164(raw)
	return key[1:] if key else None


DEFAULT_COUNTRY_CODE = "91"


def from_typed(raw, default_country_code=DEFAULT_COUNTRY_CODE):
	"""The "+<digits>" key for a number a PERSON typed (a Lead's phone), or None when it cannot be told apart from a wrong number.

	An explicit country ("+91...", "0091...") is taken as written. A bare number is given `default_country_code` only
	when its shape is unambiguous: 10 digits, or 11 digits with the national "0" in front, or the country code already
	written without the "+" (12 digits for +91). For India the 10 digits must be a mobile number (starts with 6 to 9),
	because a WhatsApp customer is on a mobile. Anything else (a landline with an STD code, 8 or 9 digits, a number
	with letters mixed in) returns None so the rep is asked to correct it instead of messaging a stranger."""
	if raw is None:
		return None
	text = str(raw).strip()
	if not text or re.search(r"[A-Za-z]", text.replace("ext", "").replace("x", "")):
		return None
	if text.startswith("+") or text.startswith("00"):
		return e164(text)
	digits = re.sub(r"\D", "", text)
	cc = str(default_country_code or "").lstrip("+")
	national = None
	if len(digits) == 10:
		national = digits
	elif len(digits) == 11 and digits.startswith("0"):
		national = digits[1:]
	elif cc and len(digits) == len(cc) + 10 and digits.startswith(cc):
		national = digits[len(cc):]
	if national is None:
		return None
	if cc == "91" and national[0] not in "6789":
		return None
	return e164("+" + cc + national)
