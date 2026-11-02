"""What a Meta template is made of, which values it needs, and the exact components to send (no Frappe, tested offline).

`parse` reads the `components` Meta returns for a template into a plain structure with a list of SLOTS: one per thing a
person (or a record) must supply when sending it.

  header.1 / header.<name>   a variable in a text header (one is allowed)
  header.media               the file of an image, video or document header
  body.1, body.2 ... / body.<name>   body variables, positional or named
  button.<n>                 the value of button n: the end of a URL (when the URL has {{1}}) or the code of a copy-code button

Shapes the ERP cannot send yet (carousel, limited-time offer, location header, flow / catalog / OTP buttons) are listed in
`unsupported`, so the picker can say why instead of Meta rejecting the send. Field names follow Meta's reference as of
Oct 2026 and are UNVERIFIED against live Meta for the rarer shapes.
"""

import re

MAX_PARAM = 1024
MAX_HEADER_PARAM = 60
MAX_COUPON = 15
_POSITIONAL = re.compile(r"\{\{\s*(\d+)\s*\}\}")
_NAMED = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")
_ANY = re.compile(r"\{\{\s*([A-Za-z0-9_]+)\s*\}\}")
_BAD = re.compile(r"[\n\r\t]| {5,}")
MEDIA_FORMATS = ("IMAGE", "VIDEO", "DOCUMENT")
SENDABLE_BUTTONS = ("URL", "QUICK_REPLY", "PHONE_NUMBER", "COPY_CODE")
KNOWN_COMPONENTS = ("HEADER", "BODY", "FOOTER", "BUTTONS")
BUTTON_NAMES = {"COPY_CODE": "Copy code", "URL": "Open link", "PHONE_NUMBER": "Call", "QUICK_REPLY": "Reply"}  # for a button Meta gives no text


def _keys(text):
	"""The variable keys in a text: positional ones in numeric order ('1', '2' ...: Meta wants the values in that order
	however the text mentions them), named ones in order of first appearance."""
	seen = []
	for match in _ANY.finditer(text or ""):
		key = match.group(1)
		if key not in seen:
			seen.append(key)
	numbers = sorted((k for k in seen if k.isdigit()), key=int)
	return numbers + [k for k in seen if not k.isdigit()]


def _format(item, components):
	declared = str((item or {}).get("parameter_format") or "").upper()
	if declared in ("NAMED", "POSITIONAL"):
		return declared
	text = " ".join(str(c.get("text") or "") for c in components if isinstance(c, dict))
	return "NAMED" if _NAMED.search(text) and not _POSITIONAL.search(text) and any(not k.isdigit() for k in _keys(text)) else "POSITIONAL"


def parse(components, parameter_format=None):
	"""The structure of a template from Meta's `components` list. Never raises on odd input."""
	components = [c for c in (components or []) if isinstance(c, dict)]
	by_type = {}
	for c in components:
		by_type.setdefault(str(c.get("type") or "").upper(), c)
	fmt = _format({"parameter_format": parameter_format}, components)
	out = {"parameter_format": fmt, "header": None, "body": {"text": "", "slots": []}, "footer": None, "buttons": [], "slots": [], "unsupported": []}

	for kind in by_type:
		if kind not in KNOWN_COMPONENTS:
			out["unsupported"].append(f"it has a {kind.replace('_', ' ').lower()} section")

	header = by_type.get("HEADER")
	if header:
		fmt_h = str(header.get("format") or "TEXT").upper()
		entry = {"format": fmt_h, "text": header.get("text") if fmt_h == "TEXT" else None, "slots": []}
		if fmt_h == "TEXT":
			for key in _keys(entry["text"])[:1]:
				entry["slots"].append(_slot("header", key, fmt))
		elif fmt_h in MEDIA_FORMATS:
			entry["slots"].append({"id": "header.media", "component": "header", "kind": fmt_h.lower(), "label": f"Header {fmt_h.lower()}"})
		else:
			out["unsupported"].append(f"it has a {fmt_h.lower()} header")
		out["header"] = entry

	body = by_type.get("BODY") or {}
	out["body"] = {"text": body.get("text") or "", "slots": [_slot("body", key, fmt) for key in _keys(body.get("text"))]}
	if by_type.get("FOOTER"):
		out["footer"] = by_type["FOOTER"].get("text")

	for index, button in enumerate((by_type.get("BUTTONS") or {}).get("buttons") or []):
		if not isinstance(button, dict):
			continue
		kind = str(button.get("type") or "").upper()
		entry = {"index": index, "type": kind, "text": button.get("text"), "url": button.get("url"), "phone": button.get("phone_number"), "slots": []}
		if kind not in SENDABLE_BUTTONS:
			out["unsupported"].append(f"it has a {kind.replace('_', ' ').lower()} button")
		elif kind == "URL" and _keys(button.get("url")):
			entry["slots"].append({"id": f"button.{index}", "component": "button", "index": index, "kind": "url_suffix", "label": f"End of the link for \"{button.get('text') or 'button'}\""})
		elif kind == "COPY_CODE":
			entry["slots"].append({"id": f"button.{index}", "component": "button", "index": index, "kind": "coupon_code", "label": "Code to copy"})
		out["buttons"].append(entry)

	out["slots"] = list(out["header"]["slots"] if out["header"] else []) + out["body"]["slots"] + [s for b in out["buttons"] for s in b["slots"]]
	return out


