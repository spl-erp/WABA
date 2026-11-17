"""A WhatsApp bot, as pure rules: no database, no Frappe, fully testable offline.

A bot is a small graph the Waba Admin draws: blocks (nodes) joined by lines (edges). It is NOT a program: there is no code,
no expression language, nothing is evaluated. A customer's reply moves the bot along one line to the next block.

  Trigger      starts the bot (a new chat, any message while nobody has the chat, or a keyword)
  Message      sends text and goes on                      Note         writes an internal note and goes on
  Buttons      up to 3 quick-reply buttons, then WAITS     List         up to 10 choices behind one button, then WAITS
  Ask          asks a question, checks the answer (text / number / phone / email), keeps it, then WAITS
  Condition    yes / no: business hours open, an answer equals / contains, the customer is a known record
  Assign team  gives the chat to a team's least busy available agent, and the bot ends
  Hand over    the bot ends and the number's normal routing takes the chat
  End          the bot ends (and the normal routing takes the chat)

`run` walks the graph for one customer reply and returns what to send, the new state and, when the bot is over, why. It
never talks to Meta or the database; waba.bot does that around it. Every walk is bounded (a step limit; a graph in which
blocks that do not wait could loop forever is refused when the bot is published).

The graph shape mirrors Frappe's own Workflow Builder, so a canvas can draw it:
  {"nodes": [{"id", "type", "position": {"x", "y"}, "data": {...}}], "edges": [{"id", "source", "sourceHandle", "target"}]}
"""

import re
from dataclasses import dataclass, field

from waba.rules import bot_docs, outbound

TRIGGER, MESSAGE, BUTTONS, LIST, ASK = "trigger", "message", "buttons", "list", "ask"
CONDITION, ASSIGN_TEAM, HANDOVER, NOTE, END = "condition", "assign_team", "handover", "note", "end"
STATUS_LOOKUP, SEND_FILE, LINK_BUTTON = "status_lookup", "send_file", "link_button"
NODE_TYPES = (TRIGGER, MESSAGE, BUTTONS, LIST, ASK, CONDITION, ASSIGN_TEAM, HANDOVER, NOTE, END, STATUS_LOOKUP, SEND_FILE, LINK_BUTTON)
# preview blocks: built, but unusable until Waba Settings > "Bot builder: preview blocks" is switched on (see problems_for / uses_extras)
GATED_TYPES = (STATUS_LOOKUP, SEND_FILE, LINK_BUTTON)
WAITING = (BUTTONS, LIST, ASK)  # the bot stops here until the customer answers
TERMINAL = (ASSIGN_TEAM, HANDOVER, END)  # nothing comes after these

OUT, YES, NO = "out", "yes", "no"  # the handles of a block that has one way on, or two
FOUND, NONE, TIMEOUT = "found", "none", "timeout"  # Status lookup / Send document: found or not; a waiting block: no answer in time
FILE_SOURCES = ("library", "erp_pdf")
MAX_TIMEOUT_MINUTES = 720
MAX_TIMEOUTS = 3  # no-answer paths one session may run before the bot hands over

NEW_CHAT, ANY_UNASSIGNED, KEYWORD = "new_conversation", "any_unassigned", "keyword"
TRIGGERS = (NEW_CHAT, ANY_UNASSIGNED, KEYWORD)
TRIGGER_LABELS = {NEW_CHAT: "A new conversation", ANY_UNASSIGNED: "Any message while nobody has the chat", KEYWORD: "A keyword"}
EXACT, CONTAINS = "exact", "contains"

CONDITIONS = ("working_hours", "var_equals", "var_contains", "matched")
VALIDATIONS = ("text", "number", "phone", "email")

# how a session ends (the Waba Bot Session status)
ACTIVE, FINISHED, HANDED_OVER, EXPIRED, STOPPED = "Active", "Finished", "Handed over", "Expired", "Stopped by agent"
STATUSES = (ACTIVE, FINISHED, HANDED_OVER, EXPIRED, STOPPED)

BUILTIN_VARS = ("customer_name", "customer_phone", "number_name")
RESERVED_VARS = BUILTIN_VARS + ("last_choice",) + bot_docs.DOC_VARS
_VAR = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")
_VAR_NAME = re.compile(r"^[a-z][a-z0-9_]{0,30}$")

DEFAULT_HUMAN_WORDS = "agent, human, person, representative, executive, talk to someone, speak to someone"
DEFAULT_STUCK_LIMIT = 2
DEFAULT_TIMEOUT_MINUTES = 1440
DEFAULT_COOLDOWN_HOURS = 12
MAX_STEPS = 20  # blocks walked for one customer reply
MAX_BOT_MESSAGES = 30  # messages one session may send
MAX_TEXT = 1024  # a bot message (kept inside Meta's interactive limit, so one rule fits all)
MAX_PROMPT_REPLY = 40  # "agent" typed on its own; a long sentence that happens to contain it is not a request


