/* "Create Set" in the Actions menu of the Customer and Lead lists, for Waba Campaign Managers and Waba Admins.
 *
 * Added through hooks.doctype_list_js. It wraps whatever list script the doctype already has (it never replaces it), loads the
 * review window on demand and, when every row on the page is ticked while the list holds more, offers to use everything that
 * matches the current filter instead of only the visible rows. */
(function () {
	const ROLES = ["Waba Admin", "Waba Campaign Manager"];
	const allowed = () => ROLES.some((r) => frappe.user.has_role(r));

	function load_ui() {
		if (window.WabaSets) return Promise.resolve();
		return frappe.call({ method: "waba.api.inbox.assets_version", silent: true }).then((r) => {
			const v = encodeURIComponent((r && r.message) || "0");
			return $.ajax({ url: `/assets/waba/js/waba_sets_ui.js?v=${v}`, dataType: "script", cache: true });
		});
	}

	function start(listview) {
		const names = listview.get_checked_items(true);
		if (!names.length) return frappe.msgprint(__("Tick the {0} you want in the Set first.", [__(listview.doctype)]));
		const total = listview.total_count;
		const everything_on_page = names.length === listview.data.length;
		const open = (args) => load_ui().then(() => window.WabaSets.open({ doctype: listview.doctype, ...args }));
		if (everything_on_page && total && total > names.length) {
			const dialog = new frappe.ui.Dialog({
				title: __("Which people?"),
				fields: [
					{
						fieldtype: "HTML",
						fieldname: "body",
						options: `<p>${__("You ticked all {0} rows on this page, but {1} match the current filter.", [names.length, total])}</p>`,
					},
				],
				primary_action_label: __("All {0} matching the filter", [total]),
				primary_action: () => {
					dialog.hide();
					open({ filters: JSON.stringify(listview.get_filters_for_args()) });
				},
				secondary_action_label: __("Only the {0} ticked", [names.length]),
				secondary_action: () => {
					dialog.hide();
					open({ names: JSON.stringify(names) });
				},
			});
			return dialog.show();
		}
		open({ names: JSON.stringify(names) });
	}

	["Customer", "Lead"].forEach((doctype) => {
		const settings = (frappe.listview_settings[doctype] = frappe.listview_settings[doctype] || {});
		if (settings.__waba_sets) return;
		settings.__waba_sets = true;
		const previous = settings.onload;
		settings.onload = function (listview) {
			if (previous) previous.apply(this, arguments);
			if (!allowed()) return;
			listview.page.add_actions_menu_item(__("Create Set"), () => start(listview), false);
		};
	});
})();
