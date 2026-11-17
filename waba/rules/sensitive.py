"""Spotting sensitive details in an outgoing message: Aadhaar, PAN, card, bank account, UPI id, one-time codes and PINs.
Pure: no database, no network, tested offline.

The aim is to stop an agent sharing these by accident or on purpose, without blocking ordinary text. So each type is checked as
tightly as it can be without the customer's data: Aadhaar and cards must pass their checksums, a PAN must have a valid shape, a bank
account number must have a bank word next to it, and a code must sit next to a word like OTP. Phone numbers, emails, dates, amounts,
order numbers and postal PIN codes are NOT flagged. The company's own identifiers go on an allow-list and always pass.

A hit never carries the raw value: `sample` is masked (last four digits at most).
"""

import re

AADHAAR = "aadhaar"
PAN = "pan"
CARD = "card"
BANK = "bank"
UPI = "upi"
OTP = "otp"
ALL = (AADHAAR, PAN, CARD, BANK, UPI, OTP)
LABELS = {
	AADHAAR: "an Aadhaar number",
	PAN: "a PAN",
	CARD: "a card number",
	BANK: "a bank account number",
	UPI: "a UPI ID",
	OTP: "a one-time code or PIN",
}

# ---- checksums

_D = (
	(0, 1, 2, 3, 4, 5, 6, 7, 8, 9), (1, 2, 3, 4, 0, 6, 7, 8, 9, 5), (2, 3, 4, 0, 1, 7, 8, 9, 5, 6), (3, 4, 0, 1, 2, 8, 9, 5, 6, 7),
	(4, 0, 1, 2, 3, 9, 5, 6, 7, 8), (5, 9, 8, 7, 6, 0, 4, 3, 2, 1), (6, 5, 9, 8, 7, 1, 0, 4, 3, 2), (7, 6, 5, 9, 8, 2, 1, 0, 4, 3),
	(8, 7, 6, 5, 9, 3, 2, 1, 0, 4), (9, 8, 7, 6, 5, 4, 3, 2, 1, 0),
)
_P = (
	(0, 1, 2, 3, 4, 5, 6, 7, 8, 9), (1, 5, 7, 6, 2, 8, 3, 0, 9, 4), (5, 8, 0, 3, 7, 9, 6, 1, 4, 2), (8, 9, 1, 6, 0, 4, 3, 5, 2, 7),
	(9, 4, 5, 3, 1, 2, 6, 8, 7, 0), (4, 2, 8, 6, 5, 7, 3, 9, 0, 1), (2, 7, 9, 3, 8, 0, 6, 4, 1, 5), (7, 0, 4, 6, 9, 1, 3, 2, 5, 8),
)


def verhoeff_valid(digits):
	"""The check Aadhaar numbers pass (the last digit is a Verhoeff check digit)."""
	c = 0
	for i, ch in enumerate(reversed(digits)):
		c = _D[c][_P[i % 8][int(ch)]]
	return c == 0


def verhoeff_check_digit(prefix):
	"""The digit that makes prefix + digit pass `verhoeff_valid` (used to build test numbers)."""
	return next(d for d in range(10) if verhoeff_valid(prefix + str(d)))


def luhn_valid(digits):
	"""The check payment card numbers pass."""
	total = 0
	for i, ch in enumerate(reversed(digits)):
		n = int(ch)
		if i % 2 == 1:
			n *= 2
			if n > 9:
				n -= 9
		total += n
	return total % 10 == 0


def luhn_check_digit(prefix):
	return next(d for d in range(10) if luhn_valid(prefix + str(d)))


# ---- masking

def _only_digits(text):
	return re.sub(r"\D", "", text)


def _mask_digits(digits, group=None):
	last = digits[-4:]
	if group == AADHAAR:
		return f"XXXX XXXX {last}"
	if group == CARD:
		return f"XXXX XXXX XXXX {last}"
	return "X" * max(len(digits) - 4, 2) + last


def _mask_pan(pan):
	return pan[:3] + "******" + pan[-1]


def _mask_upi(handle, domain):
	return f"{handle[0]}***@{domain}"


# ---- detection

_AADHAAR = re.compile(r"(?<![\d.])([2-9]\d{3})[ -]?(\d{4})[ -]?(\d{4})(?![\d])")
_PAN = re.compile(r"(?<![A-Za-z0-9])([A-Za-z]{3})([PCHFATBLJGpchfatblj])([A-Za-z])(\d{4})([A-Za-z])(?![A-Za-z0-9])")
_CARD = re.compile(r"(?<![\d.])(?:\d[ -]?){12,18}\d(?![\d])")
_RUN = re.compile(r"(?<![\d.])\d{9,18}(?![\d])")
_BANK_WORDS = re.compile(r"(?i)(?:\ba/?c\b|\ba\.c\b|\bacc\b|\baccount\b|\bbank\b|\bifsc\b|\bsavings\b|\bcurrent a)")
_UPI = re.compile(r"(?<![\w.+-])([A-Za-z0-9._-]{2,64})@([A-Za-z][A-Za-z0-9]{1,24})(?![\w@-]|\.\w)")
# keyword -> (smallest, largest) number of digits of the code that goes with it
_OTP_WORDS = (
	(re.compile(r"(?i)\b(?:otp|one[- ]?time[- ](?:password|code|pin)|verification code|security code|passcode|password)\b"), (4, 8)),
	(re.compile(r"(?i)\b(?:cvv|cvc)\b"), (3, 4)),
	(re.compile(r"(?i)\bpin\b(?!\s*-?\s*code)"), (4, 4)),
)
_CODE = re.compile(r"(?<![\d.])\d{3,8}(?![\d.])")
_NEAR = 30


