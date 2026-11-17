frappe.listview_settings["Waba Template"] = {
	add_fields: ["status"],
	get_indicator(doc) {
		const tone = { APPROVED: "green", PENDING: "orange", DRAFT: "blue", REJECTED: "red", PAUSED: "red", DISABLED: "red", DELETED: "gray" }[doc.status] || "gray";
		return [__(doc.status), tone, `status,=,${doc.status}`];
	},
};
