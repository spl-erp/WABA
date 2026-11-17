// A locked Set: who is in it (first 500, with a link to the full list), who was left out and why, and "Copy as new Set".
frappe.ui.form.on("Waba Recipient Set", {
	refresh(frm) {
		if (frm.is_new()) return;
		frm.disable_save();
		frm.dashboard.set_headline(
			(frm.doc.included_count === 1 ? __("Locked. 1 person in this Set, {0} left out.", [frm.doc.excluded_count || 0]) : __("Locked. {0} people in this Set, {1} left out.", [frm.doc.included_count || 0, frm.doc.excluded_count || 0])) + " " + __("A Set cannot be changed; copy it to make a different one.")
		);
		frm.add_custom_button(__("Create Campaign"), () => {
			frappe.call({ method: "waba.api.campaigns.create_campaign_from_set", args: { recipient_set: frm.doc.name }, freeze: true }).then((r) => {
				if (r.message) frappe.set_route("Form", "Waba Campaign", r.message.name);
			});
		}).addClass("btn-primary");
		frm.add_custom_button(__("Copy as new Set"), () => {
			frappe.call({ method: "waba.api.campaigns.copy_set_people", args: { name: frm.doc.name }, freeze: true }).then((r) => {
				const d = r.message;
				if (!d) return;
				frappe
					.call({ method: "waba.api.inbox.assets_version", silent: true })
					.then((v) => $.ajax({ url: `/assets/waba/js/waba_sets_ui.js?v=${encodeURIComponent((v && v.message) || "0")}`, dataType: "script", cache: true }))
					.then(() => window.WabaSets.open({ doctype: d.doctype, names: JSON.stringify(d.names), title: d.title, copied_from: frm.doc.name }));
			});
		});
		frm.add_custom_button(__("See everyone"), () => frappe.set_route("List", "Waba Recipient Set Member", { recipient_set: frm.doc.name }));
		paint_people(frm);
		paint_excluded(frm);
	},
});

function paint_people(frm) {
	const wrap = frm.fields_dict.people_html.$wrapper;
	frappe.call({ method: "waba.api.campaigns.set_people", args: { name: frm.doc.name } }).then((r) => {
		const d = r.message || { rows: [], total: 0 };
		const esc = frappe.utils.escape_html;
		const route = (p) => `/desk/${frappe.router.slug(frm.doc.party_doctype)}/${encodeURIComponent(p)}`;
		wrap.html(
			`<div class="text-muted small" style="margin-bottom:6px">${
				d.total > d.rows.length ? __("First {0} of {1}. Use See everyone for the full list.", [d.rows.length, d.total]) : __("{0} people", [d.total])
			}</div>
			<div style="max-height:320px;overflow:auto"><table class="table table-bordered table-sm" style="margin:0"><thead><tr><th>${__("Name")}</th><th>${__("Record")}</th><th>${__("WhatsApp number")}</th></tr></thead><tbody>${d.rows
				.map((p) => `<tr><td>${esc(p.party_name)}</td><td><a href="${route(p.party)}">${esc(p.party)}</a></td><td>${esc(p.phone)}</td></tr>`)
				.join("")}</tbody></table></div>`
		);
	});
}

function paint_excluded(frm) {
	const wrap = frm.fields_dict.excluded_html.$wrapper;
	let data = {};
	try {
		data = JSON.parse(frm.doc.excluded_json || "{}");
	} catch (e) {
		data = {};
	}
	const rows = data.rows || [];
	const esc = frappe.utils.escape_html;
	if (!rows.length) return wrap.html(`<div class="text-muted">${__("Nobody was left out.")}</div>`);
	wrap.html(
		`<div style="max-height:320px;overflow:auto"><table class="table table-bordered table-sm" style="margin:0"><thead><tr><th>${__("Name")}</th><th>${__("Record")}</th><th>${__("Number")}</th><th>${__("Why")}</th></tr></thead><tbody>${rows
			.map((p) => `<tr><td>${esc(p.name)}</td><td>${esc(p.party)}</td><td>${esc(p.phone)}</td><td>${esc(p.label)}</td></tr>`)
			.join("")}</tbody></table></div>${
			frm.doc.excluded_count > rows.length ? `<div class="text-muted small">${__("Showing the first {0} of {1}.", [rows.length, frm.doc.excluded_count])}</div>` : ""
		}`
	);
}