# ---------------------------------------------------------------------------------------------------------- text


def used_vars(text):
	return [m.group(1) for m in _VAR.finditer(text or "")]


def render(text, variables):
	"""The text with {{name}} filled from `variables`; an unknown name becomes empty (never code, never an error)."""
	return _VAR.sub(lambda m: str((variables or {}).get(m.group(1)) or ""), text or "").strip()


def _norm(text):
	return re.sub(r"\s+", " ", str(text or "").strip()).casefold()


def _words_list(csv):
	return [_norm(w) for w in re.split(r"[,\n;]+", str(csv or "")) if _norm(w)]


def _has_word(text, word):
	return bool(re.search(r"(?<!\w)" + re.escape(word) + r"(?!\w)", text))


def matches_human(text, words_csv):
	"""The customer is asking for a person: a short message holding one of the words (as a whole word)."""
	t = _norm(text)
	if not t or len(t) > MAX_PROMPT_REPLY:
		return False
	return any(_has_word(t, w) for w in _words_list(words_csv))


def match_keywords(text, keywords_csv, mode=EXACT):
	t = _norm(text)
	if not t:
		return False
	words = _words_list(keywords_csv)
	if mode == CONTAINS:
		return any(_has_word(t, w) for w in words)
	return t in words


def match_reply(options, interactive_id=None, text=None):
	"""The button or list row the customer chose: by the id Meta sends back, else by its title, else by its number (1, 2, 3)."""
	options = list(options or [])
	if interactive_id:
		for o in options:
			if str(o.get("id")) == str(interactive_id):
				return o
	t = _norm(text)
	if t:
		for o in options:
			if _norm(o.get("title")) == t:
				return o
		if t.isdigit() and 1 <= int(t) <= len(options):
			return options[int(t) - 1]
	return None


def validate_value(kind, text):
	"""(ok, cleaned) for an answer to an Ask block."""
	value = re.sub(r"\s+", " ", str(text or "").strip())
	if not value or len(value) > 500:
		return False, ""
	if kind == "number":
		return (True, value) if re.fullmatch(r"-?\d+([.,]\d+)?", value) else (False, "")
	if kind == "phone":
		digits = re.sub(r"\D", "", value)
		return (True, value) if 7 <= len(digits) <= 15 and re.fullmatch(r"[+\d][\d\s\-()]*", value) else (False, "")
	if kind == "email":
		return (True, value) if re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value) else (False, "")
	return True, value


# ---------------------------------------------------------------------------------------------------------- the graph


def label(node):
	data = node.get("data") or {}
	return data.get("label") or {
		TRIGGER: "Trigger", MESSAGE: "Message", BUTTONS: "Buttons", LIST: "List", ASK: "Question",
		CONDITION: "Condition", ASSIGN_TEAM: "Assign to team", HANDOVER: "Hand over", NOTE: "Note", END: "End",
		STATUS_LOOKUP: "Status lookup", SEND_FILE: "Send document", LINK_BUTTON: "Link button",
	}.get(node.get("type"), "Block") + f" ({node.get('id')})"


def options(node):
	"""The choices of a Buttons or List block as [{"id", "title"}], in order."""
	data = node.get("data") or {}
	if node.get("type") == BUTTONS:
		return list(data.get("buttons") or [])
	if node.get("type") == LIST:
		return list(data.get("rows") or [])
	return []


def timeout_of(node):
	"""Minutes a customer may stay silent at this waiting block before its 'no answer' path runs (0 = no such path)."""
	if node.get("type") not in WAITING:
		return 0
	try:
		return max(0, int((node.get("data") or {}).get("timeout_minutes") or 0))
	except (TypeError, ValueError):
		return 0


def handles(node):
	"""The handles a block must have a line from."""
	t = node.get("type")
	if t == TRIGGER:
		return [x["id"] for x in starts_of(node.get("data"))]
	if t in (MESSAGE, NOTE, LINK_BUTTON):
		return [OUT]
	if t == ASK:
		return [OUT] + ([TIMEOUT] if timeout_of(node) else [])
	if t == CONDITION:
		return [YES, NO]
	if t in (STATUS_LOOKUP,):
		return [FOUND, NONE]
	if t == SEND_FILE:
		return [OUT, NONE]
	if t in (BUTTONS, LIST):
		return [str(o.get("id")) for o in options(node)] + ([TIMEOUT] if timeout_of(node) else [])
	return []


def uses_extras(graph):
	"""Does this bot use anything that is a preview feature (a preview block, or a 'no answer' timeout)?"""
	return any(n.get("type") in GATED_TYPES or timeout_of(n) for n in (graph or {}).get("nodes") or [])


