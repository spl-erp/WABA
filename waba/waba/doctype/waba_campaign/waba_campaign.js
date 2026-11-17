// The campaign form: choose the message, review, send a test, submit by typing the name, then watch and steer it.
const WABA_CAMPAIGN_STATES = { Draft: "gray", "Pending approval": "orange", Scheduled: "blue", Running: "green", Paused: "orange", Done: "green", Cancelled: "red", Rejected: "red" };

frappe.ui.form.on("Waba Campaign", {
	refresh(frm) {
		frm.disable_save();
		if (frm.is_new()) return;
		const s = frm.doc.status;
		frm.page.set_indicator(__(s), WABA_CAMPAIGN_STATES[s] || "gray");
		frm.dashboard.clear_headline();
		if (frm.doc.pause_reason) frm.dashboard.set_headline_alert(frappe.utils.escape_html(frm.doc.pause_reason), s === "Cancelled" ? "red" : "orange");
		const call = (method, args, done) => frappe.call({ method: `waba.api.campaigns.${method}`, args: { campaign: frm.doc.name, ...(args || {}) }, freeze: true }).then((r) => (done ? done(r.message) : frm.reload_doc()));
		if (s === "Draft") {
			frm.add_custom_button(__("Choose message"), () => choose_message(frm));
			if (frm.doc.template) frm.add_custom_button(__("Message values"), () => message_values(frm));
			frm.add_custom_button(__("Review"), () => review(frm), __("Check"));
			frm.add_custom_button(__("Send test"), () => send_test(frm), __("Check"));
			frm.add_custom_button(__("Save"), () => frm.save());
			frm.add_custom_button(__("Submit campaign"), () => submit(frm)).addClass("btn-primary");
		}
		if (s === "Pending approval" && frappe.user.has_role("Waba Admin")) {
			frm.add_custom_button(__("Approve"), () => call("approve")).addClass("btn-primary");
			frm.add_custom_button(__("Reject"), () => frappe.prompt({ fieldname: "reason", fieldtype: "Small Text", label: __("Why?"), reqd: 1 }, (v) => call("reject", { reason: v.reason })));
		}
		if (["Scheduled", "Running"].includes(s)) frm.add_custom_button(__("Pause"), () => call("pause"));
		if (s === "Paused") frm.add_custom_button(__("Resume"), () => call("resume")).addClass("btn-primary");
		if (["Scheduled", "Running", "Paused"].includes(s)) frm.add_custom_button(__("Reschedule"), () => reschedule(frm, call));
		if (["Scheduled", "Running", "Paused", "Pending approval", "Draft"].includes(s)) frm.add_custom_button(__("Cancel campaign"), () => frappe.confirm(__("Stop this campaign? What has not been sent will not go."), () => call("cancel")), __("More"));
		if (s !== "Draft") frm.add_custom_button(__("Check progress"), () => paint_progress(frm));
		if (frm.doc.recipient_set) frm.add_custom_button(__("Open the Set"), () => frappe.set_route("Form", "Waba Recipient Set", frm.doc.recipient_set), __("More"));
		if (s !== "Draft") frm.add_custom_button(__("See recipients"), () => frappe.set_route("List", "Waba Campaign Recipient", { campaign: frm.doc.name }), __("More"));
		paint_progress(frm);
	},
});

function paint_progress(frm) {
	const wrap = frm.fields_dict.stats_html && frm.fields_dict.stats_html.$wrapper;
	if (!wrap) return;
	frappe.call({ method: "waba.api.campaigns.progress", args: { campaign: frm.doc.name } }).then((r) => {
		const d = r.message;
		if (!d) return;
		const c = d.counts;
		const card = (label, value) => `<div style="flex:1 1 110px;border:1px solid var(--border-color);border-radius:8px;padding:8px 10px;background:var(--control-bg)"><div style="font-size:20px;font-weight:600">${value}</div><div class="text-muted small">${label}</div></div>`;
		const rate = c.sent ? Math.round((c.replied * 100) / c.sent) + "%" : "-";
		const why = (d.reasons || []).map((x) => `<li>${frappe.utils.escape_html(x.status)}: ${frappe.utils.escape_html(x.reason || "")} (${x.n})</li>`).join("");
		wrap.html(`<div style="display:flex;gap:8px;flex-wrap:wrap">${card(__("Attempted"), c.attempted)}${card(__("Sent"), c.sent)}${card(__("Delivered"), c.delivered)}${card(__("Read"), c.read)}${card(__("Replied"), c.replied)}${card(__("Reply rate"), rate)}${card(__("Limited by Meta"), c.limited)}${card(__("Other failures"), c.failed)}${card(__("Waiting"), c.pending)}${card(__("Skipped"), c.skipped)}</div>
			${d.next_run_on ? `<div class="text-muted small" style="margin-top:6px">${__("Next run on {0}.", [d.next_run_on])}</div>` : ""}
			${d.backoff_until ? `<div class="text-muted small">${__("Waiting until {0} because Meta asked us to slow down.", [d.backoff_until])}</div>` : ""}
			${why ? `<div style="margin-top:8px"><b>${__("Why some did not go")}</b><ul>${why}</ul></div>` : ""}`);
	});
}

