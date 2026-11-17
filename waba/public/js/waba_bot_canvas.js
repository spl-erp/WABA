/* The bot builder: draw a bot as blocks joined by lines, try it in a small chat, and publish it.
 *
 * Opened from the Waba Bot form (waba_bot.js). A full-screen layer over the Desk: a palette of blocks on the left, the board in
 * the middle (drag blocks, join an output dot to a block, pan and zoom), the selected block's settings on the right, and two more
 * tabs there: Problems (what stops Publish) and Try it (the Simulator, which sends nothing).
 *
 * The graph is the one waba/rules/bot.py runs; the SERVER is the only judge of whether it is valid (this file only keeps it
 * tidy and inside Meta's limits). Work is saved as a DRAFT about a second after every change (waba.api.bots.save_draft);
 * customers get the published version only, so nothing here changes a live bot until Publish.
 * Everything a person typed is escaped before it is drawn. */
(function () {
	const G = window.WabaBotGraph;
	const esc = (v) => frappe.utils.escape_html(v == null ? "" : String(v));

	const KINDS = {
		trigger: { label: __("Trigger"), group: "start", icon: "M13 2L4 14h6l-1 8 9-12h-6z" },
		message: { label: __("Message"), group: "msg", icon: "M4 5h16v11H9l-5 4z" },
		buttons: { label: __("Buttons"), group: "msg", icon: "M3 6h18v5H3zM3 14h18v5H3z" },
		list: { label: __("List"), group: "msg", icon: "M4 6h16M4 12h16M4 18h16" },
		ask: { label: __("Question"), group: "msg", icon: "M9 9a3 3 0 1 1 4 3c-1 .6-1 1-1 2M12 18v.5" },
		condition: { label: __("Condition"), group: "logic", icon: "M6 3v6a4 4 0 0 0 4 4h4a4 4 0 0 1 4 4v4M6 3v18" },
		assign_team: { label: __("Assign to team"), group: "hand", icon: "M8 11a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM2 20c0-3 3-5 6-5s6 2 6 5M17 10a2.5 2.5 0 1 0 0-5M16 15c3 0 6 1.6 6 5" },
		handover: { label: __("Hand over"), group: "hand", icon: "M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM4 21c0-4 4-6 8-6s8 2 8 6" },
		note: { label: __("Note"), group: "hand", icon: "M4 20l4-1 11-11-3-3L5 16zM14 6l3 3" },
		end: { label: __("End"), group: "hand", icon: "M6 6h12v12H6z" },
		status_lookup: { label: __("Status lookup"), group: "more", icon: "M3 3v18h18M7 14l4-4 3 3 5-6" },
		send_file: { label: __("Send document"), group: "more", icon: "M14 3H6v18h12V7zM14 3v4h4M9 13h6M9 17h6" },
		link_button: { label: __("Link button"), group: "more", icon: "M10 14a5 5 0 0 0 7 0l3-3a5 5 0 0 0-7-7l-1 1M14 10a5 5 0 0 0-7 0l-3 3a5 5 0 0 0 7 7l1-1" },
	};
	const GROUPS = [
		["msg", __("Messaging"), ["message", "buttons", "list", "ask"]],
		["logic", __("Logic"), ["condition"]],
		["hand", __("Hand over and finish"), ["assign_team", "handover", "note", "end"]],
		["more", __("More blocks (preview)"), ["link_button", "send_file", "status_lookup"]],
	];
	const HINTS = {
		trigger: __("What starts the bot."),
		message: __("Sends a message and goes on."),
		buttons: __("Up to 3 quick-reply buttons. Waits for a tap."),
		list: __("Up to 10 choices behind one button. Waits for a pick."),
		ask: __("Asks a question, keeps the answer, goes on."),
		condition: __("Two ways on: yes or no."),
		assign_team: __("Gives the chat to a person of a team: the one you pick, or the least busy available agent."),
		handover: __("The bot stops; normal routing takes the chat."),
		note: __("An internal note. The customer never sees it."),
		end: __("The bot stops."),
		status_lookup: __("Tells the customer the status of their own latest quotation, order or invoice."),
		send_file: __("Sends a library file, or the PDF of the customer's own latest document."),
		link_button: __("A message with one button that opens a web link."),
	};
	const TRIGGERS = [
		["new_conversation", __("A new conversation")],
		["any_unassigned", __("Any message while nobody has the chat")],
		["keyword", __("A keyword")],
	];
	const CONDITIONS = [
		["working_hours", __("It is within the number's business hours")],
		["matched", __("The customer is a known Lead, Contact or Customer")],
		["var_equals", __("An answer equals ...")],
		["var_contains", __("An answer contains ...")],
	];
	const VARIABLE_HELP = {
		customer_name: __("the customer's name"),
		customer_phone: __("their phone number"),
		number_name: __("your business number's name"),
		doc_name: __("the document number"),
		doc_status: __("the document's status"),
		doc_date: __("the document's date"),
		doc_total: __("the document's total"),
		doc_outstanding: __("the amount still to pay (invoices)"),
		doc_due_date: __("the payment due date (invoices)"),
	};
	const NODE_W = 244;
	const SAVE_DELAY = 1200;

	const STYLE = `
.wbb { position: fixed; inset: 0; z-index: 1045; display: flex; flex-direction: column; background: var(--bg-color, #f4f5f6); color: var(--text-color, #1f272e); font-size: 13px }
.wbb * { box-sizing: border-box }
.wbb-top { display: flex; align-items: center; gap: 8px; padding: 8px 14px; background: var(--card-bg, #fff); border-bottom: 1px solid var(--border-color, #d9dee3); flex-wrap: wrap }
.wbb-top .wbb-title { font-size: 15px; font-weight: 600; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap }
.wbb-grow { flex: 1 1 auto; min-width: 8px }
.wbb-pill { display: inline-flex; align-items: center; gap: 5px; border-radius: 10px; padding: 1px 9px; font-size: 11.5px; font-weight: 600; background: var(--control-bg, #eef0f2); color: var(--text-muted, #6b7782); white-space: nowrap }
.wbb-pill.ok { background: #e1f4ea; color: #1b7a4b } .wbb-pill.warn { background: #fff1e0; color: #a4590a } .wbb-pill.bad { background: #fde8e8; color: #b42318 }
:root[data-theme="dark"] .wbb-pill.ok { background: #16372a; color: #6fd3a0 } :root[data-theme="dark"] .wbb-pill.warn { background: #3d2c14; color: #f5b04a } :root[data-theme="dark"] .wbb-pill.bad { background: #3f1d1d; color: #f19a9a }
.wbb-saved { color: var(--text-muted, #6b7782); font-size: 12px; white-space: nowrap }
.wbb-main { position: relative; flex: 1 1 auto; display: flex; min-height: 0 }
.wbb-palette { width: 208px; flex: 0 0 208px; background: var(--card-bg, #fff); border-right: 1px solid var(--border-color, #d9dee3); overflow-y: auto; padding: 10px }
.wbb-palette input { width: 100%; margin-bottom: 8px }
.wbb-group { margin: 12px 0 5px; font-size: 11px; letter-spacing: .06em; text-transform: uppercase; color: var(--text-muted, #6b7782); font-weight: 600 }
.wbb-pitem { display: flex; align-items: center; gap: 8px; width: 100%; padding: 7px 9px; margin-bottom: 5px; border: 1px solid var(--border-color, #d9dee3); border-radius: 8px; background: var(--control-bg, #f6f7f8); color: inherit; cursor: grab; text-align: left }
.wbb-pitem:hover { border-color: var(--primary, #008069); background: var(--card-bg, #fff) }
.wbb-pitem[hidden] { display: none }
.wbb-ic { width: 26px; height: 26px; flex: 0 0 26px; border-radius: 7px; display: inline-flex; align-items: center; justify-content: center }
.wbb-ic svg { width: 15px; height: 15px; fill: none; stroke: currentColor; stroke-width: 2; stroke-linecap: round; stroke-linejoin: round }
.wbb-ic.more { background: rgba(0,151,167,.14); color: #00838f }
.wbb-count { margin-left: 6px; min-width: 22px; padding: 0 7px; border-radius: 10px; background: var(--primary, #008069); color: #fff; font-size: 11px; font-weight: 600; line-height: 18px; text-align: center }
.wbb-totals { color: var(--text-muted, #6b7782); font-size: 12px; white-space: nowrap }
.wbb-extras { display: inline-flex; align-items: center; gap: 6px }
.wbb-extras select { width: auto; padding: 2px 6px }
.wbb-ic.start { background: rgba(0,128,105,.14); color: #00806a } .wbb-ic.msg { background: rgba(33,150,243,.14); color: #1a73c4 } .wbb-ic.logic { background: rgba(214,138,10,.16); color: #b46a05 } .wbb-ic.hand { background: rgba(142,84,214,.15); color: #7a46c4 }
.wbb-board { position: relative; flex: 1 1 auto; min-width: 0; overflow: hidden; cursor: grab; background-color: var(--bg-color, #f4f5f6); background-image: radial-gradient(var(--border-color, #cfd5db) 1px, transparent 1px); background-size: 22px 22px; touch-action: none }
.wbb-board.panning { cursor: grabbing }
.wbb-world { position: absolute; left: 0; top: 0; transform-origin: 0 0 }
.wbb-edges { position: absolute; left: 0; top: 0; width: 1px; height: 1px; overflow: visible; pointer-events: none }
.wbb-edges path { fill: none; stroke: var(--text-muted, #7b8791); stroke-width: 2; pointer-events: none }
.wbb-edges path.hit { stroke: transparent; stroke-width: 16; pointer-events: stroke; cursor: pointer }
.wbb-edges path.sel { stroke: var(--primary, #008069); stroke-width: 3 }
.wbb-edges path.tmp { stroke: var(--primary, #008069); stroke-dasharray: 5 4 }
.wbb-edges polygon { fill: var(--text-muted, #7b8791); stroke: none; pointer-events: none }
.wbb-edges polygon.sel { fill: var(--primary, #008069) }
.wbb-edges .cut { pointer-events: all; cursor: pointer; fill: var(--card-bg, #fff); stroke: #b42318; stroke-width: 2 }
.wbb-edges .cutx { fill: none; stroke: #b42318; stroke-width: 2; pointer-events: none }
.wbb-node { position: absolute; width: ${NODE_W}px; background: var(--card-bg, #fff); border: 1px solid var(--border-color, #d9dee3); border-radius: 10px; box-shadow: 0 1px 3px rgba(0,0,0,.08); cursor: default; user-select: none }
.wbb-node.sel { border-color: var(--primary, #008069); box-shadow: 0 0 0 2px rgba(0,128,105,.3), 0 4px 12px rgba(0,0,0,.12) }
.wbb-node.active { box-shadow: 0 0 0 3px #f5b04a, 0 4px 12px rgba(0,0,0,.14) }
.wbb-node.target { box-shadow: 0 0 0 3px rgba(26,115,196,.45) }
.wbb-nh { display: flex; align-items: center; gap: 8px; padding: 8px 8px 8px 10px; cursor: move; border-radius: 10px 10px 0 0 }
.wbb-nh b { flex: 1 1 auto; font-size: 13px; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap }
.wbb-kebab { border: 0; background: transparent; color: var(--text-muted, #6b7782); width: 24px; height: 24px; border-radius: 6px; cursor: pointer; font-size: 16px; line-height: 1 }
.wbb-kebab:hover { background: var(--control-bg, #eef0f2) }
.wbb-np { padding: 0 12px 10px; color: var(--text-muted, #5f6b76); font-size: 12px; line-height: 1.4; word-break: break-word; white-space: pre-wrap; max-height: 74px; overflow: hidden }
.wbb-in { position: absolute; left: -7px; top: 19px; width: 13px; height: 13px; border-radius: 50%; background: var(--card-bg, #fff); border: 2px solid var(--text-muted, #7b8791) }
.wbb-node.target .wbb-in { border-color: #1a73c4; background: #1a73c4 }
.wbb-outs { border-top: 1px solid var(--border-color, #e3e7ea) }
.wbb-out { position: relative; padding: 5px 22px 5px 12px; font-size: 12px; text-align: right; color: var(--text-color, #1f272e); min-height: 26px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap }
.wbb-out + .wbb-out { border-top: 1px dashed var(--border-color, #e3e7ea) }
.wbb-dot { position: absolute; right: -7px; top: 50%; margin-top: -7px; width: 14px; height: 14px; border-radius: 50%; background: var(--primary, #008069); border: 2px solid var(--card-bg, #fff); cursor: crosshair; box-shadow: 0 0 0 1px var(--primary, #008069) }
.wbb-dot:hover { transform: scale(1.25) }
.wbb-dot.joined { background: var(--primary, #008069) } .wbb-dot:not(.joined) { background: var(--card-bg, #fff); border-color: var(--primary, #008069) }
.wbb-flag { position: absolute; right: -6px; top: -6px; width: 14px; height: 14px; border-radius: 50%; background: #d92d20; border: 2px solid var(--card-bg, #fff) }
.wbb-zoom { position: absolute; left: 12px; bottom: 12px; display: flex; gap: 4px; background: var(--card-bg, #fff); border: 1px solid var(--border-color, #d9dee3); border-radius: 8px; padding: 3px }
.wbb-zoom button { min-width: 30px }
.wbb-hint { position: absolute; left: 50%; top: 14px; transform: translateX(-50%); background: var(--card-bg, #fff); border: 1px solid var(--border-color, #d9dee3); border-radius: 18px; padding: 4px 14px; color: var(--text-muted, #6b7782); font-size: 12px; pointer-events: none }
.wbb-side { width: 352px; flex: 0 0 352px; background: var(--card-bg, #fff); border-left: 1px solid var(--border-color, #d9dee3); display: flex; flex-direction: column; min-height: 0 }
.wbb-tabs { display: flex; border-bottom: 1px solid var(--border-color, #d9dee3) }
.wbb-tab { flex: 1; padding: 9px 4px; border: 0; background: transparent; color: var(--text-muted, #6b7782); font-weight: 600; border-bottom: 2px solid transparent; cursor: pointer }
.wbb-tab.on { color: var(--text-color, #1f272e); border-bottom-color: var(--text-color, #1f272e) }
.wbb-pane { flex: 1 1 auto; overflow-y: auto; padding: 12px 14px 20px; min-height: 0 }
.wbb-pane h4 { margin: 0 0 4px; font-size: 14px }
.wbb-pane .sub { color: var(--text-muted, #6b7782); font-size: 12px; margin-bottom: 12px }
.wbb-f { margin-bottom: 12px }
.wbb-f > label { display: block; font-weight: 600; font-size: 12px; margin-bottom: 4px }
.wbb-f .count { float: right; font-weight: 400; color: var(--text-muted, #6b7782) } .wbb-f .count.over { color: #b42318; font-weight: 600 }
.wbb-f textarea, .wbb-f input, .wbb-f select { width: 100%; padding: 6px 9px; border: 1px solid var(--border-color, #d9dee3); border-radius: 8px; background: var(--control-bg, #f6f7f8); color: inherit; font: inherit }
.wbb-f textarea { min-height: 84px; resize: vertical }
.wbb-chips { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 5px }
.wbb-chipv { border: 1px dashed var(--border-color, #c3cad1); background: transparent; border-radius: 12px; padding: 1px 9px; font-size: 11.5px; color: var(--text-muted, #5f6b76); cursor: pointer }
.wbb-chipv:hover { border-color: var(--primary, #008069); color: var(--primary, #008069) }
.wbb-opt { display: flex; gap: 6px; align-items: flex-start; margin-bottom: 7px }
.wbb-opt .col { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 4px }
.wbb-opt .x { border: 0; background: transparent; color: #b42318; font-size: 18px; cursor: pointer; padding: 3px 6px }
.wbb-prob { display: block; width: 100%; text-align: left; margin-bottom: 6px; padding: 8px 10px; border: 1px solid var(--border-color, #d9dee3); border-left: 3px solid #d92d20; border-radius: 8px; background: var(--control-bg, #f6f7f8); color: inherit; cursor: pointer }
.wbb-good { color: #1b7a4b; font-weight: 600 }
.wbb-chat { display: flex; flex-direction: column; gap: 7px; padding: 10px; border-radius: 10px; background: var(--control-bg, #efeae2); min-height: 220px; max-height: 46vh; overflow-y: auto; margin-bottom: 8px }
.wbb-bub { max-width: 88%; padding: 6px 10px; border-radius: 8px; background: var(--card-bg, #fff); box-shadow: 0 1px 1px rgba(0,0,0,.1); white-space: pre-wrap; word-break: break-word }
.wbb-bub.me { align-self: flex-end; background: #d9fdd3; color: #111b21 }
:root[data-theme="dark"] .wbb-bub.me { background: #005c4b; color: #e9edef }
.wbb-sys { align-self: center; text-align: center; font-size: 11.5px; color: var(--text-muted, #6b7782); background: rgba(127,127,127,.12); border-radius: 10px; padding: 2px 10px }
.wbb-sim-btns { display: flex; flex-direction: column; gap: 5px; margin-top: 6px }
.wbb-sim-btns button { border: 1px solid var(--border-color, #cfd5db); background: var(--card-bg, #fff); color: var(--primary, #008069); border-radius: 8px; padding: 6px; font-weight: 600; cursor: pointer }
.wbb-sim-btns button:hover { background: var(--control-bg, #f0f2f4) }
.wbb-send { display: flex; gap: 6px } .wbb-send input { flex: 1; min-width: 0 }
.wbb-toggles { display: flex; flex-direction: column; gap: 4px; margin: 0 0 10px; font-size: 12px }
.wbb-toggles label { display: flex; align-items: center; gap: 6px; font-weight: 400 }
.wbb-note { margin: 8px 14px; padding: 8px 12px; border-radius: 8px; background: #fff1e0; color: #8a4b08; font-size: 12.5px }
.wbb-compact .wbb-palette, .wbb-compact .wbb-edit-only { display: none }
.wbb-compact .wbb-main { flex-direction: column }
.wbb-compact .wbb-board { flex: 0 0 38% }
.wbb-compact .wbb-side { flex: 1 1 auto; width: auto; border-left: 0; border-top: 1px solid var(--border-color, #d9dee3) }
.wbb-compact .wbb-node .wbb-kebab, .wbb-compact .wbb-dot { display: none }
.wbb-menu { position: fixed; z-index: 1060; background: var(--card-bg, #fff); border: 1px solid var(--border-color, #d9dee3); border-radius: 8px; box-shadow: 0 6px 20px rgba(0,0,0,.18); padding: 4px; min-width: 140px }
.wbb-menu button { display: block; width: 100%; text-align: left; border: 0; background: transparent; padding: 7px 10px; border-radius: 6px; color: inherit; cursor: pointer }
.wbb-menu button:hover { background: var(--control-bg, #eef0f2) }
.wbb-menu button.danger { color: #b42318 }
@media (max-width: 900px) { .wbb-palette { width: 160px; flex-basis: 160px } .wbb-side { width: 300px; flex-basis: 300px } }
@media (prefers-reduced-motion: no-preference) { .wbb-node, .wbb-dot { transition: box-shadow .12s, transform .12s } }
`;

	function style() {
		if (document.getElementById("waba-bot-style")) return;
		const el = document.createElement("style");
		el.id = "waba-bot-style";
		el.textContent = STYLE;
		document.head.appendChild(el);
	}

	const icon = (kind) => `<span class="wbb-ic ${KINDS[kind].group}"><svg viewBox="0 0 24 24"><path d="${KINDS[kind].icon}"/></svg></span>`;
	const canon = (v) => JSON.stringify(v, (k, x) => (x && typeof x === "object" && !Array.isArray(x) ? Object.keys(x).sort().reduce((o, key) => ((o[key] = x[key]), o), {}) : x));

	class Builder {
		constructor(name, opts) {
			this.name = name;
			this.opts = opts || {};
			this.graph = G.start();
			this.history = new G.History();
			this.selected = null;
			this.selectedEdge = null;
			this.view = { x: 60, y: 40, k: 1 };
			this.problems = [];
			this.teams = [];
			this.agents = {}; // team -> people an Assign block may name (loaded when a team is chosen)
			this.published = null;
			this.version = 0;
			this.enabled = 0;
			this.tab = "block";
			this.dirty = false;
			this.saving = false;
			this.savedAt = null;
			this.sim = { state: {}, chat: [], open_now: 1, matched: 1, published: 0, problems: null, has_docs: 1, timeout_minutes: 0 };
			this.compact = window.innerWidth < 700;
			this.extras = !!(frappe.boot && frappe.boot.waba_extra_blocks); // the preview features: hidden until released in Waba Settings
			this.library = [];
			this.counts = null;
			this.countDays = 30;
		}

		// ------------------------------------------------------------------------------------------ opening
		start() {
			style();
			frappe.call({ method: "frappe.client.get", args: { doctype: "Waba Bot", name: this.name }, freeze: true }).then((r) => {
				const doc = r.message;
				this.bot_name = doc.bot_name;
				this.version = doc.version || 0;
				this.enabled = doc.enabled;
				this.published = doc.published_json ? G.parse(doc.published_json) : null;
				this.graph = G.parse(doc.graph_json) || (this.published ? G.clone(this.published) : G.start());
				if (!this.graph.nodes.some((n) => n.type === "trigger")) G.addNode(this.graph, "trigger", { x: 40, y: 160 });
				G.normalizeTrigger(this.graph); // an older bot (one start on the Trigger itself) opens in the list form
				if (this.extras) {
					frappe.db.get_list("Waba Shared File", { fields: ["name", "title", "enabled"], limit: 200, order_by: "title asc" }).then((rows) => {
						this.library = rows || [];
						if (this.tab === "block") this.render_panel();
					});
				}
				frappe.db.get_list("Waba Team", { fields: ["name"], limit: 200, order_by: "name asc" }).then((rows) => {
					this.teams = (rows || []).map((t) => t.name);
					if (this.tab === "block") this.render_panel();
				});
				this.build();
				this.fit();
				this.check();
			});
		}

		build() {
			const top = `
				<div class="wbb-top">
					<button class="btn btn-default btn-sm wbb-close">${__("Close")}</button>
					<span class="wbb-title">${esc(this.bot_name)}</span>
					<span class="wbb-pill wbb-status"></span>
					<span class="wbb-saved"></span>
					<span class="wbb-grow"></span>
					${this.extras && !this.compact ? `<span class="wbb-totals"></span><span class="wbb-extras"><button class="btn btn-default btn-sm wbb-nums">${__("Show numbers")}</button><select class="form-control input-sm wbb-days"><option value="7">${__("7 days")}</option><option value="30" selected>${__("30 days")}</option><option value="90">${__("90 days")}</option></select></span>` : ""}
					<button class="btn btn-default btn-sm wbb-undo" title="Ctrl+Z">${__("Undo")}</button>
					<button class="btn btn-default btn-sm wbb-tidy wbb-edit-only">${__("Tidy up")}</button>
					<button class="btn btn-default btn-sm wbb-save wbb-edit-only" title="Ctrl+S">${__("Save")}</button>
					<button class="btn btn-primary btn-sm wbb-publish wbb-edit-only">${__("Publish")}</button>
				</div>`;
			const palette = `
				<div class="wbb-palette">
					<input type="search" class="form-control input-sm wbb-search" placeholder="${esc(__("Search for blocks"))}">
					${GROUPS.filter(([key]) => key !== "more" || this.extras).map(([key, title, kinds]) => `<div class="wbb-group" data-g="${key}">${esc(title)}</div>${kinds.map((k) => `<button class="wbb-pitem" draggable="true" data-kind="${k}" title="${esc(HINTS[k])}">${icon(k)}<span>${esc(KINDS[k].label)}</span></button>`).join("")}`).join("")}
					<div class="text-muted" style="margin-top:14px;font-size:12px">${__("Click a block to add it, or drag it onto the board. Drag from a round dot to a block to join them.")}</div>
				</div>`;
			const board = `
				<div class="wbb-board" tabindex="0">
					<div class="wbb-world"><svg class="wbb-edges"><g class="wbb-edge-layer"></g></svg><div class="wbb-nodes"></div></div>
					<div class="wbb-zoom"><button class="btn btn-default btn-xs wbb-zo">&minus;</button><button class="btn btn-default btn-xs wbb-fit">${__("Fit")}</button><button class="btn btn-default btn-xs wbb-zi">+</button></div>
					<div class="wbb-hint wbb-edit-only">${__("Scroll to zoom, drag the board to move around")}</div>
				</div>`;
			const side = `
				<div class="wbb-side">
					<div class="wbb-tabs"><button class="wbb-tab on wbb-edit-only" data-t="block">${__("Block")}</button><button class="wbb-tab" data-t="problems">${__("Problems")}</button><button class="wbb-tab" data-t="try">${__("Try it")}</button></div>
					<div class="wbb-pane"></div>
				</div>`;
			this.$ = $(`<div class="wbb ${this.compact ? "wbb-compact" : ""}" tabindex="-1" role="dialog" aria-label="${esc(__("Bot builder"))}">${top}${this.compact ? `<div class="wbb-note">${esc(__("Editing needs a larger screen. You can still try the bot here."))}</div>` : ""}<div class="wbb-main">${palette}${board}${side}</div></div>`).appendTo(document.body);
			this.$board = this.$.find(".wbb-board");
			this.$world = this.$.find(".wbb-world");
			this.$nodes = this.$.find(".wbb-nodes");
			this.$layer = this.$.find(".wbb-edge-layer");
			this.$pane = this.$.find(".wbb-pane");
			if (this.compact) this.tab = "try";
			this.wire();
			this.render();
			this.$.trigger("focus");
		}

		// ------------------------------------------------------------------------------------------ wiring
		wire() {
			const root = this.$;
			root.find(".wbb-close").on("click", () => this.close());
			root.find(".wbb-save").on("click", () => this.save(true));
			root.find(".wbb-publish").on("click", () => this.publish());
			root.find(".wbb-undo").on("click", () => this.undo());
			root.find(".wbb-nums").on("click", () => this.toggle_counts());
			root.find(".wbb-days").on("change", (ev) => {
				this.countDays = parseInt(ev.target.value, 10) || 30;
				if (this.counts) this.load_counts();
			});
			root.find(".wbb-tidy").on("click", () => {
				this.snapshot();
				G.tidy(this.graph);
				this.changed();
				this.render();
				this.fit();
			});
			root.find(".wbb-zi").on("click", () => this.zoom(1.2));
			root.find(".wbb-zo").on("click", () => this.zoom(1 / 1.2));
			root.find(".wbb-fit").on("click", () => this.fit());
			root.find(".wbb-tab").on("click", (ev) => this.show_tab($(ev.currentTarget).data("t")));
			root.find(".wbb-search").on("input", (ev) => {
				const q = String(ev.target.value || "").trim().toLowerCase();
				root.find(".wbb-pitem").each(function () {
					$(this).prop("hidden", !!q && !$(this).text().toLowerCase().includes(q));
				});
			});
			root.find(".wbb-pitem").on("click", (ev) => this.add_at_center($(ev.currentTarget).data("kind")));
			root.find(".wbb-pitem").on("dragstart", (ev) => {
				ev.originalEvent.dataTransfer.setData("text/plain", `waba-bot:${$(ev.currentTarget).data("kind")}`);
				ev.originalEvent.dataTransfer.effectAllowed = "copy";
			});
			this.$board.on("dragover", (ev) => ev.preventDefault());
			this.$board.on("drop", (ev) => {
				ev.preventDefault();
				const text = ev.originalEvent.dataTransfer.getData("text/plain") || "";
				if (text.startsWith("waba-bot:")) this.add_node(text.slice(9), this.to_world(ev.originalEvent.clientX, ev.originalEvent.clientY));
			});
			this.$board.on("wheel", (ev) => {
				ev.preventDefault();
				this.zoom(ev.originalEvent.deltaY < 0 ? 1.1 : 1 / 1.1, ev.originalEvent.clientX, ev.originalEvent.clientY);
			});
			this.$board.on("pointerdown", (ev) => this.board_down(ev));
			this.$board.on("scroll", () => {
				this.$board[0].scrollLeft = 0; // the board is moved by its own pan, never scrolled (focus or text selection must not shift it)
				this.$board[0].scrollTop = 0;
			});
			root.on("keydown", (ev) => this.keys(ev));
			this.on_resize = () => this.draw_edges();
			window.addEventListener("resize", this.on_resize);
		}

		keys(ev) {
			const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(ev.target.tagName);
			if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === "s") {
				ev.preventDefault();
				this.save(true);
			} else if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === "z" && !typing) {
				ev.preventDefault();
				this.undo();
			} else if ((ev.key === "Delete" || ev.key === "Backspace") && !typing && !this.compact) {
				if (this.selectedEdge) this.remove_edge(this.selectedEdge);
				else if (this.selected) this.remove_node(this.selected);
			} else if (ev.key === "Escape") {
				if (this.menu) this.close_menu();
				else if (this.selected || this.selectedEdge) this.select(null);
			}
		}

		// ------------------------------------------------------------------------------------------ view
		to_world(clientX, clientY) {
			const r = this.$board[0].getBoundingClientRect();
			return { x: (clientX - r.left - this.view.x) / this.view.k, y: (clientY - r.top - this.view.y) / this.view.k };
		}

		apply_view() {
			this.$world.css("transform", `translate(${this.view.x}px, ${this.view.y}px) scale(${this.view.k})`);
		}

		zoom(factor, cx, cy) {
			const r = this.$board[0].getBoundingClientRect();
			const px = (cx == null ? r.left + r.width / 2 : cx) - r.left;
			const py = (cy == null ? r.top + r.height / 2 : cy) - r.top;
			const k = Math.min(1.6, Math.max(0.2, this.view.k * factor));
			this.view.x = px - ((px - this.view.x) / this.view.k) * k;
			this.view.y = py - ((py - this.view.y) / this.view.k) * k;
			this.view.k = k;
			this.apply_view();
		}

		fit() {
			const nodes = this.graph.nodes;
			if (!nodes.length || !this.$board) return;
			const r = this.$board[0].getBoundingClientRect();
			let x1 = Infinity, y1 = Infinity, x2 = -Infinity, y2 = -Infinity;
			for (const n of nodes) {
				const el = this.node_el(n.id);
				const h = el.length ? el.outerHeight() : 120;
				x1 = Math.min(x1, n.position.x);
				y1 = Math.min(y1, n.position.y);
				x2 = Math.max(x2, n.position.x + NODE_W);
				y2 = Math.max(y2, n.position.y + h);
			}
			const pad = 50;
			const k = Math.min(1, (r.width - pad * 2) / Math.max(1, x2 - x1), (r.height - pad * 2) / Math.max(1, y2 - y1));
			this.view.k = Math.max(0.2, k);
			this.view.x = pad - x1 * this.view.k + Math.max(0, (r.width - pad * 2 - (x2 - x1) * this.view.k) / 2);
			this.view.y = pad - y1 * this.view.k;
			this.apply_view();
		}

		board_down(ev) {
			if (ev.target !== this.$board[0] && ev.target !== this.$world[0] && !$(ev.target).is(".wbb-nodes, svg.wbb-edges")) return;
			this.select(null);
			const start = { x: ev.clientX, y: ev.clientY, vx: this.view.x, vy: this.view.y };
			this.$board.addClass("panning");
			const move = (e) => {
				this.view.x = start.vx + e.clientX - start.x;
				this.view.y = start.vy + e.clientY - start.y;
				this.apply_view();
			};
			const up = () => {
				this.$board.removeClass("panning");
				document.removeEventListener("pointermove", move);
				document.removeEventListener("pointerup", up);
			};
			document.addEventListener("pointermove", move);
			document.addEventListener("pointerup", up);
		}

		// ------------------------------------------------------------------------------------------ graph changes
		snapshot() {
			this.history.push(this.graph);
		}

		undo() {
			const previous = this.history.undo();
			if (!previous) return frappe.show_alert({ message: __("Nothing to undo."), indicator: "orange" }, 2);
			this.graph = previous;
			if (this.selected && !G.find(this.graph, this.selected)) this.selected = null;
			this.changed();
			this.render();
		}

		add_node(kind, position) {
			if (this.compact) return;
			this.snapshot();
			const node = G.addNode(this.graph, kind, position);
			if (!node) {
				this.history.undo();
				return frappe.show_alert({ message: __("A bot has only one Trigger."), indicator: "orange" }, 3);
			}
			this.changed();
			this.render();
			this.select(node.id);
		}

		add_at_center(kind) {
			const r = this.$board[0].getBoundingClientRect();
			const jitter = (this.graph.nodes.length % 5) * 26;
			const p = this.to_world(r.left + r.width / 2, r.top + r.height / 2);
			this.add_node(kind, { x: p.x - NODE_W / 2 + jitter, y: p.y - 40 + jitter });
		}

		remove_node(id) {
			const node = G.find(this.graph, id);
			if (!node) return;
			if (node.type === "trigger") return frappe.show_alert({ message: __("The Trigger cannot be deleted. Change what starts the bot instead."), indicator: "orange" }, 4);
			this.snapshot();
			G.removeNode(this.graph, id);
			this.selected = null;
			this.changed();
			this.render();
		}

		remove_edge(id) {
			this.snapshot();
			G.disconnect(this.graph, id);
			this.selectedEdge = null;
			this.changed();
			this.render();
		}

		changed() {
			this.dirty = true;
			this.refresh_status();
			clearTimeout(this.timer);
			this.timer = setTimeout(() => this.save(false), SAVE_DELAY);
		}

		// ------------------------------------------------------------------------------------------ saving and publishing
		save(show) {
			clearTimeout(this.timer);
			if (this.saving) {
				this.again = true;
				return this.saving;
			}
			this.saving = frappe
				.call({ method: "waba.api.bots.save_draft", args: { bot: this.name, graph: JSON.stringify(this.graph) }, type: "POST" })
				.then((r) => {
					this.dirty = false;
					this.savedAt = new Date();
					this.set_problems((r.message || {}).detail || []);
					if (show) frappe.show_alert({ message: __("Draft saved."), indicator: "green" }, 2);
				})
				.catch(() => {
					this.dirty = true;
				})
				.always(() => {
					this.saving = null;
					this.refresh_status();
					if (this.again) {
						this.again = false;
						this.save(false);
					}
				});
			this.refresh_status();
			return this.saving;
		}

		check() {
			frappe.call({ method: "waba.api.bots.check", args: { bot: this.name }, silent: true }).then((r) => this.set_problems((r.message || {}).detail || []));
		}

		publish() {
			Promise.resolve(this.save(false)).then(() => {
				if (this.problems.length) {
					this.show_tab("problems");
					return frappe.msgprint({ title: __("The bot cannot be published yet"), message: this.problems.map((p) => esc(p.text)).join("<br>"), indicator: "red" });
				}
				frappe.confirm(__("Publish this bot? Customers will get this version from now on."), () => {
					frappe.call({ method: "waba.api.bots.publish", args: { bot: this.name }, type: "POST", freeze: true }).then((r) => {
						this.version = (r.message || {}).version || this.version + 1;
						this.published = G.clone(this.graph);
						this.refresh_status();
						frappe.show_alert({ message: __("Published version {0}. Switch the bot on in the form when you are ready.", [this.version]), indicator: "green" }, 6);
					});
				});
			});
		}

		close() {
			Promise.resolve(this.dirty ? this.save(false) : null).then(() => {
				clearTimeout(this.timer);
				window.removeEventListener("resize", this.on_resize);
				this.close_menu();
				this.$.remove();
				if (this.opts.onClose) this.opts.onClose();
			});
		}

		set_problems(detail) {
			this.problems = detail || [];
			this.draw_flags();
			this.refresh_status();
			if (this.tab === "problems") this.render_panel();
		}

		refresh_status() {
			if (!this.$) return;
			const differs = !this.published || canon(this.published) !== canon(this.graph);
			const pill = this.$.find(".wbb-status");
			if (!this.version) pill.attr("class", "wbb-pill warn wbb-status").text(__("Not published yet"));
			else if (differs) pill.attr("class", "wbb-pill warn wbb-status").text(__("Version {0} live, draft has changes", [this.version]));
			else pill.attr("class", "wbb-pill ok wbb-status").text(__("Version {0} is live", [this.version]));
			const text = this.saving ? __("Saving...") : this.dirty ? __("Unsaved changes") : this.savedAt ? __("Draft saved {0}", [this.savedAt.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })]) : "";
			this.$.find(".wbb-saved").text(text);
			this.$.find(".wbb-undo").prop("disabled", !this.history.canUndo);
			this.$.find('.wbb-tab[data-t="problems"]').text(this.problems.length ? __("Problems ({0})", [this.problems.length]) : __("Problems"));
		}

		// ------------------------------------------------------------------------------------------ drawing the board
		node_el(id) {
			return this.$nodes.find(`.wbb-node[data-id="${CSS.escape(String(id))}"]`);
		}

		preview(node) {
			const d = node.data || {};
			if (node.type === "trigger" && Array.isArray(d.starts)) {
				return d.starts.map((x) => (x.mode === "keyword" ? `${__("Keyword")}: ${(x.keywords || "").trim() || "…"}` : (TRIGGERS.find((t) => t[0] === x.mode) || ["", __("Choose what starts the bot")])[1])).join("\n");
			}
			if (node.type === "trigger") {
				if (d.mode === "keyword") return `${__("A keyword")}: ${d.keywords || ""}`;
				return (TRIGGERS.find((t) => t[0] === d.mode) || ["", __("Choose what starts the bot")])[1];
			}
			if (node.type === "condition") return (CONDITIONS.find((c) => c[0] === d.kind) || ["", ""])[1] + (d.value ? ` "${d.value}"` : "");
			if (node.type === "assign_team") return d.team ? `${__("Team")}: ${d.team}${d.agent ? `\n${__("Agent")}: ${((this.agents[d.team] || []).find((a) => a.user === d.agent) || {}).full_name || d.agent}` : ""}` : __("Choose a team");
			if (node.type === "ask") return `${d.text || ""}${d.var ? `\n→ {{${d.var}}}` : ""}${G.timeoutOf(node) ? `\n${__("No answer after {0} min", [G.timeoutOf(node)])}` : ""}`;
			if (node.type === "buttons" || node.type === "list") return `${d.text || ""}${G.timeoutOf(node) ? `\n${__("No answer after {0} min", [G.timeoutOf(node)])}` : ""}`;
			if (node.type === "status_lookup") return `${d.doctype || ""}: ${d.text || ""}`;
			if (node.type === "send_file") return d.source === "erp_pdf" ? __("PDF of the customer's latest {0}", [d.doctype || ""]) : `${__("File")}: ${(this.library.find((f) => f.name === d.shared_file) || {}).title || d.shared_file || __("choose a file")}`;
			if (node.type === "link_button") return `${d.text || ""}\n[${d.button_text || ""}] ${d.url || ""}`;
			return d.text || "";
		}

		render() {
			this.apply_view();
			this.$nodes.empty();
			for (const n of this.graph.nodes) this.$nodes.append(this.node_html(n));
			this.$.find(".wbb-hint").prop("hidden", this.graph.nodes.length > 1);
			this.draw_flags();
			// measure after layout, so lines meet the dots
			requestAnimationFrame(() => this.draw_edges());
			this.render_panel();
			this.refresh_status();
		}

		node_html(n) {
			const k = KINDS[n.type] || { label: n.type, group: "msg", icon: "" };
			const outs = G.handlesOf(n);
			const joined = new Set(this.graph.edges.filter((e) => e.source === n.id).map((e) => e.sourceHandle || "out"));
			const single = outs.length === 1 && outs[0].id === "out";
			const rows = single
				? `<div class="wbb-outs"><div class="wbb-out" data-handle="out"><span class="wbb-dot ${joined.has("out") ? "joined" : ""}" data-handle="out"></span>${esc(__("then"))}</div></div>`
				: outs.length
				? `<div class="wbb-outs">${outs.map((h) => `<div class="wbb-out" data-handle="${esc(h.id)}">${esc(h.label)}<span class="wbb-dot ${joined.has(h.id) ? "joined" : ""}" data-handle="${esc(h.id)}"></span></div>`).join("")}</div>`
				: "";
			const el = $(`
				<div class="wbb-node ${this.selected === n.id ? "sel" : ""}" data-id="${esc(n.id)}" style="left:${n.position.x}px;top:${n.position.y}px">
					${n.type === "trigger" ? "" : '<span class="wbb-in"></span>'}
					<div class="wbb-nh">${icon(n.type in KINDS ? n.type : "message")}<b>${esc(k.label)}</b>${this.counts && this.counts.blocks && this.counts.blocks[n.id] != null ? `<span class="wbb-count" title="${esc(__("Customers who reached this block in the last {0} days", [this.counts.days]))}">${esc(this.counts.blocks[n.id])}</span>` : ""}${n.type === "trigger" ? "" : `<button class="wbb-kebab" aria-label="${esc(__("More"))}">&#8942;</button>`}</div>
					<div class="wbb-np">${esc(this.preview(n))}</div>
					${rows}
				</div>`);
			el.on("pointerdown", (ev) => this.node_down(ev, n.id));
			el.find(".wbb-kebab").on("pointerdown", (ev) => ev.stopPropagation()).on("click", (ev) => this.node_menu(ev, n.id));
			el.find(".wbb-dot").on("pointerdown", (ev) => this.dot_down(ev, n.id, $(ev.currentTarget).data("handle")));
			return el;
		}

		draw_flags() {
			if (!this.$nodes) return;
			this.$nodes.find(".wbb-flag").remove();
			const bad = new Set(this.problems.map((p) => p.node).filter(Boolean));
			bad.forEach((id) => this.node_el(id).append(`<span class="wbb-flag" title="${esc(__("This block has a problem"))}"></span>`));
		}

		point(el) {
			const r = el[0].getBoundingClientRect();
			const b = this.$world[0].getBoundingClientRect();
			return { x: (r.left + r.width / 2 - b.left) / this.view.k, y: (r.top + r.height / 2 - b.top) / this.view.k };
		}

		path(a, b) {
			const dx = Math.max(50, Math.abs(b.x - a.x) / 2);
			return `M${a.x},${a.y} C${a.x + dx},${a.y} ${b.x - dx},${b.y} ${b.x},${b.y}`;
		}

		draw_edges() {
			if (!this.$layer) return;
			let svg = "";
			for (const e of this.graph.edges) {
				const from = this.node_el(e.source).find(`.wbb-dot[data-handle="${CSS.escape(String(e.sourceHandle || "out"))}"]`);
				const to = this.node_el(e.target).find(".wbb-in");
				if (!from.length || !to.length) continue;
				const a = this.point(from);
				const b = this.point(to);
				const d = this.path(a, b);
				const sel = this.selectedEdge === e.id;
				svg += `<path class="${sel ? "sel" : ""}" d="${d}"/><polygon class="${sel ? "sel" : ""}" points="${b.x - 11},${b.y - 5} ${b.x - 1},${b.y} ${b.x - 11},${b.y + 5}"/><path class="hit" data-edge="${esc(e.id)}" d="${d}"/>`;
				if (sel && !this.compact) {
					const mx = (a.x + b.x) / 2;
					const my = (a.y + b.y) / 2;
					svg += `<g data-cut="${esc(e.id)}"><circle class="cut" cx="${mx}" cy="${my}" r="11"/><path class="cutx" d="M${mx - 4},${my - 4} L${mx + 4},${my + 4} M${mx + 4},${my - 4} L${mx - 4},${my + 4}"/></g>`;
				}
			}
			this.$layer.html(svg);
			this.$layer.find("path.hit").on("click", (ev) => {
				ev.stopPropagation();
				this.selectedEdge = $(ev.currentTarget).data("edge");
				this.selected = null;
				this.render_selection();
				this.draw_edges();
			});
			this.$layer.find("[data-cut]").on("pointerdown", (ev) => ev.stopPropagation()).on("click", (ev) => this.remove_edge($(ev.currentTarget).data("cut")));
		}

		// ------------------------------------------------------------------------------------------ dragging and joining
		node_down(ev, id) {
			if ($(ev.target).closest(".wbb-dot, .wbb-kebab").length) return;
			ev.stopPropagation();
			this.select(id);
			if (this.compact) return;
			const node = G.find(this.graph, id);
			const start = { x: ev.clientX, y: ev.clientY, nx: node.position.x, ny: node.position.y };
			const before = JSON.stringify(this.graph);
			let moved = false;
			const el = this.node_el(id);
			const move = (e) => {
				const dx = (e.clientX - start.x) / this.view.k;
				const dy = (e.clientY - start.y) / this.view.k;
				if (!moved && Math.hypot(dx, dy) < 3) return;
				moved = true;
				node.position = { x: Math.round(start.nx + dx), y: Math.round(start.ny + dy) };
				el.css({ left: node.position.x, top: node.position.y });
				this.draw_edges();
			};
			const up = () => {
				document.removeEventListener("pointermove", move);
				document.removeEventListener("pointerup", up);
				if (moved) {
					this.history.stack.push(before);
					this.changed();
				}
			};
			document.addEventListener("pointermove", move);
			document.addEventListener("pointerup", up);
		}

		dot_down(ev, source, handle) {
			ev.stopPropagation();
			ev.preventDefault();
			if (this.compact) return;
			const a = this.point($(ev.currentTarget));
			const tmp = $(document.createElementNS("http://www.w3.org/2000/svg", "path")).addClass("tmp");
			this.$layer.append(tmp);
			let target = null;
			const move = (e) => {
				const p = this.to_world(e.clientX, e.clientY);
				tmp.attr("d", this.path(a, p));
				const hit = document.elementFromPoint(e.clientX, e.clientY);
				const node = hit && hit.closest ? hit.closest(".wbb-node") : null;
				const id = node ? node.getAttribute("data-id") : null;
				const found = id && id !== source ? G.find(this.graph, id) : null;
				target = found && found.type !== "trigger" ? id : null;
				this.$nodes.find(".wbb-node").removeClass("target");
				if (target) this.node_el(target).addClass("target");
			};
			const up = () => {
				document.removeEventListener("pointermove", move);
				document.removeEventListener("pointerup", up);
				tmp.remove();
				this.$nodes.find(".wbb-node").removeClass("target");
				if (target) {
					this.snapshot();
					G.connect(this.graph, source, handle, target);
					this.changed();
					this.render();
				}
			};
			document.addEventListener("pointermove", move);
			document.addEventListener("pointerup", up);
			move(ev);
		}

		node_menu(ev, id) {
			ev.stopPropagation();
			this.close_menu();
			const r = ev.currentTarget.getBoundingClientRect();
			this.menu = $(`<div class="wbb-menu" style="left:${Math.min(r.left, window.innerWidth - 170)}px;top:${r.bottom + 4}px"><button data-a="dup">${esc(__("Duplicate"))}</button><button class="danger" data-a="del">${esc(__("Delete"))}</button></div>`).appendTo(document.body);
			this.menu.on("click", "button", (e) => {
				const action = $(e.currentTarget).data("a");
				this.close_menu();
				if (action === "del") this.remove_node(id);
				else {
					this.snapshot();
					const copy = G.duplicate(this.graph, id);
					this.changed();
					this.render();
					if (copy) this.select(copy.id);
				}
			});
			setTimeout(() => $(document).one("click", () => this.close_menu()), 0);
		}

		close_menu() {
			if (this.menu) this.menu.remove();
			this.menu = null;
		}

		select(id) {
			this.selected = id;
			this.selectedEdge = null;
			if (id && this.tab !== "block" && !this.compact) this.tab = "block";
			this.render_selection();
			this.draw_edges();
			this.render_panel();
		}

		render_selection() {
			this.$nodes.find(".wbb-node").removeClass("sel");
			if (this.selected) this.node_el(this.selected).addClass("sel");
		}

		refresh_node(id) {
			const node = G.find(this.graph, id);
			const old = this.node_el(id);
			if (!node || !old.length) return;
			const fresh = this.node_html(node);
			old.replaceWith(fresh);
			this.draw_flags();
			this.draw_edges();
		}

		// ------------------------------------------------------------------------------------------ right-hand panel
		show_tab(t) {
			this.tab = t;
			this.$.find(".wbb-tab").removeClass("on").filter(`[data-t="${t}"]`).addClass("on");
			this.render_panel();
		}

		render_panel() {
			if (!this.$pane) return;
			this.$.find(".wbb-tab").removeClass("on").filter(`[data-t="${this.tab}"]`).addClass("on");
			if (this.tab === "problems") return this.panel_problems();
			if (this.tab === "try") return this.panel_try();
			this.panel_block();
		}

		panel_problems() {
			const list = this.problems;
			this.$pane.html(
				list.length
					? `<h4>${__("What stops Publish")}</h4><div class="sub">${__("Click one to go to its block.")}</div>${list.map((p, i) => `<button class="wbb-prob" data-i="${i}">${esc(p.text)}</button>`).join("")}`
					: `<h4 class="wbb-good">${__("No problems")}</h4><div class="sub">${__("This draft can be published.")}</div>`
			);
			this.$pane.find(".wbb-prob").on("click", (ev) => {
				const p = list[$(ev.currentTarget).data("i")];
				if (p && p.node && G.find(this.graph, p.node)) {
					this.tab = "block";
					this.select(p.node);
					this.show_tab("block");
				}
			});
		}

		field(label, inner, count) {
			return `<div class="wbb-f"><label>${esc(label)}${count || ""}</label>${inner}</div>`;
		}

		counter(len, max) {
			return `<span class="count ${len > max ? "over" : ""}">${len}/${max}</span>`;
		}

		varChips() {
			return `<div class="wbb-chips">${G.variables(this.graph)
				.map((v) => `<button type="button" class="wbb-chipv" data-v="${esc(v)}" title="${esc(VARIABLE_HELP[v] || __("the answer to your question"))}">{{${esc(v)}}}</button>`)
				.join("")}</div>`;
		}

		panel_block() {
			const node = this.selected ? G.find(this.graph, this.selected) : null;
			if (!node) {
				this.$pane.html(`<h4>${__("Nothing selected")}</h4><div class="sub">${__("Click a block on the board to change it, or add one from the left.")}</div>`);
				return;
			}
			const d = node.data;
			const k = KINDS[node.type];
			let html = `<h4>${icon(node.type)} ${esc(k.label)}</h4><div class="sub">${esc(HINTS[node.type])}</div>`;
			const text = (key, label, max = 1024, hint) =>
				this.field(label, `<textarea data-k="${key}" maxlength="${max + 200}">${esc(d[key] || "")}</textarea>${hint === false ? "" : this.varChips()}`, this.counter((d[key] || "").length, max));
			if (node.type === "trigger") {
				const starts = G.startsOf(node);
				const many = starts.length > 1;
				html += `<div class="text-muted" style="font-size:12px;margin-bottom:6px">${__("Each start is its own line out of the Trigger. A customer message that matches a start follows that line. A keyword start comes before a new conversation, which comes before any message.")}</div>`;
				html += starts
					.map((x, n) => {
						const sid = esc(x.id);
						let card = `<div class="wbb-f" style="border:1px solid var(--border-color,#d1d8dd);border-radius:8px;padding:8px;margin-bottom:8px"><label>${esc(__("Start {0}", [n + 1]))}${many ? ` <button class="x" data-rmstart="${sid}" title="${esc(__("Remove this start"))}" style="float:right">&times;</button>` : ""}</label>`;
						card += this.field(__("Name on the line (optional)"), `<input data-sk="label" data-sid="${sid}" maxlength="28" value="${esc(x.label || "")}">`);
						card += this.field(__("Starts when"), `<select data-sk="mode" data-sid="${sid}"><option value="">${esc(__("Choose..."))}</option>${TRIGGERS.map(([v, l]) => `<option value="${v}" ${x.mode === v ? "selected" : ""}>${esc(l)}</option>`).join("")}</select>`);
						if (x.mode === "keyword") {
							card += this.field(__("Keywords"), `<textarea data-sk="keywords" data-sid="${sid}" style="min-height:60px">${esc(x.keywords || "")}</textarea><div class="text-muted" style="font-size:11.5px">${__("Separate with commas, for example: price, rate card")}</div>`);
							card += this.field(__("The message must"), `<select data-sk="match" data-sid="${sid}"><option value="exact" ${x.match !== "contains" ? "selected" : ""}>${esc(__("be exactly a keyword"))}</option><option value="contains" ${x.match === "contains" ? "selected" : ""}>${esc(__("contain a keyword"))}</option></select>`);
						}
						return card + "</div>";
					})
					.join("");
				html += `<button class="btn btn-default btn-xs wbb-addstart" ${starts.length >= G.MAX_STARTS ? "disabled" : ""}>${__("Add a start")}</button>`;
				html += `<div class="text-muted" style="font-size:12px;margin-top:8px">${__("The bot never starts on a chat a person already has, for a customer who opted out, or outside your test phone list.")}</div>`;
			} else if (node.type === "message") html += text("text", __("Message"));
			else if (node.type === "note") html += text("text", __("Internal note"), 1024) + `<div class="text-muted" style="font-size:12px">${__("Agents see it in the chat. The customer never does.")}</div>`;
			else if (node.type === "handover" || node.type === "end") html += text("text", __("Last message (optional)"));
			else if (node.type === "buttons") {
				html += text("text", __("Message"));
				html += `<div class="wbb-f"><label>${__("Buttons")} <span class="count">${(d.buttons || []).length}/${G.MAX_BUTTONS}</span></label>${(d.buttons || [])
					.map((b) => `<div class="wbb-opt"><div class="col"><input data-opt="${esc(b.id)}" data-f="title" maxlength="40" value="${esc(b.title || "")}">${this.counter((b.title || "").length, 20)}</div><button class="x" data-rm="${esc(b.id)}" title="${esc(__("Remove"))}">&times;</button></div>`)
					.join("")}<button class="btn btn-default btn-xs wbb-add" ${(d.buttons || []).length >= G.MAX_BUTTONS ? "disabled" : ""}>${__("Add button")}</button></div>`;
			} else if (node.type === "list") {
				html += text("text", __("Message"));
				html += this.field(__("Button that opens the list"), `<input data-k="button_text" maxlength="40" value="${esc(d.button_text || "")}">`, this.counter((d.button_text || "").length, 20));
				html += `<div class="wbb-f"><label>${__("Choices")} <span class="count">${(d.rows || []).length}/${G.MAX_ROWS}</span></label>${(d.rows || [])
					.map((r) => `<div class="wbb-opt"><div class="col"><input data-opt="${esc(r.id)}" data-f="title" maxlength="40" value="${esc(r.title || "")}" placeholder="${esc(__("Title"))}">${this.counter((r.title || "").length, 24)}<input data-opt="${esc(r.id)}" data-f="description" maxlength="100" value="${esc(r.description || "")}" placeholder="${esc(__("Description (optional)"))}"></div><button class="x" data-rm="${esc(r.id)}" title="${esc(__("Remove"))}">&times;</button></div>`)
					.join("")}<button class="btn btn-default btn-xs wbb-add" ${(d.rows || []).length >= G.MAX_ROWS ? "disabled" : ""}>${__("Add choice")}</button></div>`;
			} else if (node.type === "ask") {
				html += text("text", __("Question"));
				html += this.field(__("Keep the answer as"), `<input data-k="var" maxlength="31" value="${esc(d.var || "")}"><div class="text-muted" style="font-size:11.5px">${__("A short name, for example city. Use it later as {{city}}.")}</div>`);
				html += this.field(__("The answer should be"), `<select data-k="validate">${[["text", __("Any text")], ["number", __("A number")], ["phone", __("A phone number")], ["email", __("An email address")]].map(([v, l]) => `<option value="${v}" ${(d.validate || "text") === v ? "selected" : ""}>${esc(l)}</option>`).join("")}</select>`);
				html += this.field(__("If it does not fit, say"), `<input data-k="retry_text" maxlength="200" value="${esc(d.retry_text || "")}">`);
			} else if (node.type === "condition") {
				html += this.field(__("Check whether"), `<select data-k="kind"><option value="">${esc(__("Choose..."))}</option>${CONDITIONS.map(([v, l]) => `<option value="${v}" ${d.kind === v ? "selected" : ""}>${esc(l)}</option>`).join("")}</select>`);
				if (d.kind === "var_equals" || d.kind === "var_contains") {
					const vars = G.variables(this.graph).filter((v) => !G.BUILTIN_VARS.includes(v));
					html += this.field(__("Answer"), `<select data-k="var"><option value="">${esc(__("Choose..."))}</option>${vars.map((v) => `<option value="${esc(v)}" ${d.var === v ? "selected" : ""}>${esc(v)}</option>`).join("")}</select>`);
					html += this.field(__("Value"), `<input data-k="value" maxlength="140" value="${esc(d.value || "")}">`);
					if (!vars.length) html += `<div class="text-muted" style="font-size:12px">${__("Add a Question block first: a condition checks an answer the customer gave.")}</div>`;
				}
				html += `<div class="text-muted" style="font-size:12px">${__("Draw the Yes line and the No line from the two dots on the block.")}</div>`;
			} else if (node.type === "assign_team") {
				html += this.field(__("Team"), `<select data-k="team"><option value="">${esc(__("Choose..."))}</option>${this.teams.map((t) => `<option value="${esc(t)}" ${d.team === t ? "selected" : ""}>${esc(t)}</option>`).join("")}${d.team && !this.teams.includes(d.team) ? `<option selected value="${esc(d.team)}">${esc(d.team)}</option>` : ""}</select>`);
				if (d.team) {
					const people = this.agents[d.team];
					if (!people) this.load_agents(d.team);
					const list = people || [];
					const opts = list.map((a) => `<option value="${esc(a.user)}" ${d.agent === a.user ? "selected" : ""}>${esc(a.full_name)}${a.role === "Team Lead" ? ` (${esc(__("Team Lead"))})` : ""}</option>`).join("");
					const gone = d.agent && people && !list.some((a) => a.user === d.agent) ? `<option selected value="${esc(d.agent)}">${esc(d.agent)} (${esc(__("not in team"))})</option>` : "";
					html += this.field(__("Agent"), `<select data-k="agent"><option value="">${esc(people ? __("Any available agent (least busy)") : __("Loading..."))}</option>${opts}${gone}</select>`);
				}
				html += text("text", __("Message before handing over (optional)"));
				html += `<div class="text-muted" style="font-size:12px">${__("Pick a person, or leave it on Any to give the chat to the team's least busy available agent. A chosen person gets the chat even when Away. If they can no longer take it, it goes to the team instead.")}</div>`;
			} else if (node.type === "link_button") {
				html += text("text", __("Message"));
				html += this.field(__("Button text"), `<input data-k="button_text" maxlength="40" value="${esc(d.button_text || "")}">`, this.counter((d.button_text || "").length, 20));
				html += this.field(__("Web address"), `<input data-k="url" maxlength="2100" value="${esc(d.url || "")}" placeholder="https://"><div class="text-muted" style="font-size:11.5px">${__("Must start with https://")}</div>`);
			} else if (node.type === "send_file") {
				html += this.field(__("Send"), `<select data-k="source"><option value="library" ${d.source !== "erp_pdf" ? "selected" : ""}>${esc(__("A file from the shared library"))}</option><option value="erp_pdf" ${d.source === "erp_pdf" ? "selected" : ""}>${esc(__("The customer's latest document, as a PDF"))}</option></select>`);
				if (d.source === "erp_pdf") {
					html += this.field(__("Document"), `<select data-k="doctype">${["Quotation", "Sales Order", "Sales Invoice"].map((t) => `<option value="${t}" ${d.doctype === t ? "selected" : ""}>${esc(__(t))}</option>`).join("")}</select><div class="text-muted" style="font-size:11.5px">${__("Only the customer's own documents. Nothing is sent if they have none: use the Nothing to send line.")}</div>`);
				} else {
					html += this.field(__("Library file"), `<select data-k="shared_file"><option value="">${esc(__("Choose..."))}</option>${this.library.map((f) => `<option value="${esc(f.name)}" ${d.shared_file === f.name ? "selected" : ""}>${esc(f.title)}${f.enabled ? "" : " (off)"}</option>`).join("")}</select>`);
				}
				html += text("caption", __("Caption (optional)"));
			} else if (node.type === "status_lookup") {
				html += this.field(__("Look up"), `<select data-k="doctype">${["Quotation", "Sales Order", "Sales Invoice"].map((t) => `<option value="${t}" ${d.doctype === t ? "selected" : ""}>${esc(__(t))}</option>`).join("")}</select><div class="text-muted" style="font-size:11.5px">${__("The customer's own latest submitted one. Never anyone else's, and never one the customer names.")}</div>`);
				html += text("text", __("Message when found"));
				html += `<div class="text-muted" style="font-size:12px">${__("Draw the Found line and the Not found line from the two dots on the block.")}</div>`;
			}
			if (this.extras && ["buttons", "list", "ask"].includes(node.type)) {
				html += this.field(__("If the customer does not answer within (minutes)"), `<input type="number" min="0" max="${G.MAX_TIMEOUT}" data-timeout="1" value="${esc(d.timeout_minutes || "")}" placeholder="0"><div class="text-muted" style="font-size:11.5px">${__("Leave empty for none. Adds a No answer line you can join to a reminder or a hand over. Up to {0} minutes; it runs at most 3 times per customer.", [G.MAX_TIMEOUT])}</div>`);
			}
			if (node.type !== "trigger") html += `<hr><button class="btn btn-default btn-xs wbb-del" style="color:#b42318">${__("Delete this block")}</button>`;
			this.$pane.html(html);
			this.wire_panel(node);
		}

		load_agents(team) {
			this.agents[team] = this.agents[team] || null;
			if (this.agents_loading === team) return;
			this.agents_loading = team;
			frappe.call({ method: "waba.api.bots.team_agents", args: { team }, type: "GET" }).always(() => (this.agents_loading = null)).then((r) => {
				this.agents[team] = (r && r.message) || [];
				if (this.tab === "block") this.render_panel();
				this.refresh_node && this.graph.nodes.filter((n) => n.type === "assign_team").forEach((n) => this.refresh_node(n.id));
			});
		}

		wire_panel(node) {
			const id = node.id;
			const d = node.data;
			const self = this;
			let typingSnapshot = false;
			const beforeEdit = () => {
				if (!typingSnapshot) {
					this.snapshot();
					typingSnapshot = true;
					setTimeout(() => (typingSnapshot = false), 1500);
				}
			};
			this.$pane.find("[data-k]").on("input change", function () {
				beforeEdit();
				const key = $(this).data("k");
				let value = this.value;
				if (key === "var") value = value.toLowerCase().replace(/[^a-z0-9_]/g, "_").replace(/^[^a-z]+/, "");
				if (key === "var" && node.type === "ask") this.value = value;
				if (key === "team" && node.type === "assign_team") G.setTeam(self.graph, id, value);
				else d[key] = value;
				const $f = $(this).closest(".wbb-f").find(".count").first();
				if ($f.length && $(this).is("textarea,input")) {
					const max = key === "button_text" ? 20 : 1024;
					$f.text(`${value.length}/${max}`).toggleClass("over", value.length > max);
				}
				self.refresh_node(id);
				self.changed();
				if ($(this).is("select") && ["mode", "kind", "source", "team"].includes(key)) self.panel_block();
			});
			this.$pane.find("[data-sk]").on("input change", function () {
				beforeEdit();
				G.setStart(self.graph, $(this).data("sid"), $(this).data("sk"), this.value);
				self.refresh_node(id);
				self.changed();
				if ($(this).is("select") && $(this).data("sk") === "mode") self.panel_block();
			});
			this.$pane.find(".wbb-addstart").on("click", () => {
				this.snapshot();
				if (G.addStart(this.graph)) {
					this.changed();
					this.refresh_node(id);
					this.panel_block();
				} else this.history.undo();
			});
			this.$pane.find("[data-rmstart]").on("click", (ev) => {
				this.snapshot();
				if (G.removeStart(this.graph, $(ev.currentTarget).data("rmstart"))) {
					this.changed();
					this.render();
				} else this.history.undo();
			});
			this.$pane.find("[data-timeout]").on("input change", function () {
				beforeEdit();
				G.setTimeout(self.graph, id, this.value);
				self.refresh_node(id);
				self.changed();
			});
			this.$pane.find("[data-opt]").on("input", function () {
				beforeEdit();
				const list = node.type === "buttons" ? d.buttons : d.rows;
				const option = list.find((o) => String(o.id) === String($(this).data("opt")));
				if (!option) return;
				option[$(this).data("f")] = this.value;
				if ($(this).data("f") === "title") {
					const max = node.type === "buttons" ? 20 : 24;
					$(this).siblings(".count").text(`${this.value.length}/${max}`).toggleClass("over", this.value.length > max);
				}
				self.refresh_node(id);
				self.changed();
			});
			this.$pane.find(".wbb-add").on("click", () => {
				this.snapshot();
				if (G.addOption(this.graph, id)) {
					this.changed();
					this.refresh_node(id);
					this.panel_block();
				}
			});
			this.$pane.find("[data-rm]").on("click", (ev) => {
				this.snapshot();
				if (G.removeOption(this.graph, id, $(ev.currentTarget).data("rm"))) {
					this.changed();
					this.render();
				} else this.history.undo();
			});
			this.$pane.find(".wbb-chipv").on("click", function () {
				const ta = $(this).closest(".wbb-f").find("textarea")[0];
				if (!ta) return;
				const at = ta.selectionStart == null ? ta.value.length : ta.selectionStart;
				const token = `{{${$(this).data("v")}}}`;
				ta.value = ta.value.slice(0, at) + token + ta.value.slice(ta.selectionEnd == null ? at : ta.selectionEnd);
				ta.focus();
				ta.selectionStart = ta.selectionEnd = at + token.length;
				$(ta).trigger("input");
			});
			this.$pane.find(".wbb-del").on("click", () => this.remove_node(id));
		}

		// ------------------------------------------------------------------------------------------ the Simulator
		panel_try() {
			const s = this.sim;
			const chat = s.chat
				.map((m) => {
					if (m.kind === "sys") return `<div class="wbb-sys">${esc(m.text)}</div>`;
					if (m.kind === "me") return `<div class="wbb-bub me">${esc(m.text)}</div>`;
					const choices = (m.buttons || m.rows || [])
						.map((c, i) => `<button data-i="${i}" data-m="${m.i}" ${m.live ? "" : "disabled"}>${esc(c.title)}</button>`)
						.join("");
					return `<div class="wbb-bub">${esc(m.text)}${choices ? `<div class="wbb-sim-btns">${m.rows ? `<div class="text-muted" style="font-size:11.5px">${esc(m.button || "")}</div>` : ""}${choices}</div>` : ""}</div>`;
				})
				.join("");
			const problems = s.problems && s.problems.length ? `<div class="wbb-prob" style="border-left-color:#d92d20">${s.problems.map((p) => esc(p)).join("<br>")}</div>` : "";
			this.$pane.html(`
				<h4>${__("Try the bot")}</h4><div class="sub">${__("Talk to it as a customer would. Nothing is sent to anyone.")}</div>
				<div class="wbb-toggles">
					${G.startsOf(this.graph.nodes.find((n) => n.type === "trigger")).length > 1 ? `<label>${esc(__("Start with"))} <select class="s-startsel">${G.startsOf(this.graph.nodes.find((n) => n.type === "trigger")).map((x) => `<option value="${esc(x.id)}" ${s.start === x.id ? "selected" : ""}>${esc(G.startLabel(x))}</option>`).join("")}</select></label>` : ""}
					<label><input type="checkbox" class="s-hours" ${s.open_now ? "checked" : ""}> ${__("Business hours: open")}</label>
					<label><input type="checkbox" class="s-known" ${s.matched ? "checked" : ""}> ${__("The customer is a known record")}</label>
					<label><input type="checkbox" class="s-pub" ${s.published ? "checked" : ""} ${this.version ? "" : "disabled"}> ${__("Try the published version (not the draft)")}</label>
					${this.extras ? `<label><input type="checkbox" class="s-docs" ${s.has_docs ? "checked" : ""}> ${__("The customer has documents and files")}</label>` : ""}
				</div>
				${problems}
				<div class="wbb-chat">${chat || `<div class="wbb-sys">${esc(__("Press Start to begin"))}</div>`}</div>
				<div class="wbb-send"><input type="text" class="form-control input-sm s-text" placeholder="${esc(__("Type a reply..."))}" ${s.state.node ? "" : "disabled"}><button class="btn btn-primary btn-sm s-go" ${s.state.node ? "" : "disabled"}>${__("Send")}</button></div>
				<div style="margin-top:10px"><button class="btn btn-default btn-sm s-start">${s.chat.length ? __("Start again") : __("Start")}</button>${this.extras && s.state.node && s.timeout_minutes ? ` <button class="btn btn-default btn-sm s-quiet">${__("The customer goes quiet")}</button>` : ""}</div>`);
			const box = this.$pane.find(".wbb-chat")[0];
			box.scrollTop = box.scrollHeight;
			this.$pane.find(".s-startsel").on("change", (ev) => (s.start = ev.target.value));
			this.$pane.find(".s-hours").on("change", (ev) => (s.open_now = ev.target.checked ? 1 : 0));
			this.$pane.find(".s-known").on("change", (ev) => (s.matched = ev.target.checked ? 1 : 0));
			this.$pane.find(".s-pub").on("change", (ev) => (s.published = ev.target.checked ? 1 : 0));
			this.$pane.find(".s-docs").on("change", (ev) => (s.has_docs = ev.target.checked ? 1 : 0));
			this.$pane.find(".s-quiet").on("click", () => this.sim_call("", null, "timeout"));
			this.$pane.find(".s-start").on("click", () => this.sim_start());
			const send = () => {
				const input = this.$pane.find(".s-text");
				const text = String(input.val() || "").trim();
				if (text) this.sim_step(text, null);
			};
			this.$pane.find(".s-go").on("click", send);
			this.$pane.find(".s-text").on("keydown", (ev) => ev.key === "Enter" && send());
			this.$pane.find(".wbb-sim-btns button").on("click", (ev) => {
				const m = s.chat.find((x) => x.i === Number($(ev.currentTarget).data("m")));
				const c = (m.buttons || m.rows)[$(ev.currentTarget).data("i")];
				this.sim_step(c.title, c.id);
			});
		}

		sim_start() {
			const s = this.sim;
			s.state = {};
			s.chat = [];
			s.problems = null;
			this.mark_active(null);
			this.sim_call("", null);
		}

		sim_step(text, id) {
			const s = this.sim;
			s.chat.forEach((m) => (m.live = false));
			s.chat.push({ kind: "me", text });
			this.sim_call(text, id);
		}

		sim_call(text, id, event) {
			const s = this.sim;
			Promise.resolve(this.dirty ? this.save(false) : null).then(() =>
				frappe
					.call({ method: "waba.api.bots.simulate", args: { bot: this.name, state: JSON.stringify(s.state || {}), text, interactive_id: id, open_now: s.open_now, matched: s.matched, published: s.published, event: event || "reply", has_docs: s.has_docs, start: s.start || null }, type: "POST", freeze: false })
					.then((r) => {
						const out = r.message || {};
						if (out.problems && out.problems.length) {
							s.problems = out.problems;
							return this.panel_try();
						}
						s.problems = null;
						s.state = out.state || {};
						s.timeout_minutes = out.timeout_minutes || 0;
						if (event === "timeout") s.chat.push({ kind: "sys", text: __("The customer did not answer in time") });
						(out.actions || []).forEach((a) => {
							const i = s.chat.length + 1;
							if (a.do === "note") s.chat.push({ kind: "sys", text: `${__("Internal note")}: ${a.text}` });
							else if (a.do === "buttons") s.chat.push({ kind: "bot", i, text: a.body, buttons: a.buttons, live: true });
							else if (a.do === "list") s.chat.push({ kind: "bot", i, text: a.body, rows: a.rows, button: a.button, live: true });
							else if (a.do === "cta") s.chat.push({ kind: "bot", i, text: `${a.body}\n[${a.button}] ${a.url}` });
							else if (a.do === "file") s.chat.push({ kind: "sys", text: __("Would send the library file {0}", [(this.library.find((f) => f.name === a.file) || {}).title || a.file]) });
							else if (a.do === "pdf") s.chat.push({ kind: "sys", text: __("Would send the PDF of {0} {1}", [a.doctype, a.name]) });
							else s.chat.push({ kind: "bot", i, text: a.body });
						});
						if (out.ended) {
							const why = { assign_team: (out.agent ? __("Handed to {0} (team {1})", [out.agent, out.team || ""]) : __("Handed to team {0}", [out.team || ""])), handover: __("Handed over to the normal routing"), asked: __("The customer asked for a person. Handed over."), stuck: __("The replies were not understood. Handed over."), finished: __("The bot finished"), loop: __("Stopped: too many steps"), missing: __("Stopped: the bot changed") }[out.kind] || out.reason || __("The bot ended");
							s.chat.push({ kind: "sys", text: why });
						}
						this.mark_active(s.state && s.state.node);
						this.panel_try();
					})
			);
		}

		toggle_counts() {
			if (this.counts) {
				this.counts = null;
				this.$.find(".wbb-totals").text("");
				this.$.find(".wbb-nums").text(__("Show numbers"));
				return this.render();
			}
			this.load_counts();
		}

		load_counts() {
			frappe.call({ method: "waba.api.bots.block_counts", args: { bot: this.name, days: this.countDays }, silent: true }).then((r) => {
				const out = r.message || {};
				if (!out.enabled) return;
				this.counts = out;
				const t = out.totals || {};
				const parts = ["Finished", "Handed over", "Expired", "Stopped by agent"].filter((k) => t[k]).map((k) => `${t[k]} ${__(k).toLowerCase()}`);
				this.$.find(".wbb-totals").text(parts.length ? `${__("Last {0} days", [out.days])}: ${parts.join(", ")}` : __("No customers in the last {0} days", [out.days]));
				this.$.find(".wbb-nums").text(__("Hide numbers"));
				this.render();
			});
		}

		mark_active(id) {
			this.$nodes.find(".wbb-node").removeClass("active");
			if (id) this.node_el(id).addClass("active");
		}
	}

	function open(name, opts) {
		new Builder(name, opts).start();
	}

	window.WabaBotBuilder = { open };
})();