def declared_vars(graph):
	names = list(BUILTIN_VARS) + ["last_choice"]
	for n in graph.get("nodes") or []:
		if n.get("type") == ASK and _VAR_NAME.match(str((n.get("data") or {}).get("var") or "")):
			names.append(n["data"]["var"])
	if any(n.get("type") == STATUS_LOOKUP for n in graph.get("nodes") or []):
		names += list(bot_docs.DOC_VARS)
	return names


def trigger_of(graph):
	for n in graph.get("nodes") or []:
		if n.get("type") == TRIGGER:
			return n.get("data") or {}
	return {}


MAX_STARTS = 10


def starts_of(trigger):
	"""The ways a bot can start, as [{id, label, mode, keywords, match}]. The id is the output point on the Trigger block.
	An older bot (one mode on the Trigger itself, no list) counts as one start whose output point is `out`."""
	d = trigger or {}
	if isinstance(d.get("starts"), list):
		return [
			{"id": str(x.get("id") or ""), "label": str(x.get("label") or "").strip(), "mode": x.get("mode"), "keywords": x.get("keywords"), "match": x.get("match")}
			for x in d["starts"]
			if isinstance(x, dict)
		]
	return [{"id": OUT, "label": "", "mode": d.get("mode"), "keywords": d.get("keywords"), "match": d.get("match")}]


def start_name(start):
	return start.get("label") or TRIGGER_LABELS.get(start.get("mode"), "")


def match_start(trigger, *, first_message, text):
	"""The start of this Trigger that the customer's message hits, or None. A keyword start wins over a new-conversation start,
	which wins over an any-message start; between starts of the same kind the one listed first wins."""
	starts = starts_of(trigger)
	for mode in (KEYWORD, NEW_CHAT, ANY_UNASSIGNED):
		for start in starts:
			if start.get("mode") == mode and _start_matches(start, first_message, text):
				return start
	return None


def _start_matches(start, first_message, text):
	mode = start.get("mode")
	if mode == NEW_CHAT:
		return bool(first_message)
	if mode == ANY_UNASSIGNED:
		return True
	if mode == KEYWORD:
		return match_keywords(text, start.get("keywords"), start.get("match") or EXACT)
	return False


def trigger_modes(graph):
	"""The kinds of start a bot has (a set), for the one-bot-per-start rule."""
	return {s.get("mode") for s in starts_of(trigger_of(graph)) if s.get("mode")}


def _edge_map(graph):
	out = {}
	for e in graph.get("edges") or []:
		out.setdefault((e.get("source"), e.get("sourceHandle") or OUT), e.get("target"))
	return out


def next_node(graph, node_id, handle=OUT):
	return _edge_map(graph).get((node_id, handle))


def validate_graph(graph, extras=True):
	"""Plain-words problems that stop a bot being published (empty list = fine). `extras` is whether the preview features are
	switched on (Waba Settings); with them off, a bot that uses one cannot be published."""
	return [p["text"] for p in problems_for(graph, extras)]


