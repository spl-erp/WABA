frappe.ui.form.on("Waba Notification Log", {
	refresh(frm) {
		const tone = { "Pending approval": "orange", Queued: "blue", Sending: "blue", Sent: "green", Skipped: "gray", Failed: "red", Cancelled: "gray" }[frm.doc.status] || "gray";
		frm.dashboard.set_headline(frm.doc.reason ? `${frm.doc.status}: ${frm.doc.reason}` : frm.doc.status, tone);
		if (frm.doc.status === "Pending approval") {
			frm.add_custom_button(__("Review and send"), () => {
				const run = () => window.WabaNotifyUI.review(frm.doc.name, () => frm.reload_doc());
				if (window.WabaNotifyUI) return run();
				frappe.call({ method: "waba.api.inbox.assets_version", silent: true }).then((r) => {
					const v = encodeURIComponent((r && r.message) || "0");
					const base = "/assets/waba/js";
					const lib = window.WabaLib ? Promise.resolve() : $.ajax({ url: `${base}/waba_inbox_lib.js?v=${v}`, dataType: "script", cache: true });
					Promise.resolve(lib).then(() => $.ajax({ url: `${base}/waba_notify_ui.js?v=${v}`, dataType: "script", cache: true })).then(run);
				});
			}).addClass("btn-primary");
		}
		if (frm.doc.conversation) frm.add_custom_button(__("Open conversation"), () => frappe.set_route("Form", "Waba Conversation", frm.doc.conversation));
	},
});
