// A bot's form: the settings, and the buttons that open the builder, load the ready-made bot and publish. The design itself is
// drawn in the builder (public/js/waba_bot_canvas.js), a full-screen layer over this page.
frappe.ui.form.on("Waba Bot", {
	refresh(frm) {
		if (frm.is_new()) return;
		const live = frm.doc.version ? __("Published version {0}.", [frm.doc.version]) : __("Not published yet.");
		frm.dashboard.set_headline(`${live} ${frm.doc.enabled ? __("The bot is ON.") : __("The bot is OFF.")} ${__("Customers get the published version only; editing never changes a live bot until you Publish.")}`);
		if (!frm.doc.enabled) {
			// a bot that is off is never a candidate, so nothing in a chat would say why it stayed silent: say it here
			frm.dashboard.set_headline_alert(__("This bot is OFF, so it answers nobody. Tick Enabled below and save when you want it to start."), "red");
		}
		frm.add_custom_button(__("Open builder"), () => open_builder(frm)).addClass("btn-primary");
		frm.add_custom_button(__("Use starter..."), () => use_starter(frm), __("Bot"));
		frm.add_custom_button(__("Publish"), () => publish(frm), __("Bot"));
		frm.add_custom_button(__("See sessions"), () => frappe.set_route("List", "Waba Bot Session", { bot: frm.doc.name }), __("Bot"));
		frm.add_custom_button(__("See log"), () => frappe.set_route("List", "Waba Bot Log", { bot: frm.doc.name }), __("Bot"));
		frm.set_df_property("graph_json", "hidden", 1);
	},
});

function load_builder() {
	return frappe
		.call({ method: "waba.api.inbox.assets_version", silent: true })
		.then((v) => {
			const stamp = encodeURIComponent((v && v.message) || "0");
			const load = (file) => $.ajax({ url: `/assets/waba/js/${file}?v=${stamp}`, dataType: "script", cache: true });
			return load("waba_bot_graph.js").then(() => load("waba_bot_canvas.js"));
		});
}

function open_builder(frm) {
	const go = () => load_builder().then(() => window.WabaBotBuilder.open(frm.doc.name, { onClose: () => frm.reload_doc() }));
	if (frm.is_dirty()) frm.save().then(go);
	else go();
}

function use_starter(frm) {
	// the gallery of ready-made bots is a preview feature: while it is off, the form offers the Welcome + menu starter only
	if (!(frappe.boot && frappe.boot.waba_extra_blocks)) return welcome_starter(frm);
	frappe.call({ method: "waba.api.bots.starters" }).then((r) => gallery(frm, r.message || []));
}

function gallery(frm, starters) {
	if (!starters.length) return welcome_starter(frm);
	const by_title = Object.fromEntries(starters.map((s) => [s.title, s]));
	const dialog = new frappe.ui.Dialog({
		title: __("Start from a ready-made bot"),
		fields: [
			{
				fieldtype: "Select",
				fieldname: "starter",
				label: __("Starter"),
				options: starters.map((s) => s.title).join("\n"),
				default: starters[0].title,
				change() {
					const picked = by_title[dialog.get_value("starter")];
					dialog.fields_dict.about.$wrapper.html(`<p class="text-muted">${frappe.utils.escape_html(picked ? picked.description : "")}</p>`);
				},
			},
			{ fieldtype: "HTML", fieldname: "about", options: `<p class="text-muted">${frappe.utils.escape_html(starters[0].description)}</p>` },
			{ fieldtype: "Link", options: "Waba Team", fieldname: "sales", label: __("Team for Sales"), depends_on: 'eval:doc.starter=="Welcome + menu"', description: __("Leave empty to use the number's normal routing.") },
			{ fieldtype: "Link", options: "Waba Team", fieldname: "accounts", label: __("Team for Accounts"), depends_on: 'eval:doc.starter=="Welcome + menu"', description: __("Leave empty to use the number's normal routing.") },
			{ fieldtype: "HTML", options: `<p class="text-muted small">${__("This replaces the draft. You can change everything in the builder afterwards.")}</p>` },
		],
		primary_action_label: __("Use this starter"),
		primary_action(values) {
			const picked = by_title[values.starter];
			dialog.hide();
			frappe
				.call({ method: "waba.api.bots.use_starter", args: { bot: frm.doc.name, key: picked.key, sales_team: values.sales || null, accounts_team: values.accounts || null }, type: "POST", freeze: true })
				.then(() => {
					frappe.show_alert({ message: __("The starter is in your draft. Open the builder to see it."), indicator: "green" }, 5);
					frm.reload_doc();
				});
		},
	});
	dialog.show();
}

function welcome_starter(frm) {
	const dialog = new frappe.ui.Dialog({
		title: __("Use the Welcome + menu starter"),
		fields: [
			{ fieldtype: "HTML", options: `<p>${__("This replaces the draft with a ready-made bot: it greets a new chat by name and offers Sales, Accounts or Talk to a person. You can change everything in the builder afterwards.")}</p>` },
			{ fieldtype: "Link", options: "Waba Team", fieldname: "sales", label: __("Team for Sales"), description: __("Leave empty to use the number's normal routing.") },
			{ fieldtype: "Link", options: "Waba Team", fieldname: "accounts", label: __("Team for Accounts"), description: __("Leave empty to use the number's normal routing.") },
		],
		primary_action_label: __("Use starter"),
		primary_action(values) {
			dialog.hide();
			frappe.call({ method: "waba.api.bots.use_starter", args: { bot: frm.doc.name, sales_team: values.sales || null, accounts_team: values.accounts || null }, type: "POST", freeze: true }).then(() => {
				frappe.show_alert({ message: __("The starter is in your draft. Open the builder to see it."), indicator: "green" }, 5);
				frm.reload_doc();
			});
		},
	});
	dialog.show();
}

function publish(frm) {
	frappe.call({ method: "waba.api.bots.check", args: { bot: frm.doc.name } }).then((r) => {
		const problems = (r.message || {}).problems || [];
		if (problems.length) {
			frappe.msgprint({ title: __("The bot cannot be published yet"), message: problems.map((p) => frappe.utils.escape_html(p)).join("<br>"), indicator: "red" });
			return;
		}
		frappe.confirm(__("Publish this bot? Customers will get this version from now on."), () => {
			frappe.call({ method: "waba.api.bots.publish", args: { bot: frm.doc.name }, type: "POST", freeze: true }).then((r2) => {
				frappe.show_alert({ message: __("Published version {0}.", [(r2.message || {}).version]), indicator: "green" }, 5);
				frm.reload_doc();
			});
		});
	});
}