def _card_network(digits):
	"""Does the number start and end like a card of a known network? (A long number that only happens to pass the checksum does not.)"""
	n, p = len(digits), digits
	if p[0] == "4" and n in (13, 16, 19):
		return True  # Visa
	if n == 16 and (51 <= int(p[:2]) <= 55 or 2221 <= int(p[:4]) <= 2720):
		return True  # Mastercard
	if n == 15 and p[:2] in ("34", "37"):
		return True  # American Express
	if n in (14, 15, 16, 17, 18, 19) and (p[:2] in ("36", "38", "39") or 300 <= int(p[:3]) <= 305):
		return True  # Diners Club
	if 16 <= n <= 19 and (p[:4] == "6011" or p[:2] == "65" or 644 <= int(p[:3]) <= 649 or p[:2] in ("60", "81", "82") or p[:3] == "508"):
		return True  # Discover, RuPay
	if 16 <= n <= 19 and 3528 <= int(p[:4]) <= 3589:
		return True  # JCB
	if 12 <= n <= 19 and (p[:4] in ("5018", "5020", "5038", "5893", "6304", "6759", "6761", "6762", "6763")):
		return True  # Maestro
	return False


def parse_allow_list(text):
	"""The allowed identifiers (one per line or comma separated) as a set that `scan` understands."""
	allowed = set()
	for item in re.split(r"[\n,;]+", text or ""):
		item = item.strip()
		if not item:
			continue
		allowed.add(item.lower())
		allowed.add(item.upper())
		digits = _only_digits(item)
		if len(digits) >= 8:
			allowed.add(digits)
	return frozenset(allowed)


def _is_allowed(value, allow):
	if not allow:
		return False
	digits = _only_digits(value)
	return value.lower() in allow or value.upper() in allow or (len(digits) >= 8 and digits in allow)


def scan(text, enabled=ALL, allow=frozenset()):
	"""[{code, label, sample}] for every sensitive detail found in `text`, in order of appearance."""
	text = str(text or "")
	enabled = set(enabled or ())
	found = []  # (position, hit)
	taken = []  # spans already explained by a stricter type, so one number is not reported twice

	def free(span):
		return not any(span[0] < b and a < span[1] for a, b in taken)

	def add(code, span, sample):
		found.append((span[0], {"code": code, "label": LABELS[code], "sample": sample}))
		taken.append(span)

	if AADHAAR in enabled:
		for m in _AADHAAR.finditer(text):
			digits = "".join(m.groups())
			before = text[max(0, m.start() - 3) : m.start()]
			mobile_with_country_code = digits.startswith("91") and digits[2] in "6789"
			if "+" in before or mobile_with_country_code:
				continue  # a phone number with its country code, not an Aadhaar
			if verhoeff_valid(digits) and not _is_allowed(digits, allow) and free(m.span()):
				add(AADHAAR, m.span(), _mask_digits(digits, AADHAAR))
	if PAN in enabled:
		for m in _PAN.finditer(text):
			value = m.group(0).upper()
			if not _is_allowed(value, allow) and free(m.span()):
				add(PAN, m.span(), _mask_pan(value))
	if BANK in enabled:
		for m in _RUN.finditer(text):
			digits = m.group(0)
			if len(digits) == 10 and digits[0] in "6789":
				continue  # a mobile number
			window = text[max(0, m.start() - 40) : m.end() + 40]
			if _BANK_WORDS.search(window) and not _is_allowed(digits, allow) and free(m.span()):
				add(BANK, m.span(), _mask_digits(digits))
	if CARD in enabled:
		for m in _CARD.finditer(text):
			digits = _only_digits(m.group(0))
			if 13 <= len(digits) <= 19 and luhn_valid(digits) and _card_network(digits) and not _is_allowed(digits, allow) and free(m.span()):
				add(CARD, m.span(), _mask_digits(digits, CARD))
	if UPI in enabled:
		for m in _UPI.finditer(text):
			value = m.group(0)
			if not _is_allowed(value, allow) and free(m.span()):
				add(UPI, m.span(), _mask_upi(m.group(1), m.group(2)))
	if OTP in enabled:
		for word, (low, high) in _OTP_WORDS:
			for m in word.finditer(text):
				ahead = _CODE.search(text, m.end(), min(len(text), m.end() + _NEAR))
				behind = None
				for c in _CODE.finditer(text, max(0, m.start() - _NEAR), m.start()):
					behind = c
				for code in (ahead, behind):
					if code and low <= len(code.group(0)) <= high and not _is_allowed(code.group(0), allow) and free(code.span()):
						add(OTP, code.span(), "X" * len(code.group(0)))
						break
	found.sort(key=lambda pair: pair[0])
	return [hit for _pos, hit in found]


def describe(hits):
	"""'an Aadhaar number (XXXX XXXX 1234) and a PAN (ABC******F)': what to tell the person."""
	parts = [f"{h['label']} ({h['sample']})" for h in hits]
	if not parts:
		return ""
	return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]
