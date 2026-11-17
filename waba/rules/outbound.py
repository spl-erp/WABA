"""What may be sent, and the exact JSON Meta expects (no Frappe, tested offline).

Free text is allowed only while the 24-hour window is open (see rules/window.py); outside it only an approved template.
Template variables are positional ({{1}}, {{2}} ...). Meta rejects a template parameter that is empty, contains a
line break or tab, has more than four spaces in a row, or is very long (error 132018 / 132000); those are checked here
so the agent is told before anything is sent. NAMED template parameters are not supported yet.
"""

import re

from waba.rules import window
from waba.rules.phone import wa_digits

MAX_TEXT = 4096
MAX_PARAM = 1024
_VARIABLE = re.compile(r"\{\{\s*(\d+)\s*\}\}")
_BAD_PARAM = re.compile(r"[\n\r\t]| {5,}")

EMPTY = "empty"
TOO_LONG = "too_long"
WINDOW_CLOSED = "window_closed"
NO_PHONE = "no_phone"


def variable_count(template_text):
	"""How many positional variables a template text needs (the highest {{n}})."""
	found = [int(n) for n in _VARIABLE.findall(template_text or "")]
	return max(found) if found else 0


def fill(template_text, params):
	"""The template text with {{n}} replaced; a missing parameter leaves its {{n}} visible."""

	def one(match):
		index = int(match.group(1))
		return str(params[index - 1]) if 0 < index <= len(params) else match.group(0)

	return _VARIABLE.sub(one, template_text or "")


def check_free_text(body, last_inbound_at, now):
	"""(ok, code, message). Free text needs a non-empty body of at most 4096 characters and an open window."""
	text = (body or "").strip()
	if not text:
		return False, EMPTY, "Write a message first."
	if len(text) > MAX_TEXT:
		return False, TOO_LONG, f"A WhatsApp message can have at most {MAX_TEXT} characters."
	if not window.is_window_open(last_inbound_at, now):
		return False, WINDOW_CLOSED, "The 24-hour window is closed. Send an approved template instead."
	return True, None, None


def check_media_send(last_inbound_at, now):
	"""(ok, code, message). A file, like free text, can only be sent while the 24-hour window is open."""
	if not window.is_window_open(last_inbound_at, now):
		return False, WINDOW_CLOSED, "The 24-hour window is closed. Send an approved template instead."
	return True, None, None


def check_recipient(phone):
	"""(ok, code, message). Sending needs a phone number; a customer known only by WhatsApp user ID cannot be written to yet."""
	if wa_digits(phone):
		return True, None, None
	return False, NO_PHONE, (
		"This customer is known only by a WhatsApp user ID. Sending by user ID is not supported yet "
		"(it needs a live test with Meta); use their phone number once you have it."
	)


def validate_params(template_text, params):
	"""A list of problems with the values for a template's variables (empty list = fine)."""
	params = list(params or [])
	needed = variable_count(template_text)
	errors = []
	if len(params) != needed:
		errors.append(f"This template needs {needed} value(s); {len(params)} given.")
	for index, value in enumerate(params, start=1):
		text = "" if value is None else str(value)
		if not text.strip():
			errors.append(f"Value {index} is empty.")
		elif _BAD_PARAM.search(text):
			errors.append(f"Value {index} has a line break, a tab or more than 4 spaces in a row, which WhatsApp does not allow.")
		elif len(text) > MAX_PARAM:
			errors.append(f"Value {index} is longer than {MAX_PARAM} characters.")
	return errors


def text_payload(to_phone, body, reply_to_message_id=None):
	payload = {
		"messaging_product": "whatsapp",
		"recipient_type": "individual",
		"to": wa_digits(to_phone),
		"type": "text",
		"text": {"preview_url": False, "body": body.strip()},
	}
	if reply_to_message_id:
		payload["context"] = {"message_id": reply_to_message_id}
	return payload


