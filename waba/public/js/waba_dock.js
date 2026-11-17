/* The floating WhatsApp chat on a Lead, Contact or Customer form (opened from the WhatsApp icon in the form header).
 *
 * It is the inbox's own chat view in a small docked window: WabaInbox runs in "dock" mode (no list, no toolbar), so replying,
 * notes, templates, files, retries and the 24-hour window behave exactly as in the inbox, and every server call re-checks the
 * same visibility rules (waba.api.inbox.thread / waba.api.send.*). This file only builds the window and picks the conversation.
 * The server's answer for the form (waba.api.party.context, kept on frm.__waba by waba_party.js) says which conversations this
 * person may open. Loaded on demand by waba_party.js. */
;(function () {
	if (window.WabaDock) return;
	const esc = (v) => frappe.utils.escape_html(v == null ? "" : String(v));

	/** The inbox's scripts and style, loaded once (the same promise the inbox page uses, so nothing loads twice). */
	function assets() {
		if (!window.__waba_inbox_assets) {
			window.__waba_inbox_assets = frappe.call({ method: "waba.api.inbox.assets_version", silent: true }).then((r) => {
				const v = encodeURIComponent((r && r.message) || "0");
				const base = "/assets/waba";
				$("<link>", { rel: "stylesheet", href: `${base}/css/waba_inbox.css?v=${v}` }).appendTo("head");
				return $.ajax({ url: `${base}/js/waba_inbox_lib.js?v=${v}`, dataType: "script", cache: true })
					.then(() => $.ajax({ url: `${base}/js/waba_template_dialog.js?v=${v}`, dataType: "script", cache: true }))
					.then(() => $.ajax({ url: `${base}/js/waba_inbox_app.js?v=${v}`, dataType: "script", cache: true }))
					.then(() => window.WabaDockGeometry || $.ajax({ url: `${base}/js/waba_dock_geometry.js?v=${v}`, dataType: "script", cache: true }));
			});
		}
		return window.__waba_inbox_assets;
	}

	const GEOM_KEY = "waba_dock_geom_v1";

	const dock = {
		frm: null,
		_open: false,
		minimised: false,
		$el: null,
		$body: null,
		inbox: null,
		current: null,
		geom: null,

		/** The inbox asks this: is a conversation on screen right now (so alerts stay quiet for it)? */
		get visible() {
			return this._open && !this.minimised;
		},

		build() {
			if (this.$el) return;
			this.$el = $(`
				<div class="waba-shell waba-dock" hidden role="dialog" aria-label="${__("WhatsApp chat")}">
					<div class="waba-dock-head" tabindex="0" title="${__("Drag to move. Double-click to put it back in the corner.")}">
						<span class="waba-dock-logo">${WabaLib.brandMark(24)}</span>
						<div class="waba-dock-title"><b class="waba-dock-name"></b><small class="waba-dock-hint"></small></div>
						<select class="waba-dock-pick" hidden aria-label="${__("Choose a conversation")}"></select>
						<button class="waba-dock-btn waba-dock-inbox" title="${__("Open in the inbox")}" aria-label="${__("Open in the inbox")}">${WabaLib.icon("external", 16)}</button>
						<button class="waba-dock-btn waba-dock-min" title="${__("Minimise")}" aria-label="${__("Minimise")}">${WabaLib.icon("chevron", 16)}</button>
						<button class="waba-dock-btn waba-dock-close" title="${__("Close")}" aria-label="${__("Close")}">${WabaLib.icon("x", 16)}</button>
					</div>
					<div class="waba-dock-body"></div>
					<div class="waba-dock-empty" hidden></div>
					${["n", "s", "e", "w", "nw", "ne", "sw", "se"].map((h) => `<i class="waba-dock-h" data-h="${h}" aria-hidden="true"></i>`).join("")}
				</div>`).appendTo(document.body);
			this.$body = this.$el.find(".waba-dock-body");
			this.$el.find(".waba-dock-close").on("click", () => this.close());
			this.$el.find(".waba-dock-min").on("click", () => this.minimise(!this.minimised));
			this.$el.find(".waba-dock-head .waba-dock-title").on("click", () => this.minimised && this.minimise(false));
			this.$el.find(".waba-dock-inbox").on("click", () => {
				if (!this.current) return;
				// a new tab: the form you are working on stays exactly as it is, and so does this chat window
				const url = `/desk/waba-inbox?conversation=${encodeURIComponent(this.current)}`;
				const tab = window.open(url, "_blank", "noopener");
				if (!tab) frappe.msgprint(__("Your browser blocked the new tab. <a href='{0}' target='_blank' rel='noopener'>Open the inbox here</a>.", [url]));
			});
			this.$el.find(".waba-dock-pick").on("change", (ev) => this.show($(ev.currentTarget).val()));
			this.inbox = new window.WabaInbox(null, null, { dock: this });
			if (frappe.router && frappe.router.on) frappe.router.on("change", () => this.on_route());
			this.$el.on("animationend", () => this.$el.css("animation", "none")); // a transform left on a fixed box would trap popovers inside it
			this.bind_geometry();
		},

		// ---------------------------------------------------------------- where it sits and how big it is (waba_dock_geometry.js)

		viewport() {
			return [window.innerWidth, window.innerHeight];
		},

		saved() {
			try {
				return window.WabaDockGeometry.parse(window.localStorage.getItem(GEOM_KEY));
			} catch (e) {
				return null; // storage blocked: the window simply starts in the corner each time
			}
		},

		save() {
			try {
				window.localStorage.setItem(GEOM_KEY, JSON.stringify(this.geom));
			} catch (e) {
				/* private mode */
			}
		},

		/** Put the window where `g` says. On a phone it stays full screen (the stylesheet decides). */
		apply(g, save) {
			this.geom = g;
			this.$el.css({ left: g.x, top: g.y, width: g.w, height: g.h, right: "auto", bottom: "auto" });
			if (save) this.save();
		},

		place() {
			const G = window.WabaDockGeometry;
			const [vw, vh] = this.viewport();
			this.apply(G.fit(this.saved(), vw, vh), false);
		},

		bind_geometry() {
			const G = window.WabaDockGeometry;
			const self = this;
			let op = null; // {kind, handle, x0, y0, start, id, target}

			const begin = (ev, kind, handle, target) => {
				if (G.isPhone(window.innerWidth) || (ev.pointerType === "mouse" && ev.button !== 0)) return;
				if (kind === "move" && $(ev.target).closest("button, select, option, a, input").length) return;
				op = { kind, handle, x0: ev.clientX, y0: ev.clientY, start: { ...self.geom }, id: ev.pointerId, target };
				try {
					target.setPointerCapture(ev.pointerId);
				} catch (e) {
					/* not every browser allows it */
				}
				self.$el.addClass("dragging");
				document.body.style.cursor = kind === "move" ? "grabbing" : window.getComputedStyle(target).cursor; // keeps the cursor right when the pointer outruns the window
				ev.preventDefault();
			};
			const step = (ev) => {
				if (!op || ev.pointerId !== op.id) return;
				const [vw, vh] = self.viewport();
				const dx = ev.clientX - op.x0;
				const dy = ev.clientY - op.y0;
				self.apply(op.kind === "move" ? G.move(op.start, dx, dy, vw, vh) : G.resize(op.start, op.handle, dx, dy, vw, vh), false);
			};
			const end = (ev) => {
				if (!op || ev.pointerId !== op.id) return;
				try {
					op.target.releasePointerCapture(ev.pointerId);
				} catch (e) {
					/* already released */
				}
				op = null;
				self.$el.removeClass("dragging");
				document.body.style.cursor = "";
				self.save();
			};

			const head = this.$el.find(".waba-dock-head")[0];
			head.addEventListener("pointerdown", (ev) => begin(ev, "move", "", head));
			head.addEventListener("pointermove", step);
			head.addEventListener("pointerup", end);
			head.addEventListener("pointercancel", end);
			this.$el.find(".waba-dock-h").each(function () {
				const handle = this.getAttribute("data-h");
				this.addEventListener("pointerdown", (ev) => begin(ev, "size", handle, this));
				this.addEventListener("pointermove", step);
				this.addEventListener("pointerup", end);
				this.addEventListener("pointercancel", end);
			});

			// double-click on the title bar: back to the corner (and forget the saved place)
			this.$el.find(".waba-dock-head").on("dblclick", (ev) => {
				if ($(ev.target).closest("button, select, option, a").length || G.isPhone(window.innerWidth)) return;
				const [vw, vh] = this.viewport();
				this.apply(G.defaults(vw, vh), false);
				try {
					window.localStorage.removeItem(GEOM_KEY);
				} catch (e) {
					/* nothing stored */
				}
			});

			// keyboard: Alt + arrows move by 20 px, Alt + Shift + arrows resize by 20 px
			this.$el.find(".waba-dock-head").on("keydown", (ev) => {
				if (!ev.altKey || G.isPhone(window.innerWidth) || !ev.key.startsWith("Arrow")) return;
				const [vw, vh] = this.viewport();
				const d = { ArrowLeft: [-20, 0], ArrowRight: [20, 0], ArrowUp: [0, -20], ArrowDown: [0, 20] }[ev.key];
				if (!d) return;
				ev.preventDefault();
				this.apply(ev.shiftKey ? G.resize(this.geom, "se", d[0], d[1], vw, vh) : G.move(this.geom, d[0], d[1], vw, vh), true);
			});

			// a smaller browser window: bring it back inside
			$(window).on("resize.waba_dock", () => {
				if (!this._open || !this.geom) return;
				const [vw, vh] = this.viewport();
				this.apply(G.clamp(this.geom, vw, vh), false);
			});
		},

		on_route() {
			if (!this._open || !this.frm) return;
			const r = frappe.get_route();
			if (r[0] !== "Form" || r[1] !== this.frm.doctype || r[2] !== this.frm.docname) this.close();
		},

		/** Open the window for this form (or close it when it is already open for the same document). */
		toggle(frm) {
			if (this._open && this.frm && this.frm.doctype === frm.doctype && this.frm.docname === frm.docname) return this.close();
			return this.open(frm);
		},

		open(frm) {
			return assets().then(() => {
				this.build();
				this.frm = frm;
				this._open = true;
				this.minimised = false;
				this.$el.removeClass("min").css("animation", "").prop("hidden", false);
				this.place();
				this.render(true);
			});
		},

		/** The form's conversations changed (a message was just sent from the form): redraw, keeping the one that is open. */
		update(frm) {
			if (!this._open || this.frm !== frm) return;
			this.render(false);
		},

		conversations() {
			return ((this.frm && this.frm.__waba && this.frm.__waba.conversations) || []).slice();
		},

		render(first) {
			const ctx = (this.frm && this.frm.__waba) || {};
			const list = this.conversations();
			this.$el.find(".waba-dock-name").text(ctx.title || (this.frm && this.frm.docname) || "");
			this.$el.find(".waba-dock-hint").text("");
			const $pick = this.$el.find(".waba-dock-pick");
			const $empty = this.$el.find(".waba-dock-empty");
			if (!list.length) {
				this.current = null;
				$pick.prop("hidden", true);
				this.$body.prop("hidden", true);
				$empty
					.prop("hidden", false)
					.html(`<div class="waba-dock-empty-in">${WabaLib.brandMark(44)}<p>${__("No WhatsApp chat with {0} yet that you may see.", [esc(ctx.title || "")])}</p>
						<button class="waba-btn primary waba-dock-start">${__("Message on WhatsApp")}</button></div>`);
				$empty.find(".waba-dock-start").on("click", () => this.frm.__waba_start && this.frm.__waba_start());
				this.inbox.close_thread();
				return;
			}
			$empty.prop("hidden", true).empty();
			this.$body.prop("hidden", false);
			const keep = !first && this.current && list.some((c) => c.name === this.current) ? this.current : list[0].name;
			$pick
				.prop("hidden", list.length < 2)
				.html(list.map((c) => `<option value="${esc(c.name)}">${esc(c.number_name || c.name)} (${esc(c.status)}${c.window_open ? ", " + esc(__("window open")) : ""})</option>`).join(""))
				.val(keep);
			this.show(keep);
		},

		show(name) {
			this.current = name;
			return this.inbox.open_thread(name);
		},

		minimise(on) {
			this.minimised = !!on;
			this.$el.toggleClass("min", this.minimised);
			this.inbox.publish_state(); // a minimised window is not being read: alerts ring again
			if (!this.minimised && this.current) this.inbox.open_thread(this.current, { quiet: true });
		},

		close() {
			this._open = false;
			if (this.$el) this.$el.prop("hidden", true);
			if (this.inbox) {
				this.inbox.close_thread();
				this.inbox.publish_state();
			}
			this.current = null;
		},
	};

	window.WabaDock = dock;
})();
