"""Writing a new template in the ERP: check a draft the way Meta will, and build the exact request (no Frappe, tested offline).

A draft is a plain dict:

  template_name, language, category (UTILITY or MARKETING), header_format ("" / TEXT / IMAGE / VIDEO / DOCUMENT), header_text,
  header_handle (the id Meta gave to the sample file of a media header), body_text, footer_text,
  buttons [{type, text, url, phone_number, example}], examples {"body.1": "Rahul", "header.1": "SO-9", "button.0": "abc"}

`check` returns every problem in plain words; `request` builds the body of Meta's create call. The limits follow Meta's
published template rules as of Oct 2026 and have NOT been exercised against live Meta yet (Meta also rejects things only it
knows, such as policy; its reason is shown to the person). Authentication templates are not supported here.
"""

import re

from waba.rules import templates as anatomy

NAME_RE = re.compile(r"^[a-z0-9_]{1,512}$")
LANG_RE = re.compile(r"^[a-z]{2,3}(_[A-Z]{2})?$")
ALLOWED_CATEGORIES = ("UTILITY", "MARKETING")
HEADER_FORMATS = ("", "TEXT", "IMAGE", "VIDEO", "DOCUMENT")
BUTTON_TYPES = ("URL", "QUICK_REPLY", "PHONE_NUMBER", "COPY_CODE")

MAX_HEADER = 60
MAX_BODY = 1024
MAX_FOOTER = 60
MAX_BUTTON_TEXT = 25
MAX_URL = 2000
MAX_BUTTONS = 10
MAX_URL_BUTTONS = 2
MAX_PHONE_BUTTONS = 1
MAX_COPY_BUTTONS = 1
MAX_COUPON = 15

_VAR = re.compile(r"\{\{\s*([A-Za-z0-9_]+)\s*\}\}")
_NAMED_OK = re.compile(r"^[a-z][a-z0-9_]*$")
_PHONE = re.compile(r"^\+\d{7,15}$")


def variable_keys(text):
	"""The variable keys of a text in the order they must be given: numbers ascending, then names in order of appearance."""
	return anatomy._keys(text)


def _style(keys):
	"""'POSITIONAL', 'NAMED', or None for a text with no variables; 'MIXED' when both kinds are used."""
	if not keys:
		return None
	numeric = [k.isdigit() for k in keys]
	if all(numeric):
		return "POSITIONAL"
	if not any(numeric):
		return "NAMED"
	return "MIXED"


def check_name(name):
	if not name:
		return ["Give the template a name."]
	if not NAME_RE.match(name):
		return ["The name may have only lowercase letters, digits and underscores (for example order_update)."]
	return []


def check(draft, for_submit=False):
	"""A list of plain-words problems (empty list = fine). `for_submit` adds what must exist before sending to Meta."""
	problems = []
	problems += check_name(draft.get("template_name"))
	if not LANG_RE.match(str(draft.get("language") or "")):
		problems.append("Choose the language code, for example en, en_US or hi.")
	if draft.get("category") not in ALLOWED_CATEGORIES:
		problems.append("Choose Utility or Marketing. Authentication templates cannot be written here.")

	body = str(draft.get("body_text") or "").strip()
	body_keys = variable_keys(body)
	style = _style(body_keys)
	if not body:
		problems.append("The message text is required.")
	elif len(body) > MAX_BODY:
		problems.append(f"The message text is longer than {MAX_BODY} characters.")
	if style == "MIXED":
		problems.append("Use either numbered values ({{1}}, {{2}}) or named values ({{customer_name}}) in the message, not both.")
	elif style == "POSITIONAL" and body_keys != [str(i) for i in range(1, len(body_keys) + 1)]:
		problems.append("Numbered values must run 1, 2, 3 without gaps.")
	elif style == "NAMED":
		bad = [k for k in body_keys if not _NAMED_OK.match(k)]
		if bad:
			problems.append("Named values must be lowercase letters, digits and underscores, starting with a letter: " + ", ".join(bad) + ".")
	if body and body_keys:
		if re.match(r"^\s*\{\{", body) or re.search(r"\}\}\s*$", body):
			problems.append("The message cannot start or end with a value; add some fixed text before and after.")
		if len(_VAR.sub("", body).strip()) < 10 * len(body_keys):
			problems.append("There is too little fixed text around the values; WhatsApp needs more words for each value.")

	fmt = str(draft.get("header_format") or "")
	if fmt not in HEADER_FORMATS:
		problems.append("The header must be none, text, image, video or document.")
	header_keys = []
	if fmt == "TEXT":
		header = str(draft.get("header_text") or "").strip()
		header_keys = variable_keys(header)
		if not header:
			problems.append("Write the header text, or choose no header.")
		elif len(header) > MAX_HEADER:
			problems.append(f"The header is longer than {MAX_HEADER} characters.")
		if len(header_keys) > 1:
			problems.append("A header can have only one value.")
		if header_keys and style and _style(header_keys) != style:
			problems.append("The header and the message must use the same kind of values (numbered or named).")
	elif fmt in ("IMAGE", "VIDEO", "DOCUMENT") and for_submit and not draft.get("header_handle"):
		problems.append(f"The {fmt.lower()} header needs a sample file; choose one and upload it first.")

	footer = str(draft.get("footer_text") or "").strip()
	if footer:
		if len(footer) > MAX_FOOTER:
			problems.append(f"The footer is longer than {MAX_FOOTER} characters.")
		if _VAR.search(footer):
			problems.append("The footer cannot have values.")

	buttons = [b for b in (draft.get("buttons") or []) if b and b.get("type")]
	problems += _check_buttons(buttons)

	examples = draft.get("examples") or {}
	for component, keys in (("body", body_keys), ("header", header_keys)):
		for key in keys:
			if not str(examples.get(f"{component}.{key}") or "").strip():
				problems.append(f"Give an example for the {component} value {{{{{key}}}}}; WhatsApp needs it to review the template.")
	for index, b in enumerate(buttons):
		if b["type"] == "URL" and _VAR.search(str(b.get("url") or "")) and not str(examples.get(f"button.{index}") or b.get("example") or "").strip():
			problems.append(f"Give an example web address for the button \"{b.get('text') or index + 1}\".")
	for key, value in examples.items():
		if re.search(r"[\n\r]", str(value or "")):
			problems.append(f"The example for {key} cannot have a line break.")
	return problems


