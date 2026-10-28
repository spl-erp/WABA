frappe.listview_settings["Waba Conversation"] = {
	add_fields: ["match_state", "status", "unread_count", "window_expires_at"],
	get_indicator(doc) {
		if (doc.match_state === "Triage") return [__("Triage"), "orange", "match_state,=,Triage"];
		if (doc.status === "Done") return [__("Done"), "gray", "status,=,Done"];
		const open = doc.window_expires_at && frappe.datetime.str_to_obj(doc.window_expires_at) > new Date();
		return open
			? [__("Window open"), "green", "status,=,Open"]
			: [__("Window closed"), "red", "status,=,Open"];
	},
};
