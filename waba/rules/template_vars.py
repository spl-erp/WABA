"""Fill a template's values from what the ERP already knows (no Frappe, tested offline).

Each slot of a template (see rules/templates.py) has a map row saying where its value comes from:

  Ask each time   the rep types it
  Record field    a field of the matched Lead, Contact or Customer (`customer_name`, `mobile_no`, or `address.city` for a nested one)
  Literal         fixed text written in the map
  Sender name     the logged-in person's full name
  Today           today's date as dd-mm-yyyy
  Customer name   the best name we have for the customer
  Shared file     a file from the Shared Files library (media headers)

`resolve` never raises and never reads anything outside the dictionaries it is given: the caller decides which record
fields it may expose, so a map can only reach what that user is allowed to read.
"""

ASK = "Ask each time"
RECORD = "Record field"
LITERAL = "Literal"
SENDER = "Sender name"
TODAY = "Today"
CUSTOMER = "Customer name"
SHARED = "Shared file"
SOURCE_TYPES = (ASK, RECORD, LITERAL, SENDER, TODAY, CUSTOMER, SHARED)


def lookup(record, path):
	"""A value from a record dict by 'field' or 'a.b'; None when absent or not a plain value."""
	current = record
	for part in str(path or "").split("."):
		if not isinstance(current, dict) or part not in current:
			return None
		current = current[part]
	if isinstance(current, (dict, list, tuple, set)) or current is None:
		return None
	text = str(current).strip()
	return text or None


def resolve(rows, context):
	"""({slot: value}, [slots still needing a person]) for the active rows of a template's variable map.

	`context` has: record (dict), sender (str), today (str), customer_name (str). A value that is a media choice comes back
	as {"shared_file": name}."""
	context = context or {}
	values, missing = {}, []
	for row in rows or []:
		if not row.get("slot") or row.get("active") in (0, "0", False):
			continue
		kind = row.get("source_type") or ASK
		source = row.get("source") or ""
		value = None
		if kind == RECORD:
			value = lookup(context.get("record") or {}, source)
		elif kind == LITERAL:
			value = source.strip() or None
		elif kind == SENDER:
			value = (context.get("sender") or "").strip() or None
		elif kind == TODAY:
			value = (context.get("today") or "").strip() or None
		elif kind == CUSTOMER:
			value = (context.get("customer_name") or "").strip() or None
		elif kind == SHARED:
			value = {"shared_file": source} if source else None
		if value is None and kind in (RECORD, CUSTOMER) and str(row.get("fallback") or "").strip():
			value = str(row["fallback"]).strip()  # a campaign gives each per-person value a stand-in for a record that has none
		if value is None:
			missing.append(row["slot"])
		else:
			values[row["slot"]] = value
	return values, missing


PER_PERSON = (RECORD, CUSTOMER)
_SENDER_WORDS = ("agent", "sender", "executive", "representative", "rep ", "advisor", "our name", "your name", "from ")


def guess_source(label, example=""):
	"""Where a campaign should take a value from, judged from its label: (source_type, fallback). A name-like label is the
	customer's name; an agent/sender label is the sender; a date label is today; anything else is the same text for everyone."""
	text = f"{label or ''} {example or ''}".lower().strip()
	if any(w in text for w in _SENDER_WORDS):
		return SENDER, ""
	if "date" in text or "today" in text:
		return TODAY, ""
	if "name" in text or "customer" in text or "client" in text:
		return CUSTOMER, "Sir/Madam"
	return LITERAL, ""


def row_problem(row):
	"""Plain-words reason a campaign value choice cannot be used, or None. `row`: source_type, source, fallback."""
	kind = row.get("source_type")
	if kind not in (RECORD, LITERAL, SENDER, TODAY, CUSTOMER, SHARED):
		return "Choose where this value comes from."
	if kind == LITERAL and not str(row.get("source") or "").strip():
		return "Type the text that goes to everyone."
	if kind == RECORD and not str(row.get("source") or "").strip():
		return "Choose which field of the person's record to use."
	if kind == SHARED and not str(row.get("source") or "").strip():
		return "Choose the header file from the shared library."
	if kind in PER_PERSON and not str(row.get("fallback") or "").strip():
		return "Type what to use when a person's record has no value (for example Sir/Madam)."
	return None


def merge(prefilled, typed):
	"""What the rep typed or chose wins over what the map filled in; blank typed values do not erase a filled one."""
	out = dict(prefilled or {})
	for slot, value in (typed or {}).items():
		if value is None or (isinstance(value, str) and not value.strip()):
			continue
		out[slot] = value
	return out


def public_record(doc_dict, exposed=None):
	"""Only plain readable fields of a record, for use as `context['record']`. Private-looking keys and passwords are left out."""
	skip = ("password", "secret", "token", "api_key")
	out = {}
	for key, value in (doc_dict or {}).items():
		if key.startswith("_") or any(word in key for word in skip):
			continue
		if exposed is not None and key not in exposed:
			continue
		if isinstance(value, (str, int, float)) or value is None:
			out[key] = value
	return out
