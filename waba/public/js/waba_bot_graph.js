/* The bot builder's graph: pure functions (no DOM), tested offline in Node.
 *
 * A bot is {nodes: [{id, type, position: {x, y}, data}], edges: [{id, source, sourceHandle, target}]}. The same shape the server
 * checks and runs (waba/rules/bot.py). Every function changes the graph it is given and returns what it made; the builder takes a
 * snapshot first (History) so each change can be undone. The server is the only judge of whether a bot is valid: nothing here
 * decides that, it only keeps the graph tidy and within Meta's limits (3 buttons, 10 list rows). */
(function (root, factory) {
	const g = factory();
	if (typeof module !== "undefined" && module.exports) module.exports = g;
	else root.WabaBotGraph = g;
})(typeof self !== "undefined" ? self : this, function () {
	const MAX_BUTTONS = 3;
	const MAX_ROWS = 10;
	const BUILTIN_VARS = ["customer_name", "customer_phone", "number_name"];
	const DOC_VARS = ["doc_name", "doc_status", "doc_date", "doc_total", "doc_outstanding", "doc_due_date"]; // offered once a Status lookup block exists
	const GATED = ["status_lookup", "send_file", "link_button"]; // preview blocks: the builder shows them only while Waba Settings allows
	const MAX_TIMEOUT = 720;
	const MAX_STARTS = 10;
	const START_LABELS = { new_conversation: "A new conversation", any_unassigned: "Any message while nobody has the chat", keyword: "A keyword" };
	const COL = 300; // distance between columns when tidying
	const ROW = 170;

	const DEFAULTS = {
		trigger: () => ({ mode: "new_conversation" }),
		message: () => ({ text: "Hello {{customer_name}}!" }),
		buttons: () => ({ text: "How can we help you?", buttons: [{ id: "b1", title: "Option 1" }, { id: "b2", title: "Option 2" }] }),
		list: () => ({ text: "Please choose one.", button_text: "Choose", rows: [{ id: "r1", title: "Option 1", description: "" }, { id: "r2", title: "Option 2", description: "" }] }),
		ask: () => ({ text: "Please tell us your city.", var: "", validate: "text", retry_text: "Sorry, that does not look right." }),
		condition: () => ({ kind: "working_hours" }),
		assign_team: () => ({ team: "", agent: "", text: "Connecting you with our team. Someone will reply shortly." }),
		handover: () => ({ text: "Connecting you with one of our team. Someone will reply shortly." }),
		note: () => ({ text: "" }),
		end: () => ({ text: "Thank you!" }),
		status_lookup: () => ({ doctype: "Sales Order", text: "Your order {{doc_name}} dated {{doc_date}} is {{doc_status}}. Total: {{doc_total}}." }),
		send_file: () => ({ source: "library", shared_file: "", doctype: "Quotation", caption: "" }),
		link_button: () => ({ text: "You can find more on our website.", button_text: "Open website", url: "https://" }),
	};
	const TYPES = Object.keys(DEFAULTS);
	const TERMINAL = ["assign_team", "handover", "end"];

	const clone = (graph) => JSON.parse(JSON.stringify(graph));

	function empty() {
		return { nodes: [], edges: [] };
	}

	function find(graph, id) {
		return (graph.nodes || []).find((n) => n.id === id) || null;
	}

	function newId(graph, prefix) {
		const used = new Set([...(graph.nodes || []).map((n) => n.id), ...(graph.edges || []).map((e) => e.id)]);
		let n = 1;
		while (used.has(`${prefix}_${n}`)) n++;
		return `${prefix}_${n}`;
	}

	/** The answer names already used by Question blocks, so a new one gets its own (answer1, answer2, ...). */
	function freeVarName(graph) {
		const used = new Set(variables(graph));
		let n = 1;
		while (used.has(`answer${n}`)) n++;
		return `answer${n}`;
	}

	function addNode(graph, type, position) {
		if (!DEFAULTS[type]) return null;
		if (type === "trigger" && graph.nodes.some((n) => n.type === "trigger")) return null; // one Trigger only
		const data = DEFAULTS[type]();
		if (type === "ask") data.var = freeVarName(graph);
		const node = { id: newId(graph, type), type, position: { x: Math.round(position?.x ?? 40), y: Math.round(position?.y ?? 40) }, data };
		graph.nodes.push(node);
		return node;
	}

	function removeNode(graph, id) {
		const node = find(graph, id);
		if (!node || node.type === "trigger") return false; // the Trigger is never deleted, only changed
		graph.nodes = graph.nodes.filter((n) => n.id !== id);
		graph.edges = graph.edges.filter((e) => e.source !== id && e.target !== id);
		return true;
	}

	/** The output points of a block, in the order they are drawn: [{id, label}]. */
	function timeoutOf(node) {
		const n = parseInt(node.data && node.data.timeout_minutes, 10);
		return ["buttons", "list", "ask"].includes(node.type) && n > 0 ? n : 0;
	}

	/** The ways a bot starts, [{id, label, mode, keywords, match}]. An older Trigger (one mode on the block itself) is one start with the point `out`. */
	function startsOf(node) {
		const d = (node && node.data) || {};
		if (Array.isArray(d.starts)) return d.starts;
		return [{ id: "out", label: "", mode: d.mode || "", keywords: d.keywords || "", match: d.match || "exact" }];
	}

	/** The words shown on a start's output point: its name, else its keywords, else its kind. */
	function startLabel(start) {
		if (start.label) return start.label;
		if (start.mode === "keyword" && (start.keywords || "").trim()) return start.keywords.trim().replace(/\s+/g, " ").slice(0, 28);
		return START_LABELS[start.mode] || "Choose a start";
	}

	/** Give an older Trigger the list form (one start, s1) and move its line to it. Returns whether anything changed. */
	function normalizeTrigger(graph) {
		const node = (graph.nodes || []).find((n) => n.type === "trigger");
		if (!node || Array.isArray(node.data && node.data.starts)) return false;
		const d = node.data || {};
		node.data = { starts: [{ id: "s1", label: "", mode: d.mode || "", keywords: d.keywords || "", match: d.match || "exact" }] };
		for (const e of graph.edges || []) if (e.source === node.id && (e.sourceHandle || "out") === "out") e.sourceHandle = "s1";
		return true;
	}

	function triggerNode(graph) {
		return (graph.nodes || []).find((n) => n.type === "trigger") || null;
	}

	/** Add a start to the Trigger (a keyword one, ready to fill in). Returns it, or null at the limit. */
	function addStart(graph) {
		const node = triggerNode(graph);
		if (!node) return null;
		normalizeTrigger(graph);
		const list = node.data.starts;
		if (list.length >= MAX_STARTS) return null;
		const used = new Set(list.map((x) => x.id));
		let n = list.length + 1;
		while (used.has(`s${n}`)) n++;
		const start = { id: `s${n}`, label: "", mode: "keyword", keywords: "", match: "exact" };
		list.push(start);
		return start;
	}

	/** Remove a start and the line that left from it. The last start stays. */
	function removeStart(graph, startId) {
		const node = triggerNode(graph);
		if (!node) return false;
		normalizeTrigger(graph);
		const list = node.data.starts;
		const i = list.findIndex((x) => x.id === startId);
		if (i < 0 || list.length <= 1) return false;
		list.splice(i, 1);
		graph.edges = graph.edges.filter((e) => !(e.source === node.id && (e.sourceHandle || "out") === startId));
		return true;
	}

	function setStart(graph, startId, key, value) {
		const node = triggerNode(graph);
		if (!node || !["label", "mode", "keywords", "match"].includes(key)) return false;
		normalizeTrigger(graph);
		const start = node.data.starts.find((x) => x.id === startId);
		if (!start) return false;
		start[key] = value;
		return true;
	}

	function handlesOf(node) {
		const d = node.data || {};
		if (node.type === "trigger") return startsOf(node).map((x) => ({ id: x.id, label: startsOf(node).length === 1 && x.id === "out" ? "" : startLabel(x) }));
		const noAnswer = timeoutOf(node) ? [{ id: "timeout", label: "No answer" }] : [];
		if (node.type === "buttons") return (d.buttons || []).map((b) => ({ id: String(b.id), label: b.title || "(no title)" })).concat(noAnswer);
		if (node.type === "list") return (d.rows || []).map((r) => ({ id: String(r.id), label: r.title || "(no title)" })).concat(noAnswer);
		if (node.type === "ask") return noAnswer.length ? [{ id: "out", label: "Answered" }].concat(noAnswer) : [{ id: "out", label: "" }];
		if (node.type === "condition") return [{ id: "yes", label: "Yes" }, { id: "no", label: "No" }];
		if (node.type === "status_lookup") return [{ id: "found", label: "Found" }, { id: "none", label: "Not found" }];
		if (node.type === "send_file") return [{ id: "out", label: "Sent" }, { id: "none", label: "Nothing to send" }];
		if (TERMINAL.includes(node.type)) return [];
		return [{ id: "out", label: "" }];
	}

	/** Choose a team for an Assign block. A person belongs to one team, so changing the team clears the agent. */
	function setTeam(graph, id, team) {
		const node = find(graph, id);
		if (!node || node.type !== "assign_team") return false;
		if ((node.data.team || "") !== (team || "")) node.data.agent = "";
		node.data.team = team || "";
		return true;
	}

	/** Set or clear a waiting block's 'no answer' time (minutes, 0 or empty = none). Clearing it drops the line that left from it. */
	function setTimeout_(graph, id, minutes) {
		const node = find(graph, id);
		if (!node || !["buttons", "list", "ask"].includes(node.type)) return false;
		const n = Math.min(MAX_TIMEOUT, Math.max(0, parseInt(minutes, 10) || 0));
		if (n > 0) node.data.timeout_minutes = n;
		else {
			delete node.data.timeout_minutes;
			graph.edges = graph.edges.filter((e) => !(e.source === id && e.sourceHandle === "timeout"));
		}
		return true;
	}

	/** Join an output point to a block. An output has one line only, so a new one replaces the old. Returns the line or null. */
	function connect(graph, source, handle, target) {
		const from = find(graph, source);
		const to = find(graph, target);
		if (!from || !to || source === target || to.type === "trigger") return null;
		if (!handlesOf(from).some((h) => h.id === handle)) return null;
		graph.edges = graph.edges.filter((e) => !(e.source === source && (e.sourceHandle || "out") === handle));
		const edge = { id: newId(graph, "line"), source, sourceHandle: handle, target };
		graph.edges.push(edge);
		return edge;
	}

	function disconnect(graph, edgeId) {
		const before = graph.edges.length;
		graph.edges = graph.edges.filter((e) => e.id !== edgeId);
		return graph.edges.length < before;
	}

	/** A copy of a block, offset a little, without its lines. The Trigger cannot be copied. */
	function duplicate(graph, id) {
		const node = find(graph, id);
		if (!node || node.type === "trigger") return null;
		const copy = { id: newId(graph, node.type), type: node.type, position: { x: node.position.x + 40, y: node.position.y + 40 }, data: clone(node.data) };
		graph.nodes.push(copy);
		return copy;
	}

	function optionList(node) {
		return node.type === "buttons" ? node.data.buttons : node.type === "list" ? node.data.rows : null;
	}

	/** A new button or list row with an id that stays the same when its title is edited. Returns it, or null at Meta's limit. */
	function addOption(graph, id) {
		const node = find(graph, id);
		const list = node && optionList(node);
		if (!list) return null;
		if (list.length >= (node.type === "buttons" ? MAX_BUTTONS : MAX_ROWS)) return null;
		const prefix = node.type === "buttons" ? "b" : "r";
		const used = new Set(list.map((o) => String(o.id)));
		let n = list.length + 1;
		while (used.has(prefix + n)) n++;
		const option = node.type === "buttons" ? { id: prefix + n, title: `Option ${list.length + 1}` } : { id: prefix + n, title: `Option ${list.length + 1}`, description: "" };
		list.push(option);
		return option;
	}

	/** Remove a button or list row and the line that left from it. Returns whether it was removed (a choice block keeps at least one). */
	function removeOption(graph, id, optionId) {
		const node = find(graph, id);
		const list = node && optionList(node);
		if (!list || list.length <= 1) return false;
		const index = list.findIndex((o) => String(o.id) === String(optionId));
		if (index < 0) return false;
		list.splice(index, 1);
		graph.edges = graph.edges.filter((e) => !(e.source === id && String(e.sourceHandle) === String(optionId)));
		return true;
	}

	/** The values a message may use: the three built in, plus the answers kept by Question blocks. */
	function variables(graph) {
		const names = [...BUILTIN_VARS];
		for (const n of graph.nodes || []) {
			const v = n.type === "ask" && n.data && n.data.var;
			if (v && !names.includes(v)) names.push(v);
		}
		if ((graph.nodes || []).some((n) => n.type === "status_lookup")) names.push(...DOC_VARS);
		return names;
	}

	/** Arrange the blocks in columns by how far they are from the Trigger, so a tangled bot reads left to right again. */
	function tidy(graph) {
		const depth = {};
		const trigger = graph.nodes.find((n) => n.type === "trigger");
		if (trigger) {
			depth[trigger.id] = 0;
			const queue = [trigger.id];
			while (queue.length) {
				const cur = queue.shift();
				for (const e of graph.edges) {
					if (e.source === cur && depth[e.target] === undefined) {
						depth[e.target] = depth[cur] + 1;
						queue.push(e.target);
					}
				}
			}
		}
		const columns = {};
		const lost = Math.max(0, ...Object.values(depth)) + 1; // blocks nothing leads to wait in a last column
		for (const n of graph.nodes) {
			const d = depth[n.id] === undefined ? lost : depth[n.id];
			(columns[d] = columns[d] || []).push(n);
		}
		for (const [d, nodes] of Object.entries(columns)) {
			nodes.forEach((n, i) => {
				n.position = { x: 40 + Number(d) * COL, y: 40 + i * ROW };
			});
		}
		return graph;
	}

	/** Undo: a stack of earlier snapshots (as text, so later edits cannot reach into them). */
	class History {
		constructor(limit = 30) {
			this.limit = limit;
			this.stack = [];
		}
		push(graph) {
			const text = JSON.stringify(graph);
			if (this.stack[this.stack.length - 1] === text) return;
			this.stack.push(text);
			if (this.stack.length > this.limit) this.stack.shift();
		}
		get canUndo() {
			return this.stack.length > 0;
		}
		undo() {
			const text = this.stack.pop();
			return text ? JSON.parse(text) : null;
		}
		clear() {
			this.stack = [];
		}
	}

	function parse(text) {
		try {
			const value = JSON.parse(text || "null");
			if (value && Array.isArray(value.nodes)) return { nodes: value.nodes, edges: Array.isArray(value.edges) ? value.edges : [] };
		} catch (e) {
			/* not valid: start again */
		}
		return null;
	}

	/** A first graph for an empty bot: just the Trigger, in the middle of the left. */
	function start() {
		const graph = empty();
		addNode(graph, "trigger", { x: 40, y: 160 });
		return graph;
	}

	return { MAX_BUTTONS, MAX_ROWS, MAX_TIMEOUT, BUILTIN_VARS, DOC_VARS, GATED, TYPES, TERMINAL, timeoutOf, setTimeout: setTimeout_, setTeam, MAX_STARTS, startsOf, startLabel, normalizeTrigger, addStart, removeStart, setStart, clone, empty, start, find, newId, addNode, removeNode, handlesOf, connect, disconnect, duplicate, addOption, removeOption, variables, tidy, History, parse };
});
