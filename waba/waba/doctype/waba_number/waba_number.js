/* The Number form: (1) once the teams run the agent lists, the Agents table is only a copy of what the teams say;
 * (2) the Registration buttons walk a new number through Meta's steps: check, one-time code, register with a PIN.
 * Everything is decided on the server (waba.api.numbers); each button contacts Meta once, sends no message and costs nothing. */
frappe.ui.form.on("Waba Number", {
	refresh(frm) {
		frappe.db.get_single_value("Waba Settings", "teams_manage_agents").then((on) => {
			if (!on) return;
			frm.set_df_property("agents", "read_only", 1);
			frm.fields_dict.agents.grid.wrapper.find(".grid-add-row, .grid-remove-rows").hide();
			frm.set_intro(__("The agents of this number come from the teams that use it. Change them on the Team, not here."), "blue");
		});
		if (frm.doc.coexistence) frm.set_intro(__("This number is also used in the WhatsApp Business app. The registration buttons are off for it: registering it again would cut that link."), "blue");
		if (frm.is_new() || !frm.doc.phone_number_id || frm.doc.coexistence) return;
		if (!["System Manager", "Waba Admin"].some((r) => frappe.user_roles.includes(r))) return;
		const group = __("Registration");
		const e = frappe.utils.escape_html;
		const call = (method, args, done) =>
			frappe.call({ method: `waba.api.numbers.${method}`, args: { number: frm.doc.name, ...args }, freeze: true, freeze_message: __("Asking Meta...") }).then((r) => {
				const out = r.message || {};
				if (out.ok) done(out);
				else frappe.msgprint({ title: __("Meta did not accept it"), message: e(out.error || ""), indicator: "red" });
				frm.reload_doc();
			});
		const ask = (text, run) => frappe.confirm(`${e(text)}<br><br>${e(__("This contacts Meta once. No message is sent and nothing is charged."))}`, run);

		frm.add_custom_button(__("Check registration"), () =>
			call("check", {}, (out) => frappe.msgprint({ title: __("Registration"), message: e(out.text), indicator: out.next === "done" ? "green" : "orange" })), group);
		frm.add_custom_button(__("Send a code by SMS"), () =>
			ask(__("Meta will send a one-time code by SMS to {0}. Someone must be able to read that phone.", [frm.doc.display_number]), () =>
				call("request_code", { method: "SMS" }, (out) => frappe.msgprint({ message: e(out.note), indicator: "blue" }))), group);
		frm.add_custom_button(__("Send a code by voice call"), () =>
			ask(__("Meta will phone {0} and read out a one-time code.", [frm.doc.display_number]), () =>
				call("request_code", { method: "VOICE" }, (out) => frappe.msgprint({ message: e(out.note), indicator: "blue" }))), group);
		frm.add_custom_button(__("Enter the code"), () => {
			const d = new frappe.ui.Dialog({
				title: __("Enter the code Meta sent to {0}", [frm.doc.display_number]),
				fields: [{ fieldname: "code", label: __("6-digit code"), fieldtype: "Data", reqd: 1, description: __("For example 123456 or 123-456.") }],
				primary_action_label: __("Verify"),
				primary_action: (v) => {
					d.hide();
					call("verify_code", { code: v.code }, (out) => frappe.show_alert({ message: out.note, indicator: "green" }, 8));
				},
			});
			d.show();
		}, group);
		frm.add_custom_button(__("Register number"), () => {
			const d = new frappe.ui.Dialog({
				title: __("Register {0} with Meta", [frm.doc.display_number]),
				fields: [
					{ fieldtype: "HTML", fieldname: "info", options: `<div class="text-muted small">${e(__("From now on this number runs on the WhatsApp API and can no longer be used in the WhatsApp or WhatsApp Business app (unless Meta's coexistence applies). Choose a 6-digit PIN and keep it: Meta needs it to change or delete this number."))}</div>` },
					{ fieldname: "pin", label: __("Two-step PIN (6 digits)"), fieldtype: "Password", reqd: 1 },
					{ fieldname: "pin2", label: __("Repeat the PIN"), fieldtype: "Password", reqd: 1 },
					{ fieldname: "remember", label: __("Save the PIN on this number (encrypted)"), fieldtype: "Check", default: 1 },
				],
				primary_action_label: __("Register"),
				primary_action: (v) => {
					if (v.pin !== v.pin2) return frappe.msgprint(__("The two PINs are not the same."));
					d.hide();
					call("register", { pin: v.pin, remember: v.remember ? 1 : 0, confirm: 1 }, (out) => frappe.show_alert({ message: out.note, indicator: "green" }, 8));
				},
			});
			d.show();
		}, group);
	},
});
