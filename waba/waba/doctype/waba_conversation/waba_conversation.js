frappe.ui.form.on("Waba Conversation", {
	refresh(frm) {
		if (frm.is_new()) return;
		const open = frm.doc.window_expires_at && frappe.datetime.str_to_obj(frm.doc.window_expires_at) > new Date();
		frm.dashboard.set_headline(
			open
				? __("The 24-hour window is open until {0}. Any message can be sent.", [frappe.datetime.str_to_user(frm.doc.window_expires_at)])
				: __("The 24-hour window is closed. Only an approved template can be sent."),
			open ? "green" : "orange"
		);

		const send = (method, args, success_message) =>
			frappe
				.call({ method: `waba.api.send.${method}`, args: { conversation: frm.doc.name, ...args }, freeze: true, freeze_message: __("Sending...") })
				.then((r) => {
					const out = r.message || {};
					if (out.ok) {
						frappe.show_alert({ message: success_message || __("Sent to Meta. Delivery ticks will follow."), indicator: "green" }, 6);
						frm.reload_doc();
					} else if (out.error) {
						frappe.msgprint({ title: __("Not sent"), message: out.error, indicator: "red" });
						frm.reload_doc();
					}
				});

		if (open) {
			frm.add_custom_button(__("Reply"), () => {
				frappe.prompt(
					[{ fieldname: "body", label: __("Message"), fieldtype: "Small Text", reqd: 1 }],
					(values) => send("send_text", { body: values.body }),
					__("Reply to {0}", [frm.doc.customer_label || frm.doc.customer_phone]),
					__("Send")
				);
			}).addClass("btn-primary");
		}

		const load_dialog = () => {
			if (window.WabaTemplateForm) return Promise.resolve();
			return frappe.call({ method: "waba.api.inbox.assets_version", silent: true }).then((r) => {
				const v = encodeURIComponent((r && r.message) || "0");
				const base = "/assets/waba/js";
				const lib = window.WabaLib ? Promise.resolve() : $.ajax({ url: `${base}/waba_inbox_lib.js?v=${v}`, dataType: "script", cache: true });
				return Promise.resolve(lib).then(() => $.ajax({ url: `${base}/waba_template_dialog.js?v=${v}`, dataType: "script", cache: true }));
			});
		};

		frm.add_custom_button(__("Send template"), () => {
			frappe.call({ method: "waba.api.send.templates_for", args: { conversation: frm.doc.name } }).then((r) => {
				const templates = r.message || [];
				if (!templates.length) {
					frappe.msgprint(__("No approved template found. Press Meta, Sync templates on the WhatsApp Account first."));
					return;
				}
				load_dialog().then(() =>
					window.WabaTemplateDialog.open({
						title: __("Send a template"),
						templates,
						load: (template) => frappe.call({ method: "waba.api.send.template_form", args: { conversation: frm.doc.name, template } }).then((res) => res.message),
						send: (template, values) =>
							frappe
								.call({ method: "waba.api.send.send_template", args: { conversation: frm.doc.name, template, params: values }, freeze: true, freeze_message: __("Sending...") })
								.then((res) => {
									const out = res.message || {};
									if (out.ok) frappe.show_alert({ message: __("Sent to Meta. Delivery ticks will follow."), indicator: "green" }, 6);
									else if (out.error) frappe.msgprint({ title: __("Not sent"), message: out.error, indicator: "red" });
									frm.reload_doc();
									return !!out.ok;
								}),
					})
				);
			});
		});

		if (frm.doc.unread_count) {
			frm.add_custom_button(__("Mark as read"), () => send("mark_read", {}, __("Marked as read.")));
		}
	},
});
