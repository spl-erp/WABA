frappe.listview_settings["Waba Notification Log"] = {
	add_fields: ["status"],
	get_indicator(doc) {
		const tone = { "Pending approval": "orange", Queued: "blue", Sending: "blue", Sent: "green", Skipped: "gray", Failed: "red", Cancelled: "gray" }[doc.status] || "gray";
		return [__(doc.status), tone, `status,=,${doc.status}`];
	},
	onload(listview) {
		listview.page.add_inner_button(__("Waiting for you"), () => listview.filter_area.add([[listview.doctype, "status", "=", "Pending approval"]]));
	},
};
