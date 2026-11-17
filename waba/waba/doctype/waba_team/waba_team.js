/* The Team form is where the people of a department are set. Setup check lists what is wrong; Apply (Waba Admin) makes the teams
 * the one source for each Number's agents and for the Waba roles. Everything is decided on the server (waba.api.teams). */
frappe.ui.form.on("Waba Team", {
	refresh(frm) {
		if (frm.is_new()) return;
		const e = frappe.utils.escape_html;
		frm.add_custom_button(__("Setup check"), () => {
			frappe.call({ method: "waba.api.teams.setup_check" }).then((r) => {
				const out = r.message || { problems: [] };
				const tone = { error: "red", warning: "orange", info: "blue" };
				const rows = out.problems.map((p) => `<div style="margin-bottom:6px"><span class="indicator-pill ${tone[p.level] || "gray"}">${e(p.level)}</span> ${e(p.text)}</div>`).join("");
				const head = out.managed ? __("The teams already run the agent lists and roles.") : __("The teams do not run the agent lists yet. Apply turns that on once there are no errors.");
				frappe.msgprint({ title: __("Setup check"), message: `<p>${e(head)}</p>${rows || `<p>${e(__("Nothing to fix."))}</p>`}`, wide: true });
			});
		});
		if (frappe.user_roles.includes("Waba Admin")) {
			frm.add_custom_button(__("Apply to numbers"), () => {
				frappe.confirm(
					__("From now on each Number's agents and the Waba roles follow the teams. People who are agents on a number but in no team lose access. Run the Setup check first. Continue?"),
					() =>
						frappe.call({ method: "waba.api.teams.apply", freeze: true, freeze_message: __("Applying...") }).then((r) => {
							const out = r.message || {};
							frappe.show_alert({ message: __("Applied. Roles added: {0}, removed: {1}.", [out.roles_added || 0, out.roles_removed || 0]), indicator: "green" }, 8);
							frm.reload_doc();
						})
				);
			}).addClass("btn-primary");
		}
	},
});