def _slot(component, key, fmt):
	named = fmt == "NAMED" or not str(key).isdigit()
	return {
		"id": f"{component}.{key}",
		"component": component,
		"key": key,
		"name": key if named else None,
		"kind": "text",
		"label": key.replace("_", " ").capitalize() if named else f"{component.capitalize()} value {key}",
	}


def slot_ids(structure):
	return [s["id"] for s in structure["slots"]]


def sendable(structure):
	"""(ok, why). False when the template has a part the ERP cannot send yet."""
	if structure["unsupported"]:
		return False, "This template cannot be sent from the ERP yet: " + "; ".join(structure["unsupported"]) + "."
	return True, ""


def validate(structure, values):
	"""A list of plain-words problems with the values for a template's slots (empty list = fine)."""
	values = values or {}
	problems = []
	ok, why = sendable(structure)
	if not ok:
		return [why]
	for slot in structure["slots"]:
		value = values.get(slot["id"])
		text = "" if value is None else str(value)
		label = slot["label"]
		if not text.strip():
			problems.append(f"{label} is empty." if slot["kind"] != "image" and slot["kind"] not in ("video", "document") else f"Choose the {slot['kind']} for the header.")
			continue
		if slot["kind"] == "text":
			limit = MAX_HEADER_PARAM if slot["component"] == "header" else MAX_PARAM
			if _BAD.search(text):
				problems.append(f"{label} has a line break, a tab or more than 4 spaces in a row, which WhatsApp does not allow.")
			elif len(text) > limit:
				problems.append(f"{label} is longer than {limit} characters.")
		elif slot["kind"] == "url_suffix":
			if re.search(r"\s", text):
				problems.append(f"{label} must not contain spaces.")
			elif len(text) > 2000:
				problems.append(f"{label} is too long.")
		elif slot["kind"] == "coupon_code":
			if len(text) > MAX_COUPON or not re.fullmatch(r"[A-Za-z0-9]+", text):
				problems.append(f"{label} must be letters and digits only, at most {MAX_COUPON}.")
	return problems


def components_for_send(structure, values):
	"""The `components` list of a Meta template send for these slot values (call `validate` first)."""
	values = values or {}
	out = []
	header = structure["header"]
	if header and header["slots"]:
		slot = header["slots"][0]
		if slot["kind"] == "text":
			out.append({"type": "header", "parameters": [_text_param(slot, values[slot["id"]])]})
		else:
			out.append({"type": "header", "parameters": [{"type": slot["kind"], slot["kind"]: {"id": str(values[slot["id"]])}}]})
	if structure["body"]["slots"]:
		out.append({"type": "body", "parameters": [_text_param(s, values[s["id"]]) for s in structure["body"]["slots"]]})
	for button in structure["buttons"]:
		for slot in button["slots"]:
			value = str(values[slot["id"]]).strip()
			if slot["kind"] == "url_suffix":
				out.append({"type": "button", "sub_type": "url", "index": str(button["index"]), "parameters": [{"type": "text", "text": value}]})
			else:
				out.append({"type": "button", "sub_type": "copy_code", "index": str(button["index"]), "parameters": [{"type": "coupon_code", "coupon_code": value}]})
	return out


def _text_param(slot, value):
	param = {"type": "text", "text": str(value).strip()}
	if slot.get("name"):
		param["parameter_name"] = slot["name"]
	return param


def render(structure, values):
	"""The template's readable parts with the values put in; a missing value leaves its {{variable}} visible."""
	values = values or {}

	def fill(text, component):
		def one(match):
			key = match.group(1)
			value = values.get(f"{component}.{key}")
			return str(value).strip() if value not in (None, "") else match.group(0)

		return _ANY.sub(one, text or "")

	header = structure["header"]
	return {
		"header": fill(header["text"], "header") if header and header["format"] == "TEXT" else (f"[{header['format'].lower()}]" if header else ""),
		"body": fill(structure["body"]["text"], "body"),
		"footer": structure["footer"] or "",
		"buttons": [b["text"] or BUTTON_NAMES.get(b["type"], b["type"]) for b in structure["buttons"]],
	}


def from_positional(structure, params):
	"""Values for the body slots from the old list form ['Rahul', 'SO-1'] (what callers passed before C10)."""
	slots = structure["body"]["slots"]
	params = list(params or [])
	return {slot["id"]: params[i] for i, slot in enumerate(slots) if i < len(params)}


def from_fields(header_format, header_text, body_text, footer_text):
	"""Components for a template stored before C10 (no components JSON yet): what the old sync kept. Buttons are unknown
	there and treated as none until the next Sync templates."""
	components = []
	if header_format:
		components.append({"type": "HEADER", "format": str(header_format).upper(), "text": header_text})
	components.append({"type": "BODY", "text": body_text or ""})
	if footer_text:
		components.append({"type": "FOOTER", "text": footer_text})
	return components


def typed_values(structure, params):
	"""The slot values a caller passed, whatever form: None, a dict, a JSON string of a dict or list, a list, or lines of
	text (the old one-per-line form, which fills the body slots in order)."""
	import json

	if params is None or params == "" or params == []:
		return {}
	if isinstance(params, str):
		try:
			loaded = json.loads(params)
		except ValueError:
			return from_positional(structure, params.splitlines())
		return typed_values(structure, loaded) if isinstance(loaded, (dict, list)) else from_positional(structure, params.splitlines())
	if isinstance(params, dict):
		return dict(params)
	return from_positional(structure, list(params))
