/* The review window for a campaign Set.
 *
 * Opened from the Actions menu of the Customer and Lead lists ("Create Set") and from a locked Set's form ("Copy as new Set").
 * It shows who would be in the Set, who is left out and why, lets the person untick people, and only then locks the Set.
 * The rules are the server's (waba.api.campaigns.review_set / create_set); the server applies them again on Confirm, so nobody
 * the review left out can be added from here. */
(function () {
	const esc = (v) => frappe.utils.escape_html(v == null ? "" : String(v));
	const SHOWN = 300; // rows drawn at once; the search box finds anyone else

	const STYLE = `
.waba-set { font-size: 13px }
.waba-set-sum { display:flex; gap:10px; flex-wrap:wrap; margin:0 0 10px }
.waba-set-sum > div { flex:1 1 120px; border:1px solid var(--border-color); border-radius:8px; padding:8px 10px; background:var(--control-bg) }
.waba-set-sum b { display:block; font-size:20px; line-height:1.2 }
.waba-set-sum span { color:var(--text-muted); font-size:12px }
.waba-set-sum .waba-set-in b { color:var(--green-600, #278f5e) }
.waba-set-bar { display:flex; gap:8px; align-items:center; margin:8px 0 }
.waba-set-bar input { flex:1; min-width:0 }
.waba-set-table { max-height:260px; overflow:auto; border:1px solid var(--border-color); border-radius:8px }
.waba-set-table table { width:100%; border-collapse:collapse }
.waba-set-table th, .waba-set-table td { padding:5px 10px; border-bottom:1px solid var(--border-color); text-align:left; vertical-align:middle }
.waba-set-table th { position:sticky; top:0; background:var(--subtle-fg, var(--control-bg)); font-weight:600; font-size:12px; z-index:1 }
.waba-set-table td.waba-set-chk, .waba-set-table th.waba-set-chk { width:34px }
.waba-set-table tr.waba-set-off td { opacity:.5; text-decoration:line-through }
.waba-set-note { color:var(--text-muted); font-size:12px; margin-top:4px }
.waba-set-why { display:inline-block; padding:1px 8px; border-radius:10px; background:var(--bg-orange, #fff1e3); color:var(--text-on-orange, #b45309); font-size:11px; white-space:nowrap }
.waba-set-reasons { margin:6px 0 0; color:var(--text-muted) }
`;

	function style() {
		if (document.getElementById("waba-sets-style")) return;
		const el = document.createElement("style");
		el.id = "waba-sets-style";
		el.textContent = STYLE;
		document.head.appendChild(el);
	}

	/* args: { doctype, names? , filters?, title?, copied_from? } ; done(set_name) after the Set is locked */
	function open(args, done) {
		style();
		frappe
			.call({ method: "waba.api.campaigns.review_set", args: { doctype: args.doctype, names: args.names || null, filters: args.filters || null }, freeze: true, freeze_message: __("Checking who can be messaged...") })
			.then((r) => r.message && show(r.message, args, done));
	}

	function show(data, args, done) {
		const included = data.included || [];
		const excluded = data.excluded || [];
		const ticked = new Set(included.map((p) => p.party));
		let query = "";
		const dialog = new frappe.ui.Dialog({
			title: __("Create Set"),
			size: "large",
			fields: [
				{ fieldtype: "Data", fieldname: "title", label: __("Set name"), reqd: 1, default: args.title || "" },
				{ fieldtype: "HTML", fieldname: "body" },
				{ fieldtype: "Small Text", fieldname: "note", label: __("Note (optional)"), description: __("For your own reference, for example the purpose of this Set.") },
			],
			primary_action_label: __("Confirm and lock this Set"),
			primary_action: (values) => {
				if (!ticked.size) return frappe.msgprint(__("Everyone is unticked, so there is nothing to put in the Set."));
				frappe.confirm(
					__("Lock this Set with {0} people? It cannot be changed afterwards (you can copy it as a new Set).", [ticked.size]),
					() => {
						dialog.get_primary_btn().prop("disabled", true);
						frappe
							.call({
								method: "waba.api.campaigns.create_set",
								args: { title: values.title, doctype: data.doctype, names: JSON.stringify(Array.from(ticked)), note: values.note || "", copied_from: args.copied_from || null },
								freeze: true,
								freeze_message: __("Locking the Set..."),
							})
							.then((r) => {
								const name = r.message && r.message.name;
								dialog.hide();
								if (!name) return;
								frappe.show_alert({ message: __("Set {0} is locked.", [name]), indicator: "green" }, 6);
								if (done) done(name);
								else frappe.set_route("Form", "Waba Recipient Set", name);
							})
							.catch(() => dialog.get_primary_btn().prop("disabled", false));
					}
				);
			},
		});

		const $body = dialog.fields_dict.body.$wrapper;
		const reasons = Object.keys(data.counts || {})
			.filter((k) => data.counts[k])
			.map((k) => {
				const row = excluded.find((x) => x.reason === k);
				return `${data.counts[k]} × ${esc(row ? row.label : k)}`;
			});

		$body.html(`<div class="waba-set">
			<div class="waba-set-sum">
				<div><b>${esc(data.chosen)}</b><span>${__("chosen")}</span></div>
				<div class="waba-set-in"><b data-role="in">${esc(ticked.size)}</b><span>${__("will be in the Set")}</span></div>
				<div><b>${esc(excluded.length)}</b><span>${__("left out")}</span></div>
			</div>
			${reasons.length ? `<div class="waba-set-reasons">${__("Left out")}: ${reasons.join(" · ")}</div>` : ""}
			<div class="waba-set-note">${__("Audience rule")}: ${esc(data.rule)}. ${__("One number per person: the WhatsApp number, then the mobile, then the phone.")}</div>
			<div class="waba-set-bar">
				<input type="search" class="form-control input-sm" data-role="q" placeholder="${__("Find a person in this list")}">
				<button class="btn btn-xs btn-default" data-role="all">${__("Tick all")}</button>
				<button class="btn btn-xs btn-default" data-role="none">${__("Untick all")}</button>
			</div>
			<div class="waba-set-table" data-role="in-table"></div>
			<div class="waba-set-note" data-role="more"></div>
			${
				excluded.length
					? `<details style="margin-top:12px"><summary>${__("Left out ({0})", [excluded.length])}</summary>
				<div class="waba-set-table" style="margin-top:6px"><table><thead><tr><th>${__("Name")}</th><th>${__("Number")}</th><th>${__("Why")}</th></tr></thead><tbody>${excluded
					.slice(0, 500)
					.map((p) => `<tr><td>${esc(p.name)}<div class="waba-set-note">${esc(p.party)}</div></td><td>${esc(p.phone)}</td><td><span class="waba-set-why">${esc(p.label)}</span></td></tr>`)
					.join("")}</tbody></table></div>${excluded.length > 500 ? `<div class="waba-set-note">${__("Showing the first 500.")}</div>` : ""}</details>`
					: ""
			}
		</div>`);

		function paint() {
			const q = query.trim().toLowerCase();
			const matches = q ? included.filter((p) => `${p.name} ${p.party} ${p.phone}`.toLowerCase().includes(q)) : included;
			const rows = matches.slice(0, SHOWN);
			$body.find('[data-role="in-table"]').html(
				`<table><thead><tr><th class="waba-set-chk"></th><th>${__("Name")}</th><th>${__("Record")}</th><th>${__("WhatsApp number")}</th></tr></thead><tbody>${rows
					.map(
						(p) =>
							`<tr class="${ticked.has(p.party) ? "" : "waba-set-off"}"><td class="waba-set-chk"><input type="checkbox" data-party="${esc(p.party)}" ${ticked.has(p.party) ? "checked" : ""}></td><td>${esc(p.name)}</td><td>${esc(p.party)}</td><td>${esc(p.phone)}</td></tr>`
					)
					.join("")}</tbody></table>`
			);
			$body.find('[data-role="more"]').text(
				matches.length > SHOWN
					? __("Showing {0} of {1}. Search to find anyone else; Tick all and Untick all apply to everyone.", [SHOWN, matches.length])
					: matches.length
						? ""
						: __("Nobody matches.")
			);
			$body.find('[data-role="in"]').text(ticked.size);
		}

		$body.on("input", '[data-role="q"]', (ev) => {
			query = ev.target.value;
			paint();
		});
		$body.on("change", 'input[type="checkbox"][data-party]', (ev) => {
			const id = ev.target.getAttribute("data-party");
			ev.target.checked ? ticked.add(id) : ticked.delete(id);
			$(ev.target).closest("tr").toggleClass("waba-set-off", !ev.target.checked);
			$body.find('[data-role="in"]').text(ticked.size);
		});
		$body.on("click", '[data-role="all"]', () => {
			included.forEach((p) => ticked.add(p.party));
			paint();
		});
		$body.on("click", '[data-role="none"]', () => {
			ticked.clear();
			paint();
		});
		paint();
		dialog.show();
	}

	window.WabaSets = { open };
})();
