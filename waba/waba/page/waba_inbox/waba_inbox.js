/* Loader for the WhatsApp inbox. The page's code lives in the app's public folder (served from disk) and is requested
 * with a version stamp that changes whenever those files change, so nothing needs clearing after an update. */

frappe.pages["waba-inbox"].on_page_load = (wrapper) => {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __("WhatsApp Inbox"), single_column: true });
	waba_inbox_assets().then(() => {
		wrapper.waba_inbox = new window.WabaInbox(page, wrapper);
		if (wrapper.waba_shown) wrapper.waba_inbox.show();
	});
};

frappe.pages["waba-inbox"].on_page_show = (wrapper) => {
	wrapper.waba_shown = true;
	if (wrapper.waba_inbox) wrapper.waba_inbox.show();
};

frappe.pages["waba-inbox"].on_page_hide = (wrapper) => {
	wrapper.waba_shown = false;
	if (wrapper.waba_inbox) wrapper.waba_inbox.hide();
};

function waba_inbox_assets() {
	if (!window.__waba_inbox_assets) {
		window.__waba_inbox_assets = frappe.call({ method: "waba.api.inbox.assets_version", silent: true }).then((r) => {
			const v = encodeURIComponent((r && r.message) || "0");
			const base = "/assets/waba";
			$("<link>", { rel: "stylesheet", href: `${base}/css/waba_inbox.css?v=${v}` }).appendTo("head");
			return $.ajax({ url: `${base}/js/waba_inbox_lib.js?v=${v}`, dataType: "script", cache: true })
				.then(() => $.ajax({ url: `${base}/js/waba_template_dialog.js?v=${v}`, dataType: "script", cache: true }))
				.then(() => $.ajax({ url: `${base}/js/waba_inbox_app.js?v=${v}`, dataType: "script", cache: true }));
		});
	}
	return window.__waba_inbox_assets;
}