def problems_for(graph, extras=True):
	"""The same problems as validate_graph, each with the block it is about: [{"node": id or None, "text": ...}]. The builder
	marks the block and lists the text; Publish refuses while there are any."""
	if not isinstance(graph, dict) or not isinstance(graph.get("nodes"), list):
		return [{"node": None, "text": "The bot is empty. Add a Trigger and some blocks."}]
	nodes = graph["nodes"]
	edges = graph.get("edges") or []
	found = []

	def add(text, node=None):
		found.append({"node": node.get("id") if isinstance(node, dict) else node, "text": text})

	ids = [n.get("id") for n in nodes]
	if len(set(ids)) != len(ids) or any(not i for i in ids):
		add("Every block needs its own id.")
	by_id = {n.get("id"): n for n in nodes}
	triggers = [n for n in nodes if n.get("type") == TRIGGER]
	if len(triggers) != 1:
		add("A bot needs exactly one Trigger block." if triggers or nodes else "The bot is empty. Add a Trigger and some blocks.", triggers[1] if len(triggers) > 1 else None)
	known = set(declared_vars(graph))
	for n in nodes:
		if not extras:
			if n.get("type") in GATED_TYPES:
				add(f"{label(n)} is a preview block that is switched off, so it cannot be used yet.", n)
			if timeout_of(n):
				add(f"{label(n)} has a 'no answer' timeout, which is a preview feature that is switched off.", n)
		if n.get("type") not in NODE_TYPES:
			add(f"{label(n)} is of an unknown kind.", n)
			continue
		for p in _node_problems(n, known):
			add(f"{label(n)}: {p}", n)
	# the lines
	seen = set()
	for e in edges:
		src, dst, handle = by_id.get(e.get("source")), by_id.get(e.get("target")), e.get("sourceHandle") or OUT
		if not src or not dst:
			add("A line joins a block that no longer exists.")
			continue
		if dst.get("type") == TRIGGER:
			add(f"{label(dst)} cannot have a line coming into it.", dst)
		if src.get("type") in TERMINAL:
			add(f"{label(src)} ends the bot, so nothing can follow it.", src)
			continue
		if handle not in handles(src):
			add(f"{label(src)} has a line from '{handle}', which it does not have.", src)
		if (src["id"], handle) in seen:
			add(f"{label(src)} has two lines from the same point.", src)
		seen.add((src["id"], handle))
	for n in nodes:
		if n.get("type") in NODE_TYPES:
			for h in handles(n):
				if (n["id"], h) not in seen:
					add(f"{label(n)}{'' if h == OUT else ' (' + _handle_name(n, h) + ')'} is not joined to anything. Join it to a block or an End.", n)
	# everything reachable from the trigger
	if len(triggers) == 1:
		edge_map = _edge_map(graph)
		reached, stack = set(), [triggers[0]["id"]]
		while stack:
			cur = stack.pop()
			if cur in reached or cur not in by_id:
				continue
			reached.add(cur)
			stack += [t for (s, _h), t in edge_map.items() if s == cur]
		for n in nodes:
			if n.get("id") not in reached:
				add(f"{label(n)} is not reachable from the Trigger.", n)
		if _loops_without_waiting(by_id, edge_map):
			add("The blocks form a loop that never waits for the customer. Put a Buttons, List or Question block in the loop.")
	return found


def _handle_name(node, handle):
	for o in options(node):
		if str(o.get("id")) == handle:
			return o.get("title") or handle
	if node.get("type") == TRIGGER:
		for x in starts_of(node.get("data")):
			if x["id"] == handle:
				return start_name(x) or handle
	return {YES: "Yes", NO: "No"}.get(handle, handle)


def _loops_without_waiting(by_id, edge_map):
	"""True when blocks that do not wait for the customer can lead back to themselves (an endless loop)."""
	state = {}

	def visit(node_id):
		if state.get(node_id) == 1:
			return True
		if state.get(node_id) == 2:
			return False
		node = by_id.get(node_id)
		if not node or node.get("type") in WAITING or node.get("type") in TERMINAL:
			return False
		state[node_id] = 1
		for (src, _h), target in edge_map.items():
			if src == node_id and visit(target):
				return True
		state[node_id] = 2
		return False

	return any(visit(i) for i in by_id)


def _text_problems(text, known, what="The text"):
	text = (text or "").strip()
	problems = []
	if not text:
		problems.append(f"{what} is empty.")
	elif len(text) > MAX_TEXT:
		problems.append(f"{what} can have at most {MAX_TEXT} characters.")
	for name in used_vars(text):
		if name not in known:
			problems.append(f"{what} uses {{{{{name}}}}}, which is not a known value. Use {', '.join('{{' + k + '}}' for k in BUILTIN_VARS)} or an answer from a Question block.")
	return problems


def _node_problems(node, known):
	return _core_problems(node, known) + _timeout_problems(node)


def _timeout_problems(node):
	d = node.get("data") or {}
	if node.get("type") not in WAITING or d.get("timeout_minutes") in (None, "", 0, "0"):
		return []
	try:
		minutes = int(d.get("timeout_minutes"))
	except (TypeError, ValueError):
		return ["The 'no answer' time must be a whole number of minutes."]
	if not 1 <= minutes <= MAX_TIMEOUT_MINUTES:
		return [f"The 'no answer' time must be between 1 and {MAX_TIMEOUT_MINUTES} minutes (a message can only be sent while the customer's 24-hour window is open)."]
	return []


