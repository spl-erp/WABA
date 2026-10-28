"""Rep tags: how a QR code or a wa.me link tells the ERP which rep a new conversation is for.

A link carries a prefilled message of at most 140 characters (Meta's limit). The tag is a short rep code in
square brackets at the end, for example "Hello, I want a quotation [R12]". When the customer sends it, the
first message contains the tag and routing can send the conversation to that rep.
"""

import re

PREFILL_MAX = 140
CODE = re.compile(r"[A-Za-z0-9_-]{1,20}")
_TAG = re.compile(r"\[([A-Za-z0-9_-]{1,20})\]")


def is_valid_code(code):
	return bool(code) and CODE.fullmatch(str(code)) is not None


def extract_rep_tag(text):
	"""The last [CODE] in a message, or "" if there is none. Codes are compared case-insensitively."""
	if not text:
		return ""
	found = _TAG.findall(str(text))
	return found[-1] if found else ""


def make_prefill_text(base, code):
	"""`base` + " [code]", with `base` shortened if needed so the result stays within 140 characters."""
	if not is_valid_code(code):
		raise ValueError("A rep code is 1 to 20 letters, digits, underscores or hyphens.")
	suffix = f" [{code}]"
	room = PREFILL_MAX - len(suffix)
	base = (base or "").strip()
	if len(base) > room:
		base = base[: max(room - 1, 0)].rstrip() + "…"
	return (base + suffix).strip()
