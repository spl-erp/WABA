/* The alert logic. Pure decisions come first (tested offline in Node); the browser part below only runs in the Desk.
 *
 * Source of events: the content-free realtime message "waba_inbox" ({conversation, kind}), which the server sends only to
 * the people who may see that conversation. Only kind "message" (a new customer message) and "handed_over" (a transfer to
 * you) alert; delivery ticks, notes and assignments never do. The text shown is read with frappe.db.get_value, so it passes the
 * normal permission check. Settings are per browser (localStorage). */
(function (root, factory) {
	const core = factory();
	if (typeof module !== "undefined" && module.exports) module.exports = core;
	else core.start(root);
})(typeof self !== "undefined" ? self : this, function () {
	const KEY = "waba_alerts_v1";
	const DEFAULTS = { sound: true, desktop: false };
	// a new customer message, or a conversation handed to this person (sent only to them). Ticks and notes never alert.
	const ALERT_KINDS = ["message", "handed_over"];

	/** Settings from stored text, filling in anything missing or malformed. */
	function readPrefs(text) {
		let stored = {};
		try {
			stored = JSON.parse(text || "{}") || {};
		} catch (e) {
			stored = {};
		}
		return { sound: typeof stored.sound === "boolean" ? stored.sound : DEFAULTS.sound, desktop: typeof stored.desktop === "boolean" ? stored.desktop : DEFAULTS.desktop };
	}

	/**
	 * What to do for one realtime event.
	 * ctx: {kind, conversation, hidden (tab not visible), inbox: {visible, current} or null, prefs}
	 * Returns null (do nothing) or {sound, toast, desktop, count}.
	 */
	function decide(ctx) {
		if (!ctx || !ALERT_KINDS.includes(ctx.kind) || !ctx.conversation) return null;
		const inbox = ctx.inbox && ctx.inbox.visible ? ctx.inbox : null;
		const looking = !ctx.hidden && inbox && inbox.current === ctx.conversation;
		if (looking) return null; // the person is reading this very conversation
		return {
			sound: !!ctx.prefs.sound,
			toast: !ctx.hidden, // in the page: a small notice; in a background tab: a desktop notification instead
			desktop: !!ctx.prefs.desktop && !!ctx.hidden,
			count: !!ctx.hidden,
		};
	}

	/** "(3) WhatsApp Inbox": the tab title with the unread count in front (no double prefix). */
	function titleWithCount(title, count) {
		const base = String(title || "").replace(/^\(\d+\)\s*/, "");
		return count > 0 ? `(${count}) ${base}` : base;
	}

	/** The text of the red count on the sidebar Inbox label: nothing for zero, 99+ for a lot. */
	function badgeText(count) {
		const n = Math.floor(Number(count) || 0);
		return n <= 0 ? "" : n > 99 ? "99+" : String(n);
	}

	const BADGE_CSS =
		// the pill sits where Frappe puts its own counters: 8 px from the right edge of the item, vertically centred
		".waba-sidebar-badge{position:relative;flex:none;margin:0 8px 0 auto;min-width:20px;height:18px;padding:0 6px;box-sizing:border-box;border-radius:9px;" +
		"background:linear-gradient(180deg,#ef4444,#d92d20);color:#fff;font-size:11px;font-weight:700;line-height:18px;text-align:center;letter-spacing:.01em;" +
		"font-variant-numeric:tabular-nums;box-shadow:0 1px 2px rgba(217,45,32,.35);user-select:none}" +
		// a rise in the count: one quick pop and one soft ring, never on a plain redraw of the sidebar
		".waba-sidebar-badge.waba-pop{animation:waba-badge-pop .28s cubic-bezier(.3,1.5,.5,1)}" +
		".waba-sidebar-badge.waba-pop::after{content:'';position:absolute;inset:-2px;border-radius:11px;border:2px solid rgba(239,68,68,.55);animation:waba-badge-ring .9s ease-out forwards;pointer-events:none}" +
		// the item itself says something is waiting: a stronger label
		".body-sidebar a.waba-has-unread .sidebar-item-label{font-weight:600;color:var(--text-color,inherit)}" +
		// a collapsed sidebar has no room for a number: a small dot on the icon instead
		".body-sidebar-container:not(.expanded) a.waba-has-unread{position:relative}" +
		".body-sidebar-container:not(.expanded) .waba-sidebar-badge{position:absolute;top:3px;right:3px;margin:0;min-width:9px;width:9px;height:9px;padding:0;font-size:0;line-height:0;border-radius:50%;box-shadow:0 0 0 2px var(--bg-color,#fff)}" +
		"@keyframes waba-badge-pop{from{transform:scale(.55)}to{transform:scale(1)}}" +
		"@keyframes waba-badge-ring{from{opacity:1;transform:scale(1)}to{opacity:0;transform:scale(1.7)}}" +
		"@media (prefers-reduced-motion:reduce){.waba-sidebar-badge.waba-pop,.waba-sidebar-badge.waba-pop::after{animation:none}}";

	function start(root) {
		if (!root.frappe || !root.document || root.waba_alerts) return;
		const state = { hiddenCount: 0, audio: null };
		const load = () => readPrefs(root.localStorage && root.localStorage.getItem(KEY));
		const save = (prefs) => {
			try {
				root.localStorage.setItem(KEY, JSON.stringify(prefs));
			} catch (e) {
				/* private mode: the setting lasts until reload */
			}
		};

		// A three-note rising chime, clearly louder than the old two-tone beep: sine plus a soft triangle for body, about 0.75 s.
		function beep() {
			try {
				const Ctx = root.AudioContext || root.webkitAudioContext;
				if (!Ctx) return;
				state.audio = state.audio || new Ctx();
				if (state.audio.state === "suspended") state.audio.resume();
				const ctx = state.audio;
				const t = ctx.currentTime;
				const master = ctx.createGain();
				master.gain.value = 0.9;
				const comp = ctx.createDynamicsCompressor(); // keeps the louder chime from distorting on laptop speakers
				master.connect(comp);
				comp.connect(ctx.destination);
				[
					[659.25, 0],
					[783.99, 0.17],
					[1046.5, 0.34],
				].forEach(([freq, at]) => {
					["sine", "triangle"].forEach((type, k) => {
						const osc = ctx.createOscillator();
						const gain = ctx.createGain();
						osc.type = type;
						osc.frequency.value = freq;
						const peak = k === 0 ? 0.55 : 0.18;
						gain.gain.setValueAtTime(0.0001, t + at);
						gain.gain.exponentialRampToValueAtTime(peak, t + at + 0.02);
						gain.gain.exponentialRampToValueAtTime(0.0001, t + at + (at === 0.34 ? 0.45 : 0.3));
						osc.connect(gain);
						gain.connect(master);
						osc.start(t + at);
						osc.stop(t + at + 0.5);
					});
				});
			} catch (e) {
				/* the browser may block sound until the first click */
			}
		}

		function open(conversation) {
			if (root.waba_inbox_state && root.waba_inbox_state.visible) $(root.document).trigger("waba:open", [conversation]);
			else {
				root.waba_open_conversation = conversation;
				root.frappe.set_route("waba-inbox");
			}
		}

		function resetTitle() {
			state.hiddenCount = 0;
			root.document.title = titleWithCount(root.document.title, 0);
		}
		root.document.addEventListener("visibilitychange", () => !root.document.hidden && resetTitle());
		root.addEventListener("focus", resetTitle);
		$(root.document).one("click keydown", () => {
			// browsers only allow sound after the first interaction: prepare it now
			try {
				const Ctx = root.AudioContext || root.webkitAudioContext;
				if (Ctx) state.audio = state.audio || new Ctx();
			} catch (e) {
				/* ignore */
			}
		});

		// ---- the red count on the sidebar Inbox label (Frappe has no badge for sidebar items, so it is drawn here and re-applied
		// whenever the sidebar is rebuilt)
		state.unread = Number(root.frappe.boot && root.frappe.boot.waba_unread) || 0;
		state.shown = state.unread; // no pop for the count the page started with
		const style = root.document.createElement("style");
		style.textContent = BADGE_CSS;
		root.document.head.appendChild(style);
		function paintBadge() {
			const text = badgeText(state.unread);
			const rose = state.unread > (state.shown || 0);
			root.document.querySelectorAll('.body-sidebar a[href$="waba-inbox"], .sidebar a[href$="waba-inbox"]').forEach((anchor) => {
				anchor.classList.toggle("waba-has-unread", !!text);
				let badge = anchor.querySelector(".waba-sidebar-badge");
				if (!text) return badge && badge.remove();
				const label = state.unread === 1 ? __("1 chat with unread messages") : __("{0} chats with unread messages", [text]);
				if (!badge) {
					badge = root.document.createElement("span");
					badge.className = "waba-sidebar-badge";
					anchor.appendChild(badge);
				}
				if (badge.textContent !== text) badge.textContent = text;
				badge.setAttribute("aria-label", label);
				badge.setAttribute("title", label);
				if (rose) {
					badge.classList.remove("waba-pop");
					void badge.offsetWidth; // restart the animation
					badge.classList.add("waba-pop");
					setTimeout(() => badge.classList.remove("waba-pop"), 1000);
				}
			});
			state.shown = state.unread;
		}
		let paintQueued = false;
		const schedulePaint = () => {
			if (paintQueued) return;
			paintQueued = true;
			root.requestAnimationFrame(() => {
				paintQueued = false;
				paintBadge();
			});
		};
		new root.MutationObserver(schedulePaint).observe(root.document.body, { childList: true, subtree: true });
		const refreshUnread = root.frappe.utils.debounce(() => {
			root.frappe.call({ method: "waba.api.inbox.unread_total", type: "GET", silent: true }).then((r) => {
				state.unread = Number(r && r.message) || 0;
				paintBadge();
			});
		}, 400);
		setInterval(refreshUnread, 60000); // a safety net if the live connection drops
		root.document.addEventListener("visibilitychange", () => !root.document.hidden && refreshUnread());
		schedulePaint();

		// the browser phone for WhatsApp calls, only for people the server flagged (waba.boot.call_flags)
		const calls = root.frappe.boot && root.frappe.boot.waba_calls;
		if (calls && calls.enabled && (calls.make || calls.take)) {
			root.frappe.call({ method: "waba.api.inbox.assets_version", silent: true }).then(function (r) {
				root.$.ajax({ url: "/assets/waba/js/waba_call_phone.js?v=" + encodeURIComponent((r && r.message) || "0"), dataType: "script", cache: true });
			});
		}

		root.frappe.realtime.on("waba_inbox", () => refreshUnread()); // any change (new message, read, hand-over) can change the count
		root.frappe.realtime.on("waba_inbox", (data) => {
			const plan = decide({ kind: data && data.kind, conversation: data && data.conversation, hidden: root.document.hidden, inbox: root.waba_inbox_state || null, prefs: load() });
			if (!plan) return;
			if (plan.sound) beep();
			if (plan.count) {
				state.hiddenCount += 1;
				root.document.title = titleWithCount(root.document.title, state.hiddenCount);
			}
			if (!plan.toast && !plan.desktop) return;
			root.frappe.db.get_value("Waba Conversation", data.conversation, ["customer_label", "last_message_preview"]).then((r) => {
				const row = (r && r.message) || {};
				const who = row.customer_label || "WhatsApp";
				const text = (data.kind === "handed_over" ? __("Handed over to you") + ": " : "") + (row.last_message_preview || "");
				if (plan.toast) {
					root.frappe.show_alert({ message: `<b>${root.frappe.utils.escape_html(who)}</b>: ${root.frappe.utils.escape_html(text)}`, indicator: "green" }, 8, { [__("Open")]: () => open(data.conversation) });
				}
				if (plan.desktop && root.Notification && root.Notification.permission === "granted") {
					const note = new root.Notification(who, { body: text, tag: data.conversation });
					note.onclick = () => {
						root.focus();
						open(data.conversation);
						note.close();
					};
				}
			});
		});

		root.waba_alerts = {
			refresh_unread: refreshUnread,
			prefs: load,
			set(partial) {
				save({ ...load(), ...partial });
			},
			enable_desktop() {
				if (!root.Notification) return root.frappe.msgprint(__("This browser does not support desktop notifications."));
				if (root.Notification.permission === "denied") return root.frappe.msgprint(__("Notifications are blocked for this site in the browser. Allow them in the address bar's site settings, then try again."));
				const done = (permission) => (permission === "granted" ? this.set({ desktop: true }) : root.frappe.msgprint(__("Desktop notifications were not allowed.")));
				if (root.Notification.permission === "granted") return done("granted");
				root.Notification.requestPermission().then(done);
			},
		};
	}

	return { readPrefs, decide, titleWithCount, badgeText, start, KEY, DEFAULTS };
});