function choose_message(frm) {
	frappe.call({ method: "waba.api.campaigns.campaign_numbers" }).then((r) => {
		const numbers = r.message || [];
		if (!numbers.length) return frappe.msgprint(__("No number is switched on for Campaigns. Open a Waba Number and tick Campaigns."));
		const label = (n) => `${n.name} · ${n.display_name || n.display_number}${n.receive_only ? " (receive only)" : ""}`;
		let templates = [];
		const dialog = new frappe.ui.Dialog({
			title: __("Choose the message"),
			fields: [
				{ fieldname: "number", fieldtype: "Select", label: __("Send from"), reqd: 1, options: numbers.map(label).join("\n"), default: frm.doc.waba_number ? label(numbers.find((n) => n.name === frm.doc.waba_number) || numbers[0]) : label(numbers[0]), change: () => load_templates() },
				{ fieldname: "template", fieldtype: "Select", label: __("Template"), reqd: 1, options: "" },
				{ fieldtype: "HTML", fieldname: "note" },
			],
			primary_action_label: __("Use this message"),
			primary_action: (v) => {
				const n = numbers.find((x) => label(x) === v.number);
				const t = templates.find((x) => `${x.title} (${x.category.toLowerCase()}, ${x.language})` === v.template);
				if (!n || !t) return;
				frappe.call({ method: "waba.api.campaigns.set_message", args: { campaign: frm.doc.name, number: n.name, template: t.name }, freeze: true }).then(() => {
					dialog.hide();
					frm.reload_doc().then(() => message_values(frm));
				});
			},
		});
		function load_templates() {
			const n = numbers.find((x) => label(x) === dialog.get_value("number"));
			if (!n) return;
			frappe.call({ method: "waba.api.campaigns.template_choices", args: { number: n.name } }).then((res) => {
				templates = res.message || [];
				dialog.set_df_property("template", "options", templates.map((t) => `${t.title} (${t.category.toLowerCase()}, ${t.language})`).join("\n"));
				dialog.get_field("note").$wrapper.html(templates.length ? "" : `<div class="text-muted">${__("This number's account has no approved Marketing or Utility template the ERP can send.")}</div>`);
			});
		}
		dialog.show();
		load_templates();
	});
}

const WCV_KINDS = [
	["Customer name", __("Each person's name")],
	["Record field", __("A field of each person's record")],
	["Sender name", __("Sender's name (the person running the campaign)")],
	["Today", __("Today's date")],
	["Literal", __("The same text for everyone")],
];

