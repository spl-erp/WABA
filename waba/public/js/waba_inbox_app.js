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
				<button class="waba-refresh">${WabaLib.icon("refresh", 17)}<span>${__("Refresh")}</span></button>
			</header>`).appendTo($parent);

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
		this.counts = {};
		this.$el = $(`<aside class="waba-list"><div class="waba-tabs"></div><div class="waba-items"></div></aside>`).appendTo($parent);
		this.$tabs = this.$el.find(".waba-tabs");
		this.$items = this.$el.find(".waba-items");
		this.render_tabs();
	}

	set_counts(counts) {
		this.counts = counts || {};
		this.render_tabs();
	}

	render_tabs() {
		const tabs = [
			["open", __("Open"), this.counts.open],
			["unread", __("Unread"), this.counts.unread],
			["triage", __("Triage"), this.counts.triage],
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
			this.$items.html(`<div class="waba-empty">${__("No conversations here.")}</div>`);
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
	constructor($parent, handlers) {
		this.handlers = handlers;
		this.mode = null;
		this.draft = "";
		this.$el = $(`<div class="waba-composer"></div>`).appendTo($parent);
	}

	/** mode: "open" (type and send), "closed" (template only), "no_phone" (cannot reply by user ID). */
	set_mode(mode) {
		if (mode === this.mode) return;
		this.draft = this.$el.find("textarea").val() || this.draft;
		this.mode = mode;
		const attach = `<button class="waba-circle" disabled title="${__("Attachments arrive in a later release")}" aria-label="${__("Attach a file")}">${WabaLib.icon("paperclip", 19)}</button>`;
		const emoji = (enabled) => `<button class="waba-circle waba-emoji-btn" ${enabled ? "" : "disabled"} aria-label="${__("Emoji")}" title="${__("Emoji")}">${WabaLib.icon("smile", 19)}</button>`;
		if (mode === "closed") {
			this.$el.html(`${attach}${emoji(false)}
				<div class="waba-inputwrap disabled">${__("Window closed: only approved templates can be sent.")}</div>
				<button class="waba-btn primary waba-send-template">${WabaLib.icon("send", 16)}<span class="waba-btn-text">${__("Send template")}</span></button>`);
			this.$el.find(".waba-send-template").on("click", () => this.handlers.onTemplate());
			return;
		}
		if (mode === "no_phone") {
			this.$el.html(`${attach}${emoji(false)}<div class="waba-inputwrap disabled">${__("This customer is known only by a WhatsApp user ID; replying needs their phone number (not supported yet).")}</div>`);
			return;
		}
		this.$el.html(`${attach}${emoji(true)}
			<div class="waba-inputwrap"><textarea rows="1" placeholder="${window.innerWidth < 768 ? __("Type a message") : __("Type a message (Enter to send, Shift+Enter for a new line)")}"></textarea></div>
			<button class="waba-send" aria-label="${__("Send")}">${WabaLib.icon("send", 20)}</button>`);
		this.$text = this.$el.find("textarea").val(this.draft);
		this.$send = this.$el.find(".waba-send");
		this.autosize();
		this.$text.on("input", () => {
			this.draft = this.$text.val();
			this.autosize();
		});
		this.$text.on("keydown", (ev) => {
			if (ev.key === "Enter" && !ev.shiftKey) {
				ev.preventDefault();
				this.submit();
			}
		});
		this.$send.on("click", () => this.submit());
		this.$el.find(".waba-emoji-btn").on("click", (ev) => {
			ev.stopPropagation();
			this.toggle_emoji();
		});
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
		this.draft = el.value;
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
		this.handlers.onSend(body).then((ok) => {
			if (ok) {
				this.draft = "";
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
			this.has_more = data.has_more;
			this.query = "";
			this.hit = -1;
			this.$el.html(`<div class="waba-th-head"></div><div class="waba-banner"></div><div class="waba-findbar" hidden></div><div class="waba-messages"></div>`);
			this.$head = this.$el.find(".waba-th-head");
			this.$banner = this.$el.find(".waba-banner");
			this.$find = this.$el.find(".waba-findbar");
			this.$messages = this.$el.find(".waba-messages");
			this.composer = new WabaComposer(this.$el, {
				onSend: (body) => this.handlers.onSend(body),
				onTemplate: () => this.handlers.onTemplate(),
			});
		}
		if (!fresh && !this.older.length) this.has_more = data.has_more;
		this.merge();
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
	}

	oldest_time() {
		return this.messages.length ? this.messages[0].sent_at : null;
	}

	/** Add an older page (oldest first) in front and keep the reader where they were. */
	add_older(rows, has_more) {
		const box = this.$messages[0];
		const heightBefore = box.scrollHeight;
		const topBefore = box.scrollTop;
		const known = new Set(this.messages.map((m) => m.name));
		this.older = rows.filter((m) => !known.has(m.name)).concat(this.older);
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
		const env = c.environment && c.environment !== "Production" ? `<span class="waba-env">${waba_e(c.environment)}</span>` : "";
		this.$head.html(`
			<button class="waba-iconbtn waba-back" aria-label="${__("Back")}">${WabaLib.icon("back", 20)}</button>
			<span class="waba-avatar lg" style="background:${WabaLib.avatarColor(lines.name)}">${waba_e(WabaLib.initials(lines.name))}</span>
			<div class="waba-th-id">
				<div class="waba-th-name"><span>${waba_e(lines.name)}</span>${c.match_state === "Matched" ? WabaLib.verifiedBadge(17) : ""}${env}</div>
				${lines.sub ? `<div class="waba-th-phone">${waba_e(lines.sub)}</div>` : ""}
				${party}
			</div>
			<div class="waba-th-actions">
				<button class="waba-btn waba-open-record">${WabaLib.icon("external", 15)}<span class="waba-btn-text">${__("Open Record")}</span></button>
				<button class="waba-btn waba-template-btn">${WabaLib.icon("send", 15)}<span class="waba-btn-text">${__("Send Template")}</span></button>
				<button class="waba-iconbtn waba-more-btn" aria-label="${__("More actions")}">${WabaLib.icon("more", 20)}</button>
			</div>`);
		this.$head.find(".waba-back").on("click", () => this.handlers.onBack());
		this.$head.find(".waba-open-record").on("click", () => this.handlers.onOpenRecord());
		this.$head.find(".waba-template-btn").on("click", () => this.handlers.onTemplate());
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
		const html = this.messages
			.map((m) => {
				const day = WabaLib.dayLabel(m.sent_at);
				const sep = day && day !== lastDay ? `<div class="waba-day"><span>${waba_e(day)}</span></div>` : "";
				lastDay = day || lastDay;
				return sep + this.message_html(m);
			})
			.join("");
		this.$messages.html(earlier + (html || `<div class="waba-day"><span>${__("No messages yet")}</span></div>`));
		this.$messages.find(".waba-earlier").on("click", (ev) => {
			$(ev.currentTarget).prop("disabled", true);
			this.handlers.onEarlier(this.oldest_time());
		});
		this.$messages.find(".waba-quote").on("click", (ev) => this.jump_to($(ev.currentTarget).data("ref")));
		if (this.query) this.collect_hits();
		if (keepPosition) return;
		if (stick || nearBottom) box.scrollTop = box.scrollHeight;
		else box.scrollTop = previousTop;
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

	message_html(m) {
		const out = m.direction === "Out";
		const failed = m.status === "Failed";
		const tick = out ? WabaLib.tickFor(m.status) : null;
		const tag = m.template_title ? `<div class="waba-tag">${WabaLib.icon("send", 12)}${__("Template")}: ${waba_e(m.template_title)}</div>` : "";
		const senderName = out ? waba_e(m.sent_by_name || __("Sent")) : "";
		const sender = out && !failed ? `<div class="waba-sender">${senderName}</div>` : "";
		const err = failed
			? `<div class="waba-errorbox">${WabaLib.icon("warning", 15)}<span>${__("Not delivered")}: ${waba_e(m.error_message || __("Meta did not accept this message."))}</span></div>`
			: "";
		const tickHtml = tick ? `<span class="waba-tick ${tick.tone}" title="${waba_e(__(tick.label))}">${WabaLib.icon(tick.icon, 16)}</span>` : "";
		const quote = m.reply_to_message_id
			? `<div class="waba-quote" data-ref="${waba_e(m.reply_to_message_id)}"><b>${waba_e(m.reply_to_sender || (m.reply_to_direction === "Out" ? __("You") : __("Customer")))}</b><span>${waba_e(m.reply_to_body || __("Original message"))}</span></div>`
			: "";
		const text = WabaLib.highlight(WabaLib.linkify(m.body || ""), this.query);
		return `<div class="waba-msg ${out ? "out" : "in"} ${failed ? "failed" : ""}" data-id="${waba_e(m.name)}" data-mid="${waba_e(m.message_id || "")}">
			<div class="waba-bubble">${sender}${tag}${quote}<div class="waba-text">${text}</div>${err}
				<div class="waba-foot">${failed ? `<span class="waba-foot-name">${senderName}</span>` : ""}<span class="waba-foot-right"><span>${waba_e(WabaLib.clockLabel(m.sent_at))}</span> ${tickHtml}</span></div></div></div>`;
	}
}

// ---------------------------------------------------------------------------------------------- the page

class WabaInbox {
	constructor(page, wrapper) {
		this.page = page;
		this.wrapper = wrapper;
		this.current = null;
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
		});
		this.$shell.prepend(this.toolbar.$el);
		this.$panels = this.$shell.find(".waba-inbox");
		this.list = new WabaList(this.$panels, {
			onTab: () => this.load_list(),
			onOpen: (name) => this.open_thread(name),
			onMore: () => this.load_list(false),
		});
		this.thread = new WabaThread(this.$panels, {
			onBack: () => this.close_thread(),
			onSend: (body) => this.send("send_text", { body }),
			onTemplate: () => this.template_dialog(),
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
		frappe.call({ method: "waba.api.inbox.summary", silent: true }).then((r) => this.list.set_counts(r.message || {}));
	}

	load_list(reset = true) {
		const start = reset ? 0 : this.list.rows.length;
		return frappe
			.call({
				method: "waba.api.inbox.conversations",
				args: { view: this.list.view, number: this.number || null, search: this.search || null, start, limit: 30 },
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
		return frappe.call({ method: "waba.api.inbox.thread", args: { conversation: name }, silent: true }).then((r) => {
			if (this.current !== name) return; // another conversation was opened meanwhile; ignore this late answer
			this.thread.show(r.message, { stick: changed });
			this.list.select(name);
			if (r.message.conversation.unread_count > 0) this.mark_read(name);
		});
	}

	load_earlier(before) {
		const name = this.current;
		return frappe.call({ method: "waba.api.inbox.thread", args: { conversation: name, before }, silent: true }).then((r) => {
			if (this.current !== name || !r.message) return;
			this.thread.add_older(r.message.messages, r.message.has_more);
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
