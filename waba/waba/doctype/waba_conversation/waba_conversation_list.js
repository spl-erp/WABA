frappe.listview_settings["Waba Conversation"] = {
	add_fields: ["status", "window_expires_at"],
	// Whether the sender is matched has its own column ("Matched?") and the Triage shortcut; the badge says where the
	// conversation stands: finished, answerable now (24-hour window open) or needing a template.
	get_indicator(doc) {
		if (doc.status === "Done") return [__("Done"), "gray", "status,=,Done"];
		const open = doc.window_expires_at && frappe.datetime.str_to_obj(doc.window_expires_at) > new Date();
		return open
			? [__("Window open"), "green", "status,=,Open"]
			: [__("Window closed"), "red", "status,=,Open"];
	},
};
