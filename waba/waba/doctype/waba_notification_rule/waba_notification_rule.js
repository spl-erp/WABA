frappe.ui.form.on("Waba Notification Rule", {
	setup(frm) {
		frm.set_query("waba_number", () => ({ filters: { enabled: 1, purpose_notifications: 1 } }));
		frm.set_query("template", () => {
			const filters = { status: "APPROVED", category: "UTILITY", unsendable_reason: ["is", "not set"] };
			if (frm.__account) filters.account = frm.__account;
			return { filters };
		});
	},
	refresh(frm) {
		frm.dashboard.clear_headline();
		if (frm.doc.still_needed) frm.dashboard.set_headline(__("Still needed: {0}", [frm.doc.still_needed.split("\n").join(" ")]), "orange");
		else if (!frm.is_new()) frm.dashboard.set_headline(frm.doc.enabled ? __("This rule is switched on ({0}).", [frm.doc.mode]) : __("This rule is complete but switched off."), frm.doc.enabled ? "green" : "blue");
		frm.trigger("load_account");
		if (!frm.is_new()) {
			frm.add_custom_button(__("What would it send now?"), () => {
				frappe.call({ method: "waba.notify.would_send", args: { rule: frm.doc.name } }).then((r) => {
					const out = r.message || {};
					if (!out.ready) return frappe.msgprint({ title: __("Not ready"), message: (out.problems || []).map((p) => frappe.utils.escape_html(p)).join("<br>"), indicator: "orange" });
					const rows = (out.would || []).map((x) => `<tr><td>${frappe.utils.escape_html(x.name)}</td><td>${frappe.utils.escape_html(x.customer || "")}</td><td>${frappe.utils.escape_html(x.phone || x.problem)}</td><td>${frappe.utils.escape_html(x.event)}</td></tr>`).join("");
					frappe.msgprint({
						title: __("A dry run: nothing is sent"),
						message: out.count ? `<p>${__("{0} record(s) would get a message if this rule ran now:", [out.count])}</p><table class="table table-sm"><tbody>${rows}</tbody></table>` : __("No record is due right now."),
						wide: true,
					});
				});
			});
		}
	},
	waba_number(frm) {
		frm.set_value("template", null);
		frm.trigger("load_account");
	},
	load_account(frm) {
		if (!frm.doc.waba_number) return (frm.__account = null);
		frappe.db.get_value("Waba Number", frm.doc.waba_number, ["account", "receive_only"]).then((r) => {
			frm.__account = r.message && r.message.account;
			if (r.message && r.message.receive_only) frm.dashboard.add_comment(__("This number is receive only: an Automatic rule cannot send from it."), "orange", true);
		});
	},
});