// Where each value in the message comes from. Nothing is typed per person: a name is taken from each person's own record,
// with a stand-in (for example Sir/Madam) for a record that has none; only fixed text (an offer code, a link) is typed, once.
function message_values(frm) {
	if (!frm.doc.template || !frm.doc.recipient_set) return frappe.msgprint(__("Choose the message first."));
	const esc = frappe.utils.escape_html;
	let current = {};
	try {
		current = (JSON.parse(frm.doc.template_values || "{}").sources) || {};
	} catch (e) {}
	let form = null;
	let state = {};
	let timer = null;
	const dialog = new frappe.ui.Dialog({
		title: __("Message values"),
		size: "large",
		fields: [{ fieldtype: "HTML", fieldname: "body" }],
		primary_action_label: __("Save"),
		primary_action: () => {
			frappe.call({ method: "waba.api.campaigns.save_values", args: { campaign: frm.doc.name, sources: JSON.stringify(state) }, freeze: true }).then(() => {
				dialog.hide();
				frm.reload_doc();
			});
		},
	});
	const $w = dialog.get_field("body").$wrapper;

	function card(p, title) {
		if (!p) return "";
		return `<div style="flex:1 1 280px"><div class="text-muted small" style="margin-bottom:4px">${title}</div>
			<div style="background:#e7f6ec;border-radius:12px;padding:10px 12px;white-space:pre-wrap">${p.header ? `<b>${esc(p.header)}</b><br>` : ""}${esc(p.body)}${p.footer ? `<div class="text-muted small" style="margin-top:6px">${esc(p.footer)}</div>` : ""}</div></div>`;
	}

	function row_html(c) {
		const s = state[c.id];
		const kinds = WCV_KINDS.map(([k, l]) => `<option value="${k}" ${s.source_type === k ? "selected" : ""}>${esc(l)}</option>`).join("");
		const fields = (form.record_fields || []).map((f) => `<option value="${esc(f.fieldname)}" ${s.source === f.fieldname ? "selected" : ""}>${esc(f.label)}</option>`).join("");
		const needs_fb = s.source_type === "Customer name" || s.source_type === "Record field";
		return `<div class="wcv-row" data-slot="${esc(c.id)}" style="border:1px solid var(--border-color);border-radius:8px;padding:10px;margin-bottom:8px">
			<div><b>${esc(c.label)}</b> <span class="text-muted small">${c.example ? __("e.g. {0}", [esc(c.example)]) : ""}</span></div>
			<div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:6px">
				<select class="form-control input-sm wcv-kind" style="flex:1 1 220px">${kinds}</select>
				${s.source_type === "Literal" ? `<input class="form-control input-sm wcv-source" style="flex:2 1 220px" placeholder="${__("Text sent to everyone")}" value="${esc(s.source)}">` : ""}
				${s.source_type === "Record field" ? `<select class="form-control input-sm wcv-source" style="flex:2 1 220px"><option value="">${__("Choose a field")}</option>${fields}</select>` : ""}
				${needs_fb ? `<input class="form-control input-sm wcv-fallback" style="flex:1 1 160px" placeholder="${__("If empty, use…")}" value="${esc(s.fallback)}">` : ""}
			</div></div>`;
	}

	function media_html() {
		return (form.slots || [])
			.filter((s) => ["image", "video", "document"].includes(s.kind))
			.map((s) => {
				const cur = (state[s.id] || {}).source || "";
				const opts = (form.shared_files || []).map((f) => `<option value="${esc(f.name)}" ${cur === f.name ? "selected" : ""}>${esc(f.title)}</option>`).join("");
				return `<div class="wcv-media" data-slot="${esc(s.id)}" style="border:1px solid var(--border-color);border-radius:8px;padding:10px;margin-bottom:8px"><b>${esc(s.label)}</b> <span class="text-muted small">${__("(the same file for everyone)")}</span><select class="form-control input-sm" style="margin-top:6px"><option value="">${__("Choose from the shared library")}</option>${opts}</select></div>`;
			})
			.join("");
	}

	function paint(full) {
		const warn = (form.warnings || []).map((w) => `<div class="alert alert-warning">${esc(w)}</div>`).join("");
		if (full) {
			$w.html(`${warn}<div class="text-muted small" style="margin-bottom:8px">${__("This message goes to everyone in the Set. Nothing is typed per person: names and fields are taken from each person's own record.")}</div>
				<div class="wcv-rows">${(form.choices || []).map(row_html).join("")}${media_html()}</div>
				<div class="wcv-previews" style="display:flex;gap:12px;flex-wrap:wrap;margin-top:10px"></div>`);
		}
		$w.find(".wcv-previews").html(card(form.preview, __("Preview for {0}", [esc(form.sample_name || __("the first person"))])) + card(form.blank_preview, __("Preview when a person's record has no value")));
	}

	function refresh() {
		clearTimeout(timer);
		timer = setTimeout(() => {
			frappe.call({ method: "waba.api.campaigns.template_form", args: { recipient_set: frm.doc.recipient_set, template: frm.doc.template, sources: JSON.stringify(state) } }).then((r) => {
				if (r.message) {
					form.preview = r.message.preview;
					form.blank_preview = r.message.blank_preview;
					paint(false);
				}
			});
		}, 300);
	}

	$w.on("change", ".wcv-kind", (ev) => {
		const slot = $(ev.target).closest(".wcv-row").data("slot");
		const kind = ev.target.value;
		state[slot] = { source_type: kind, source: "", fallback: kind === "Customer name" ? "Sir/Madam" : "" };
		const c = form.choices.find((x) => x.id === slot);
		$(ev.target).closest(".wcv-row").replaceWith(row_html(c));
		refresh();
	});
	$w.on("input change", ".wcv-source", (ev) => {
		state[$(ev.target).closest(".wcv-row").data("slot")].source = ev.target.value;
		refresh();
	});
	$w.on("input", ".wcv-fallback", (ev) => {
		state[$(ev.target).closest(".wcv-row").data("slot")].fallback = ev.target.value;
		refresh();
	});
	$w.on("change", ".wcv-media select", (ev) => {
		const slot = $(ev.target).closest(".wcv-media").data("slot");
		state[slot] = { source_type: "Shared file", source: ev.target.value, fallback: "" };
		refresh();
	});

	frappe.call({ method: "waba.api.campaigns.template_form", args: { recipient_set: frm.doc.recipient_set, template: frm.doc.template, sources: JSON.stringify(current) } }).then((r) => {
		form = r.message;
		if (!form) return;
		state = {};
		form.choices.forEach((c) => (state[c.id] = Object.assign({}, c.choice)));
		(form.slots || []).filter((s) => ["image", "video", "document"].includes(s.kind)).forEach((s) => (state[s.id] = current[s.id] || { source_type: "Shared file", source: s.value || "", fallback: "" }));
		paint(true);
	});
	dialog.show();
}

