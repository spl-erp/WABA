/* "New conversation" in the inbox: find a person in the ERP, choose the number and a Utility template, send.
 *
 * Step 1 searches Leads, Contacts and Customers (waba.api.party.search_people). Step 2 is the same message form as on the
 * Lead / Contact / Customer forms (number, phone, template, values) built from waba.api.party.context with Utility templates
 * only. Everything is decided on the server (waba.api.party.start_chat): consent, opt-out, the number, Meta's daily limit.
 * When the person already has a chat on that number the inbox simply opens it. Needs waba_inbox_lib.js and waba_template_dialog.js. */
(function () {
	const esc = (v) => frappe.utils.escape_html(v == null ? "" : String(v));

	function consent_html(ctx) {
		const c = ctx.consent || {};
		if (c.opted_out) return `<span class="indicator-pill red">${__("Opted out")}</span> <span class="text-muted">${c.flag ? __("The record is marked do not contact.") : esc(c.source || "")}</span>`;
		if (c.state === "Yes") return `<span class="indicator-pill green">${__("WhatsApp consent: Yes")}</span>${c.source ? ` <span class="text-muted">${esc(c.source)}</span>` : ""}`;
		return `<span class="indicator-pill orange">${__("No WhatsApp consent recorded")}</span> <span class="text-muted">${__("First messages need it; a customer who writes to you first does not.")}</span>`;
	}

	/** onOpen(conversation) is called to show a conversation (a new one, or the one that already existed). */
	function open(onOpen) {
		search_step(onOpen);
	}

	function search_step(onOpen) {
		let timer = null;
		let seq = 0;
		const dialog = new frappe.ui.Dialog({
			title: __("New conversation"),
			fields: [
				{ fieldtype: "HTML", fieldname: "intro", options: `<p class="text-muted" style="margin-bottom:6px">${__("Find the Lead, Contact or Customer you want to message. Only people in the ERP can be messaged.")}</p>` },
				{ fieldtype: "Data", fieldname: "q", label: __("Name, company or phone"), reqd: 0 },
				{ fieldtype: "HTML", fieldname: "results" },
			],
		});
		dialog.get_primary_btn().hide();
		const $res = dialog.get_field("results").$wrapper;
		const paint = (rows, msg) => {
			if (msg) return $res.html(`<div class="text-muted" style="padding:8px 0">${esc(msg)}</div>`);
			$res.html(
				`<div class="list-group" style="max-height:320px;overflow:auto">${rows
					.map(
						(r, i) => `<a href="#" class="list-group-item list-group-item-action waba-new-hit" data-i="${i}" style="display:flex;justify-content:space-between;gap:10px;align-items:center">
							<span><b>${esc(r.title)}</b> <span class="text-muted small">${esc(__(r.doctype))} &middot; ${esc(r.name)}</span></span>
							<span class="text-muted small">${r.has_phone ? esc(r.phone_hint) : esc(__("no usable phone"))}</span></a>`
					)
					.join("")}</div>`
			);
			$res.find(".waba-new-hit").on("click", (ev) => {
				ev.preventDefault();
				const r = rows[$(ev.currentTarget).data("i")];
				dialog.hide();
				message_step(r.doctype, r.name, onOpen);
			});
		};
		dialog.get_field("q").$input.on("input", (ev) => {
			clearTimeout(timer);
			const text = ev.target.value.trim();
			if (text.length < 2) return paint([], __("Type at least two letters or four digits."));
			timer = setTimeout(() => {
				const mine = ++seq;
				frappe.call({ method: "waba.api.party.search_people", args: { query: text }, silent: true }).then((r) => {
					if (mine !== seq) return;
					const rows = (r && r.message) || [];
					paint(rows, rows.length ? "" : __("Nobody found. Add them as a Lead in the ERP first."));
				});
			}, 250);
		});
		dialog.show();
		setTimeout(() => dialog.get_field("q").$input.trigger("focus"), 200);
	}

	function load_template_form() {
		if (window.WabaTemplateForm) return Promise.resolve();
		return frappe.call({ method: "waba.api.inbox.assets_version", silent: true }).then((r) => {
			const v = encodeURIComponent((r && r.message) || "0");
			const base = "/assets/waba/js";
			const lib = window.WabaLib ? Promise.resolve() : $.ajax({ url: `${base}/waba_inbox_lib.js?v=${v}`, dataType: "script", cache: true });
			return Promise.resolve(lib).then(() => $.ajax({ url: `${base}/waba_template_dialog.js?v=${v}`, dataType: "script", cache: true }));
		});
	}

	function message_step(doctype, name, onOpen) {
		frappe.call({ method: "waba.api.party.context", args: { doctype, name, utility_only: 1 }, freeze: true }).then((r) => {
			const ctx = r && r.message;
			if (!ctx) return;
			load_template_form().then(() => build(doctype, name, ctx, onOpen));
		});
	}

	function build(doctype, name, ctx, onOpen) {
		const numbers = ctx.numbers || [];
		const phones = (ctx.phones || []).filter((p) => p.key);
		const numberByLabel = Object.fromEntries(numbers.map((n) => [n.label, n]));
		const phoneByLabel = Object.fromEntries(phones.map((p) => [`${p.raw}${p.label ? " (" + p.label + ")" : ""}`, p]));
		const wrote = (ctx.conversations || []).some((c) => c.last_inbound_at);
		let dialog;

		const existing = () => {
			const n = numberByLabel[dialog.get_value("number")];
			return n ? (ctx.conversations || []).find((c) => c.waba_number === n.name) : null;
		};
		const reason = () => {
			const n = numberByLabel[dialog.get_value("number")];
			if (!numbers.length) return __("You are not set up to send from any WhatsApp number.");
			if (!phones.length) return __("This record has no phone number WhatsApp can use. Fix the number on the record first.");
			if (existing()) return __("This person already has a conversation on this number.");
			if (ctx.consent.opted_out) return __("This customer has opted out of WhatsApp messages.");
			if (!wrote && ctx.consent.state !== "Yes") return __("There is no WhatsApp consent on this record. Record it on the record first, or wait for the customer to message you.");
			if (n && !n.templates.length) return __("No approved Utility template for this number. Press Meta, Sync templates on its WhatsApp Account, or write one under Setup > Templates.");
			return "";
		};
		const refresh_state = () => {
			if (!dialog) return;
			const why = reason();
			const open_btn = existing() ? `<button class="btn btn-xs btn-default waba-open-existing" style="margin-left:8px">${__("Open chat")}</button>` : "";
			dialog.get_field("problem").$wrapper.html(why ? `<div class="alert alert-warning" style="margin:0">${esc(why)}${open_btn}</div>` : "");
			dialog.get_field("problem").$wrapper.find(".waba-open-existing").on("click", () => {
				dialog.hide();
				onOpen(existing().name);
			});
			const form_ok = dialog.tplctl ? dialog.tplctl.form.sendable : false;
			dialog.get_primary_btn().prop("disabled", !!why || !form_ok);
		};
		const fill_templates = () => {
			if (!dialog) return;
			const n = numberByLabel[dialog.get_value("number")];
			const list = n ? n.templates : [];
			dialog.templates = Object.fromEntries(list.map((t) => [t.title, t]));
			const field = dialog.get_field("template");
			field.df.options = list.map((t) => t.title).join("\n");
			field.refresh();
			Promise.resolve(dialog.set_value("template", list.length ? list[0].title : "")).then(show_template);
		};
		const show_template = () => {
			if (!dialog) return;
			const t = (dialog.templates || {})[dialog.get_value("template")];
			const n = numberByLabel[dialog.get_value("number")];
			const $box = dialog.get_field("tplform").$wrapper;
			dialog.tplctl = null;
			if (!t || !n) {
				$box.html("");
				return refresh_state();
			}
			$box.html(`<div class="text-muted small">${__("Loading...")}</div>`);
			refresh_state();
			frappe.call({ method: "waba.api.party.template_form", args: { doctype, name, number: n.name, template: t.name } }).then((r) => {
				if (dialog.get_value("template") !== t.title) return;
				dialog.tplctl = new window.WabaTemplateForm($box, r.message);
				refresh_state();
			});
		};

		dialog = new frappe.ui.Dialog({
			title: __("New conversation: {0}", [ctx.title]),
			fields: [
				{ fieldtype: "HTML", fieldname: "consent", options: `<div style="margin-bottom:8px">${consent_html(ctx)}</div>` },
				{ fieldtype: "HTML", fieldname: "problem" },
				{ fieldname: "number", label: __("Send from"), fieldtype: "Select", options: numbers.map((n) => n.label).join("\n"), default: numbers.length ? numbers[0].label : "", reqd: 1, change: fill_templates },
				{ fieldname: "phone", label: __("To"), fieldtype: "Select", options: Object.keys(phoneByLabel).join("\n"), default: Object.keys(phoneByLabel)[0] || "", reqd: 1 },
				{ fieldname: "template", label: __("Template"), fieldtype: "Select", reqd: 1, change: show_template },
				{ fieldtype: "HTML", fieldname: "tplform" },
			],
			primary_action_label: __("Send"),
			primary_action: (values) => {
				const tpl = dialog.templates[values.template];
				const ctl = dialog.tplctl;
				if (!tpl || !ctl) return;
				const typed = ctl.collect();
				if (!typed.ok) return frappe.show_alert({ message: __("Fill in every value first."), indicator: "orange" }, 4);
				dialog.get_primary_btn().prop("disabled", true);
				ctl
					.upload(typed.values)
					.then((vals) =>
						frappe.call({
							method: "waba.api.party.start_chat",
							args: { doctype, name, number: numberByLabel[values.number].name, phone: phoneByLabel[values.phone].raw, template: tpl.name, params: vals },
							freeze: true,
							freeze_message: __("Sending..."),
						})
					)
					.then((r) => {
						const out = r.message || {};
						dialog.hide();
						if (out.existing) {
							frappe.show_alert({ message: out.error, indicator: "blue" }, 4);
							return onOpen(out.existing);
						}
						if (out.ok) {
							frappe.show_alert({ message: __("Sent."), indicator: "green" }, 5);
							return onOpen(out.conversation);
						}
						frappe.msgprint({ title: __("Not sent"), message: esc(out.error || __("Meta did not accept the message.")), indicator: "red" });
						if (out.conversation) onOpen(out.conversation);
					})
					.catch(() => dialog.get_primary_btn().prop("disabled", false));
			},
		});
		dialog.show();
		fill_templates();
	}

	window.WabaStartChat = { open };
})();
