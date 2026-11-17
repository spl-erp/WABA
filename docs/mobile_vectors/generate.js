/* Test vectors for the phone app, made by running the browser inbox's own helper functions (waba_inbox_lib.js) on fixed inputs.
 * The app team's code must give the same answers, so the two inboxes behave the same. Regenerate with:
 *   node apps/waba/docs/mobile_vectors/generate.js > apps/waba/docs/mobile_vectors/vectors.json
 * A test fails when vectors.json is out of date, so a change in the browser's rules always reaches the app team. */
const path = require("path");
const L = require(path.join(__dirname, "..", "..", "waba", "public", "js", "waba_inbox_lib.js"));

const iso = (s) => new Date(s);
const MB = 1024 * 1024;

const out = {
	_about: "Generated from waba_inbox_lib.js. Each group: a function name, its inputs and the expected output.",
	time_left: [
		["2026-11-12T10:00:00Z", "2026-11-12T08:00:00Z"],
		["2026-11-12T08:00:30Z", "2026-11-12T08:00:00Z"],
		["2026-11-12T08:00:00Z", "2026-11-12T08:00:00Z"],
		["2026-11-11T08:00:00Z", "2026-11-12T08:00:00Z"],
		["2026-11-13T07:59:00Z", "2026-11-12T08:00:00Z"],
	].map(([expires, now]) => ({ expires, now, expected: L.timeLeft(iso(expires), iso(now)) })),
	wa_format: [
		"plain text",
		"*bold* and _italic_ and ~gone~",
		"```code```",
		"5 - 6 pm, a*b*c and snake_case_name",
		"*not closed",
		"price *rs 500* only",
		"a link <a href=\"https://x.in/a_b_c\">https://x.in/a_b_c</a> *stays*",
		"(_inside brackets_)",
	].map((input) => ({ input, expected: L.waFormat(input) })),
	quick_replies_filter: (() => {
		const list = [
			{ title: "Thanks", body: "Thank you for contacting us." },
			{ title: "Price", body: "Our price list is attached." },
			{ title: "Hours", body: "We are open 9 to 6, thanks." },
		];
		return ["", "thank", "PRICE", "attached", "xyz", "  hours "].map((query) => ({ query, list, expected: L.filterQuickReplies(list, query) }));
	})(),
	fill_template: [
		{ text: "Hello {{1}}, your order {{2}} is ready.", component: "body", values: { "body.1": "Asha", "body.2": "SO-12" } },
		{ text: "Hello {{1}}, your order {{2}} is ready.", component: "body", values: { "body.1": "Asha" } },
		{ text: "Hi {{ name }}", component: "body", values: { "body.name": "  Ravi  " } },
		{ text: "Header {{1}}", component: "header", values: { "body.1": "wrong component" } },
		{ text: "No variables", component: "body", values: {} },
	].map((c) => ({ ...c, expected: L.fillTemplate(c.text, c.component, c.values) })),
	missing_slots: (() => {
		const slots = [{ id: "body.1" }, { id: "body.2" }, { id: "header.1" }];
		return [
			{},
			{ "body.1": "x", "body.2": " ", "header.1": { file: "a.png" } },
			{ "body.1": "x", "body.2": "y", "header.1": { shared_file: "F-1" } },
			{ "header.1": {} },
		].map((values) => ({ slots, values, expected: L.missingSlots(slots, values) }));
	})(),
	first_unread: (() => {
		const m = (name, direction) => ({ name, direction });
		const messages = [m("a", "In"), m("b", "Out"), m("c", "In"), m("d", "In"), m("e", "Out")];
		return [0, 1, 2, 3, 9].map((unread) => ({ messages, unread, expected: L.firstUnread(messages, unread) }));
	})(),
	reminder_choices: ["2026-11-12 12:00:00", "2026-11-14 09:30:00", "2026-11-15 22:00:00", "not a date"].map((now) => ({ now, expected: L.reminderChoices(now) })),
	check_upload: [
		["image/jpeg", 1000],
		["image/png", 6 * MB],
		["application/pdf", 100 * MB],
		["application/pdf", 101 * MB],
		["video/mp4", 0],
		["application/x-msdownload", 10],
		["audio/ogg; codecs=opus", 50000],
		["image/webp", 400 * 1024],
		["image/webp", 600 * 1024],
	].map(([mime, size]) => ({ mime, size, expected: L.checkUpload(mime, size) })),
	human_size: [0, 1, 1023, 1024, 1500, MB, 5 * MB + 300000].map((bytes) => ({ bytes, expected: L.humanSize(bytes) })),
	tick_for: ["Queued", "Sent", "Delivered", "Read", "Failed", "Unknown"].map((status) => ({ status, expected: L.tickFor(status) })),
};

process.stdout.write(JSON.stringify(out, null, 1) + "\n");