function review(frm) {
	frappe.call({ method: "waba.api.campaigns.review", args: { campaign: frm.doc.name }, freeze: true }).then((r) => {
		const d = r.message;
		if (!d) return;
		const warn = (d.warnings || []).map((w) => `<div class="alert alert-warning" style="margin:6px 0">${frappe.utils.escape_html(w)}</div>`).join("");
		frappe.msgprint({ title: __("Review"), message: `<p>${frappe.utils.escape_html(d.text)}</p>${d.approval ? `<p>${__("A Waba Admin must approve this campaign before it goes.")}</p>` : ""}${warn}`, wide: true });
		frm.reload_doc();
	});
}

function send_test(frm) {
	const d = new frappe.ui.Dialog({
		title: __("Send a test"),
		fields: [
			{ fieldname: "mine", fieldtype: "Check", label: __("Send to my own number (from my user record)"), default: 1 },
			{ fieldname: "extra", fieldtype: "Small Text", label: __("Other test numbers (one per line)"), default: frm.doc.test_numbers || "" },
			{ fieldtype: "HTML", options: `<div class="text-muted small">${__("The real message is sent to these numbers only. Test sends are not counted in the report.")}</div>` },
		],
		primary_action_label: __("Send test"),
		primary_action: (v) => {
			frappe
				.call({ method: "frappe.client.set_value", args: { doctype: "Waba Campaign", name: frm.doc.name, fieldname: "test_numbers", value: v.extra || "" } })
				.then(() => frappe.call({ method: "waba.api.campaigns.send_test", args: { campaign: frm.doc.name, include_mine: v.mine ? 1 : 0 }, freeze: true, freeze_message: __("Sending...") }))
				.then((r) => {
					d.hide();
					const rows = ((r.message && r.message.results) || []).map((x) => `<tr><td>${frappe.utils.escape_html(x.phone)}</td><td>${frappe.utils.escape_html(x.status)}</td><td>${frappe.utils.escape_html(x.reason || "")}</td></tr>`).join("");
					frappe.msgprint({ title: __("Test result"), message: `<table class="table table-bordered table-sm"><tbody>${rows}</tbody></table>` });
				});
		},
	});
	d.show();
}

function submit(frm) {
	frm.save().then(() => {
		frappe.call({ method: "waba.api.campaigns.review", args: { campaign: frm.doc.name }, freeze: true }).then((r) => {
			const d = r.message || {};
			const d2 = new frappe.ui.Dialog({
				title: __("Send to {0} people?", [d.people || 0]),
				fields: [
					{ fieldtype: "HTML", options: `<p>${frappe.utils.escape_html(d.text || "")}</p>${(d.warnings || []).map((w) => `<div class="alert alert-warning" style="margin:6px 0">${frappe.utils.escape_html(w)}</div>`).join("")}<p><b>${__("This goes to real people. Type the campaign's name to confirm:")}</b><br><code>${frappe.utils.escape_html(frm.doc.title)}</code></p>` },
					{ fieldname: "confirm", fieldtype: "Data", label: __("Campaign name"), reqd: 1 },
				],
				primary_action_label: __("Submit"),
				primary_action: (v) => {
					frappe.call({ method: "waba.api.campaigns.submit", args: { campaign: frm.doc.name, confirm_name: v.confirm }, freeze: true }).then(() => {
						d2.hide();
						frm.reload_doc();
					});
				},
			});
			d2.show();
		});
	});
}

function reschedule(frm, call) {
	frappe.prompt({ fieldname: "start_at", fieldtype: "Datetime", label: __("New time"), reqd: 1 }, (v) => call("reschedule", { start_at: v.start_at }), __("Reschedule"));
}
