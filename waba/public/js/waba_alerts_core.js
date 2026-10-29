/* The alert logic. Pure decisions come first (tested offline in Node); the browser part below only runs in the Desk.
 *
 * Source of events: the content-free realtime message "waba_inbox" ({conversation, kind}). Only kind "message" (a new
 * customer message) alerts; delivery ticks never do. The text shown is read with frappe.db.get_value, so it passes the
 * normal permission check. Settings are per browser (localStorage). */
(function (root, factory) {
	const core = factory();
	if (typeof module !== "undefined" && module.exports) module.exports = core;
	else core.start(root);
})(typeof self !== "undefined" ? self : this, function () {
	const KEY = "waba_alerts_v1";
	const DEFAULTS = { sound: true, desktop: false };

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
		if (!ctx || ctx.kind !== "message" || !ctx.conversation) return null;
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

		function beep() {
			try {
				const Ctx = root.AudioContext || root.webkitAudioContext;
				if (!Ctx) return;
				state.audio = state.audio || new Ctx();
				if (state.audio.state === "suspended") state.audio.resume();
				const t = state.audio.currentTime;
				[880, 1175].forEach((freq, i) => {
					const osc = state.audio.createOscillator();
					const gain = state.audio.createGain();
					osc.type = "sine";
					osc.frequency.value = freq;
					gain.gain.setValueAtTime(0.0001, t + i * 0.16);
					gain.gain.exponentialRampToValueAtTime(0.18, t + i * 0.16 + 0.02);
					gain.gain.exponentialRampToValueAtTime(0.0001, t + i * 0.16 + 0.18);
					osc.connect(gain);
					gain.connect(state.audio.destination);
					osc.start(t + i * 0.16);
					osc.stop(t + i * 0.16 + 0.2);
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
				const text = row.last_message_preview || "";
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

	return { readPrefs, decide, titleWithCount, start, KEY, DEFAULTS };
});