def _core_problems(node, known):
	t = node.get("type")
	d = node.get("data") or {}
	if t == TRIGGER:
		starts = starts_of(d)
		if not starts:
			return ["Add at least one way to start the bot."]
		problems = []
		if len(starts) > MAX_STARTS:
			problems.append(f"A bot can have at most {MAX_STARTS} starts.")
		ids = [x["id"] for x in starts]
		if any(not i for i in ids) or len(set(ids)) != len(ids):
			problems.append("Every start needs its own id.")
		many = len(starts) > 1
		for n, x in enumerate(starts, 1):
			name = f"Start {n}: " if many else ""
			mode = x.get("mode")
			if mode not in TRIGGERS:
				problems.append(f"{name}Choose what starts the bot.")
			elif mode == KEYWORD:
				if not _words_list(x.get("keywords")):
					problems.append(f"{name}Write at least one keyword.")
				elif x.get("match") not in (EXACT, CONTAINS):
					problems.append(f"{name}Choose whether the message must be exactly the keyword or only contain it.")
		for mode, label_ in ((NEW_CHAT, "a new conversation"), (ANY_UNASSIGNED, "any message")):
			if sum(1 for x in starts if x.get("mode") == mode) > 1:
				problems.append(f"Only one start can begin with {label_}.")
		seen_words = {}
		for n, x in enumerate(starts, 1):
			if x.get("mode") != KEYWORD:
				continue
			for w in dict.fromkeys(_words_list(x.get("keywords"))):
				if w in seen_words and seen_words[w] != n:
					problems.append(f'The keyword "{w}" is used by Start {seen_words[w]} and Start {n}. Only the first would ever run.')
				seen_words.setdefault(w, n)
		return problems
	if t in (MESSAGE, NOTE):
		return _text_problems(d.get("text"), known)
	if t == BUTTONS:
		return _text_problems(d.get("text"), known) + outbound.check_buttons(_flat(d.get("text")), d.get("buttons"))
	if t == LIST:
		return _text_problems(d.get("text"), known) + outbound.check_list(_flat(d.get("text")), d.get("button_text"), d.get("rows"))
	if t == ASK:
		problems = _text_problems(d.get("text"), known, "The question")
		var = str(d.get("var") or "")
		if not _VAR_NAME.match(var):
			problems.append("Give the answer a name of lower-case letters, digits and underscores (for example city).")
		elif var in RESERVED_VARS:
			problems.append(f"'{var}' is already used; choose another name for the answer.")
		if d.get("validate", "text") not in VALIDATIONS:
			problems.append("Choose what kind of answer is expected.")
		return problems
	if t == CONDITION:
		kind = d.get("kind")
		if kind not in CONDITIONS:
			return ["Choose what to check."]
		if kind in ("var_equals", "var_contains"):
			problems = []
			if d.get("var") not in known or d.get("var") in BUILTIN_VARS:
				problems.append("Choose an answer from a Question block to check.")
			if not str(d.get("value") or "").strip():
				problems.append("Write the value to compare with.")
			return problems
		return []
	if t == ASSIGN_TEAM:
		problems = [] if str(d.get("team") or "").strip() else ["Choose the team."]
		if (d.get("text") or "").strip():
			problems += _text_problems(d.get("text"), known)
		return problems
	if t == LINK_BUTTON:
		problems = _text_problems(d.get("text"), known)
		button = str(d.get("button_text") or "").strip()
		if not button:
			problems.append("The button has no text.")
		elif len(button) > outbound.MAX_CTA_BUTTON:
			problems.append(f"The button text can have at most {outbound.MAX_CTA_BUTTON} characters.")
		return problems + outbound.check_cta_url(d.get("url"))
	if t == SEND_FILE:
		problems = []
		source = d.get("source")
		if source not in FILE_SOURCES:
			problems.append("Choose what to send: a file from the library, or a document from the ERP.")
		elif source == "library" and not str(d.get("shared_file") or "").strip():
			problems.append("Choose the library file.")
		elif source == "erp_pdf" and d.get("doctype") not in bot_docs.DOC_TYPES:
			problems.append("Choose which document to send (Quotation, Sales Order or Sales Invoice).")
		if (d.get("caption") or "").strip():
			problems += _text_problems(d.get("caption"), known, "The caption")
		return problems
	if t == STATUS_LOOKUP:
		problems = _text_problems(d.get("text"), known)
		if d.get("doctype") not in bot_docs.DOC_TYPES:
			problems.append("Choose which document to look up (Quotation, Sales Order or Sales Invoice).")
		return problems
	if t in (HANDOVER, END):
		return _text_problems(d.get("text"), known) if (d.get("text") or "").strip() else []
	return []


def _flat(text):
	return re.sub(_VAR, "x", text or "")  # for Meta's length limits a value is assumed short; the real length is checked when sending


# ---------------------------------------------------------------------------------------------------------- starting


def should_start(trigger, *, first_message, text):
	"""Does this customer message start a bot with this trigger? (The guards in hold_reason are separate.)"""
	return match_start(trigger, first_message=first_message, text=text) is not None


def pick_bot(candidates):
	"""The bot that answers: a keyword bot first, then a new-conversation bot, then the any-message one.
	`candidates` is [(bot_id, trigger_mode)] of the bots whose trigger matched; None when there is none."""
	for mode in (KEYWORD, NEW_CHAT, ANY_UNASSIGNED):
		for bot_id, m in candidates:
			if m == mode:
				return bot_id
	return None