def _check_buttons(buttons):
	problems = []
	if len(buttons) > MAX_BUTTONS:
		problems.append(f"At most {MAX_BUTTONS} buttons.")
	counts = {t: sum(1 for b in buttons if b["type"] == t) for t in BUTTON_TYPES}
	if counts["URL"] > MAX_URL_BUTTONS:
		problems.append(f"At most {MAX_URL_BUTTONS} web address buttons.")
	if counts["PHONE_NUMBER"] > MAX_PHONE_BUTTONS:
		problems.append("At most one call button.")
	if counts["COPY_CODE"] > MAX_COPY_BUTTONS:
		problems.append("At most one copy-code button.")
	kinds = [b["type"] for b in buttons]
	quick = [i for i, k in enumerate(kinds) if k == "QUICK_REPLY"]
	if quick and quick != list(range(quick[0], quick[-1] + 1)):
		problems.append("Put the quick-reply buttons together, one after another.")
	if quick and 0 < quick[0] < len(kinds) - len(quick) and quick[-1] != len(kinds) - 1:
		problems.append("Quick-reply buttons must come first or last.")
	for index, b in enumerate(buttons):
		kind, text = b["type"], str(b.get("text") or "").strip()
		label = text or f"button {index + 1}"
		if kind not in BUTTON_TYPES:
			problems.append(f"Button {index + 1}: unsupported kind {kind}.")
			continue
		if kind != "COPY_CODE" and not text:
			problems.append(f"Button {index + 1} needs a text.")
		if len(text) > MAX_BUTTON_TEXT:
			problems.append(f"The text of \"{label}\" is longer than {MAX_BUTTON_TEXT} characters.")
		if kind == "URL":
			url = str(b.get("url") or "").strip()
			keys = variable_keys(url)
			if not url.startswith("https://"):
				problems.append(f"The address of \"{label}\" must start with https://.")
			elif len(url) > MAX_URL:
				problems.append(f"The address of \"{label}\" is too long.")
			if len(keys) > 1 or (keys and (keys != ["1"] or not re.search(r"\{\{\s*1\s*\}\}$", url))):
				problems.append(f"\"{label}\": a web address can have one value, {{{{1}}}}, and only at the very end.")
		elif kind == "PHONE_NUMBER":
			if not _PHONE.match(str(b.get("phone_number") or "").replace(" ", "")):
				problems.append(f"The number of \"{label}\" must be in international form, for example +919876543210.")
		elif kind == "COPY_CODE":
			example = str(b.get("example") or "").strip()
			if not example:
				problems.append("The copy-code button needs an example code.")
			elif len(example) > MAX_COUPON or not re.fullmatch(r"[A-Za-z0-9]+", example):
				problems.append(f"The example code must be letters and digits, at most {MAX_COUPON}.")
	return problems


