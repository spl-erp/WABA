/* New-message alerts for the WhatsApp inbox, available on every Desk page.
 *
 * This file is only a loader (it is included app-wide through hooks.py). It does nothing unless the server flagged
 * the user (frappe.boot.waba_alerts, from waba/boot.py), and then loads waba_alerts_core.js with a version stamp so an update is picked up without clearing caches. */
(function () {
	if (window.__waba_alerts_boot) return;
	window.__waba_alerts_boot = true;
	$(document).on("startup", function () {
		try {
			if (!(frappe.boot && frappe.boot.waba_alerts)) return; // decided on the server (waba.boot)
			frappe.call({ method: "waba.api.inbox.assets_version", silent: true }).then(function (r) {
				const v = encodeURIComponent((r && r.message) || "0");
				$.ajax({ url: "/assets/waba/js/waba_alerts_core.js?v=" + v, dataType: "script", cache: true });
			});
		} catch (e) {
			/* alerts must never break the Desk */
		}
	});
})();
