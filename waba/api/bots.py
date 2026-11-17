"""The bot screens' server side: publish a bot, load the ready-made one, and try a bot without sending anything.

Only a Waba Admin builds bots (a bot talks to real customers). Reading a bot's design and trying it send nothing and touch no
customer: `simulate` runs the same pure rules as the live engine on facts you give it."""

import json

import frappe
from frappe import _

from waba import bot as engine
from waba import teams
from waba.rules import bot as rules
from waba.rules import bot_docs, bot_starters, visibility

DOCTYPE = "Waba Bot"


def _admin_only():
	if not teams.is_admin(frappe.session.user):
		frappe.throw(_("Only a Waba Admin can build bots."), frappe.PermissionError)


def _bot(name):
	_admin_only()
	return frappe.get_doc(DOCTYPE, name)


@frappe.whitelist(methods=["POST"])
def publish(bot: str):
	"""Check the draft in plain words and make it the version customers get. Switching the bot on is a separate step."""
	doc = _bot(bot)
	return {"version": doc.publish(), "problems": []}


MAX_GRAPH_BYTES = 400_000  # a bot is a few dozen blocks; this only stops a runaway or hostile save
MAX_NODES = 200


@frappe.whitelist()
def check(bot: str):
	"""The problems that would stop the draft being published (empty list = ready), each with the block it is about. Changes nothing."""
	doc = _bot(bot)
	graph = json.loads(doc.graph_json) if doc.graph_json else None
	found = rules.problems_for(graph, engine.extras_on())
	return {"problems": [p["text"] for p in found], "detail": found}


@frappe.whitelist(methods=["POST"])
def save_draft(bot: str, graph: str | dict):
	"""Keep the builder's work as the bot's DRAFT. Customers get the published version only, so this changes nothing live.
	Returns the problems the draft still has (an unfinished draft is fine to save; Publish is what refuses it)."""
	doc = _bot(bot)
	if isinstance(graph, str):
		if len(graph) > MAX_GRAPH_BYTES:
			frappe.throw(_("This bot is too large to save."))
		try:
			graph = json.loads(graph)
		except ValueError:
			frappe.throw(_("The bot design could not be read."))
	if not isinstance(graph, dict) or not isinstance(graph.get("nodes"), list) or not isinstance(graph.get("edges", []), list):
		frappe.throw(_("The bot design could not be read."))
	if len(graph["nodes"]) > MAX_NODES:
		frappe.throw(_("A bot can have at most {0} blocks.").format(MAX_NODES))
	text = json.dumps({"nodes": graph["nodes"], "edges": graph.get("edges", [])}, ensure_ascii=False)
	if len(text) > MAX_GRAPH_BYTES:
		frappe.throw(_("This bot is too large to save."))
	doc.graph_json = text
	doc.save()
	found = rules.problems_for(json.loads(text), engine.extras_on())
	return {"saved": True, "modified": str(doc.modified), "problems": [p["text"] for p in found], "detail": found}


@frappe.whitelist()
def team_agents(team: str):
	"""The people an Assign block can name: enabled members of the team and its sub-teams, as [{user, full_name, role}]."""
	_admin_only()
	parents, members, _numbers = teams.load_tree()
	if team not in parents:
		return []
	branch = visibility.subtree(team, parents)
	roles = {}
	for t, user, role in members:
		if t in branch and (user not in roles or role == visibility.LEAD):
			roles[user] = role
	rows = frappe.get_all("User", filters={"name": ["in", list(roles) or [""]], "enabled": 1}, fields=["name", "full_name"], order_by="full_name asc")
	return [{"user": r.name, "full_name": r.full_name or r.name, "role": roles[r.name]} for r in rows]


@frappe.whitelist()
def starters():
	"""The ready-made bots on offer. Welcome + menu always; the others only while the preview features are switched on."""
	_admin_only()
	return bot_starters.catalog(engine.extras_on())


@frappe.whitelist(methods=["POST"])
def use_starter(bot: str, sales_team: str | None = None, accounts_team: str | None = None, key: str = bot_starters.WELCOME_MENU):
	"""Put a ready-made bot in the draft (replacing what is there). For Welcome + menu, a named team gets the people who pick that button."""
	doc = _bot(bot)
	if key not in {s["key"] for s in bot_starters.catalog(engine.extras_on())}:
		frappe.throw(_("That starter is not available."))
	for team in (sales_team, accounts_team):
		if team and not frappe.db.exists("Waba Team", team):
			frappe.throw(_("There is no team called {0}.").format(team))
	graph = bot_starters.build(key, sales_team or None, accounts_team or None)
	doc.graph_json = json.dumps(graph, ensure_ascii=False)
	doc.save()
	return {"problems": rules.validate_graph(graph, engine.extras_on())}


