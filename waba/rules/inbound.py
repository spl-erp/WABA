"""Turn the `messages` part of a Meta delivery into plain records (no Frappe, tested offline).

Customer identity. Meta delivers a phone number as plain digits ("919876543210"). Since 2026 it also delivers a
business-scoped user id (BSUID, looks like "IN.xxxxx"); a customer with a WhatsApp username may arrive with the id
and NO phone number. The exact BSUID field names are UNVERIFIED against live Meta, so several candidates are read:
message `from` (phone or id), `from_user_id`, `user_id`; contact `wa_id`, `user_id`. The first usable phone wins as the
phone, the first id-looking value as the BSUID. A value with a letter or a dot is never treated as a phone number
(an id such as "IN.1234567890123" contains digits that would otherwise pass as one).
"""

import re

from waba.rules.phone import e164

_ID_LIKE = re.compile(r"[A-Za-z.]")
PREVIEW_LIMIT = 140

# type -> where its readable text lives inside the message
_CAPTIONED = ("image", "video", "document", "audio", "sticker")


def is_bsuid(value):
	return bool(value) and bool(_ID_LIKE.search(str(value)))


def _identity(values):
	phone = bsuid = None
	for value in values:
		if value in (None, ""):
			continue
		text = str(value).strip()
		if is_bsuid(text):
			bsuid = bsuid or text
		else:
			phone = phone or e164(text)
	return phone, bsuid


def parse_messages(value):
	"""One dict per inbound message in a `messages` change value, in the order Meta sent them."""
	contacts = [c for c in (value.get("contacts") or []) if isinstance(c, dict)]
	out = []
	for message in value.get("messages") or []:
		if not isinstance(message, dict) or not message.get("id"):
			continue
		sender = message.get("from")
		contact = next(
			(c for c in contacts if sender and sender in (c.get("wa_id"), c.get("user_id"))),
			contacts[0] if len(contacts) == 1 else {},
		)
		phone, bsuid = _identity(
			[sender, message.get("from_user_id"), message.get("user_id"), contact.get("wa_id"), contact.get("user_id")]
		)
		profile = contact.get("profile") if isinstance(contact.get("profile"), dict) else {}
		kind = str(message.get("type") or "unknown")
		out.append(
			{
				"message_id": str(message["id"]),
				"phone": phone,
				"bsuid": bsuid,
				"profile_name": profile.get("name"),
				"timestamp": _int(message.get("timestamp")),
				"type": kind,
				"body": body_text(message, kind),
				"reply_to": (message.get("context") or {}).get("id") if isinstance(message.get("context"), dict) else None,
				**details(message, kind),
			}
		)
	return out


def details(message, kind):
	"""The structured parts of a message kept beside its readable text: file reference, place, contact card, reaction
	target and button or list reply id. Keys that do not apply are None, so every message has the same shape."""
	part = message.get(kind) if isinstance(message.get(kind), dict) else {}
	out = {
		"media_id": None, "media_mime": None, "media_sha256": None, "media_filename": None, "voice": 0,
		"latitude": None, "longitude": None, "contacts": None, "reaction_to": None, "interactive_id": None,
	}
	if kind in _CAPTIONED:
		out.update(
			media_id=str(part["id"]) if part.get("id") else None,
			media_mime=part.get("mime_type"),
			media_sha256=part.get("sha256"),
			media_filename=part.get("filename"),
			voice=1 if part.get("voice") else 0,
		)
	elif kind == "location":
		out.update(latitude=_float(part.get("latitude")), longitude=_float(part.get("longitude")))
	elif kind == "contacts":
		cards = message.get("contacts") if isinstance(message.get("contacts"), list) else []
		out["contacts"] = [_card(c) for c in cards if isinstance(c, dict)] or None
	elif kind == "reaction":
		out["reaction_to"] = part.get("message_id")
	elif kind == "interactive":
		reply = part.get("button_reply") or part.get("list_reply") or {}
		out["interactive_id"] = reply.get("id")
	elif kind == "button":
		out["interactive_id"] = part.get("payload")
	return out


def _card(card):
	name = card.get("name") if isinstance(card.get("name"), dict) else {}
	phones = [p.get("phone") or p.get("wa_id") for p in (card.get("phones") or []) if isinstance(p, dict)]
	return {"name": name.get("formatted_name") or name.get("first_name") or "", "phones": [p for p in phones if p]}


def _float(value):
	try:
		return float(value)
	except (TypeError, ValueError):
		return None


def body_text(message, kind):
	"""The readable text of a message, or a bracketed label for things that are not text."""
	part = message.get(kind) if isinstance(message.get(kind), dict) else {}
	if kind == "text":
		return part.get("body") or ""
	if kind in _CAPTIONED:
		caption = part.get("caption") or part.get("filename")
		return f"[{kind}] {caption}".strip() if caption else f"[{kind}]"
	if kind == "button":
		return part.get("text") or "[button]"
	if kind == "interactive":
		reply = part.get("button_reply") or part.get("list_reply") or {}
		return reply.get("title") or "[interactive]"
	if kind == "location":
		text = " ".join(str(part.get(k)) for k in ("name", "address") if part.get(k))
		pin = f"https://www.google.com/maps?q={part['latitude']},{part['longitude']}" if part.get("latitude") is not None and part.get("longitude") is not None else ""
		return " ".join(x for x in ("[location]", text, pin) if x)
	if kind == "reaction":
		return part.get("emoji") or "[reaction]"
	if kind == "contacts":
		cards = [_card(c) for c in (message.get("contacts") or []) if isinstance(c, dict)]
		names = ", ".join(c["name"] for c in cards if c["name"])
		return f"[contacts] {names}".strip()
	return f"[{kind}]"


def preview(text):
	text = " ".join(str(text or "").split())
	return text if len(text) <= PREVIEW_LIMIT else text[: PREVIEW_LIMIT - 1] + "…"


def customer_label(profile_name, phone, bsuid):
	"""How a customer is named in lists: "Rahul · +919876543210", or just the phone / user ID when there is no name."""
	who = phone or bsuid or ""
	name = (profile_name or "").strip()
	return f"{name} · {who}" if name and who else (name or who or "Unknown")


def conversation_key(number, phone, bsuid):
	"""One thread per (business number, customer). The phone is the customer's identity when we have it; a
	username-only customer is identified by the BSUID. None when the sender cannot be identified at all."""
	who = phone or bsuid
	return f"{number}|{who}" if who and number else None


def _int(value):
	try:
		return int(value)
	except (TypeError, ValueError):
		return None
