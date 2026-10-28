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
