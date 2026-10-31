/* WhatsApp on the Lead, Contact and Customer forms (added through hooks.doctype_js; nothing of the other scripts is touched).
 *
 * A "WhatsApp" button group (message, record consent, open conversation) and a WhatsApp section in the form dashboard with
 * the consent state and this customer's conversations. Everything is decided on the server (waba.api.party.*): this file
 * only shows what the server says and disables Send, with the reason, when it already knows the answer will be no. */
(function () {
	const DOCTYPES = ["Lead", "Contact", "Customer"];
	const ROLES = ["Waba Agent", "Waba Supervisor", "Waba Admin", "System Manager"];
	const esc = (v) => frappe.utils.escape_html(v == null ? "" : String(v));
	const allowed = () => ROLES.some((r) => frappe.user.has_role(r));

	DOCTYPES.forEach((doctype) => {
		frappe.ui.form.on(doctype, {
			refresh(frm) {
				waba_party_refresh(frm);
			},
		});
	});

	function waba_party_refresh(frm) {
		if (frm.is_new() || !allowed()) return;
		frappe.call({ method: "waba.api.party.context", args: { doctype: frm.doctype, name: frm.doc.name }, silent: true }).then((r) => {
			const ctx = r && r.message;
			if (!ctx || frm.doc.name !== (ctx.name || frm.doc.name)) return;
			frm.__waba = ctx;
			render_dashboard(frm, ctx);
			add_buttons(frm, ctx);
		});
	}

	// ------------------------------------------------------------------------------------------- the form's WhatsApp section

	function marketing_text(ctx) {
		const m = (ctx.consent && ctx.consent.marketing) || { state: "Unknown" };
		return ` <span class="text-muted">&middot; ${__("Marketing")}: ${esc(m.state === "Yes" ? __("Yes") : m.state === "No" ? __("No") : __("Not recorded"))}</span>`;
	}

	function consent_line(ctx) {
		return consent_core(ctx) + marketing_text(ctx);
	}

	function consent_core(ctx) {
		const c = ctx.consent;
		const when = c.on ? ` &middot; ${esc(frappe.datetime.str_to_user(c.on))}` : "";
		const src = c.source ? ` &middot; ${esc(c.source)}` : "";
		if (c.opted_out) return `<span class="indicator-pill red">${__("Opted out")}</span> <span class="text-muted">${c.flag ? __("The record is marked do not contact.") : esc(c.source || "")}${when}</span>`;
		if (c.state === "Yes") return `<span class="indicator-pill green">${__("WhatsApp consent: Yes")}</span> <span class="text-muted">${when.replace(/^ &middot; /, "")}${src}</span>`;
		return `<span class="indicator-pill orange">${__("No WhatsApp consent recorded")}</span> <span class="text-muted">${__("First messages need it; a customer who writes to you first does not.")}</span>`;
	}

	function render_dashboard(frm, ctx) {
		frm.dashboard.parent.find(".waba-dash").closest(".custom").remove();
		const rows = (ctx.conversations || [])
			.map(
				(c) => `<tr>
				<td>${esc(c.number_name)}</td>
				<td>${esc(c.status)}${c.opted_out ? ` <span class="indicator-pill red">${__("Opted out")}</span>` : ""}</td>
				<td>${c.window_open ? `<span class="indicator-pill green">${__("Window open")}</span>` : `<span class="indicator-pill gray">${__("Window closed")}</span>`}</td>
				<td class="text-muted">${esc((c.last_message_preview || "").slice(0, 60))}</td>
				<td><a href="#" class="waba-open-conv" data-name="${esc(c.name)}">${__("Open in inbox")}</a></td></tr>`
			)
			.join("");
		const table = rows
			? `<table class="table table-sm" style="margin:8px 0 0"><tbody>${rows}</tbody></table>`
			: `<div class="text-muted" style="margin-top:6px">${__("No WhatsApp conversation with this customer that you may see.")}</div>`;
		const $body = frm.dashboard.add_section(`<div class="waba-dash">${consent_line(ctx)}${table}</div>`, __("WhatsApp"));
		frm.dashboard.show(); // the form's dashboard area stays hidden until a script asks for it
		$body.find(".waba-open-conv").on("click", (ev) => {
			ev.preventDefault();
			open_conversation($(ev.currentTarget).data("name"));
		});
	}

	function open_conversation(name) {
		window.waba_open_conversation = name;
		frappe.set_route("waba-inbox");
	}

	// ------------------------------------------------------------------------------------------- buttons

	function add_buttons(frm, ctx) {
		const group = __("WhatsApp");
		frm.add_custom_button(__("Message on WhatsApp"), () => message_dialog(frm, ctx), group);
		if (ctx.can_record_consent) {
			frm.add_custom_button(__("Record WhatsApp consent"), () => consent_dialog(frm, ctx, "Yes"), group);
			if (ctx.consent.state === "Yes") frm.add_custom_button(__("Withdraw WhatsApp consent"), () => consent_dialog(frm, ctx, "No"), group);
			frm.add_custom_button(__("Record WhatsApp marketing consent"), () => consent_dialog(frm, ctx, "Yes", "marketing"), group);
			if (ctx.consent.marketing && ctx.consent.marketing.state === "Yes") frm.add_custom_button(__("Withdraw WhatsApp marketing consent"), () => consent_dialog(frm, ctx, "No", "marketing"), group);
		}
		if ((ctx.conversations || []).length) {
			frm.add_custom_button(__("Open WhatsApp conversation"), () => open_conversation(ctx.conversations[0].name), group);
		}
	}

	// ------------------------------------------------------------------------------------------- record or withdraw consent

	function consent_dialog(frm, ctx, state, purpose = "service") {
		const yes = state === "Yes";
		const marketing = purpose === "marketing";
		const dialog = new frappe.ui.Dialog({
			title: marketing ? (yes ? __("Record WhatsApp marketing consent") : __("Withdraw WhatsApp marketing consent")) : yes ? __("Record WhatsApp consent") : __("Withdraw WhatsApp consent"),
			fields: [
				{
					fieldtype: "HTML",
					fieldname: "intro",
					options: `<p class="text-muted">${
						yes
							? marketing
								? __("Only record this when the customer has clearly agreed to receive promotions and offers on WhatsApp. This is separate from order and service messages.")
								: __("Only record this when the customer has clearly agreed to receive WhatsApp messages from Splashjet.")
							: marketing
							? __("The customer will no longer be sent promotions or offers. Order and service messages are not affected.")
							: __("The customer will no longer be sent any WhatsApp template.")
					}</p>`,
				},
				{ fieldname: "source", label: yes ? __("How did they agree?") : __("Reason"), fieldtype: "Select", options: (yes ? [""].concat(ctx.sources) : ["", __("Customer asked"), __("Wrong number"), "Other"]).join("\n"), reqd: 1 },
				{ fieldname: "on", label: __("Date"), fieldtype: "Date", default: frappe.datetime.get_today(), reqd: 1 },
			],
			primary_action_label: yes ? __("Record consent") : __("Withdraw consent"),
			primary_action: (values) => {
				dialog.hide();
				frappe.call({ method: "waba.api.party.record_consent", args: { doctype: frm.doctype, name: frm.doc.name, consent: state, source: values.source, on: values.on, purpose } }).then(() => {
					frappe.show_alert({ message: yes ? __("Consent recorded.") : __("Consent withdrawn."), indicator: yes ? "green" : "orange" }, 4);
					frm.reload_doc();
				});
			},
		});
		dialog.show();
	}

	// ------------------------------------------------------------------------------------------- message dialog

	function message_dialog(frm, ctx) {
		const numbers = ctx.numbers || [];
		const phones = (ctx.phones || []).filter((p) => p.key);
		const numberByLabel = Object.fromEntries(numbers.map((n) => [n.label, n]));
		const phoneByLabel = Object.fromEntries(phones.map((p) => [`${p.raw}${p.label ? " (" + p.label + ")" : ""}`, p]));
		const wrote = (ctx.conversations || []).some((c) => c.last_inbound_at);
		let dialog;

		const reason = () => {
			const v = dialog.get_values(true) || {};
			const n = numberByLabel[v.number];
			if (!numbers.length) return __("You are not set up to send from any WhatsApp number.");
			if (!phones.length) return __("This record has no phone number WhatsApp can use. Fix the number on the record first.");
			if (ctx.consent.opted_out) return __("This customer has opted out of WhatsApp messages.");
			if (!wrote && ctx.consent.state !== "Yes") return __("There is no WhatsApp consent on this record. Record it first, or wait for the customer to message you.");
			if (n && !n.templates.length) return __("No approved Utility template for this number. Press Meta, Sync templates on its WhatsApp Account.");
			return "";
		};
		const refresh_state = () => {
			if (!dialog) return;
			const why = reason();
			dialog.get_field("problem").$wrapper.html(why ? `<div class="alert alert-warning" style="margin:0">${esc(why)}</div>` : "");
			dialog.get_primary_btn().prop("disabled", !!why);
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
			dialog.get_field("preview").$wrapper.html(t ? `<div class="text-muted small">${t.variable_count} ${__("value(s)")} &middot; ${esc(t.language)}</div><pre style="white-space:pre-wrap;margin:4px 0 0">${esc(t.body_text)}</pre>` : "");
			refresh_state();
		};

		dialog = new frappe.ui.Dialog({
			title: __("WhatsApp: {0}", [ctx.title]),
			fields: [
				{ fieldtype: "HTML", fieldname: "consent", options: `<div style="margin-bottom:8px">${consent_line(ctx)}</div>` },
				{ fieldtype: "HTML", fieldname: "problem" },
				{ fieldname: "number", label: __("Send from"), fieldtype: "Select", options: numbers.map((n) => n.label).join("\n"), default: numbers.length ? numbers[0].label : "", reqd: 1, change: fill_templates },
				{ fieldname: "phone", label: __("To"), fieldtype: "Select", options: Object.keys(phoneByLabel).join("\n"), default: Object.keys(phoneByLabel)[0] || "", reqd: 1 },
				{ fieldname: "template", label: __("Template (Utility)"), fieldtype: "Select", reqd: 1, change: show_template },
				{ fieldtype: "HTML", fieldname: "preview" },
				{ fieldname: "values", label: __("Values"), fieldtype: "Small Text", description: __("One value per line, in order: the first line fills {{1}}, the second {{2}}, and so on.") },
			],
			primary_action_label: __("Send"),
			primary_action: (values) => {
				const tpl = dialog.templates[values.template];
				if (!tpl) return;
				dialog.get_primary_btn().prop("disabled", true);
				frappe
					.call({
						method: "waba.api.party.start",
						args: { doctype: frm.doctype, name: frm.doc.name, number: numberByLabel[values.number].name, phone: phoneByLabel[values.phone].raw, template: tpl.name, params: values.values || "" },
						freeze: true,
						freeze_message: __("Sending..."),
					})
					.then((r) => {
						const out = r.message || {};
						dialog.hide();
						if (out.ok) frappe.show_alert({ message: __("Sent."), indicator: "green" }, 6, { [__("Open")]: () => open_conversation(out.conversation) });
						else frappe.msgprint({ title: __("Not sent"), message: out.error || __("Meta did not accept the message."), indicator: "red" });
						frm.reload_doc();
					})
					.catch(() => dialog.get_primary_btn().prop("disabled", false));
			},
		});
		if (ctx.can_record_consent && !wrote && ctx.consent.state !== "Yes" && !ctx.consent.opted_out) {
			dialog.set_secondary_action_label(__("Record consent"));
			dialog.set_secondary_action(() => {
				dialog.hide();
				consent_dialog(frm, ctx, "Yes");
			});
		}
		dialog.show();
		fill_templates();
	}
})();