def components(draft):
	"""Meta's `components` for a draft (call `check` first)."""
	examples = draft.get("examples") or {}
	body = str(draft.get("body_text") or "").strip()
	body_keys = variable_keys(body)
	named = _style(body_keys) == "NAMED"
	out = []
	fmt = str(draft.get("header_format") or "")
	if fmt == "TEXT":
		text = str(draft.get("header_text") or "").strip()
		keys = variable_keys(text)
		part = {"type": "HEADER", "format": "TEXT", "text": text}
		if keys:
			value = str(examples.get(f"header.{keys[0]}") or "").strip()
			part["example"] = {"header_text_named_params": [{"param_name": keys[0], "example": value}]} if named else {"header_text": [value]}
		out.append(part)
	elif fmt in ("IMAGE", "VIDEO", "DOCUMENT"):
		part = {"type": "HEADER", "format": fmt}
		if draft.get("header_handle"):
			part["example"] = {"header_handle": [str(draft["header_handle"])]}
		out.append(part)
	body_part = {"type": "BODY", "text": body}
	if body_keys:
		values = [str(examples.get(f"body.{k}") or "").strip() for k in body_keys]
		body_part["example"] = {"body_text_named_params": [{"param_name": k, "example": v} for k, v in zip(body_keys, values)]} if named else {"body_text": [values]}
	out.append(body_part)
	footer = str(draft.get("footer_text") or "").strip()
	if footer:
		out.append({"type": "FOOTER", "text": footer})
	buttons = []
	for index, b in enumerate(b for b in (draft.get("buttons") or []) if b and b.get("type")):
		kind, text = b["type"], str(b.get("text") or "").strip()
		if kind == "URL":
			item = {"type": "URL", "text": text, "url": str(b.get("url") or "").strip()}
			if variable_keys(item["url"]):
				item["example"] = [str(examples.get(f"button.{index}") or b.get("example") or "").strip()]
			buttons.append(item)
		elif kind == "QUICK_REPLY":
			buttons.append({"type": "QUICK_REPLY", "text": text})
		elif kind == "PHONE_NUMBER":
			buttons.append({"type": "PHONE_NUMBER", "text": text, "phone_number": str(b.get("phone_number") or "").replace(" ", "")})
		elif kind == "COPY_CODE":
			buttons.append({"type": "COPY_CODE", "example": str(b.get("example") or "").strip()})
	if buttons:
		out.append({"type": "BUTTONS", "buttons": buttons})
	return out


def request(draft):
	"""The JSON body of Meta's create-template call."""
	body_keys = variable_keys(str(draft.get("body_text") or ""))
	return {
		"name": draft["template_name"],
		"language": draft["language"],
		"category": draft["category"],
		"parameter_format": "NAMED" if _style(body_keys) == "NAMED" else "POSITIONAL",
		"components": components(draft),
	}


def slots(draft):
	"""The value slots a draft defines, as templates.parse would see them once Meta has it: [{id, label}] for the examples table."""
	structure = anatomy.parse(components(draft), request(draft)["parameter_format"])
	return [{"id": s["id"], "label": s["label"]} for s in structure["slots"]]


def from_components(components):
	"""Draft fields (with the examples) for an existing template's `components`: how a template is copied as a new draft.
	The sample file handle of a media header is not carried over (it belongs to the old template): the new draft needs its own."""
	out = {"header_format": "", "header_text": "", "body_text": "", "footer_text": "", "buttons": [], "examples": {}}
	for c in components or []:
		if not isinstance(c, dict):
			continue
		kind = str(c.get("type") or "").upper()
		example = c.get("example") if isinstance(c.get("example"), dict) else {}
		if kind == "HEADER":
			out["header_format"] = str(c.get("format") or "TEXT").upper()
			if out["header_format"] == "TEXT":
				out["header_text"] = c.get("text") or ""
				keys = variable_keys(out["header_text"])
				values = example.get("header_text") or []
				named = example.get("header_text_named_params") or []
				if keys and named:
					out["examples"][f"header.{named[0].get('param_name') or keys[0]}"] = named[0].get("example") or ""
				elif keys and values:
					out["examples"][f"header.{keys[0]}"] = values[0]
		elif kind == "BODY":
			out["body_text"] = c.get("text") or ""
			keys = variable_keys(out["body_text"])
			named = example.get("body_text_named_params") or []
			rows = example.get("body_text") or []
			if named:
				for item in named:
					out["examples"][f"body.{item.get('param_name')}"] = item.get("example") or ""
			elif rows and isinstance(rows[0], list):
				for key, value in zip(keys, rows[0]):
					out["examples"][f"body.{key}"] = value
		elif kind == "FOOTER":
			out["footer_text"] = c.get("text") or ""
		elif kind == "BUTTONS":
			for index, b in enumerate(x for x in (c.get("buttons") or []) if isinstance(x, dict)):
				btype = str(b.get("type") or "").upper()
				item = {"type": btype, "text": b.get("text") or "", "url": b.get("url") or "", "phone_number": b.get("phone_number") or "", "example": ""}
				ex = b.get("example")
				if btype == "URL" and isinstance(ex, list) and ex:
					item["example"] = ex[0]
					out["examples"][f"button.{index}"] = ex[0]
				elif btype == "COPY_CODE" and ex:
					item["example"] = ex[0] if isinstance(ex, list) else ex
				out["buttons"].append(item)
	return out
