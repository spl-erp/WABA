/* Review and send a waiting WhatsApp notification (Manual mode).
 *
 * One dialog used from the Notification Log list and form, and from the "WhatsApp" button on a Quotation, Sales Invoice or Lead.
 * It shows exactly what would go out, filled in from the record, and anything standing in the way. Everything is decided on the
 * server (waba.notify.preview / approve / dismiss); a message is sent only when a person presses Send, and the same checks as an
 * automatic send run again at that moment. Needs waba_inbox_lib.js. */
(function () {
	const e = (v) => WabaLib.escapeHtml(v);

	function review(log, done) {
		frappe.call({ method: "waba.notify.preview", args: { log } }).then((r) => {
			const f = r.message;
			if (!f) return;
			const blockers = [];
			if (f.problem_record) blockers.push(f.problem_record);
			if (f.hold) blockers.push(f.hold);
			if (!f.sendable) blockers.push(f.problem);
			if ((f.unfilled || []).length) {
				const names = f.slots.filter((s) => s.needs_input).map((s) => s.label);
				blockers.push(__("The record cannot fill these values: {0}. Set where they come from in the template's variable map.", [names.join(", ")]));
			}
			const p = f.preview || {};
			const buttons = (f.parts.buttons || []).map((b) => `<span style="display:inline-block;padding:4px 10px;margin:4px 4px 0 0;border-radius:8px;background:#fff;color:#0a7cff;font-weight:600;font-size:13px">${e(b.text || b.type)}</span>`).join("");
			const card = `<div style="background:#e7f6ec;border-radius:12px;padding:12px 14px;max-width:440px">
				${p.header ? `<div style="font-weight:700;margin-bottom:4px">${e(p.header)}</div>` : ""}
				<div style="white-space:pre-wrap">${e(p.body)}</div>
				${p.footer ? `<div style="color:#667781;font-size:12px;margin-top:6px">${e(p.footer)}</div>` : ""}${buttons ? `<div>${buttons}</div>` : ""}</div>`;
			const warn = blockers.length ? `<div class="alert alert-warning" style="margin-top:12px">${blockers.map((b) => e(b)).join("<br>")}</div>` : "";
			const dialog = new frappe.ui.Dialog({
				title: __("Review: {0}", [e(f.rule_name)]),
				fields: [{ fieldtype: "HTML", fieldname: "body" }],
				primary_action_label: __("Send now"),
				primary_action: () => {
					dialog.get_primary_btn().prop("disabled", true);
					frappe.call({ method: "waba.notify.approve", args: { log }, freeze: true, freeze_message: __("Sending...") }).then((res) => {
						const out = res.message || {};
						dialog.hide();
						if (out.ok) frappe.show_alert({ message: __("Sent."), indicator: "green" }, 5);
						else frappe.msgprint({ title: __("Not sent"), message: e(out.error || __("Refused.")), indicator: "red" });
						if (done) done(out);
					});
				},
				secondary_action_label: __("Dismiss"),
				secondary_action: () => {
					frappe.prompt([{ fieldname: "reason", label: __("Why? (optional)"), fieldtype: "Small Text" }], (v) => {
						frappe.call({ method: "waba.notify.dismiss", args: { log, reason: v.reason || "" } }).then(() => {
							dialog.hide();
							frappe.show_alert({ message: __("Dismissed."), indicator: "orange" }, 4);
							if (done) done({ ok: false, dismissed: true });
						});
					}, __("Dismiss this message"), __("Dismiss"));
				},
			});
			dialog.get_field("body").$wrapper.html(
				`<div class="text-muted small" style="margin-bottom:8px">${e(__("To"))} <b>${e(f.phone || "")}</b> &middot; ${e(f.title)}</div>${card}${warn}`
			);
			dialog.get_primary_btn().prop("disabled", blockers.length > 0);
			dialog.show();
		});
	}

	/** From a Quotation, Sales Invoice or Lead form: put a message for this document in the waiting list and review it. */
	function for_document(doctype, name) {
		frappe.call({ method: "waba.notify.prepare_for_document", args: { doctype, name } }).then((r) => {
			if (r.message && r.message.log) review(r.message.log);
		});
	}

	window.WabaNotifyUI = { review, for_document };
})();
