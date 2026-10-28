frappe.ui.form.on("Waba Account", {
	refresh(frm) {
		if (frm.is_new()) return;
		const run = (method, label) =>
			frappe
				.call({ method: `waba.meta.actions.${method}`, args: { account: frm.doc.name }, freeze: true, freeze_message: __("Talking to Meta...") })
				.then((r) => {
					frappe.show_alert({ message: r.message, indicator: "green" }, 8);
					frm.reload_doc();
				});
		frm.add_custom_button(__("Test connection"), () => run("test_connection"), __("Meta"));
		frm.add_custom_button(__("Subscribe webhook"), () => run("subscribe_webhook"), __("Meta"));
		frm.add_custom_button(__("Sync numbers"), () => run("sync_numbers"), __("Meta"));
	},
});