def hold_reason(*, switch_on, published, opted_out, assigned, receive_only, number_ok, test_ok, cooling_down):
	"""The first reason a bot must NOT act on this conversation, as (code, plain words) or None when it may."""
	if not switch_on:
		return "switch_off", "Bots are switched off in Waba Settings."
	if not published:
		return "not_published", "The bot has no published version."
	if receive_only:
		return "receive_only", "The number is set to receive only, so nothing can be sent from it."
	if not number_ok:
		return "number", "The number is switched off or not set up for conversations."
	if opted_out:
		return "opted_out", "The customer asked not to be messaged."
	if assigned:
		return "assigned", "A person already has this chat."
	if not test_ok:
		return "test_mode", "Test mode is on and this phone is not on the test list."
	if cooling_down:
		return "cooldown", "The bot already finished with this customer a short while ago."
	return None


def is_cooling_down(last_ended_at, now, hours):
	if not last_ended_at or not hours or hours <= 0:
		return False
	return (now - last_ended_at).total_seconds() < hours * 3600


def session_expired(last_activity, now, minutes):
	if not last_activity or not minutes or minutes <= 0:
		return False
	return (now - last_activity).total_seconds() >= minutes * 60


def over_cap(sent, adding, cap=MAX_BOT_MESSAGES):
	return sent + adding > cap


# ---------------------------------------------------------------------------------------------------------- the walk


@dataclass
class Result:
	actions: list = field(default_factory=list)  # what to send / write, in order
	state: dict = field(default_factory=dict)  # {"node", "vars", "retries"} to keep for the next reply
	ended: str | None = None  # None while waiting for the customer, else FINISHED or HANDED_OVER
	kind: str | None = None  # why it ended: finished, handover, assign_team, asked, stuck, loop, missing
	team: str | None = None
	agent: str | None = None  # the person an Assign block named (None = the team's least busy available agent)
	reason: str = ""  # plain words for the chat's Event note
	log: list = field(default_factory=list)  # [{"node", "type", "input", "result"}]
	timeout_minutes: int = 0  # >0: the block the customer now waits at has a 'no answer' path after this many minutes


def _prompt(node, variables):
	d = node.get("data") or {}
	body = render(d.get("text"), variables)
	if node["type"] == BUTTONS:
		return {"do": "buttons", "body": body, "buttons": [{"id": str(b["id"]), "title": b["title"].strip()} for b in options(node)]}
	if node["type"] == LIST:
		rows = [{"id": str(r["id"]), "title": r["title"].strip(), "description": (r.get("description") or "").strip()} for r in options(node)]
		return {"do": "list", "body": body, "button": (d.get("button_text") or "Choose").strip(), "rows": rows}
	return {"do": "text", "body": body}