def template_payload(to_phone, name, language, params):
	payload = {
		"messaging_product": "whatsapp",
		"recipient_type": "individual",
		"to": wa_digits(to_phone),
		"type": "template",
		"template": {"name": name, "language": {"code": language}},
	}
	if params:
		payload["template"]["components"] = [
			{"type": "body", "parameters": [{"type": "text", "text": str(p).strip()} for p in params]}
		]
	return payload


def template_components_payload(to_phone, name, language, components):
	"""A template send with its components already built (rules/templates.components_for_send); none for a plain template."""
	payload = {
		"messaging_product": "whatsapp",
		"recipient_type": "individual",
		"to": wa_digits(to_phone),
		"type": "template",
		"template": {"name": name, "language": {"code": language}},
	}
	if components:
		payload["template"]["components"] = components
	return payload


# Meta's limits for an interactive message (reply buttons and a list), checked here so a bot is told at Publish, not at send time
MAX_BUTTONS = 3
MAX_BUTTON_TITLE = 20
MAX_INTERACTIVE_BODY = 1024
MAX_LIST_ROWS = 10
MAX_LIST_BUTTON = 20
MAX_ROW_TITLE = 24
MAX_ROW_DESCRIPTION = 72
MAX_REPLY_ID = 200


def check_buttons(body, buttons):
	"""A list of problems with a reply-button message (empty = fine). `buttons` is [{"id", "title"}]."""
	problems = []
	text = (body or "").strip()
	if not text:
		problems.append("The message text is empty.")
	elif len(text) > MAX_INTERACTIVE_BODY:
		problems.append(f"The message text can have at most {MAX_INTERACTIVE_BODY} characters.")
	buttons = list(buttons or [])
	if not 1 <= len(buttons) <= MAX_BUTTONS:
		problems.append(f"Use 1 to {MAX_BUTTONS} buttons (WhatsApp allows no more); use a list for more choices.")
	problems += _check_options(buttons, "button", MAX_BUTTON_TITLE)
	return problems


def check_list(body, button_text, rows):
	"""A list of problems with a list message (empty = fine). `rows` is [{"id", "title", "description"?}]."""
	problems = []
	text = (body or "").strip()
	if not text:
		problems.append("The message text is empty.")
	elif len(text) > MAX_INTERACTIVE_BODY:
		problems.append(f"The message text can have at most {MAX_INTERACTIVE_BODY} characters.")
	label = (button_text or "").strip()
	if not label:
		problems.append("The list button has no text.")
	elif len(label) > MAX_LIST_BUTTON:
		problems.append(f"The list button text can have at most {MAX_LIST_BUTTON} characters.")
	rows = list(rows or [])
	if not 1 <= len(rows) <= MAX_LIST_ROWS:
		problems.append(f"A list needs 1 to {MAX_LIST_ROWS} choices.")
	problems += _check_options(rows, "choice", MAX_ROW_TITLE)
	for row in rows:
		if len((row.get("description") or "").strip()) > MAX_ROW_DESCRIPTION:
			problems.append(f"The description of '{row.get('title')}' can have at most {MAX_ROW_DESCRIPTION} characters.")
	return problems


def _check_options(options, noun, max_title):
	problems, seen_ids, seen_titles = [], set(), set()
	for option in options:
		title = (option.get("title") or "").strip()
		oid = str(option.get("id") or "").strip()
		if not title:
			problems.append(f"A {noun} has no title.")
		elif len(title) > max_title:
			problems.append(f"The {noun} '{title}' is longer than {max_title} characters.")
		if title and title.casefold() in seen_titles:
			problems.append(f"Two {noun}s are called '{title}'.")
		seen_titles.add(title.casefold())
		if not oid or len(oid) > MAX_REPLY_ID:
			problems.append(f"The {noun} '{title}' needs an id of 1 to {MAX_REPLY_ID} characters.")
		elif oid in seen_ids:
			problems.append(f"Two {noun}s share the id '{oid}'.")
		seen_ids.add(oid)
	return problems


MAX_CTA_BUTTON = 20
MAX_CTA_URL = 2000
_CTA_URL = re.compile(r"https://[A-Za-z0-9.-]+\.[A-Za-z]{2,}(:\d+)?(/\S*)?")


