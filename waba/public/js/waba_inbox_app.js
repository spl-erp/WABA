/* WhatsApp inbox: the page's classes. Loaded by the loader in waba/page/waba_inbox/waba_inbox.js (with a version stamp
 * from waba.api.inbox.assets_version, so a changed file is picked up without clearing any cache).
 *
 * Parts: WabaToolbar (number, search, refresh), WabaList (tabs and conversation rows), WabaThread (header, window
 * banner, messages), WabaComposer (the reply box), WabaInbox (state, data, realtime). Pure helpers and icons live in
 * waba_inbox_lib.js. Every call goes to the existing server functions waba.api.inbox.* and waba.api.send.*; this file
 * holds no data of its own. */
(function () {
const waba_e = (value) => WabaLib.escapeHtml(value);

// ---------------------------------------------------------------------------------------------- toolbar

class WabaToolbar {
	constructor($parent, handlers) {
		this.handlers = handlers;
		this.number = "";
		this.numbers = [];
		this.$el = $(`
			<header class="waba-topbar">
				<div class="waba-brand-block">
					${WabaLib.brandMark(40)}
					<div class="waba-brand-text">
						<h1 class="waba-title">${__("WhatsApp Inbox")}</h1>
						<p class="waba-subtitle">${__("Manage your customer conversations")}</p>
					</div>
				</div>
				<div class="waba-numsel">
					<button class="waba-pill-btn" aria-haspopup="listbox">
						${WabaLib.icon("phone", 18)}<span class="waba-grow">${__("All numbers")}</span>${WabaLib.icon("chevron", 16)}
					</button>
					<div class="waba-pop" role="listbox" hidden></div>
				</div>
				<label class="waba-searchbox">
					${WabaLib.icon("search", 18)}
					<input type="search" placeholder="${__("Search by name, phone number or message...")}" autocomplete="off" />
					<span class="waba-kbd" title="${__("Press / to search")}">/</span>
				</label>
				<button class="waba-away" hidden></button>
				<button class="waba-refresh">${WabaLib.icon("refresh", 17)}<span>${__("Refresh")}</span></button>
			</header>`).appendTo($parent);
		this.$away = this.$el.find(".waba-away");
		this.available = null;
		this.$away.on("click", () => this.handlers.onAvailable(!this.available));

		this.$pill = this.$el.find(".waba-pill-btn");
		this.$pop = this.$el.find(".waba-pop");
		this.$search = this.$el.find("input");

		this.$pill.on("click", (ev) => {
			ev.stopPropagation();
			this.$pop.prop("hidden", !this.$pop.prop("hidden"));
		});
		$(document).on("click.waba_numsel", () => this.$pop.prop("hidden", true));
		this.$search.on("input", frappe.utils.debounce(() => this.handlers.onSearch(this.$search.val().trim()), 300));
		this.$el.find(".waba-refresh").on("click", () => this.handlers.onRefresh());
		this.load_numbers();
	}

	load_numbers() {
		frappe.db
			.get_list("Waba Number", { fields: ["name", "display_name", "enabled"], limit: 100, order_by: "name asc" })
			.then((rows) => {
				this.numbers = rows || [];
				this.render_numbers();
				if (this.handlers.onNumbers) this.handlers.onNumbers(this.numbers);
			});
	}

	render_numbers() {
		const items = [{ name: "", label: __("All numbers"), sub: "" }].concat(
			this.numbers.map((n) => ({ name: n.name, label: n.display_name || n.name, sub: n.display_name ? n.name : "" }))
		);
		this.$pop.html(
			items
				.map(
					(i) =>
						`<button class="waba-pop-item ${i.name === this.number ? "active" : ""}" data-name="${waba_e(i.name)}"><span>${waba_e(i.label)}</span><small>${waba_e(i.sub)}</small></button>`
				)
				.join("")
		);
		this.$pop.find(".waba-pop-item").on("click", (ev) => {
			this.number = $(ev.currentTarget).data("name") || "";
			const picked = items.find((i) => i.name === this.number);
			this.$pill.find(".waba-grow").text(picked ? picked.label : __("All numbers"));
			this.$pop.prop("hidden", true);
			this.render_numbers();
			this.handlers.onNumber(this.number);
		});
	}

	focus_search() {
		this.$search.trigger("focus").trigger("select");
	}

	/** true / false for an agent (their own away switch); null hides it (a person who works no number). */
	set_available(value) {
		this.available = value === undefined ? null : value;
		if (this.available === null) return this.$away.prop("hidden", true);
		this.$away
			.prop("hidden", false)
			.toggleClass("away", !this.available)
			.attr("title", this.available ? __("You get new conversations. Click to go away.") : __("You get no new conversations. Click to become available."))
			.html(`<span class="waba-dot2"></span><span>${this.available ? __("Available") : __("Away")}</span>`);
	}

	destroy() {
		$(document).off("click.waba_numsel");
	}
}

// ---------------------------------------------------------------------------------------------- list

class WabaList {
	constructor($parent, handlers) {
		this.handlers = handlers;
		this.rows = [];
		this.has_more = false;
		this.current = null;
		this.view = "open";
		this.scope = "all";
		this.counts = {};
		this.$el = $(`<aside class="waba-list"><div class="waba-tabs"></div><div class="waba-scope" hidden></div><div class="waba-items"></div></aside>`).appendTo($parent);
		this.$tabs = this.$el.find(".waba-tabs");
		this.$scope = this.$el.find(".waba-scope");
		this.$items = this.$el.find(".waba-items");
		this.render_tabs();
	}

	set_counts(counts) {
		this.counts = counts || {};
		this.render_tabs();
		this.render_scope();
	}

	/** Mine / Team / All: only for people who oversee others (a Lead); an agent has nothing to switch. */
	render_scope() {
		const show = !!this.counts.can_oversee;
		this.$scope.prop("hidden", !show);
		if (!show) {
			this.scope = "all";
			return this.$scope.empty();
		}
		const options = [["all", __("All")], ["mine", __("Mine")], ["team", __("Others")]];
		this.$scope.html(options.map(([key, label]) => `<button class="waba-seg ${key === this.scope ? "active" : ""}" data-scope="${key}">${label}</button>`).join(""));
		this.$scope.find(".waba-seg").on("click", (ev) => {
			this.scope = $(ev.currentTarget).data("scope");
			this.render_scope();
			this.handlers.onScope(this.scope);
		});
	}

	render_tabs() {
		const tabs = [
			["open", __("Open"), this.counts.open],
			["unread", __("Unread"), this.counts.unread],
			["triage", __("Triage"), this.counts.triage],
			...(this.counts.can_oversee ? [["unassigned", __("Unassigned"), this.counts.unassigned]] : []),
			["done", __("Done")],
			["all", __("All")],
		];
		this.$tabs.html(
			tabs
				.map(
					([key, label, n]) =>
						`<button class="waba-tab ${key === this.view ? "active" : ""}" data-view="${key}">${label}${n ? ` <span class="waba-count">${n}</span>` : ""}</button>`
				)
				.join("")
		);
		this.$tabs.find(".waba-tab").on("click", (ev) => {
			this.view = $(ev.currentTarget).data("view");
			this.render_tabs();
			this.handlers.onTab(this.view);
		});
	}

	set_rows(rows, has_more) {
		this.rows = rows;
		this.has_more = has_more;
		this.render();
	}

	select(name) {
		this.current = name;
		this.$items.find(".waba-row").removeClass("selected").filter(`[data-name="${name}"]`).addClass("selected");
	}

	clear_unread(name) {
		const row = this.rows.find((r) => r.name === name);
		if (row) row.unread_count = 0;
		this.render();
	}

	render() {
		if (!this.rows.length) {
			const none = this.numbers_known && !this.numbers_known.length;
			this.$items.html(`<div class="waba-empty">${none ? __("No WhatsApp number is set up for you. Ask an administrator.") : __("No conversations here.")}</div>`);
			return;
		}
		const html = this.rows.map((r) => this.row_html(r)).join("");
		this.$items.html(
			html +
				(this.has_more
					? `<button class="waba-more">${WabaLib.icon("arrowdown", 15)}${__("Load more")}</button>`
					: "")
		);
		this.$items.find(".waba-row").on("click", (ev) => this.handlers.onOpen($(ev.currentTarget).data("name")));
		this.$items.find(".waba-more").on("click", () => this.handlers.onMore());
	}

	row_html(r) {
		const lines = WabaLib.customerLines(r);
		const unread = r.unread_count > 0;
		const chips = [];
		if (r.match_state === "Triage") chips.push(`<span class="waba-chip orange">${__("Triage")}</span>`);
		if (r.status === "Done") chips.push(`<span class="waba-chip">${__("Done")}</span>`);
		else chips.push(`<span class="waba-chip ${r.window_open ? "green" : "red"}">${r.window_open ? __("Window open") : __("Window closed")}</span>`);
		if (r.number_name) chips.push(`<span class="waba-chip">${waba_e(r.number_name)}</span>`);
		if (this.counts.can_oversee && r.status !== "Done") {
			chips.push(r.assigned_to ? `<span class="waba-chip blue">${WabaLib.icon("user", 11)}${waba_e(r.assigned_name || r.assigned_to)}</span>` : `<span class="waba-chip orange">${__("Unassigned")}</span>`);
		}
		return `
			<button class="waba-row ${unread ? "unread" : ""} ${r.name === this.current ? "selected" : ""}" data-name="${waba_e(r.name)}">
				<span class="waba-avatar" style="background:${WabaLib.avatarColor(lines.name)}">${waba_e(WabaLib.initials(lines.name))}</span>
				<span class="waba-row-main">
					<span class="waba-row-top">
						<span class="waba-row-name"><span>${waba_e(lines.name)}</span>${r.match_state === "Matched" ? WabaLib.verifiedBadge(15) : ""}</span>
						<span class="waba-row-time">${r.last_message_at ? waba_e(frappe.datetime.prettyDate(r.last_message_at, true)) : ""}</span>
					</span>
					${lines.sub ? `<span class="waba-row-phone">${waba_e(lines.sub)}</span>` : ""}
					<span class="waba-row-bottom">
						<span class="waba-row-preview">${waba_e(r.last_message_preview || "")}</span>
						${unread ? `<span class="waba-badge">${r.unread_count}</span>` : ""}
					</span>
					<span class="waba-chips">${chips.join("")}</span>
				</span>
			</button>`;
	}
}

// ---------------------------------------------------------------------------------------------- composer

class WabaComposer {
	constructor($parent, handlers, drafts) {
		this.handlers = handlers;
		this.mode = null; // "open" (type and send), "closed" (template only), "no_phone" (cannot reply by user ID)
		this.kind = "reply"; // "reply" goes to the customer; "note" stays inside the ERP
		this.drafts = drafts || { reply: "", note: "" }; // one object per conversation, kept by the page so switching chats keeps what you typed
		this.$el = $(`<div class="waba-composer"></div>`).appendTo($parent);
	}

	set_mode(mode) {
		if (mode === this.mode) return;
		this.save_draft();
		this.mode = mode;
		this.render();
	}

	set_kind(kind) {
		if (kind === this.kind) return;
		this.save_draft();
		this.kind = kind;
		this.render();
		if (this.$text) this.$text.trigger("focus");
	}

	save_draft() {
		const v = this.$el.find("textarea").val();
		if (v !== undefined) this.drafts[this.kind] = v;
	}

	render() {
		this.close_emoji();
		this.close_quick();
		this.close_attach();
		const note = this.kind === "note";
		const tabs = `<div class="waba-compose-tabs" role="tablist">
			<button class="waba-ctab ${note ? "" : "active"}" data-kind="reply">${__("Reply")}</button>
			<button class="waba-ctab note ${note ? "active" : ""}" data-kind="note">${WabaLib.icon("note", 14)}${__("Note")}</button>
			<span class="waba-ctab-hint">${note ? __("Notes are only for your team. They are never sent to the customer.") : ""}</span></div>`;
		const can_attach = !note && this.mode === "open";
		const attach = `<button class="waba-circle waba-attach-btn" ${can_attach ? "" : "disabled"} title="${can_attach ? __("Attach a file, an ERP document or a library file") : note ? __("Notes cannot have files") : __("Files can be sent only while the 24-hour window is open")}" aria-label="${__("Attach")}">${WabaLib.icon("paperclip", 19)}</button>`;
		const emoji = (enabled) => `<button class="waba-circle waba-emoji-btn" ${enabled ? "" : "disabled"} aria-label="${__("Emoji")}" title="${__("Emoji")}">${WabaLib.icon("smile", 19)}</button>`;
		const quick = (enabled) => `<button class="waba-circle waba-quick-btn" ${enabled ? "" : "disabled"} aria-label="${__("Quick replies")}" title="${__("Quick replies (type / in an empty box)")}">${WabaLib.icon("zap", 19)}</button>`;
		this.$text = null;
		if (!note && this.mode === "closed") {
			this.$el.html(`${tabs}${attach}${emoji(false)}${quick(false)}
				<div class="waba-inputwrap disabled">${__("Window closed: only approved templates can be sent.")}</div>
				<button class="waba-btn primary waba-send-template">${WabaLib.icon("send", 16)}<span class="waba-btn-text">${__("Send template")}</span></button>`);
			this.$el.find(".waba-send-template").on("click", () => this.handlers.onTemplate());
		} else if (!note && this.mode === "no_phone") {
			this.$el.html(`${tabs}${attach}${emoji(false)}${quick(false)}<div class="waba-inputwrap disabled">${__("This customer is known only by a WhatsApp user ID; replying needs their phone number (not supported yet).")}</div>`);
		} else {
			const placeholder = note
				? __("Write a note for your team")
				: window.innerWidth < 768
				? __("Type a message")
				: __("Type a message (Enter to send, Shift+Enter for a new line)");
			this.$el.html(`${tabs}${attach}${emoji(true)}${quick(true)}
				<div class="waba-inputwrap ${note ? "note" : ""}"><textarea rows="1" placeholder="${placeholder}"></textarea></div>
				<button class="waba-send ${note ? "note" : ""}" aria-label="${note ? __("Add note") : __("Send")}" title="${note ? __("Add note") : __("Send")}">${WabaLib.icon(note ? "note" : "send", 20)}</button>`);
			this.$text = this.$el.find("textarea").val(this.drafts[this.kind]);
			this.$send = this.$el.find(".waba-send");
			this.autosize();
			this.$text.on("input", () => {
				this.drafts[this.kind] = this.$text.val();
				this.autosize();
			});
			this.$text.on("keydown", (ev) => {
				if (ev.key === "Enter" && !ev.shiftKey) {
					ev.preventDefault();
					this.submit();
				} else if (ev.key === "/" && !this.$text.val()) {
					ev.preventDefault();
					this.toggle_quick();
				}
			});
			this.$send.on("click", () => this.submit());
			this.$text.on("paste", (ev) => {
				const files = (ev.originalEvent.clipboardData && ev.originalEvent.clipboardData.files) || [];
				if (files.length && !note) {
					ev.preventDefault();
					this.handlers.onFile(files[0]);
				}
			});
			this.$el.find(".waba-attach-btn").on("click", (ev) => {
				ev.stopPropagation();
				this.toggle_attach();
			});
			this.$el.find(".waba-emoji-btn").on("click", (ev) => {
				ev.stopPropagation();
				this.toggle_emoji();
			});
			this.$el.find(".waba-quick-btn").on("click", (ev) => {
				ev.stopPropagation();
				this.toggle_quick();
			});
		}
		this.$el.find(".waba-ctab").on("click", (ev) => this.set_kind($(ev.currentTarget).data("kind")));
	}

	// ---- attach: device file, ERP document, shared library
	toggle_attach() {
		if (this.$attach && this.$attach.is(":visible")) return this.close_attach();
		this.close_emoji();
		this.close_quick();
		this.close_attach();
		this.$attach = $(`<div class="waba-attach" role="menu">
			<button class="waba-attach-item" data-act="device">${WabaLib.icon("upload", 17)}<span><b>${__("Device file")}</b><i>${__("Photo, PDF, document, audio or video")}</i></span></button>
			<button class="waba-attach-item" data-act="erp">${WabaLib.icon("file", 17)}<span><b>${__("ERP document")}</b><i>${__("Quotation, order, invoice or delivery note as PDF")}</i></span></button>
			<button class="waba-attach-item" data-act="library">${WabaLib.icon("folder", 17)}<span><b>${__("Shared library")}</b><i>${__("Approved brochures and price lists")}</i></span></button>
			<input type="file" class="waba-file-input" hidden accept="image/jpeg,image/png,video/mp4,video/3gpp,audio/*,application/pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.txt" /></div>`).appendTo(this.$el);
		const $input = this.$attach.find(".waba-file-input");
		$input.on("change", () => {
			const f = $input[0].files && $input[0].files[0];
			this.close_attach();
			if (f) this.handlers.onFile(f);
		});
		this.$attach.find(".waba-attach-item").on("click", (ev) => {
			const act = $(ev.currentTarget).data("act");
			if (act === "device") return $input.trigger("click");
			this.close_attach();
			if (act === "erp") this.handlers.onDocument();
			else this.handlers.onLibrary();
		});
		setTimeout(() => $(document).one("click.wabaattach", (ev) => {
			if (!$(ev.target).closest(".waba-attach").length) this.close_attach();
		}), 0);
	}

	close_attach() {
		if (this.$attach) this.$attach.remove();
		this.$attach = null;
		$(document).off("click.wabaattach");
	}

	// ---- quick replies: a panel above the box with a search field and the saved answers
	toggle_quick() {
		if (this.$quick && this.$quick.is(":visible")) return this.close_quick();
		this.close_emoji();
		this.close_quick();
		this.$quick = $(`<div class="waba-quick" role="dialog" aria-label="${__("Quick replies")}">
			<input class="waba-quick-q" type="search" placeholder="${__("Search quick replies")}" autocomplete="off" />
			<div class="waba-quick-list"><div class="waba-empty">${__("Loading...")}</div></div></div>`).appendTo(this.$el);
		const list = (items) =>
			this.$quick.find(".waba-quick-list").html(
				items.length
					? items.map((r, i) => `<button class="waba-quick-item" data-i="${i}"><b>${waba_e(r.title)}</b><span>${waba_e(r.body)}</span></button>`).join("")
					: `<div class="waba-empty">${__("No quick replies yet. Add them in the Waba workspace, Quick Replies.")}</div>`
			);
		let shown = [];
		const draw = (all, q) => {
			shown = WabaLib.filterQuickReplies(all, q);
			list(shown);
		};
		this.handlers.onQuick().then((all) => {
			if (!this.$quick) return;
			draw(all, "");
			this.$quick.find(".waba-quick-q").on("input", (ev) => draw(all, $(ev.currentTarget).val()));
		});
		this.$quick.on("click", ".waba-quick-item", (ev) => {
			const r = shown[$(ev.currentTarget).data("i")];
			if (r) this.insert(r.body);
			this.close_quick();
		});
		this.$quick.on("click", (ev) => ev.stopPropagation());
		$(document).one("click.waba_quick", () => this.close_quick());
		$(document).on("keydown.waba_quick", (ev) => ev.key === "Escape" && this.close_quick());
		this.$quick.find(".waba-quick-q").trigger("focus");
	}

	close_quick() {
		if (this.$quick) this.$quick.remove();
		this.$quick = null;
		$(document).off("click.waba_quick keydown.waba_quick");
	}

	// ---- emoji picker: a small panel above the box with a search field and category tabs
	toggle_emoji() {
		if (this.$emoji && this.$emoji.is(":visible")) return this.close_emoji();
		this.close_emoji();
		const groups = WabaLib.EMOJI_GROUPS;
		this.$emoji = $(`<div class="waba-emoji" role="dialog" aria-label="${__("Emoji")}">
			<input class="waba-emoji-q" type="search" placeholder="${__("Search emoji")}" autocomplete="off" />
			<div class="waba-emoji-tabs">${groups.map((g, i) => `<button class="waba-emoji-tab ${i === 0 ? "active" : ""}" data-i="${i}" title="${waba_e(g.name)}">${g.icon}</button>`).join("")}</div>
			<div class="waba-emoji-grid"></div></div>`).appendTo(this.$el);
		const grid = (items) =>
			this.$emoji.find(".waba-emoji-grid").html(items.map(([e, kw]) => `<button class="waba-emoji-item" title="${waba_e(kw)}">${e}</button>`).join("") || `<div class="waba-empty">${__("No emoji found")}</div>`);
		grid(groups[0].items);
		this.$emoji.find(".waba-emoji-tab").on("click", (ev) => {
			const i = $(ev.currentTarget).data("i");
			this.$emoji.find(".waba-emoji-tab").removeClass("active").filter(`[data-i="${i}"]`).addClass("active");
			this.$emoji.find(".waba-emoji-q").val("");
			grid(groups[i].items);
		});
		this.$emoji.find(".waba-emoji-q").on("input", (ev) => {
			const q = $(ev.currentTarget).val();
			grid(q.trim() ? WabaLib.emojiSearch(q) : groups[0].items);
		});
		this.$emoji.on("click", ".waba-emoji-item", (ev) => this.insert($(ev.currentTarget).text()));
		this.$emoji.on("click", (ev) => ev.stopPropagation());
		$(document).one("click.waba_emoji", () => this.close_emoji());
		$(document).on("keydown.waba_emoji", (ev) => ev.key === "Escape" && this.close_emoji());
		this.$emoji.find(".waba-emoji-q").trigger("focus");
	}

	close_emoji() {
		if (this.$emoji) this.$emoji.remove();
		this.$emoji = null;
		$(document).off("click.waba_emoji keydown.waba_emoji");
	}

	/** Put text at the cursor of the reply box (replacing any selection) and keep the box in focus. */
	insert(text) {
		if (!this.$text) return;
		const el = this.$text[0];
		const start = el.selectionStart ?? el.value.length;
		const end = el.selectionEnd ?? el.value.length;
		el.setRangeText(text, start, end, "end");
		this.drafts[this.kind] = el.value;
		this.autosize();
		this.$text.trigger("focus");
	}

	autosize() {
		const el = this.$text[0];
		el.style.height = "44px";
		el.style.height = Math.min(el.scrollHeight, 140) + "px";
	}

	submit() {
		const body = (this.$text.val() || "").trim();
		if (!body) return;
		this.$send.prop("disabled", true);
		const sent = this.kind === "note" ? this.handlers.onNote(body) : this.handlers.onSend(body);
		sent.then((ok) => {
			if (ok) {
				this.drafts[this.kind] = "";
				this.$text.val("");
				this.autosize();
			}
			this.$send.prop("disabled", false);
			this.$text.trigger("focus");
		});
	}
}

// ---------------------------------------------------------------------------------------------- thread

class WabaThread {
	constructor($parent, handlers) {
		this.handlers = handlers;
		this.name = null;
		this.data = null;
		this.expanded = false;
		this.older = []; // messages loaded by "Load earlier messages", kept across live refreshes
		this.older_notes = [];
		this.notes = [];
		this.messages = [];
		this.has_more = false;
		this.query = "";
		this.hit = -1;
		this.$el = $(`<section class="waba-thread"></section>`).appendTo($parent);
		this.placeholder();
	}

	placeholder() {
		this.name = null;
		this.data = null;
		if (this.composer) this.composer.close_emoji();
		this.composer = null;
		this.$el.html(`<div class="waba-placeholder">${WabaLib.brandMark(54)}<div>${__("Pick a conversation on the left.")}</div></div>`);
	}

	/** Show a conversation. A different one rebuilds the skeleton; the same one only refreshes its parts. */
	show(data, opts = {}) {
		const c = data.conversation;
		const fresh = this.name !== c.name;
		this.data = data;
		if (fresh) {
			this.name = c.name;
			this.expanded = false;
			this.older = [];
			this.older_notes = [];
			this.has_more = data.has_more;
			this.query = "";
			this.hit = -1;
			this.divider_at = null;
			this.divider_n = 0;
			this.unseen = 0;
			this.last_count = 0;
			this.$el.html(`<div class="waba-th-head"></div><div class="waba-banner"></div><div class="waba-findbar" hidden></div><div class="waba-messages"></div><button class="waba-jump" hidden>${WabaLib.icon("arrowdown", 16)}<span></span></button>`);
			this.$head = this.$el.find(".waba-th-head");
			this.$banner = this.$el.find(".waba-banner");
			this.$find = this.$el.find(".waba-findbar");
			this.$messages = this.$el.find(".waba-messages");
			this.composer = new WabaComposer(
				this.$el,
				{
					onSend: (body) => this.handlers.onSend(body),
					onNote: (body) => this.handlers.onNote(body),
					onQuick: () => this.handlers.onQuick(),
					onTemplate: () => this.handlers.onTemplate(),
					onFile: (file) => this.handlers.onFile(file),
					onDocument: () => this.handlers.onDocument(),
					onLibrary: () => this.handlers.onLibrary(),
				},
				this.handlers.draftsFor(c.name)
			);
			this.$jump = this.$el.find(".waba-jump").on("click", () => this.scroll_latest());
			this.$messages.on("scroll", () => this.on_scroll());
			this.$el.on("dragover", (ev) => {
				if (this.composer && this.composer.mode === "open") ev.preventDefault();
			});
			this.$el.on("drop", (ev) => {
				const files = ev.originalEvent.dataTransfer && ev.originalEvent.dataTransfer.files;
				if (files && files.length && this.composer && this.composer.mode === "open") {
					ev.preventDefault();
					this.handlers.onFile(files[0]);
				}
			});
		}
		if (!fresh && !this.older.length) this.has_more = data.has_more;
		this.merge();
		if (fresh) {
			this.divider_n = c.unread_count || 0;
			this.divider_at = WabaLib.firstUnread(this.messages, this.divider_n); // where "N new messages" starts, kept while the chat stays open
		}
		this.render_head();
		this.render_banner();
		this.render_messages(fresh || opts.stick);
		this.composer.set_mode(!c.window_open ? "closed" : c.can_reply_by_phone ? "open" : "no_phone");
	}

	/** The latest page from the server plus any older pages the user loaded, oldest first, each message once. */
	merge() {
		const latest = this.data.messages;
		const ids = new Set(latest.map((m) => m.name));
		this.messages = this.older.filter((m) => !ids.has(m.name)).concat(latest);
		const noteIds = new Set((this.data.notes || []).map((n) => n.name));
		this.notes = this.older_notes.filter((n) => !noteIds.has(n.name)).concat(this.data.notes || []);
	}

	oldest_time() {
		return this.messages.length ? this.messages[0].sent_at : null;
	}

	/** Add an older page (oldest first) in front and keep the reader where they were. */
	add_older(rows, has_more, notes) {
		const box = this.$messages[0];
		const heightBefore = box.scrollHeight;
		const topBefore = box.scrollTop;
		const known = new Set(this.messages.map((m) => m.name));
		this.older = rows.filter((m) => !known.has(m.name)).concat(this.older);
		const knownNotes = new Set(this.notes.map((n) => n.name));
		this.older_notes = (notes || []).filter((n) => !knownNotes.has(n.name)).concat(this.older_notes);
		this.has_more = has_more;
		this.merge();
		this.render_messages(false, true);
		box.scrollTop = box.scrollHeight - heightBefore + topBefore;
	}

	render_head() {
		const c = this.data.conversation;
		const lines = WabaLib.customerLines({ ...c, name: c.name });
		const party =
			c.party_doctype && c.party
				? `<a class="waba-th-record" href="${frappe.utils.get_form_link(c.party_doctype, c.party)}">${WabaLib.icon("link", 14)}${waba_e(c.party_doctype)}: ${waba_e(c.party)}</a>`
				: `<span class="waba-chip orange" style="margin-top:4px">${__("Not in the ERP yet")}</span>`;
		const assignee = c.assigned_to
			? `<div class="waba-th-assign">${WabaLib.icon("user", 13)}${__("Assigned to {0}", [waba_e(c.assigned_name || c.assigned_to)])}${c.assigned_reason ? ` <span class="waba-why">· ${waba_e(c.assigned_reason)}</span>` : ""}</div>`
			: `<div class="waba-th-assign waiting">${WabaLib.icon("clock", 13)}${c.waiting ? __("Waiting for an agent") : __("Not assigned")}</div>`;
		const env = c.environment && c.environment !== "Production" ? `<span class="waba-env">${waba_e(c.environment)}</span>` : "";
		this.$head.html(`
			<button class="waba-iconbtn waba-back" aria-label="${__("Back")}">${WabaLib.icon("back", 20)}</button>
			<span class="waba-avatar lg" style="background:${WabaLib.avatarColor(lines.name)}">${waba_e(WabaLib.initials(lines.name))}</span>
			<div class="waba-th-id">
				<div class="waba-th-name"><span>${waba_e(lines.name)}</span>${c.match_state === "Matched" ? WabaLib.verifiedBadge(17) : ""}${env}</div>
				${lines.sub ? `<div class="waba-th-phone">${waba_e(lines.sub)}</div>` : ""}
				${party}
				${assignee}
			</div>
			<div class="waba-th-actions">
				${c.can_transfer ? `<button class="waba-btn waba-transfer-btn" title="${__("Hand this conversation to another agent")}">${WabaLib.icon("transfer", 15)}<span class="waba-btn-text">${__("Transfer")}</span></button>
				<button class="waba-btn waba-status-btn" title="${c.status === "Done" ? __("Reopen") : __("Mark done")}">${WabaLib.icon(c.status === "Done" ? "undo" : "done", 15)}<span class="waba-btn-text">${c.status === "Done" ? __("Reopen") : __("Mark done")}</span></button>` : ""}
				<button class="waba-btn waba-btn-secondary waba-open-record" title="${__("Open Record")}">${WabaLib.icon("external", 15)}<span class="waba-btn-text">${__("Open Record")}</span></button>
				<button class="waba-btn waba-btn-secondary waba-template-btn" title="${__("Send Template")}">${WabaLib.icon("send", 15)}<span class="waba-btn-text">${__("Send Template")}</span></button>
				<button class="waba-iconbtn waba-more-btn" aria-label="${__("More actions")}">${WabaLib.icon("more", 20)}</button>
			</div>`);
		this.$head.find(".waba-back").on("click", () => this.handlers.onBack());
		this.$head.find(".waba-open-record").on("click", () => this.handlers.onOpenRecord());
		this.$head.find(".waba-template-btn").on("click", () => this.handlers.onTemplate());
		this.$head.find(".waba-transfer-btn").on("click", () => this.handlers.onTransfer());
		this.$head.find(".waba-status-btn").on("click", () => this.handlers.onStatus(c.status === "Done" ? "Open" : "Done"));
		this.$head.find(".waba-more-btn").on("click", (ev) => this.handlers.onMore($(ev.currentTarget)));
	}

	render_banner() {
		const c = this.data.conversation;
		const left = c.window_open ? WabaLib.timeLeft(frappe.datetime.str_to_obj(c.window_expires_at)) : null;
		let kind = "closed";
		let line;
		let detail;
		if (c.status === "Done") {
			kind = "done";
			line = `<b>${__("Marked done.")}</b> ${__("A new message from the customer reopens it.")}`;
			detail = __("The 24-hour window still follows the customer's last message.");
		} else if (left) {
			kind = "open";
			line = `<b>${__("Window open: {0} left.", [left])}</b> ${__("Any message can be sent.")}`;
			detail = __("The window closes on {0}. After that only approved templates can be sent, and it opens again whenever the customer writes.", [frappe.datetime.str_to_user(c.window_expires_at)]);
		} else {
			line = `<b>${__("Window closed.")}</b> ${__("Only an approved template can be sent.")}`;
			detail = __("WhatsApp allows free-text replies only within 24 hours of the customer's last message. Send an approved template; when the customer replies, the window opens again.");
		}
		this.$banner
			.attr("class", `waba-banner ${kind} ${this.expanded ? "expanded" : ""}`)
			.html(`<div class="waba-banner-line">${WabaLib.brandMark(22)}<span class="waba-grow">${line}</span><span class="waba-dot"></span><button class="waba-chev" aria-label="${__("Details")}">${WabaLib.icon("chevron", 16)}</button></div><div class="waba-banner-detail">${waba_e(detail)}</div>`);
		this.$banner.find(".waba-chev").on("click", () => {
			this.expanded = !this.expanded;
			this.$banner.toggleClass("expanded", this.expanded);
		});
	}

	render_messages(stick, keepPosition) {
		const box = this.$messages[0];
		const nearBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 90;
		const previousTop = box.scrollTop;
		let lastDay = null;
		const earlier = this.has_more
			? `<div class="waba-earlier-wrap"><button class="waba-more waba-earlier">${WabaLib.icon("arrowup", 15)}${__("Load earlier messages")}</button></div>`
			: "";
		const html = WabaLib.timeline(this.messages, this.notes)
			.map((item) => {
				const day = WabaLib.dayLabel(item.at);
				const sep = day && day !== lastDay ? `<div class="waba-day"><span>${waba_e(day)}</span></div>` : "";
				lastDay = day || lastDay;
				if (item.type === "message") {
					const divider = item.data.name === this.divider_at ? `<div class="waba-unread-div"><span>${this.divider_n === 1 ? __("1 new message") : __("{0} new messages", [this.divider_n])}</span></div>` : "";
					return sep + divider + this.message_html(item.data);
				}
				return sep + (item.type === "event" ? this.event_html(item.data) : this.note_html(item.data));
			})
			.join("");
		this.$messages.html(earlier + (html || `<div class="waba-day"><span>${__("No messages yet")}</span></div>`));
		this.$messages.find(".waba-earlier").on("click", (ev) => {
			$(ev.currentTarget).prop("disabled", true);
			this.handlers.onEarlier(this.oldest_time());
		});
		this.$messages.find(".waba-quote").on("click", (ev) => this.jump_to($(ev.currentTarget).data("ref")));
		this.bind_message_actions();
		if (this.query) this.collect_hits();
		const count = this.messages.length;
		if (keepPosition) {
			this.last_count = count;
			return;
		}
		if (stick || nearBottom) {
			box.scrollTop = box.scrollHeight;
			this.unseen = 0;
		} else {
			box.scrollTop = previousTop;
			if (count > this.last_count) this.unseen += count - this.last_count; // new messages arrived while reading older ones
		}
		this.last_count = count;
		this.on_scroll();
	}

	/** The "jump to latest" pill: shown when scrolled well above the end, with how many new messages came meanwhile. */
	on_scroll() {
		if (!this.$jump) return;
		const box = this.$messages[0];
		const away = box.scrollHeight - box.scrollTop - box.clientHeight;
		if (away < 160) this.unseen = 0;
		this.$jump.prop("hidden", away < 160);
		this.$jump.find("span").text(this.unseen ? __("{0} new", [this.unseen]) : __("Latest"));
	}

	scroll_latest() {
		const box = this.$messages[0];
		box.scrollTo({ top: box.scrollHeight, behavior: "smooth" });
		this.unseen = 0;
	}

	bind_message_actions() {
		const $m = this.$messages;
		$m.find(".waba-media-open").on("click", (ev) => {
			ev.preventDefault();
			this.lightbox($(ev.currentTarget).attr("href"));
		});
		$m.find(".waba-media-retry").on("click", (ev) => this.handlers.onMediaRetry($(ev.currentTarget).data("id")));
		$m.find(".waba-retry").on("click", (ev) => {
			$(ev.currentTarget).prop("disabled", true);
			this.handlers.onRetry($(ev.currentTarget).data("id"));
		});
		$m.find(".waba-react-btn").on("click", (ev) => {
			ev.stopPropagation();
			this.react_picker($(ev.currentTarget));
		});
	}

	lightbox(src) {
		$(".waba-lightbox").remove();
		const $box = $(`<div class="waba-lightbox" role="dialog"><button class="waba-lightbox-x" aria-label="${__("Close")}">${WabaLib.icon("x", 22)}</button><img alt="" /></div>`).appendTo(document.body);
		$box.find("img").attr("src", src);
		const close = () => {
			$box.remove();
			$(document).off("keydown.wabalightbox");
		};
		$box.on("click", close);
		$(document).on("keydown.wabalightbox", (ev) => ev.key === "Escape" && close());
	}

	react_picker($anchor) {
		$(".waba-react-pop").remove();
		const id = $anchor.data("id");
		const $pop = $(`<div class="waba-react-pop">${["👍", "❤️", "😂", "😮", "🙏", "✅"].map((e) => `<button data-e="${e}">${e}</button>`).join("")}<button data-e="" title="${__("Remove my reaction")}">${WabaLib.icon("x", 14)}</button></div>`).appendTo(document.body);
		const r = $anchor[0].getBoundingClientRect();
		$pop.css({ top: Math.max(8, r.top - 46) + "px", left: Math.max(8, Math.min(window.innerWidth - 270, r.left - 100)) + "px" });
		$pop.find("button").on("click", (ev) => {
			this.handlers.onReact(id, String($(ev.currentTarget).data("e") || ""));
			$pop.remove();
		});
		setTimeout(() => $(document).one("click.wabareact", () => $pop.remove()), 0);
	}

	/** What goes inside the bubble: the file, place or contact cards when there are any, then the text. */
	content_html(m) {
		const mv = WabaLib.mediaView(m);
		const place = WabaLib.placeFor(m);
		const cards = m.message_type === "contacts" ? WabaLib.contactsFor(m) : [];
		const format = (text) => WabaLib.waFormat(WabaLib.highlight(WabaLib.linkify(text || ""), this.query));
		let out = "";
		let text = m.body || "";
		if (mv && mv.state !== "none") {
			out += this.media_html(mv, m);
			text = mv.caption;
		} else if (place) {
			const label = String(m.body || "").replace(/^\[location\]\s*/, "").replace(/https?:\/\/\S+$/, "").trim();
			out += `<a class="waba-place" href="${waba_e(place.url)}" target="_blank" rel="noopener noreferrer">${WabaLib.icon("pin", 20)}<span><b>${__("Location")}</b><i>${waba_e(label || `${place.lat.toFixed(5)}, ${place.lon.toFixed(5)}`)}</i></span>${WabaLib.icon("external", 14)}</a>`;
			text = "";
		} else if (cards.length) {
			out += cards.map((c) => `<div class="waba-contact">${WabaLib.icon("contact", 20)}<span><b>${waba_e(c.name || __("Contact"))}</b><i>${waba_e(c.phones.join(", "))}</i></span></div>`).join("");
			text = "";
		} else if (m.direction === "In") {
			const note = WabaLib.kindNote(m.message_type, m.body);
			if (note) return `<span class="waba-kindnote">${waba_e(__(note.label))} (${__("not shown")})</span>${note.rest ? " " + format(note.rest) : ""}`;
		}
		return out + (text ? `<div class="waba-caption">${format(text)}</div>` : "");
	}

	media_html(mv, m) {
		const pick = { image: "image", sticker: "image", video: "play", audio: "mic", document: "file" }[mv.kind];
		if (mv.state === "pending") return `<div class="waba-media-wait">${WabaLib.icon(pick, 18)}<span>${__("Fetching the file...")}</span></div>`;
		if (mv.state === "failed")
			return `<div class="waba-media-wait failed">${WabaLib.icon("warning", 18)}<span>${__("The file could not be fetched")}${mv.error ? ": " + waba_e(mv.error) : ""} <button class="waba-link waba-media-retry" data-id="${waba_e(m.name)}">${__("Try again")}</button></span></div>`;
		const url = waba_e(mv.url);
		if (mv.kind === "image" || mv.kind === "sticker")
			return `<a class="waba-media-open" href="${url}"><img class="waba-media-img ${mv.kind === "sticker" ? "sticker" : ""}" src="${url}" alt="${waba_e(mv.name || __("Photo"))}" loading="lazy" /></a>`;
		if (mv.kind === "video") return `<video class="waba-media-video" controls preload="metadata" src="${url}"></video>`;
		if (mv.kind === "audio") return `<div class="waba-media-audio">${WabaLib.icon(mv.voice ? "mic" : "play", 18)}<audio controls preload="none" src="${url}"></audio></div>`;
		return `<a class="waba-doc" href="${waba_e(mv.downloadUrl)}" target="_blank" rel="noopener noreferrer">${WabaLib.icon("file", 24)}<span><b>${waba_e(mv.name || __("Document"))}</b><i>${waba_e([mv.size, (mv.mime.split("/")[1] || "").toUpperCase()].filter(Boolean).join(" · "))}</i></span>${WabaLib.icon("download", 17)}</a>`;
	}

	/** Scroll ONLY the message list so that `el` is in the middle. (the browser's scroll-into-view call would also scroll the page around it.) */
	center(el) {
		const box = this.$messages[0];
		const b = box.getBoundingClientRect();
		const r = el.getBoundingClientRect();
		box.scrollTo({ top: box.scrollTop + (r.top - b.top) - box.clientHeight / 2 + r.height / 2, behavior: "smooth" });
	}

	/** Scroll to the message a reply refers to (when it is among the loaded ones) and flash it. */
	jump_to(messageId) {
		const $m = this.$messages.find(`.waba-msg[data-mid="${String(messageId).replace(/"/g, "")}"]`);
		if (!$m.length) {
			frappe.show_alert({ message: __("The original message is older; load earlier messages first."), indicator: "orange" }, 5);
			return;
		}
		this.center($m[0]);
		$m.addClass("flash");
		setTimeout(() => $m.removeClass("flash"), 1600);
	}

	// ---- search inside the conversation (loaded messages; "Load earlier" widens it)
	open_search() {
		this.$find.prop("hidden", false).html(`
			${WabaLib.icon("search", 16)}
			<input type="search" placeholder="${__("Search in this conversation")}" autocomplete="off" />
			<span class="waba-find-count"></span>
			<button class="waba-iconbtn waba-find-prev" aria-label="${__("Previous match")}">${WabaLib.icon("arrowup", 16)}</button>
			<button class="waba-iconbtn waba-find-next" aria-label="${__("Next match")}">${WabaLib.icon("arrowdown", 16)}</button>
			<button class="waba-iconbtn waba-find-close" aria-label="${__("Close search")}">${WabaLib.icon("x", 16)}</button>`);
		const $q = this.$find.find("input").val(this.query);
		$q.on("input", frappe.utils.debounce(() => this.set_query($q.val()), 200));
		$q.on("keydown", (ev) => {
			if (ev.key === "Enter") {
				ev.preventDefault();
				this.step(ev.shiftKey ? -1 : 1);
			} else if (ev.key === "Escape") this.close_search();
		});
		this.$find.find(".waba-find-prev").on("click", () => this.step(-1));
		this.$find.find(".waba-find-next").on("click", () => this.step(1));
		this.$find.find(".waba-find-close").on("click", () => this.close_search());
		$q.trigger("focus");
	}

	close_search() {
		this.query = "";
		this.hit = -1;
		this.$find.prop("hidden", true).empty();
		this.render_messages(false, true);
	}

	set_query(text) {
		this.query = (text || "").trim();
		this.hit = -1;
		this.render_messages(false, true);
		if (this.hits && this.hits.length) this.step(1);
	}

	collect_hits() {
		this.hits = this.$messages.find("mark").toArray();
		const n = this.hits.length;
		const label = !this.query ? "" : !n ? __("No matches") : this.hit >= 0 ? `${this.hit + 1} / ${n}` : __("{0} found", [n]);
		this.$find.find(".waba-find-count").text(label);
		if (this.hit >= 0 && this.hits[this.hit]) $(this.hits[this.hit]).addClass("current");
	}

	step(direction) {
		if (!this.hits || !this.hits.length) return;
		$(this.hits[this.hit]).removeClass("current");
		this.hit = (this.hit + direction + this.hits.length) % this.hits.length;
		const el = this.hits[this.hit];
		$(el).addClass("current");
		this.center(el);
		this.$find.find(".waba-find-count").text(`${this.hit + 1} / ${this.hits.length}`);
	}

	event_html(n) {
		return `<div class="waba-event" data-note="${waba_e(n.name)}"><span>${WabaLib.highlight(waba_e(n.body), "")}</span></div>`;
	}

	note_html(n) {
		const text = WabaLib.highlight(WabaLib.linkify(n.body || ""), this.query);
		return `<div class="waba-msg note" data-note="${waba_e(n.name)}"><div class="waba-bubble note"><div class="waba-sender">${WabaLib.icon("note", 12)}${__("Note")} · ${waba_e(n.user_name || n.user || "")}</div><div class="waba-text">${text}</div>
			<div class="waba-foot"><span class="waba-foot-right"><span>${waba_e(WabaLib.clockLabel(n.creation))}</span></span></div></div></div>`;
	}

	message_html(m) {
		const out = m.direction === "Out";
		const failed = m.status === "Failed";
		const tick = out ? WabaLib.tickFor(m.status) : null;
		const tag = m.template_title ? `<div class="waba-tag">${WabaLib.icon("send", 12)}${__("Template")}: ${waba_e(m.template_title)}</div>` : "";
		const senderName = out ? waba_e(m.sent_by_name || __("Sent")) : "";
		const sender = out && !failed ? `<div class="waba-sender">${senderName}</div>` : "";
		const err = failed
			? `<div class="waba-errorbox">${WabaLib.icon("warning", 15)}<span>${__("Not delivered")}: ${waba_e(m.error_message || __("Meta did not accept this message."))}${WabaLib.canRetry(m) ? ` <button class="waba-link waba-retry" data-id="${waba_e(m.name)}">${__("Send again")}</button>` : ""}</span></div>`
			: "";
		const tickHtml = tick ? `<span class="waba-tick ${tick.tone}" title="${waba_e(__(tick.label))}">${WabaLib.icon(tick.icon, 16)}</span>` : "";
		const quote = m.reply_to_message_id
			? `<div class="waba-quote" data-ref="${waba_e(m.reply_to_message_id)}"><b>${waba_e(m.reply_to_sender || (m.reply_to_direction === "Out" ? __("You") : __("Customer")))}</b><span>${waba_e(m.reply_to_body || __("Original message"))}</span></div>`
			: "";
		const text = this.content_html(m);
		const react_on = m.direction === "In" && m.message_id && this.data && this.data.conversation && this.data.conversation.window_open;
		const react_btn = react_on ? `<button class="waba-react-btn" data-id="${waba_e(m.name)}" title="${__("React")}" aria-label="${__("React")}">${WabaLib.icon("smile", 14)}</button>` : "";
		const chips = WabaLib.reactionsFor(m).map((r) => `<span class="waba-chip" title="${waba_e(__(r.who))}">${waba_e(r.emoji)}</span>`).join("");
		const info = [m.sent_at && `${__("Sent")} ${m.sent_at}`, m.delivered_at && `${__("Delivered")} ${m.delivered_at}`, m.read_at && `${__("Read")} ${m.read_at}`].filter(Boolean).join(" · ");
		return `<div class="waba-msg ${out ? "out" : "in"} ${failed ? "failed" : ""}" data-id="${waba_e(m.name)}" data-mid="${waba_e(m.message_id || "")}">
			<div class="waba-bubble">${react_btn}${sender}${tag}${quote}<div class="waba-text">${text}</div>${chips ? `<div class="waba-reacts">${chips}</div>` : ""}${err}
				<div class="waba-foot">${failed ? `<span class="waba-foot-name">${senderName}</span>` : ""}<span class="waba-foot-right"><span title="${waba_e(info)}">${waba_e(WabaLib.clockLabel(m.sent_at))}</span> ${tickHtml}</span></div></div></div>`;
	}
}

// ---------------------------------------------------------------------------------------------- the page

class WabaInbox {
	constructor(page, wrapper) {
		this.page = page;
		this.wrapper = wrapper;
		this.current = null;
		this.drafts = {}; // what was typed per conversation, kept while the page is open
		this.number = "";
		this.search = "";
		this.$shell = $(`<div class="waba-shell"><div class="waba-inbox"></div></div>`);
		$(page.main).empty().append(this.$shell);
		this.toolbar = new WabaToolbar(this.$shell, {
			onNumber: (number) => {
				this.number = number;
				this.load_list();
			},
			onSearch: (text) => {
				this.search = text;
				this.load_list();
			},
			onRefresh: () => this.refresh(),
			onAvailable: (value) => this.set_available(value),
			onNumbers: (rows) => {
				if (this.list) {
					this.list.numbers_known = rows;
					this.list.render();
				}
			},
		});
		this.$shell.prepend(this.toolbar.$el);
		this.$panels = this.$shell.find(".waba-inbox");
		this.list = new WabaList(this.$panels, {
			onTab: () => this.load_list(),
			onScope: () => {
				this.load_list();
				this.refresh_counts();
			},
			onOpen: (name) => this.open_thread(name),
			onMore: () => this.load_list(false),
		});
		this.thread = new WabaThread(this.$panels, {
			onBack: () => this.close_thread(),
			onSend: (body) => this.send("send_text", { body }),
			onNote: (body) => this.add_note(body),
			onQuick: () => this.quick_replies(),
			onTransfer: () => this.transfer_dialog(),
			onStatus: (status) => this.set_status(status),
			onTemplate: () => this.template_dialog(),
			onFile: (file) => this.file_dialog(file),
			onDocument: () => this.document_dialog(),
			onLibrary: () => this.library_dialog(),
			onReact: (id, emoji) => this.react(id, emoji),
			onRetry: (id) => this.retry_message(id),
			onMediaRetry: (id) => this.retry_media(id),
			draftsFor: (name) => (this.drafts[name] = this.drafts[name] || { reply: "", note: "" }),
			onEarlier: (before) => this.load_earlier(before),
			onOpenRecord: () => this.open_record(),
			onMore: ($anchor) => this.more_menu($anchor),
		});
		$(document).off("waba:open").on("waba:open", (ev, name) => name && this.open_thread(name));
		this.reload_soon = frappe.utils.debounce(() => this.on_event(), 400);
		frappe.realtime.on("waba_inbox", (data) => {
			this.pending = data || {};
			this.reload_soon();
		});
	}

	// ---------------------------------------------------------------- lifecycle

	publish_state() {
		window.waba_inbox_state = { visible: !!this.shown, current: this.current };
	}

	show() {
		this.shown = true;
		this.refresh();
		this.publish_state();
		if (window.waba_open_conversation) {
			const wanted = window.waba_open_conversation;
			window.waba_open_conversation = null;
			this.open_thread(wanted);
		}
		clearInterval(this.timer);
		// a safety net if the realtime connection drops; it also keeps the "time left" text honest
		this.timer = setInterval(() => {
			this.refresh_counts();
			if (this.thread.data) this.thread.render_banner();
		}, 30000);
		$(document).off("keydown.waba_inbox").on("keydown.waba_inbox", (ev) => {
			const tag = (ev.target.tagName || "").toLowerCase();
			if (ev.key === "/" && !ev.ctrlKey && !ev.metaKey && !["input", "textarea", "select"].includes(tag) && !ev.target.isContentEditable) {
				ev.preventDefault();
				this.toolbar.focus_search();
			}
		});
	}

	hide() {
		this.shown = false;
		this.publish_state();
		clearInterval(this.timer);
		$(document).off("keydown.waba_inbox");
	}

	refresh() {
		this.load_list();
		this.refresh_counts();
		if (this.current) this.open_thread(this.current, { quiet: true });
	}

	on_event() {
		const data = this.pending || {};
		this.load_list();
		this.refresh_counts();
		if (this.current && (!data.conversation || data.conversation === this.current)) this.open_thread(this.current, { quiet: true });
	}

	// ---------------------------------------------------------------- list

	refresh_counts() {
		frappe
			.call({ method: "waba.api.inbox.summary", args: { number: this.number || null, scope: this.list.scope }, silent: true })
			.then((r) => {
				const counts = r.message || {};
				this.list.set_counts(counts);
				this.toolbar.set_available(counts.available);
				this.page_can_oversee = !!counts.can_oversee;
			});
	}

	load_list(reset = true) {
		const start = reset ? 0 : this.list.rows.length;
		return frappe
			.call({
				method: "waba.api.inbox.conversations",
				args: { view: this.list.view, scope: this.list.scope, number: this.number || null, search: this.search || null, start, limit: 30 },
				silent: true,
			})
			.then((r) => {
				const out = r.message || { rows: [], has_more: false };
				this.list.set_rows(reset ? out.rows : this.list.rows.concat(out.rows), out.has_more);
				this.list.select(this.current);
			});
	}

	// ---------------------------------------------------------------- thread

	open_thread(name, opts = {}) {
		const changed = this.current !== name;
		this.current = name;
		this.publish_state();
		this.$panels.addClass("show-thread");
		this.$shell.addClass("thread-open");
		return frappe
			.call({
				method: "waba.api.inbox.thread",
				args: { conversation: name },
				silent: true,
				error: () => {
					// no longer allowed to see it (it was transferred away): leave the chat quietly, the list refresh drops the row
					if (this.current === name) this.close_thread();
					this.load_list();
				},
			})
			.then((r) => {
				if (!r || !r.message || this.current !== name) return; // another conversation was opened meanwhile, or no access
				this.thread.show(r.message, { stick: changed });
				this.list.select(name);
				if (r.message.conversation.unread_count > 0) this.mark_read(name);
			});
	}

	load_earlier(before) {
		const name = this.current;
		return frappe.call({ method: "waba.api.inbox.thread", args: { conversation: name, before }, silent: true }).then((r) => {
			if (this.current !== name || !r.message) return;
			this.thread.add_older(r.message.messages, r.message.has_more, r.message.notes);
		});
	}

	close_thread() {
		this.current = null;
		this.publish_state();
		this.$panels.removeClass("show-thread");
		this.$shell.removeClass("thread-open");
		this.thread.placeholder();
		this.list.select(null);
	}

	mark_read(name) {
		return frappe.call({ method: "waba.api.send.mark_read", args: { conversation: name }, silent: true }).then(() => {
			this.list.clear_unread(name);
			this.list.select(this.current);
			this.refresh_counts();
		});
	}

	conversation() {
		return this.thread.data && this.thread.data.conversation;
	}

	open_record() {
		const c = this.conversation();
		if (!c) return;
		if (c.party_doctype && c.party) frappe.set_route("Form", c.party_doctype, c.party);
		else frappe.set_route("Form", "Waba Conversation", c.name);
	}

	more_menu($anchor) {
		const c = this.conversation();
		if (!c) return;
		const items = [];
		if (c.unread_count > 0) items.push({ icon: "check", label: __("Mark as read"), run: () => this.mark_read(c.name) });
		if (c.customer_phone) {
			items.push({ icon: "copy", label: __("Copy phone number"), run: () => frappe.utils.copy_to_clipboard(c.customer_phone) });
		}
		items.push({ icon: "search", label: __("Search in conversation"), run: () => this.thread.open_search() });
		items.push({ icon: "external", label: __("Open conversation record"), run: () => frappe.set_route("Form", "Waba Conversation", c.name) });
		const alerts = window.waba_alerts;
		if (alerts) {
			const prefs = alerts.prefs();
			items.push({ icon: "bell", label: __("Sound alerts: {0}", [prefs.sound ? __("On") : __("Off")]), run: () => alerts.set({ sound: !prefs.sound }) });
			items.push({
				icon: "bell",
				label: __("Desktop notifications: {0}", [prefs.desktop ? __("On") : __("Off")]),
				run: () => (prefs.desktop ? alerts.set({ desktop: false }) : alerts.enable_desktop()),
			});
		}
		$(".waba-pop.waba-menu").remove();
		const $menu = $(`<div class="waba-pop waba-menu" style="position:fixed"></div>`).html(
			items.map((i, n) => `<button class="waba-pop-item" data-n="${n}">${WabaLib.icon(i.icon, 16)}<span>${waba_e(i.label)}</span></button>`).join("")
		);
		this.$shell.append($menu);
		const rect = $anchor[0].getBoundingClientRect();
		$menu.css({ top: rect.bottom + 6, left: Math.max(8, rect.right - 240), minWidth: 240 });
		$menu.find(".waba-pop-item").on("click", (ev) => {
			items[$(ev.currentTarget).data("n")].run();
			$menu.remove();
		});
		setTimeout(() => $(document).one("click.waba_menu", () => $menu.remove()), 0);
	}

	// ---------------------------------------------------------------- teamwork

	set_available(value) {
		return frappe.call({ method: "waba.api.inbox.set_available", args: { available: value ? 1 : 0 }, silent: true }).then((r) => {
			const now = r.message && r.message.available;
			this.toolbar.set_available(now);
			frappe.show_alert({ message: now ? __("You are available: new conversations can come to you.") : __("You are away: you get no new conversations."), indicator: now ? "green" : "orange" }, 4);
			this.refresh_counts();
		});
	}

	add_note(body) {
		return frappe
			.call({ method: "waba.api.inbox.add_note", args: { conversation: this.current, body }, freeze: false })
			.then((r) => {
				if (!r.message) return false;
				this.open_thread(this.current, { quiet: true });
				return true;
			})
			.catch(() => false);
	}

	quick_replies() {
		if (this.qr) return Promise.resolve(this.qr);
		return frappe.call({ method: "waba.api.inbox.quick_replies", silent: true }).then((r) => {
			this.qr = r.message || [];
			setTimeout(() => (this.qr = null), 60000); // a minute, so a new reply shows up soon after it is saved
			return this.qr;
		});
	}

	set_status(status) {
		const c = this.conversation();
		if (!c) return;
		frappe.call({ method: "waba.api.inbox.set_status", args: { conversation: c.name, status } }).then(() => {
			this.open_thread(c.name, { quiet: true });
			this.load_list();
			this.refresh_counts();
		});
	}

	transfer_dialog() {
		const c = this.conversation();
		if (!c) return;
		frappe.call({ method: "waba.api.inbox.transfer_targets", args: { conversation: c.name } }).then((r) => {
			const people = (r.message || []).filter((p) => !p.is_current);
			if (!people.length) {
				frappe.msgprint(__("Nobody else works this number. Add agents on the number first."));
				return;
			}
			const label = (p) => `${p.full_name}${p.available ? "" : " (" + __("away") + ")"}, ${__("{0} open", [p.open])}`;
			const byLabel = Object.fromEntries(people.map((p) => [label(p), p.user]));
			const dialog = new frappe.ui.Dialog({
				title: __("Transfer {0}", [c.customer_label]),
				fields: [
					{
						fieldname: "to",
						label: __("Hand over to"),
						fieldtype: "Select",
						// one person: chosen for you; several: the box starts empty so the choice is deliberate
						options: (people.length > 1 ? [""] : []).concat(Object.keys(byLabel)).join("\n"),
						default: people.length === 1 ? Object.keys(byLabel)[0] : "",
						reqd: 1,
					},
					{ fieldname: "note", label: __("Note for them"), fieldtype: "Small Text", reqd: 1, description: __("What they need to know. Only your team sees it.") },
				],
				primary_action_label: __("Transfer"),
				primary_action: (values) => {
					dialog.hide();
					frappe
						.call({ method: "waba.api.inbox.transfer", args: { conversation: c.name, to_user: byLabel[values.to], note: values.note } })
						.then(() => {
							frappe.show_alert({ message: __("Transferred."), indicator: "green" }, 4);
							this.open_thread(c.name, { quiet: true });
							this.load_list();
							this.refresh_counts();
						});
				},
			});
			dialog.show();
		});
	}

	// ---------------------------------------------------------------- sending

	send(method, args) {
		return frappe
			.call({ method: `waba.api.send.${method}`, args: { conversation: this.current, ...args }, freeze: false })
			.then((r) => {
				const out = r.message || {};
				if (out.error) frappe.msgprint({ title: __("Not sent"), message: out.error, indicator: "red" });
				this.open_thread(this.current, { quiet: true });
				this.load_list();
				return !!out.ok;
			})
			.catch(() => false);
	}

	// ---- files: device upload with a preview, ERP documents, the shared library

	/** Upload to a private file (Frappe's own endpoint); resolves with the File's data. */
	upload_private(file) {
		return new Promise((resolve, reject) => {
			const form = new FormData();
			form.append("file", file, file.name);
			form.append("is_private", "1");
			form.append("folder", "Home");
			const xhr = new XMLHttpRequest();
			xhr.open("POST", "/api/method/upload_file");
			xhr.setRequestHeader("X-Frappe-CSRF-Token", frappe.csrf_token);
			xhr.setRequestHeader("Accept", "application/json");
			xhr.onload = () => {
				let body = {};
				try {
					body = JSON.parse(xhr.responseText);
				} catch (e) {}
				if (xhr.status >= 200 && xhr.status < 300 && body.message && body.message.file_url) return resolve(body.message);
				let why = "";
				try {
					why = JSON.parse(JSON.parse(body._server_messages || "[]")[0] || "{}").message || "";
				} catch (e) {}
				reject(new Error(why.replace(/<[^>]+>/g, "") || __("The upload was refused.")));
			};
			xhr.onerror = () => reject(new Error(__("The upload could not be sent. Check your connection.")));
			xhr.send(form);
		});
	}

	file_dialog(file) {
		const check = WabaLib.checkUpload(file.type, file.size);
		if (!check.ok) {
			frappe.msgprint({ title: __("This file cannot be sent"), message: waba_e(check.message), indicator: "red" });
			return;
		}
		const captionable = ["image", "video", "document"].includes(check.kind);
		const preview = URL.createObjectURL(file);
		const dialog = new frappe.ui.Dialog({
			title: __("Send {0}", [file.name]),
			fields: [
				{ fieldtype: "HTML", fieldname: "preview" },
				{ fieldname: "caption", label: __("Caption (optional)"), fieldtype: "Small Text", hidden: captionable ? 0 : 1 },
			],
			primary_action_label: __("Send"),
			primary_action: (v) => {
				dialog.get_primary_btn().prop("disabled", true);
				this.upload_private(file)
					.then((up) => this.send("send_file", { file_url: up.file_url, caption: v.caption || "", filename: file.name }))
					.then((ok) => {
						if (ok) dialog.hide();
						else dialog.get_primary_btn().prop("disabled", false);
					})
					.catch((e) => {
						dialog.get_primary_btn().prop("disabled", false);
						frappe.msgprint({ title: __("Not sent"), message: waba_e(e.message), indicator: "red" });
					});
			},
		});
		const shown =
			check.kind === "image"
				? `<img src="${preview}" alt="" style="max-width:100%;max-height:260px;border-radius:10px;display:block;margin:0 auto" />`
				: `<div class="waba-doc" style="pointer-events:none">${WabaLib.icon(check.kind === "video" ? "play" : check.kind === "audio" ? "mic" : "file", 24)}<span><b>${waba_e(file.name)}</b><i>${waba_e(WabaLib.humanSize(file.size))}</i></span></div>`;
		dialog.get_field("preview").$wrapper.html(shown);
		dialog.onhide = () => URL.revokeObjectURL(preview);
		dialog.show();
	}

	document_dialog() {
		const types = ["Quotation", "Sales Order", "Sales Invoice", "Delivery Note"];
		const dialog = new frappe.ui.Dialog({
			title: __("Send an ERP document as a PDF"),
			fields: [
				{
					fieldname: "doctype",
					label: __("Document type"),
					fieldtype: "Select",
					options: types.join("\n"),
					default: types[0],
					reqd: 1,
					change: () => {
						const f = dialog.get_field("name");
						f.df.options = dialog.get_value("doctype");
						dialog.set_value("name", "");
						f.refresh();
					},
				},
				{ fieldname: "name", label: __("Document"), fieldtype: "Link", options: types[0], reqd: 1 },
				{ fieldname: "caption", label: __("Caption (optional)"), fieldtype: "Small Text" },
			],
			primary_action_label: __("Send PDF"),
			primary_action: (v) => {
				dialog.get_primary_btn().prop("disabled", true);
				this.send("send_document", { doctype: v.doctype, name: v.name, caption: v.caption || "" }).then((ok) => {
					if (ok) dialog.hide();
					else dialog.get_primary_btn().prop("disabled", false);
				});
			},
		});
		dialog.show();
	}

	library_dialog() {
		frappe.call({ method: "waba.api.send.shared_files" }).then((r) => {
			const files = r.message || [];
			if (!files.length) {
				frappe.msgprint(__("The shared library has no file for you yet. A supervisor can add files in the Waba workspace, Shared Files."));
				return;
			}
			const label = (f) => `${f.category ? f.category + " - " : ""}${f.title} (${f.size})`;
			const byLabel = Object.fromEntries(files.map((f) => [label(f), f]));
			const dialog = new frappe.ui.Dialog({
				title: __("Send a file from the shared library"),
				fields: [
					{ fieldname: "file", label: __("File"), fieldtype: "Select", options: files.map(label).join("\n"), default: label(files[0]), reqd: 1 },
					{ fieldname: "caption", label: __("Caption (optional)"), fieldtype: "Small Text" },
				],
				primary_action_label: __("Send"),
				primary_action: (v) => {
					dialog.get_primary_btn().prop("disabled", true);
					this.send("send_library_file", { shared_file: byLabel[v.file].name, caption: v.caption || "" }).then((ok) => {
						if (ok) dialog.hide();
						else dialog.get_primary_btn().prop("disabled", false);
					});
				},
			});
			dialog.show();
		});
	}

	react(id, emoji) {
		frappe
			.call({ method: "waba.api.send.send_reaction", args: { message: id, emoji }, freeze: false })
			.then(() => this.open_thread(this.current, { quiet: true }));
	}

	retry_message(id) {
		frappe
			.call({ method: "waba.api.send.retry_message", args: { message: id }, freeze: false })
			.then((r) => {
				const out = r.message || {};
				if (out.error) frappe.msgprint({ title: __("Not sent"), message: waba_e(out.error), indicator: "red" });
				this.open_thread(this.current, { quiet: true });
				this.load_list();
			})
			.catch(() => this.open_thread(this.current, { quiet: true }));
	}

	retry_media(id) {
		frappe.call({ method: "waba.api.media.retry", args: { message: id }, freeze: false }).then(() => this.open_thread(this.current, { quiet: true }));
	}

	template_dialog() {
		const c = this.conversation();
		if (!c) return;
		frappe.call({ method: "waba.api.send.templates_for", args: { conversation: c.name } }).then((r) => {
			const templates = r.message || [];
			if (!templates.length) {
				frappe.msgprint(__("No approved template found. Press Meta, Sync templates on the WhatsApp Account first."));
				return;
			}
			const byTitle = Object.fromEntries(templates.map((t) => [t.title, t]));
			const dialog = new frappe.ui.Dialog({
				title: __("Send a template to {0}", [c.customer_label]),
				fields: [
					{
						fieldname: "template",
						label: __("Template"),
						fieldtype: "Select",
						options: templates.map((t) => t.title).join("\n"),
						reqd: 1,
						change: () => {
							const t = byTitle[dialog.get_value("template")];
							dialog.get_field("preview").$wrapper.html(
								t
									? `<div class="text-muted small">${waba_e(t.category)} - ${t.variable_count} ${__("value(s)")}</div><pre style="white-space:pre-wrap">${waba_e(t.body_text)}</pre>`
									: ""
							);
						},
					},
					{ fieldname: "preview", fieldtype: "HTML" },
					{
						fieldname: "values",
						label: __("Values"),
						fieldtype: "Small Text",
						description: __("One value per line, in order: the first line fills {{1}}, the second {{2}}, and so on."),
					},
				],
				primary_action_label: __("Send"),
				primary_action: (values) => {
					dialog.hide();
					this.send("send_template", { template: byTitle[values.template].name, params: values.values || "" });
				},
			});
			dialog.show();
		});
	}
}

window.WabaInbox = WabaInbox;
})();