def run(graph, state, facts, reply=None, *, human_words=DEFAULT_HUMAN_WORDS, stuck_limit=DEFAULT_STUCK_LIMIT, max_steps=MAX_STEPS, event="reply"):
	"""Walk the bot for one customer message.

	`state` is {"node": id or None (not started), "vars": {...}, "retries": n}. `facts` holds customer_name, customer_phone,
	number_name, open_now (inside business hours) and matched (a known record). `reply` is {"text", "interactive_id"} of the
	customer's answer; None when the bot is just starting (the customer's first message started it, it is not an answer).
	`facts` may also hold `docs` ({document type: values or None}, the customer's own latest documents) and `files`
	({library file: usable}), gathered before the walk so the walk itself stays pure. `event` is "timeout" when the customer
	stayed silent at a block with a 'no answer' path: the walk then leaves that block by its `timeout` line."""
	nodes = {n["id"]: n for n in graph.get("nodes") or []}
	st = {"node": (state or {}).get("node"), "vars": dict((state or {}).get("vars") or {}), "retries": (state or {}).get("retries") or 0}
	res = Result(state=st)
	reply = reply or {}
	text = reply.get("text") or ""

	def end(kind, ended, why, team=None, agent=None):
		res.ended, res.kind, res.reason, res.team, res.agent = ended, kind, why, team, agent or None
		st["node"] = None

	def variables():
		return {**{k: facts.get(k) or "" for k in BUILTIN_VARS}, **st["vars"]}

	cur = None
	if st["node"] is None:
		trigger = next((n for n in nodes.values() if n["type"] == TRIGGER), None)
		if not trigger:
			end("missing", HANDED_OVER, "the bot has no trigger")
			return res
		starts = starts_of(trigger.get("data"))
		chosen = next((x for x in starts if x["id"] == st["vars"].get("_start")), None) or (starts[0] if starts else {"id": OUT, "label": ""})
		named = len(starts) > 1 and start_name(chosen)
		res.log.append({"node": trigger["id"], "type": TRIGGER, "input": text, "result": f"started: {named}" if named else "started"})
		cur = next_node(graph, trigger["id"], chosen["id"])
	else:
		node = nodes.get(st["node"])
		if not node:
			end("missing", HANDED_OVER, "the bot was changed while the customer was in it")
			return res
		d = node.get("data") or {}
		if event == "timeout":
			res.log.append({"node": node["id"], "type": node["type"], "input": "", "result": "no answer in time"})
			cur = next_node(graph, node["id"], TIMEOUT)
			if cur is None:
				end("handover", HANDED_OVER, "the customer did not answer")
				return res
		elif node["type"] in (BUTTONS, LIST):
			chosen = match_reply(options(node), reply.get("interactive_id"), text)
			if chosen:
				st["vars"]["last_choice"] = chosen.get("title") or ""
				st["retries"] = 0
				res.log.append({"node": node["id"], "type": node["type"], "input": text or chosen.get("title") or "", "result": f"chose {chosen.get('title')}"})
				cur = next_node(graph, node["id"], str(chosen.get("id")))
			elif matches_human(text, human_words):
				res.log.append({"node": node["id"], "type": node["type"], "input": text, "result": "asked for a person"})
				end("asked", HANDED_OVER, "the customer asked for a person")
				return res
			else:
				return _retry(res, st, node, text, stuck_limit, variables(), end, "Please choose one of the options below.")
		else:  # ASK
			if matches_human(text, human_words):
				res.log.append({"node": node["id"], "type": ASK, "input": text, "result": "asked for a person"})
				end("asked", HANDED_OVER, "the customer asked for a person")
				return res
			ok, value = validate_value(d.get("validate") or "text", text)
			if ok:
				st["vars"][d["var"]] = value
				st["retries"] = 0
				res.log.append({"node": node["id"], "type": ASK, "input": text, "result": f"kept {d['var']}"})
				cur = next_node(graph, node["id"], OUT)
			else:
				return _retry(res, st, node, text, stuck_limit, variables(), end, d.get("retry_text") or "Sorry, that does not look right.")

	waiting, steps = False, 0
	while cur is not None and not res.ended:
		steps += 1
		if steps > max_steps:
			end("loop", HANDED_OVER, "the bot took too many steps")
			break
		node = nodes.get(cur)
		if not node:
			end("missing", HANDED_OVER, "the bot was changed while the customer was in it")
			break
		t, d = node["type"], node.get("data") or {}
		if t == MESSAGE:
			res.actions.append({"do": "text", "body": render(d.get("text"), variables())})
			res.log.append({"node": cur, "type": t, "input": "", "result": "sent a message"})
			cur = next_node(graph, cur, OUT)
		elif t == NOTE:
			res.actions.append({"do": "note", "text": render(d.get("text"), variables())})
			res.log.append({"node": cur, "type": t, "input": "", "result": "wrote a note"})
			cur = next_node(graph, cur, OUT)
		elif t in (BUTTONS, LIST, ASK):
			res.actions.append(_prompt(node, variables()))
			res.log.append({"node": cur, "type": t, "input": "", "result": "asked and waits"})
			st["node"], st["retries"] = cur, 0
			res.timeout_minutes = timeout_of(node)
			waiting = True
			break
		elif t == LINK_BUTTON:
			res.actions.append({"do": "cta", "body": render(d.get("text"), variables()), "button": (d.get("button_text") or "").strip(), "url": (d.get("url") or "").strip()})
			res.log.append({"node": cur, "type": t, "input": "", "result": "sent a link"})
			cur = next_node(graph, cur, OUT)
		elif t == STATUS_LOOKUP:
			doc = (facts.get("docs") or {}).get(d.get("doctype"))
			if doc:
				st["vars"].update(doc)
				res.actions.append({"do": "text", "body": render(d.get("text"), variables())})
			res.log.append({"node": cur, "type": t, "input": "", "result": f"found {doc.get('doc_name')}" if doc else "nothing found"})
			cur = next_node(graph, cur, FOUND if doc else NONE)
		elif t == SEND_FILE:
			caption = render(d.get("caption"), variables())
			if d.get("source") == "library":
				ok = bool((facts.get("files") or {}).get(d.get("shared_file")))
				action = {"do": "file", "file": d.get("shared_file"), "caption": caption}
			else:
				doc = (facts.get("docs") or {}).get(d.get("doctype"))
				ok = bool(doc)
				action = {"do": "pdf", "doctype": d.get("doctype"), "name": (doc or {}).get("doc_name"), "caption": caption}
			if ok:
				res.actions.append(action)
			res.log.append({"node": cur, "type": t, "input": "", "result": "sent a document" if ok else "nothing to send"})
			cur = next_node(graph, cur, OUT if ok else NONE)
		elif t == CONDITION:
			yes = _condition(d, st["vars"], facts)
			res.log.append({"node": cur, "type": t, "input": "", "result": "yes" if yes else "no"})
			cur = next_node(graph, cur, YES if yes else NO)
		elif t == ASSIGN_TEAM:
			if (d.get("text") or "").strip():
				res.actions.append({"do": "text", "body": render(d.get("text"), variables())})
			who = f" ({d.get('agent')})" if d.get("agent") else ""
			res.log.append({"node": cur, "type": t, "input": "", "result": f"gave the chat to team {d.get('team')}{who}"})
			end("assign_team", HANDED_OVER, f"the bot gave the chat to team {d.get('team')}{who}", d.get("team"), d.get("agent"))
		elif t == HANDOVER:
			if (d.get("text") or "").strip():
				res.actions.append({"do": "text", "body": render(d.get("text"), variables())})
			res.log.append({"node": cur, "type": t, "input": "", "result": "handed over"})
			end("handover", HANDED_OVER, "the bot handed the chat over")
		elif t == END:
			if (d.get("text") or "").strip():
				res.actions.append({"do": "text", "body": render(d.get("text"), variables())})
			res.log.append({"node": cur, "type": t, "input": "", "result": "finished"})
			end("finished", FINISHED, "the bot finished")
		else:
			end("missing", HANDED_OVER, "the bot has an unknown block")
	if not waiting and not res.ended:
		end("finished", FINISHED, "the bot finished")  # a line that leads nowhere simply ends the bot
	return res


