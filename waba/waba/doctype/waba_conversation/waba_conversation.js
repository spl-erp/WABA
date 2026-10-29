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

		frm.add_custom_button(__("Send template"), () => {
			frappe.call({ method: "waba.api.send.templates_for", args: { conversation: frm.doc.name } }).then((r) => {
				const templates = r.message || [];
				if (!templates.length) {
					frappe.msgprint(__("No approved template found. Press Meta, Sync templates on the WhatsApp Account first."));
					return;
				}
				const byTitle = Object.fromEntries(templates.map((t) => [t.title, t]));
				const dialog = new frappe.ui.Dialog({
					title: __("Send a template"),
					fields: [
						{
							fieldname: "template",
							label: __("Template"),
							fieldtype: "Select",
							options: templates.map((t) => t.title).join("\n"),
							reqd: 1,
							change() {
								const t = byTitle[dialog.get_value("template")];
								dialog.get_field("preview").$wrapper.html(
									t
										? `<div class="text-muted small">${frappe.utils.escape_html(t.category)} - ${t.variable_count} value(s)</div><pre style="white-space:pre-wrap">${frappe.utils.escape_html(t.body_text)}</pre>`
										: ""
								);
							},
						},
						{ fieldname: "preview", fieldtype: "HTML" },
						{
							fieldname: "values",
							label: __("Values"),
							fieldtype: "Small Text",
							description: __("One value per line, in order: the first line fills {{1}}, the second {{2}}, and so on."),
						},
					],
					primary_action_label: __("Send"),
					primary_action(values) {
						dialog.hide();
						send("send_template", { template: byTitle[values.template].name, params: values.values || "" });
					},
				});
				dialog.show();
			});
		});

		if (frm.doc.unread_count) {
			frm.add_custom_button(__("Mark as read"), () => send("mark_read", {}, __("Marked as read.")));
		}
	},
});