def check_cta_url(url):
	"""Problems with a link-button address (empty = fine): https only, a real host, no spaces, at most 2000 characters."""
	url = str(url or "").strip()
	if not url:
		return ["The link has no address."]
	if len(url) > MAX_CTA_URL:
		return [f"The link can have at most {MAX_CTA_URL} characters."]
	if not _CTA_URL.fullmatch(url):
		return ["The link must start with https:// and be a complete web address without spaces."]
	return []


def check_cta(body, button_text, url):
	"""A list of problems with a link-button message (empty = fine)."""
	problems = []
	text = (body or "").strip()
	if not text:
		problems.append("The message text is empty.")
	elif len(text) > MAX_INTERACTIVE_BODY:
		problems.append(f"The message text can have at most {MAX_INTERACTIVE_BODY} characters.")
	label = (button_text or "").strip()
	if not label:
		problems.append("The button has no text.")
	elif len(label) > MAX_CTA_BUTTON:
		problems.append(f"The button text can have at most {MAX_CTA_BUTTON} characters.")
	return problems + check_cta_url(url)


def cta_payload(to_phone, body, button_text, url):
	"""A message with one button that opens a web address."""
	return _interactive(
		to_phone,
		{"type": "cta_url", "body": {"text": body.strip()}, "action": {"name": "cta_url", "parameters": {"display_text": button_text.strip(), "url": url.strip()}}},
	)


def _interactive(to_phone, interactive):
	return {
		"messaging_product": "whatsapp",
		"recipient_type": "individual",
		"to": wa_digits(to_phone),
		"type": "interactive",
		"interactive": interactive,
	}


def buttons_payload(to_phone, body, buttons):
	"""Up to three quick-reply buttons under a message. A tap comes back as an interactive button_reply carrying the id."""
	return _interactive(
		to_phone,
		{
			"type": "button",
			"body": {"text": body.strip()},
			"action": {"buttons": [{"type": "reply", "reply": {"id": str(b["id"]), "title": b["title"].strip()}} for b in buttons]},
		},
	)


def list_payload(to_phone, body, button_text, rows):
	"""A list of up to ten choices behind one button. A pick comes back as an interactive list_reply carrying the id."""
	built = []
	for row in rows:
		item = {"id": str(row["id"]), "title": row["title"].strip()}
		if (row.get("description") or "").strip():
			item["description"] = row["description"].strip()
		built.append(item)
	return _interactive(
		to_phone,
		{"type": "list", "body": {"text": body.strip()}, "action": {"button": button_text.strip(), "sections": [{"title": "Options", "rows": built}]}},
	)


def media_payload(to_phone, kind, media_id, caption="", filename="", reply_to_message_id=None):
	"""A media message that refers to a file already uploaded to Meta (by id, never by public link)."""
	body = {"id": media_id}
	if caption and kind in ("image", "video", "document"):
		body["caption"] = caption.strip()
	if filename and kind == "document":
		body["filename"] = filename
	payload = {
		"messaging_product": "whatsapp",
		"recipient_type": "individual",
		"to": wa_digits(to_phone),
		"type": kind,
		kind: body,
	}
	if reply_to_message_id:
		payload["context"] = {"message_id": reply_to_message_id}
	return payload


def reaction_payload(to_phone, message_id, emoji):
	"""React to a message with an emoji; an empty emoji removes the reaction."""
	return {
		"messaging_product": "whatsapp",
		"recipient_type": "individual",
		"to": wa_digits(to_phone),
		"type": "reaction",
		"reaction": {"message_id": message_id, "emoji": emoji or ""},
	}


def read_receipt_payload(message_id):
	return {"messaging_product": "whatsapp", "status": "read", "message_id": message_id}


def sent_message_id(response_body):
	"""The WhatsApp message id from Meta's send response, or None."""
	messages = (response_body or {}).get("messages") if isinstance(response_body, dict) else None
	if isinstance(messages, list) and messages and isinstance(messages[0], dict):
		return messages[0].get("id")
	return None