@frappe.whitelist()
def block_counts(bot: str, days: int = 30):
	"""How many customers reached each block of this bot in the last 7 / 30 / 90 days, and how its sessions ended (a preview
	feature: nothing is returned while the preview features are off)."""
	_bot(bot)
	if not engine.extras_on():
		return {"enabled": False, "blocks": {}, "totals": {}}
	days = int(days) if int(days or 0) in (7, 30, 90) else 30
	since = frappe.utils.add_days(frappe.utils.now_datetime(), -days)
	blocks = dict(frappe.db.sql("select node_id, count(distinct session) from `tabWaba Bot Log` where bot = %s and creation >= %s group by node_id", (bot, since)))
	totals = dict(frappe.db.sql("select status, count(*) from `tabWaba Bot Session` where bot = %s and creation >= %s group by status", (bot, since)))
	return {"enabled": True, "days": days, "blocks": blocks, "totals": totals}


SAMPLE_DOCS = {
	bot_docs.QUOTATION: ("QTN-SAMPLE-0001", "Open", "05-11-2026", "Rs 12,345.00", "", ""),
	bot_docs.SALES_ORDER: ("SO-SAMPLE-0001", "To Deliver and Bill", "05-11-2026", "Rs 12,345.00", "", ""),
	bot_docs.SALES_INVOICE: ("INV-SAMPLE-0001", "Unpaid", "05-11-2026", "Rs 12,345.00", "Rs 4,000.00", "20-11-2026"),
}


@frappe.whitelist(methods=["POST"])
def simulate(bot: str, state: str | dict | None = None, text: str = "", interactive_id: str | None = None, open_now: int = 1, matched: int = 1, published: int = 0, event: str = "reply", has_docs: int = 1, start: str | None = None):
	"""One step of the bot as a customer would see it, with NOTHING sent. Pass back the `state` it returns to carry on. With
	`published` the live version is tried, otherwise the draft. `event` "timeout" tries the 'no answer' path; `start` is the Trigger start to begin with (by its id); `has_docs` says whether
	the made-up customer has documents and library files. Names and documents are made up."""
	doc = _bot(bot)
	source = doc.published_json if frappe.utils.cint(published) else doc.graph_json
	graph = json.loads(source) if source else None
	problems = rules.validate_graph(graph, engine.extras_on())
	if problems:
		return {"problems": problems}
	state = json.loads(state) if isinstance(state, str) and state else (state or {})
	if start and not state.get("node"):  # a new run: which of the Trigger's starts to begin with
		state = {**state, "vars": {**(state.get("vars") or {}), "_start": start}}
	facts = {"customer_name": "Asha", "customer_phone": "+91 98111 11111", "number_name": frappe.db.get_value("Waba Number", doc.waba_number, "display_name") or "us", "open_now": bool(frappe.utils.cint(open_now)), "matched": bool(frappe.utils.cint(matched))}
	have = bool(frappe.utils.cint(has_docs))
	docs_needed, files_needed = engine._needs(graph)
	if docs_needed:
		facts["docs"] = {dt: (dict(zip(bot_docs.DOC_VARS, SAMPLE_DOCS[dt])) if have else None) for dt in docs_needed}
	if files_needed:
		facts["files"] = {name: have for name in files_needed}
	timeout = event == "timeout"
	reply = {"text": text or "", "interactive_id": interactive_id} if state.get("node") and not timeout else None
	result = rules.run(graph, state, facts, reply, human_words=doc.handover_words or rules.DEFAULT_HUMAN_WORDS, stuck_limit=doc.stuck_limit or rules.DEFAULT_STUCK_LIMIT, event="timeout" if timeout else "reply")
	return {
		"problems": [],
		"actions": result.actions,
		"state": result.state,
		"ended": result.ended,
		"kind": result.kind,
		"team": result.team,
		"agent": result.agent,
		"reason": result.reason,
		"log": result.log,
		"timeout_minutes": result.timeout_minutes,
	}
