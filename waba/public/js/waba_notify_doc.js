/* A "WhatsApp" button on the Quotation, Sales Invoice and Lead forms for the people who approve Manual notifications.
 * Added through hooks.doctype_js; it never replaces another script on those forms. It puts a message for THIS document in the
 * waiting list and opens the review dialog; nothing is sent until the person presses Send there. */
;(function () {
	const APPROVERS = ["System Manager", "Waba Admin", "Waba Supervisor"];
	const LABELS = { Quotation: __("Send follow-up"), "Sales Invoice": __("Send payment reminder"), Lead: __("Send acknowledgement") };
	const allowed = () => APPROVERS.some((r) => frappe.user.has_role(r));

	function load_ui() {
		if (window.WabaNotifyUI) return Promise.resolve();
		return frappe.call({ method: "waba.api.inbox.assets_version", silent: true }).then((r) => {
			const v = encodeURIComponent((r && r.message) || "0");
			const base = "/assets/waba/js";
			const lib = window.WabaLib ? Promise.resolve() : $.ajax({ url: `${base}/waba_inbox_lib.js?v=${v}`, dataType: "script", cache: true });
			return Promise.resolve(lib).then(() => $.ajax({ url: `${base}/waba_notify_ui.js?v=${v}`, dataType: "script", cache: true }));
		});
	}

	Object.keys(LABELS).forEach((doctype) => {
		frappe.ui.form.on(doctype, {
			refresh(frm) {
				if (frm.is_new() || !allowed()) return;
				if (doctype !== "Lead" && frm.doc.docstatus !== 1) return;
				frm.add_custom_button(LABELS[doctype], () => load_ui().then(() => window.WabaNotifyUI.for_document(frm.doctype, frm.doc.name)), __("WhatsApp"));
			},
		});
	});
})();