def _retry(res, st, node, text, stuck_limit, variables, end, hint):
	st["retries"] += 1
	res.log.append({"node": node["id"], "type": node["type"], "input": text, "result": f"not understood ({st['retries']})"})
	if st["retries"] >= max(1, stuck_limit):
		end("stuck", HANDED_OVER, "the customer's replies were not understood")
		return res
	prompt = _prompt(node, variables)
	prompt["body"] = f"{hint}\n\n{prompt['body']}" if node["type"] != ASK else f"{hint} {prompt['body']}"
	res.actions.append(prompt)
	return res


def _condition(d, variables, facts):
	kind = d.get("kind")
	if kind == "working_hours":
		return bool(facts.get("open_now"))
	if kind == "matched":
		return bool(facts.get("matched"))
	have, want = _norm(variables.get(d.get("var"), "")), _norm(d.get("value"))
	if kind == "var_equals":
		return have == want
	if kind == "var_contains":
		return bool(want) and want in have
	return False


# ---------------------------------------------------------------------------------------------------------- a ready-made bot


def starter_graph(sales_team=None, accounts_team=None):
	"""The Welcome + menu bot: greets a new chat and offers Sales, Accounts or a person. A choice goes to that team when one is
	named, otherwise to the number's normal routing."""

	def end_node(node_id, team, text):
		if team:
			return {"id": node_id, "type": ASSIGN_TEAM, "position": {"x": 0, "y": 0}, "data": {"team": team, "text": text}}
		return {"id": node_id, "type": HANDOVER, "position": {"x": 0, "y": 0}, "data": {"text": text}}

	nodes = [
		{"id": "trigger", "type": TRIGGER, "position": {"x": 40, "y": 140}, "data": {"mode": NEW_CHAT}},
		{"id": "welcome", "type": MESSAGE, "position": {"x": 300, "y": 140}, "data": {"text": "Hello {{customer_name}}! Thank you for contacting {{number_name}}."}},
		{
			"id": "menu",
			"type": BUTTONS,
			"position": {"x": 580, "y": 140},
			"data": {
				"text": "How can we help you today?",
				"buttons": [{"id": "sales", "title": "Sales"}, {"id": "accounts", "title": "Accounts"}, {"id": "person", "title": "Talk to a person"}],
			},
		},
		end_node("to_sales", sales_team, "Connecting you with our Sales team. Someone will reply shortly."),
		end_node("to_accounts", accounts_team, "Connecting you with our Accounts team. Someone will reply shortly."),
		end_node("to_person", None, "Connecting you with one of our team. Someone will reply shortly."),
	]
	for i, n in enumerate(nodes[3:]):
		n["position"] = {"x": 880, "y": 20 + i * 150}
	edges = [
		{"id": "e1", "source": "trigger", "sourceHandle": OUT, "target": "welcome"},
		{"id": "e2", "source": "welcome", "sourceHandle": OUT, "target": "menu"},
		{"id": "e3", "source": "menu", "sourceHandle": "sales", "target": "to_sales"},
		{"id": "e4", "source": "menu", "sourceHandle": "accounts", "target": "to_accounts"},
		{"id": "e5", "source": "menu", "sourceHandle": "person", "target": "to_person"},
	]
	return {"nodes": nodes, "edges": edges}
