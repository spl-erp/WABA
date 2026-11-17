"""Small pure rules for the phone inbox calls (no database, tested offline)."""

MAX_DOCUMENTS = 20
MIN_QUERY = 2  # a typed search shorter than this lists only the chat's own customer's documents


def clean_query(text):
	"""The search text a person typed, trimmed and cut to a sensible length."""
	return str(text or "").strip()[:100]


def arrange_documents(own, others, limit=MAX_DOCUMENTS):
	"""The documents to offer for a chat: the chat's own customer's first, then the others the person may read, each document once.
	Every row is returned as a copy with `own` set."""
	seen, out = set(), []
	for flag, rows in ((True, own), (False, others)):
		for row in rows or []:
			key = (row.get("doctype"), row.get("name"))
			if key in seen:
				continue
			seen.add(key)
			out.append({**row, "own": flag})
	return out[: max(1, int(limit))]


DUPLICATE_SECONDS = 600  # how long a send's key is remembered
_KEY_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.:")


def clean_client_key(key):
	"""(ok, key). No key is fine (the send is not guarded); a key must be 8 to 64 letters, digits or - _ . : (a UUID fits)."""
	if key is None or str(key).strip() == "":
		return True, None
	key = str(key).strip()
	if not 8 <= len(key) <= 64 or any(ch not in _KEY_CHARS for ch in key):
		return False, None
	return True, key


def duplicate_cache_key(user, conversation, key):
	"""Where a send's answer is remembered: per person and conversation, so one person's key can never answer for another's."""
	return f"waba_send|{user}|{conversation}|{key}"
