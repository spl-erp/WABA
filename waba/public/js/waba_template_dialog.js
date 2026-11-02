/* The one template dialog, used by the inbox, the WhatsApp button on Lead / Contact / Customer, and the conversation form.
 *
 * It shows the template the way the customer will see it (header, body, footer, buttons), one labelled box per value with
 * whatever the template's variable map already filled in from the customer's record, and a header file chooser when the
 * template has a picture, video or document header. Everything is decided on the server: this file only shows the form it
 * is given (waba.api.send.template_form / waba.api.party.template_form) and hands back the values. Needs waba_inbox_lib.js. */
(function () {
	const e = (v) => WabaLib.escapeHtml(v);

	const BUTTON_NAMES = { COPY_CODE: "Copy code", URL: "Open link", PHONE_NUMBER: "Call", QUICK_REPLY: "Reply" };

	const STYLE = `
		.waba-tpl-preview { background: #e7f6ec; border-radius: 12px; padding: 12px 14px; margin-bottom: 12px; max-width: 420px; }
		.waba-tpl-head { font-weight: 700; margin-bottom: 4px; }
		.waba-tpl-media { display: inline-block; padding: 2px 10px; border-radius: 999px; background: rgba(0,0,0,.08); font-size: 12px; font-weight: 600; }
		.waba-tpl-body { white-space: pre-wrap; }
		.waba-tpl-foot { color: #667781; font-size: 12px; margin-top: 6px; }
		.waba-tpl-buttons { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
		.waba-tpl-btn { flex: 1 1 auto; text-align: center; padding: 6px 10px; border-radius: 8px; background: #fff; color: #0a7cff; font-weight: 600; font-size: 13px; }
		.waba-tpl-field { margin-bottom: 10px; }
		.waba-tpl-field label { font-size: 12px; font-weight: 600; margin-bottom: 3px; display: block; }
		.waba-tpl-field .hint { font-size: 11.5px; color: #667781; margin-top: 2px; }
		.waba-tpl-field .is-missing { border-color: #c4372f; }
		.waba-tpl-problem { margin-bottom: 10px; }`;

	function ensure_style() {
		if (!document.getElementById("waba-tpl-style")) $("<style id='waba-tpl-style'>").text(STYLE).appendTo("head");
	}

	/** The form of one template: preview, a box for each value, and a way to read them back. */
	class TemplateForm {
		constructor($el, form) {
			this.$el = $el;
			this.form = form;
			this.values = {};
			this.files = {};
			(form.slots || []).forEach((s) => {
				if (s.kind === "image" || s.kind === "video" || s.kind === "document") {
					if (s.value) this.values[s.id] = { shared_file: s.value };
				} else if (s.value) this.values[s.id] = s.value;
			});
			ensure_style();
			this.render();
		}

		render() {
			const f = this.form;
			const problem = !f.sendable ? `<div class="alert alert-warning waba-tpl-problem">${e(f.problem)}</div>` : "";
			const fields = (f.slots || []).map((s) => this.field_html(s)).join("");
			this.$el.html(`${problem}<div class="waba-tpl-preview"></div><div class="waba-tpl-fields">${fields}</div>`);
			this.preview();
			this.$el.find("input[data-slot]").on("input", (ev) => {
				this.values[$(ev.currentTarget).data("slot")] = $(ev.currentTarget).val();
				$(ev.currentTarget).removeClass("is-missing");
				this.preview();
			});
			this.$el.find("select[data-file]").on("change", (ev) => this.choose($(ev.currentTarget).data("file"), $(ev.currentTarget).val(), null));
			this.$el.find("input[data-upload]").on("change", (ev) => {
				const file = ev.currentTarget.files && ev.currentTarget.files[0];
				if (file) this.choose($(ev.currentTarget).data("upload"), "", file);
			});
		}

		field_html(s) {
			const hint = s.value && !s.needs_input ? `<div class="hint">${e(__("Filled in from the customer's record. You can change it."))}</div>` : s.example ? `<div class="hint">${e(__("For example: {0}", [s.example]))}</div>` : "";
			if (s.kind === "image" || s.kind === "video" || s.kind === "document") {
				const files = this.form.shared_files || [];
				const options = [`<option value="">${e(__("Choose from the shared library"))}</option>`].concat(
					files.map((x) => `<option value="${e(x.name)}" ${s.value === x.name ? "selected" : ""}>${e(x.title)} (${e(x.size)})</option>`)
				);
				return `<div class="waba-tpl-field"><label>${e(s.label)}</label>
					<select class="form-control" data-file="${e(s.id)}">${options.join("")}</select>
					<div class="hint">${e(__("or"))} <input type="file" data-upload="${e(s.id)}" /> <span class="waba-tpl-chosen" data-chosen="${e(s.id)}"></span></div></div>`;
			}
			return `<div class="waba-tpl-field"><label>${e(s.label)}</label>
				<input class="form-control" data-slot="${e(s.id)}" value="${e(typeof this.values[s.id] === "string" ? this.values[s.id] : "")}" placeholder="${e(s.example || "")}" />${hint}</div>`;
		}

		choose(slot, shared, file) {
			if (file) {
				this.files[slot] = file;
				this.values[slot] = { file };
				this.$el.find(`[data-chosen="${slot}"]`).text(file.name);
				this.$el.find(`select[data-file="${slot}"]`).val("");
			} else {
				delete this.files[slot];
				this.values[slot] = shared ? { shared_file: shared } : undefined;
				this.$el.find(`[data-chosen="${slot}"]`).text("");
			}
			this.$el.find(`select[data-file="${slot}"]`).removeClass("is-missing");
		}

		preview() {
			const p = this.form.parts || {};
			const text = (t, comp) => e(WabaLib.fillTemplate(t, comp, this.values));
			const head = p.header ? (p.header.format === "TEXT" ? `<div class="waba-tpl-head">${text(p.header.text, "header")}</div>` : `<div class="waba-tpl-head"><span class="waba-tpl-media">${e(p.header.format.toLowerCase())}</span></div>`) : "";
			const foot = p.footer ? `<div class="waba-tpl-foot">${e(p.footer)}</div>` : "";
			const buttons = (p.buttons || []).length ? `<div class="waba-tpl-buttons">${p.buttons.map((b) => `<span class="waba-tpl-btn">${e(b.text || BUTTON_NAMES[b.type] || b.type)}</span>`).join("")}</div>` : "";
			this.$el.find(".waba-tpl-preview").html(`${head}<div class="waba-tpl-body">${text(p.body, "body")}</div>${foot}${buttons}`);
		}

		/** {ok, values, missing}: the typed values, with the empty boxes marked. A chosen file is still a File here (see upload). */
		collect() {
			const slots = this.form.slots || [];
			const missing = WabaLib.missingSlots(slots, this.values);
			missing.forEach((id) => this.$el.find(`[data-slot="${id}"], [data-file="${id}"]`).addClass("is-missing"));
			return { ok: this.form.sendable && !missing.length, values: this.values, missing };
		}

		/** Upload any device file to a private file; resolves with plain values ready to send. */
		upload(values) {
			const out = {};
			const jobs = [];
			Object.keys(values).forEach((id) => {
				const v = values[id];
				if (v && typeof v === "object" && v.file) jobs.push(upload_private(v.file).then((up) => (out[id] = { file_url: up.file_url })));
				else if (v !== undefined) out[id] = v;
			});
			return Promise.all(jobs).then(() => out);
		}
	}

	function upload_private(file) {
		return new Promise((resolve, reject) => {
			const form = new FormData();
			form.append("file", file, file.name);
			form.append("is_private", "1");
			form.append("folder", "Home");
			const xhr = new XMLHttpRequest();
			xhr.open("POST", "/api/method/upload_file");
			xhr.setRequestHeader("X-Frappe-CSRF-Token", frappe.csrf_token);
			xhr.setRequestHeader("Accept", "application/json");
			xhr.onload = () => {
				let body = {};
				try {
					body = JSON.parse(xhr.responseText);
				} catch (err) {}
				if (xhr.status >= 200 && xhr.status < 300 && body.message && body.message.file_url) return resolve(body.message);
				reject(new Error(__("The upload was refused.")));
			};
			xhr.onerror = () => reject(new Error(__("The upload could not be sent. Check your connection.")));
			xhr.send(form);
		});
	}

	/** The standalone dialog: pick a template, fill the values, send.
	 *  opts: {title, templates: [{name, title}], load(templateName) -> Promise(form), send(templateName, values) -> Promise(bool), submit_label} */
	function open(opts) {
		const byTitle = Object.fromEntries(opts.templates.map((t) => [t.title, t]));
		const titles = opts.templates.map((t) => t.title);
		let controller = null;
		let loaded_for = null;
		const dialog = new frappe.ui.Dialog({
			title: opts.title,
			fields: [
				{ fieldname: "template", label: __("Template"), fieldtype: "Select", options: titles.join("\n"), default: titles[0], reqd: 1, change: () => load() },
				{ fieldtype: "HTML", fieldname: "form" },
			],
			primary_action_label: opts.submit_label || __("Send"),
			primary_action: () => submit(),
		});

		function load() {
			const t = byTitle[dialog.get_value("template")];
			if (!t || loaded_for === t.name) return;
			loaded_for = t.name;
			controller = null;
			dialog.get_primary_btn().prop("disabled", true);
			dialog.get_field("form").$wrapper.html(`<div class="text-muted">${e(__("Loading..."))}</div>`);
			Promise.resolve(opts.load(t.name)).then((form) => {
				if (loaded_for !== t.name) return;
				controller = new TemplateForm(dialog.get_field("form").$wrapper, form);
				dialog.get_primary_btn().prop("disabled", !form.sendable);
			});
		}

		function submit() {
			const t = byTitle[dialog.get_value("template")];
			if (!controller || !t) return;
			const result = controller.collect();
			if (!result.ok) {
				frappe.show_alert({ message: __("Fill in every value first."), indicator: "orange" }, 4);
				return;
			}
			dialog.get_primary_btn().prop("disabled", true);
			controller
				.upload(result.values)
				.then((values) => opts.send(t.name, values))
				.then((ok) => {
					if (ok) dialog.hide();
					else dialog.get_primary_btn().prop("disabled", false);
				})
				.catch((err) => {
					dialog.get_primary_btn().prop("disabled", false);
					frappe.msgprint({ title: __("Not sent"), message: e(err.message), indicator: "red" });
				});
		}

		dialog.show();
		load();
		return dialog;
	}

	window.WabaTemplateForm = TemplateForm;
	window.WabaTemplateDialog = { open, TemplateForm };
})();
