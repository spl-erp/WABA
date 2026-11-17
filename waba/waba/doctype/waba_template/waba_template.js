/* The template form. A DRAFT or REJECTED template can be written and sent to Meta from here; every other one is read-only and
 * follows Meta. Saving never sends anything: Submit to Meta does, and only after the server has checked the draft. */
frappe.ui.form.on("Waba Template", {
	setup(frm) {
		frm.set_query("header_sample", () => ({ filters: { enabled: 1 } }));
	},

	onload(frm) {
		if (!frm.is_new()) return;
		if (!frm.doc.status) frm.set_value("status", "DRAFT");
		if (!frm.doc.language) frm.set_value("language", "en");
		if (!frm.doc.category) frm.set_value("category", "UTILITY");
		if (!frm.doc.account) {
			frappe.db.get_list("Waba Account", { filters: { enabled: 1 }, fields: ["name"], limit: 2 }).then((rows) => {
				if (rows && rows.length === 1) frm.set_value("account", rows[0].name);
			});
		}
	},

	refresh(frm) {
		const editable = frm.is_new() || ["DRAFT", "REJECTED"].includes(frm.doc.status);
		frm.dashboard.clear_headline();
		if (editable) {
			frm.set_intro("");
			if (frm.is_new()) frm.set_intro(__("Write the template, then save. After saving you will see a row for each value; give each an example (Meta needs them), then press Submit to Meta."), "blue");
			else if (frm.doc.draft_problems) frm.set_intro(__("Still needed before it can be submitted:") + "<br>" + frm.doc.draft_problems.split("\n").map((p) => frappe.utils.escape_html(p)).join("<br>"), "orange");
			else frm.set_intro(__("This draft is ready. It is not at Meta until you press Submit to Meta."), "green");
		} else {
			frm.set_intro("");
			const tone = { APPROVED: "green", PENDING: "orange", REJECTED: "red", PAUSED: "red", DISABLED: "red", DELETED: "gray" }[frm.doc.status] || "blue";
			frm.dashboard.set_headline(`${frm.doc.status}${frm.doc.rejected_reason ? ": " + frm.doc.rejected_reason : ""}`, tone);
		}
		render_preview(frm);
		if (!frm.is_new() && editable) {
			frm.add_custom_button(__("Submit to Meta"), () => {
				if (frm.is_dirty()) return frappe.msgprint(__("Save the template first."));
				frappe.confirm(__("Send {0} to Meta for review? You cannot edit it while it is being reviewed.", [frm.doc.template_name]), () => {
					frappe.call({ method: "waba.api.templates.submit", args: { template: frm.doc.name }, freeze: true, freeze_message: __("Sending to Meta...") }).then((r) => {
						const out = r.message || {};
						if (out.ok) frappe.show_alert({ message: out.note || __("Sent to Meta."), indicator: "green" }, 8);
						else frappe.msgprint({ title: __("Meta did not accept it"), message: frappe.utils.escape_html(out.error || ""), indicator: "red" });
						frm.reload_doc();
					});
				});
			}).addClass("btn-primary");
			if (frm.doc.status === "DRAFT") {
				frm.add_custom_button(__("Delete draft"), () =>
					frappe.confirm(__("Delete this draft?"), () =>
						frappe.call({ method: "waba.api.templates.delete", args: { template: frm.doc.name } }).then(() => frappe.set_route("List", "Waba Template"))
					)
				);
			}
		}
		if (!frm.is_new() && frm.doc.components_json && frm.doc.status !== "DRAFT") {
			frm.add_custom_button(__("Copy as new draft"), () =>
				frappe.call({ method: "waba.api.templates.duplicate", args: { template: frm.doc.name }, freeze: true }).then((r) => {
					if (r.message && r.message.draft) frappe.set_route("Form", "Waba Template", r.message.draft);
				})
			);
		}
		if (!frm.is_new() && frm.doc.meta_template_id && !["DRAFT", "DELETED"].includes(frm.doc.status)) {
			frm.add_custom_button(__("Delete at Meta"), () => {
				frappe.prompt(
					[{ fieldname: "confirm", label: __("Type the template name to confirm"), fieldtype: "Data", reqd: 1, description: __("This deletes the {0} version of {1} at Meta.", [frm.doc.language, frm.doc.template_name]) }],
					(v) => {
						if (v.confirm !== frm.doc.template_name) return frappe.msgprint(__("The name does not match."));
						frappe.call({ method: "waba.api.templates.delete", args: { template: frm.doc.name }, freeze: true }).then((r) => {
							const out = r.message || {};
							if (out.ok) frappe.show_alert({ message: __("Deleted at Meta."), indicator: "orange" }, 6);
							else frappe.msgprint({ title: __("Not deleted"), message: frappe.utils.escape_html(out.error || ""), indicator: "red" });
							frm.reload_doc();
						});
					},
					__("Delete at Meta"),
					__("Delete")
				);
			}, __("More"));
		}
	},

	header_format: (frm) => render_preview(frm),
	header_text: (frm) => render_preview(frm),
	body_text: (frm) => render_preview(frm),
	footer_text: (frm) => render_preview(frm),
});

frappe.ui.form.on("Waba Template Button", {
	buttons_remove: (frm) => render_preview(frm),
	text: (frm) => render_preview(frm),
	type: (frm) => render_preview(frm),
});

frappe.ui.form.on("Waba Template Variable", {
	example: (frm) => render_preview(frm),
});

/** The template the way the customer will see it, with the examples in. */
function render_preview(frm) {
	const e = frappe.utils.escape_html;
	frm.dashboard.parent.find(".waba-draft-preview").closest(".form-dashboard-section").remove();
	if (!frm.doc.body_text && !frm.doc.header_text) return;
	const examples = Object.fromEntries((frm.doc.variables || []).filter((r) => r.example).map((r) => [r.slot, r.example]));
	const fill = (text, component) => String(text || "").replace(/\{\{\s*([A-Za-z0-9_]+)\s*\}\}/g, (whole, key) => examples[`${component}.${key}`] || whole);
	const head = frm.doc.header_format === "TEXT" ? `<div style="font-weight:700;margin-bottom:4px">${e(fill(frm.doc.header_text, "header"))}</div>` : frm.doc.header_format ? `<div style="margin-bottom:4px"><span style="display:inline-block;padding:2px 10px;border-radius:999px;background:rgba(0,0,0,.08);font-size:12px;font-weight:600">${e(frm.doc.header_format.toLowerCase())}</span></div>` : "";
	const names = { COPY_CODE: __("Copy code"), URL: __("Open link"), PHONE_NUMBER: __("Call"), QUICK_REPLY: __("Reply") };
	const buttons = (frm.doc.buttons || []).filter((b) => b.type).map((b) => `<span style="display:inline-block;padding:4px 10px;margin:4px 4px 0 0;border-radius:8px;background:#fff;color:#0a7cff;font-weight:600;font-size:13px">${e(b.text || names[b.type] || b.type)}</span>`).join("");
	const html = `<div class="waba-draft-preview" style="background:#e7f6ec;border-radius:12px;padding:12px 14px;max-width:440px">${head}<div style="white-space:pre-wrap">${e(fill(frm.doc.body_text, "body"))}</div>${frm.doc.footer_text ? `<div style="color:#667781;font-size:12px;margin-top:6px">${e(frm.doc.footer_text)}</div>` : ""}${buttons ? `<div>${buttons}</div>` : ""}</div>`;
	frm.dashboard.add_section(html, __("Preview"));
	frm.dashboard.show();
}
