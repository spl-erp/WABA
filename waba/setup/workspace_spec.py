"""What the Waba workspace shows, as plain data (no Frappe import, so it is tested offline).

Grows by one entry per build chunk: a new doctype or page is added to SECTIONS when the chunk that creates it is
accepted, never before, so the workspace never links to something that does not exist yet."""

import json

WORKSPACE = "Waba"
MODULE = "Waba"

# (card title, [(doctype, label, description)])
SECTIONS = [
	(
		"Connect to Meta",
		[
			("Waba Portfolio", "Portfolios", "Your Meta business and its access token"),
			("Waba Meta App", "Meta Apps", "The Meta app, its webhook address and secret"),
			("Waba Account", "WhatsApp Accounts", "WABA: templates, billing, payment status"),
		],
	),
	(
		"Numbers and people",
		[
			("Waba Number", "Numbers", "Each business number, its agents and routing rules"),
			("Waba Team", "Teams", "The organisation tree: who sees which conversations, and which numbers each team owns"),
			("Waba Quick Reply", "Quick Replies", "Saved answers agents insert from the reply box"),
		],
	),
	(
		"Messaging",
		[("Waba Template", "Templates", "Message templates as Meta has them; only approved ones can be sent")],
	),
	(
		"Conversations",
		[
			("Waba Conversation", "Conversations", "One thread per business number and customer"),
			("Waba Message", "Messages", "Every message received, stored once"),
			("Waba Identity", "WhatsApp User IDs", "Which person a WhatsApp user ID belongs to"),
		],
	),
	(
		"Activity",
		[("Waba Webhook Event", "Webhook Events", "Every delivery Meta has sent to the ERP, kept as received")],
	),
]

SHORTCUTS = [
	("Waba Account", "WhatsApp Accounts"),
	("Waba Number", "Numbers"),
	("Waba Portfolio", "Portfolios"),
	("Waba Meta App", "Meta Apps"),
	("Waba Webhook Event", "Webhook Events"),
	("Waba Conversation", "Conversations"),
]

# (page name, label): desk pages
PAGE_SHORTCUTS = [("waba-inbox", "Inbox")]

# (label, url): a saved filter on a list
URL_SHORTCUTS = [("Triage", "/app/waba-conversation?match_state=Triage")]

VIEWER_ROLES = ("Waba Admin", "Waba Supervisor", "Waba Agent", "System Manager")


def content():
	"""The workspace body (a list of blocks, stored as JSON text)."""
	blocks = [
		{"id": "hdr", "type": "header", "data": {"text": '<span class="h4"><b>WhatsApp</b></span>', "col": 12}},
	]
	for i, label in enumerate(_shortcut_labels()):
		blocks.append({"id": f"sc{i}", "type": "shortcut", "data": {"shortcut_name": label, "col": 3}})
	blocks.append({"id": "sp", "type": "spacer", "data": {"col": 12}})
	for i, (title, _rows) in enumerate(SECTIONS):
		blocks.append({"id": f"cd{i}", "type": "card", "data": {"card_name": title, "col": 4}})
	return json.dumps(blocks)


def link_rows():
	rows = []
	for title, items in SECTIONS:
		rows.append({"type": "Card Break", "label": title, "hidden": 0})
		for doctype, label, description in items:
			rows.append(
				{
					"type": "Link",
					"label": label,
					"link_type": "DocType",
					"link_to": doctype,
					"description": description,
					"hidden": 0,
					"onboard": 0,
				}
			)
	return rows


def shortcut_rows():
	pages = [{"type": "Page", "link_to": page, "label": label} for page, label in PAGE_SHORTCUTS]
	rows = [{"type": "DocType", "link_to": d, "label": l, "doc_view": "List"} for d, l in SHORTCUTS]
	return pages + rows + [{"type": "URL", "url": url, "label": label} for label, url in URL_SHORTCUTS]


def _shortcut_labels():
	return [label for _p, label in PAGE_SHORTCUTS] + [label for _d, label in SHORTCUTS] + [label for label, _u in URL_SHORTCUTS]


def merge_links(existing, wanted):
	"""`existing` rows (dicts, in order) plus whatever of `wanted` is missing, matched by label. A missing link goes
	after the last row of its card; a missing card goes at the end. Nothing existing is changed or reordered."""
	rows = [dict(r) for r in existing]
	have = {(r["type"], r.get("label")) for r in rows}
	card = None
	for row in wanted:
		if row["type"] == "Card Break":
			card = row["label"]
			if ("Card Break", card) not in have:
				rows.append(dict(row))
				have.add(("Card Break", card))
			continue
		if ("Link", row["label"]) in have:
			continue
		at = _end_of_card(rows, card)
		rows.insert(at, dict(row))
		have.add(("Link", row["label"]))
	return rows


def _end_of_card(rows, card):
	start = next((i for i, r in enumerate(rows) if r["type"] == "Card Break" and r.get("label") == card), None)
	if start is None:
		return len(rows)
	end = start + 1
	while end < len(rows) and rows[end]["type"] != "Card Break":
		end += 1
	return end


def missing_blocks(existing_content, shortcut_labels_have, cards_have):
	"""Content blocks for shortcuts and cards the workspace body does not mention yet."""
	blocks = json.loads(existing_content)
	named = {b["data"].get("shortcut_name") for b in blocks if b.get("type") == "shortcut"} | {
		b["data"].get("card_name") for b in blocks if b.get("type") == "card"
	}
	added = []
	for label in _shortcut_labels():
		if label not in named and label in shortcut_labels_have:
			added.append({"id": "sc-" + _slug(label), "type": "shortcut", "data": {"shortcut_name": label, "col": 3}})
	for title, _rows in SECTIONS:
		if title not in named and title in cards_have:
			added.append({"id": "cd-" + _slug(title), "type": "card", "data": {"card_name": title, "col": 4}})
	return added


def _slug(text):
	return "".join(c if c.isalnum() else "-" for c in text.lower())
