"""Run without a site:  python -m unittest waba.tests.test_inbox_js

The inbox's pure browser logic (public/js/waba_inbox_lib.js and waba_alerts_core.js) is plain JavaScript with no DOM or
Frappe dependency, so Node runs it here. Skipped when Node is not installed."""

import json
import os
import shutil
import subprocess
import unittest

PUBLIC = os.path.join(os.path.dirname(__file__), "..", "public", "js")
NODE = shutil.which("node")


def js(file, expression):
	path = os.path.abspath(os.path.join(PUBLIC, file))
	script = f"const m = require({json.dumps(path)}); console.log(JSON.stringify({expression}));"
	return json.loads(subprocess.check_output([NODE, "-e", script], text=True))


@unittest.skipUnless(NODE, "node is not installed")
class TestInboxLib(unittest.TestCase):
	def lib(self, expression):
		return js("waba_inbox_lib.js", expression)

	def test_initials(self):
		self.assertEqual(self.lib('[m.initials("Demo Known Customer"), m.initials("ravi"), m.initials("+919000070011"), m.initials(""), m.initials(null), m.initials("anna   o")]'), ["DK", "R", "?", "?", "?", "AO"])

	def test_avatar_colour_is_stable_and_varies(self):
		same = self.lib('[m.avatarColor("Rahul Traders"), m.avatarColor("Rahul Traders")]')
		self.assertEqual(same[0], same[1])
		palette = self.lib("m.AVATAR_COLORS")
		names = self.lib('Array.from({length: 40}, (_, i) => m.avatarColor("Customer " + i))')
		self.assertTrue(set(names) <= set(palette))
		self.assertGreaterEqual(len(set(names)), 4)

	def test_escape_html(self):
		self.assertEqual(self.lib("""m.escapeHtml('<b a="1">&\\'x\\'</b>')"""), "&lt;b a=&quot;1&quot;&gt;&amp;&#39;x&#39;&lt;/b&gt;")
		self.assertEqual(self.lib("[m.escapeHtml(null), m.escapeHtml(undefined), m.escapeHtml(5)]"), ["", "", "5"])

	def test_customer_lines(self):
		cases = self.lib(
			"""[
			m.customerLines({profile_name: "Rahul", customer_phone: "+91987"}),
			m.customerLines({customer_phone: "+91987"}),
			m.customerLines({customer_bsuid: "IN.abc", profile_name: "Asha"}),
			m.customerLines({name: "WCONV-1"})
		]"""
		)
		self.assertEqual(cases[0], {"name": "Rahul", "sub": "+91987"})
		self.assertEqual(cases[1], {"name": "+91987", "sub": ""})
		self.assertEqual(cases[2], {"name": "Asha", "sub": "IN.abc"})
		self.assertEqual(cases[3], {"name": "WCONV-1", "sub": ""})

	def test_time_left(self):
		self.assertEqual(self.lib("m.timeLeft(new Date(1000 + 3600000 * 2 + 60000 * 5), new Date(1000))"), "2 h 5 m")
		self.assertIsNone(self.lib("m.timeLeft(new Date(1000), new Date(2000))"))
		self.assertIsNone(self.lib("m.timeLeft(new Date(1000), new Date(1000))"))

	def test_ticks(self):
		got = self.lib('["Queued", "Sent", "Delivered", "Read", "Failed", "Received", null].map((s) => m.tickFor(s))')
		self.assertEqual([g and (g["icon"], g["tone"]) for g in got[:5]], [("clock", "grey"), ("check", "grey"), ("checks", "grey"), ("checks", "blue"), ("warning", "red")])
		self.assertEqual(got[5:], [None, None])

	def test_dates(self):
		self.assertEqual(self.lib('[m.dayLabel("2026-10-28 14:39:21"), m.clockLabel("2026-10-28 14:39:21"), m.dayLabel("x"), m.clockLabel(null)]'), ["28 Oct 2026", "14:39", "", ""])

	def test_linkify_escapes_first_and_links_only_web_addresses(self):
		out = self.lib("""m.linkify('Hi <script>x</script> see https://a.com/x?y=1&z=2, ok. javascript:alert(1) "https://b.org" www.c.com')""")
		self.assertIn("&lt;script&gt;", out)
		self.assertNotIn("<script>", out)
		self.assertIn('<a href="https://a.com/x?y=1&amp;z=2" target="_blank" rel="noopener noreferrer">https://a.com/x?y=1&amp;z=2</a>,', out)
		self.assertIn('<a href="https://b.org"', out)
		self.assertNotIn('href="javascript', out)
		self.assertNotIn('href="www', out)
		self.assertEqual(out.count("<a "), 2)

	def test_linkify_leaves_plain_text_alone(self):
		self.assertEqual(self.lib('m.linkify("order SO-1 shipped")'), "order SO-1 shipped")

	def test_highlight_touches_text_only(self):
		html = self.lib("""m.highlight(m.linkify("Order at https://shop.test/order now & order"), "order")""")
		self.assertEqual(html.count("<mark>"), 3)
		self.assertIn('href="https://shop.test/order"', html)  # the attribute is untouched
		self.assertEqual(self.lib('m.highlight("a &amp; b", "amp")'), "a &amp; b")  # not inside an entity
		self.assertEqual(self.lib('m.highlight("<b>x</b>", "")'), "<b>x</b>")
		self.assertEqual(self.lib('m.highlight("cost (Rs)", "(rs")'), "cost <mark>(Rs</mark>)")

	def test_count_matches(self):
		self.assertEqual(self.lib('[m.countMatches("Order order ORDER", "order"), m.countMatches("abc", ""), m.countMatches("a.b", ".")]'), [3, 0, 1])

	def test_emoji_data(self):
		groups = self.lib("m.EMOJI_GROUPS")
		self.assertGreaterEqual(len(groups), 4)
		seen = set()
		for g in groups:
			self.assertTrue(g["name"] and g["icon"] and g["items"])
			for emoji, keywords in g["items"]:
				self.assertTrue(emoji and keywords)
				self.assertNotIn(emoji, seen, emoji)
				seen.add(emoji)
		self.assertIn("🙏", [e for e, _k in self.lib('m.emojiSearch("thanks")')])
		self.assertEqual(self.lib('m.emojiSearch("")'), [])
		self.assertEqual(self.lib('m.emojiSearch("zzzzqq")'), [])

	def test_icons_and_marks_are_well_formed_svg(self):
		for name in ("phone", "search", "refresh", "paperclip", "smile", "send", "link", "external", "more", "chevron", "check", "checks", "warning", "arrowdown", "arrowup", "bell", "back", "x", "copy", "clock", "info", "zap", "transfer", "done", "undo", "note", "user"):
			svg = self.lib(f'm.icon("{name}", 16)')
			self.assertTrue(svg.startswith("<svg") and svg.endswith("</svg>"), name)
		self.assertEqual(self.lib('m.icon("nope")'), "")
		self.assertIn("<svg", self.lib("m.brandMark(32)"))
		self.assertIn("<svg", self.lib("m.verifiedBadge()"))


	def test_timeline_merges_notes_and_events_in_time_order(self):
		items = self.lib(
			"""m.timeline(
			[{name: "m1", sent_at: "2026-10-29 10:00:00"}, {name: "m2", sent_at: "2026-10-29 10:05:00"}],
			[{name: "n1", kind: "Note", creation: "2026-10-29 10:02:00"}, {name: "e1", kind: "Event", creation: "2026-10-29 09:59:00"},
			 {name: "n2", kind: "Note", creation: "2026-10-29 10:00:00"}]
		).map(i => i.type + ":" + i.data.name)"""
		)
		self.assertEqual(items, ["event:e1", "message:m1", "note:n2", "note:n1", "message:m2"])

	def test_timeline_of_nothing(self):
		self.assertEqual(self.lib("m.timeline()"), [])
		self.assertEqual(self.lib("m.timeline([], null)"), [])

	def test_quick_reply_search(self):
		sample = '[{title: "Greeting", body: "Hello, how can I help?"}, {title: "Price list", body: "Our prices are in the PDF"}, {title: "Bye", body: "Thank you"}]'
		self.assertEqual(self.lib(f'm.filterQuickReplies({sample}, "").length'), 3)
		self.assertEqual(self.lib(f'm.filterQuickReplies({sample}, "PRICE").map(r => r.title)'), ["Price list"])
		self.assertEqual(self.lib(f'm.filterQuickReplies({sample}, "thank").map(r => r.title)'), ["Bye"])
		self.assertEqual(self.lib(f'm.filterQuickReplies({sample}, "zzz")'), [])
		self.assertEqual(self.lib("m.filterQuickReplies(null, 'a')"), [])

	def test_a_note_is_escaped_like_any_text(self):
		self.assertNotIn("<script", self.lib('m.linkify("<script>alert(1)</script> see https://x.test")'))


@unittest.skipUnless(NODE, "node is not installed")
class TestAlertLogic(unittest.TestCase):
	def core(self, expression):
		return js("waba_alerts_core.js", expression)

	PREFS = "{sound: true, desktop: true}"

	def decide(self, **ctx):
		base = {"kind": "message", "conversation": "A", "hidden": False, "inbox": None}
		base.update(ctx)
		parts = ", ".join(f"{k}: {json.dumps(v)}" for k, v in base.items())
		return self.core(f"m.decide({{{parts}, prefs: {self.PREFS}}})")

	def test_a_tick_never_alerts(self):
		self.assertIsNone(self.decide(kind="status"))
		self.assertIsNone(self.decide(kind=None))

	def test_a_handover_alerts_but_a_note_or_an_assignment_does_not(self):
		self.assertIsNotNone(self.decide(kind="handed_over"))
		for kind in ("note", "assigned", "status"):
			self.assertIsNone(self.decide(kind=kind), kind)

	def test_reading_that_conversation_is_silent(self):
		self.assertIsNone(self.decide(inbox={"visible": True, "current": "A"}))

	def test_other_conversation_or_other_page_gets_sound_and_a_notice(self):
		for inbox in (None, {"visible": True, "current": "B"}, {"visible": False, "current": "A"}):
			self.assertEqual(self.decide(inbox=inbox), {"sound": True, "toast": True, "desktop": False, "count": False}, inbox)

	def test_hidden_tab_gets_desktop_notification_and_title_count(self):
		self.assertEqual(self.decide(hidden=True, inbox={"visible": True, "current": "A"}), {"sound": True, "toast": False, "desktop": True, "count": True})

	def test_settings_are_respected(self):
		off = self.core("m.decide({kind: 'message', conversation: 'A', hidden: true, inbox: null, prefs: {sound: false, desktop: false}})")
		self.assertEqual(off, {"sound": False, "toast": False, "desktop": False, "count": True})

	def test_title_count(self):
		self.assertEqual(self.core("[m.titleWithCount('WhatsApp Inbox', 3), m.titleWithCount('(2) WhatsApp Inbox', 5), m.titleWithCount('(2) X', 0), m.titleWithCount(null, 1)]"), ["(3) WhatsApp Inbox", "(5) WhatsApp Inbox", "X", "(1) "])

	def test_settings_from_storage(self):
		got = self.core("""[m.readPrefs(null), m.readPrefs("garbage"), m.readPrefs('{"sound": false}'), m.readPrefs('{"desktop": true, "sound": "x"}')]""")
		self.assertEqual(got, [{"sound": True, "desktop": False}, {"sound": True, "desktop": False}, {"sound": False, "desktop": False}, {"sound": True, "desktop": True}])

	def test_loader_trusts_the_server_flag_and_both_hooks_are_registered(self):
		root = os.path.join(os.path.dirname(__file__), "..")
		with open(os.path.join(PUBLIC, "waba_alerts.js"), encoding="utf-8") as f:
			boot = f.read()
		self.assertIn("frappe.boot.waba_alerts", boot)
		self.assertIn("waba_alerts_core.js", boot)
		with open(os.path.join(root, "hooks.py"), encoding="utf-8") as f:
			hooks = f.read()
		self.assertIn('app_include_js = ["/assets/waba/js/waba_alerts.js"]', hooks)
		self.assertIn('boot_session = "waba.boot.boot_session"', hooks)


class TestAlertRoles(unittest.TestCase):
	def test_who_gets_alerts(self):
		from waba.boot import ALERT_ROLES, wants_alerts

		self.assertEqual(ALERT_ROLES, {"Waba Admin", "Waba Supervisor", "Waba Agent"})
		self.assertTrue(wants_alerts("a@x.com", ["Waba Agent"]))
		self.assertFalse(wants_alerts("a@x.com", ["System Manager", "Sales User"]))
		self.assertFalse(wants_alerts("a@x.com", ["Sales User", "Accounts User"]))
		self.assertFalse(wants_alerts("a@x.com", []))
		self.assertFalse(wants_alerts("Guest", ["Waba Admin"]))


if __name__ == "__main__":
	unittest.main()


@unittest.skipUnless(NODE, "node is not installed")
class TestInboxMedia(unittest.TestCase):
	def lib(self, expression):
		return js("waba_inbox_lib.js", expression)

	def test_whatsapp_formatting(self):
		self.assertEqual(self.lib('m.waFormat("a *bold* _it_ ~x~")'), "a <b>bold</b> <i>it</i> <s>x</s>")
		self.assertEqual(self.lib('m.waFormat("5 * 6 * 7 and snake_case_name")'), "5 * 6 * 7 and snake_case_name")
		self.assertEqual(self.lib('m.waFormat("*unclosed and _also")'), "*unclosed and _also")
		self.assertEqual(self.lib('m.waFormat("(*note*).")'), "(<b>note</b>).")

	def test_formatting_never_touches_links(self):
		html = '<a href="https://x.com/a_b_c_d" target="_blank">https://x.com/a_b_c_d</a> and *ok*'
		self.assertEqual(self.lib(f"m.waFormat({json.dumps(html)})"), html.replace("*ok*", "<b>ok</b>"))

	def test_formatting_output_stays_escaped(self):
		out = self.lib('m.waFormat(m.escapeHtml("*<img src=x onerror=1>*"))')
		self.assertNotIn("<img", out)

	def test_upload_check(self):
		ok = self.lib('m.checkUpload("application/pdf", 1000)')
		self.assertTrue(ok["ok"])
		self.assertEqual(ok["kind"], "document")
		big = self.lib('m.checkUpload("image/png", 6 * 1024 * 1024)')
		self.assertFalse(big["ok"])
		self.assertIn("at most 5.0 MB", big["message"])
		self.assertFalse(self.lib('m.checkUpload("application/zip", 10)')["ok"])
		self.assertFalse(self.lib('m.checkUpload("image/png", 0)')["ok"])

	def test_media_view_states(self):
		base = '{name: "X1", direction: "In", message_type: "image", media_filename: "a.png", media_size: 2048, body: "[image] Hello"'
		self.assertEqual(self.lib(f'm.mediaView({base}, media_status: "Downloaded"}}).state'), "ready")
		self.assertEqual(self.lib(f'm.mediaView({base}, media_status: "Queued"}}).state'), "pending")
		self.assertEqual(self.lib(f'm.mediaView({base}, media_status: "Failed", media_error: "gone"}}).error'), "gone")
		self.assertEqual(self.lib(f'm.mediaView({base}}}).state'), "none")
		self.assertEqual(self.lib(f'm.mediaView({base}, media_status: "Downloaded"}}).caption'), "Hello")
		self.assertEqual(self.lib('m.mediaView({name: "O1", direction: "Out", message_type: "document", body: ""}).state'), "ready")
		self.assertIsNone(self.lib('m.mediaView({message_type: "text"})'))
		view = self.lib(f'm.mediaView({base}, media_status: "Downloaded"}})')
		self.assertTrue(view["url"].startswith("/api/method/waba.api.media.file?message=X1"))
		self.assertTrue(view["downloadUrl"].endswith("&download=1"))

	def test_places_contacts_reactions(self):
		self.assertEqual(self.lib("m.placeFor({latitude: 19.07, longitude: 72.87}).url"), "https://www.google.com/maps?q=19.07,72.87")
		self.assertIsNone(self.lib("m.placeFor({latitude: null, longitude: null})"))
		self.assertIsNone(self.lib("m.placeFor({latitude: 0, longitude: 0})"))
		self.assertEqual(self.lib('m.contactsFor({contacts_json: JSON.stringify([{name: "Asha", phones: ["+91 98"]}])})'), [{"name": "Asha", "phones": ["+91 98"]}])
		self.assertEqual(self.lib('m.contactsFor({contacts_json: "not json"})'), [])
		self.assertEqual(self.lib('m.reactionsFor({customer_reaction: "👍", our_reaction: "❤️"})'), [{"who": "Customer", "emoji": "👍"}, {"who": "You", "emoji": "❤️"}])
		self.assertEqual(self.lib("m.reactionsFor({})"), [])

	def test_retry_and_unread_divider(self):
		self.assertTrue(self.lib('m.canRetry({direction: "Out", status: "Failed", message_type: "text"})'))
		self.assertTrue(self.lib('m.canRetry({direction: "Out", status: "Failed", message_type: "document"})'))
		self.assertFalse(self.lib('m.canRetry({direction: "Out", status: "Failed", message_type: "template"})'))
		self.assertFalse(self.lib('m.canRetry({direction: "Out", status: "Failed", message_type: "text", retried: 1})'))
		self.assertFalse(self.lib('m.canRetry({direction: "In", status: "Failed", message_type: "text"})'))
		msgs = '[{name: "a", direction: "In"}, {name: "b", direction: "Out"}, {name: "c", direction: "In"}, {name: "d", direction: "In"}]'
		self.assertEqual(self.lib(f"m.firstUnread({msgs}, 2)"), "c")
		self.assertEqual(self.lib(f"m.firstUnread({msgs}, 1)"), "d")
		self.assertEqual(self.lib(f"m.firstUnread({msgs}, 3)"), "a")
		self.assertIsNone(self.lib(f"m.firstUnread({msgs}, 0)"))
		self.assertIsNone(self.lib(f"m.firstUnread({msgs}, 9)"))


@unittest.skipUnless(NODE, "node is not installed")
class TestTemplateDialogHelpers(unittest.TestCase):
	def lib(self, expression):
		return js("waba_inbox_lib.js", expression)

	def test_fill_template_puts_values_in_and_keeps_missing_ones_visible(self):
		self.assertEqual(self.lib('m.fillTemplate("Hi {{customer_name}}, order {{2}} for {{1}}", "body", {"body.customer_name": " Rahul ", "body.1": "x"})'), "Hi Rahul, order {{2}} for x")
		self.assertEqual(self.lib('m.fillTemplate("Order {{1}}", "header", {"body.1": "wrong component"})'), "Order {{1}}")
		self.assertEqual(self.lib('m.fillTemplate(null, "body", {})'), "")
		self.assertEqual(self.lib('m.fillTemplate("{{ 1 }}", "body", {"body.1": "  "})'), "{{ 1 }}")

	def test_missing_slots(self):
		slots = '[{id: "body.1"}, {id: "header.media"}, {id: "button.0"}]'
		self.assertEqual(self.lib(f'm.missingSlots({slots}, {{"body.1": "a", "header.media": {{shared_file: "W1"}}, "button.0": " "}})'), ["button.0"])
		self.assertEqual(self.lib(f'm.missingSlots({slots}, {{}})'), ["body.1", "header.media", "button.0"])
		self.assertEqual(self.lib(f'm.missingSlots({slots}, {{"body.1": "a", "header.media": {{file_url: "/private/x"}}, "button.0": "z"}})'), [])


@unittest.skipUnless(NODE, "node is not installed")
class TestReminderChoices(unittest.TestCase):
	def lib(self, expression):
		return js("waba_inbox_lib.js", expression)

	def test_ready_made_times(self):
		out = self.lib('m.reminderChoices("2026-11-10 12:00:00")')  # a Tuesday
		self.assertEqual([c["value"] for c in out], ["2026-11-10 14:00:00", "2026-11-11 10:00:00", "2026-11-13 10:00:00", "2026-11-16 10:00:00"])

	def test_next_monday_is_never_today(self):
		out = self.lib('m.reminderChoices("2026-11-09 08:30:00")')  # a Monday
		self.assertEqual(out[3]["value"], "2026-11-16 10:00:00")
		self.assertEqual(out[0]["value"], "2026-11-09 10:30:00")

	def test_crossing_midnight_and_month_end(self):
		out = self.lib('m.reminderChoices("2026-12-31 23:00:00")')
		self.assertEqual(out[0]["value"], "2027-01-01 01:00:00")
		self.assertEqual(out[1]["value"], "2027-01-01 10:00:00")

	def test_bad_input_gives_nothing(self):
		self.assertEqual(self.lib('m.reminderChoices("soon")'), [])
		self.assertEqual(self.lib("m.reminderChoices(null)"), [])


class TestRoundTwoPolish(unittest.TestCase):
	"""C5d: the chat-header search, shadows and motion (source checks; the look is checked in the browser)."""

	def setUp(self):
		base = os.path.join(os.path.dirname(__file__), "..", "public")
		with open(os.path.join(base, "js", "waba_inbox_app.js"), encoding="utf-8") as handle:
			self.js = handle.read()
		with open(os.path.join(base, "css", "waba_inbox.css"), encoding="utf-8") as handle:
			self.css = handle.read()

	def test_the_chat_header_has_no_search_bar_but_the_search_stays_reachable(self):
		self.assertNotIn("waba-th-search", self.js)
		self.assertNotIn("waba-th-search", self.css)
		self.assertIn('label: __("Search in conversation (Ctrl+F)")', self.js)  # the menu item
		self.assertIn("this.thread.open_search()", self.js)  # the keyboard shortcut
		self.assertIn('(ev.key === "f" || ev.key === "F") && (ev.ctrlKey || ev.metaKey)', self.js)

	def test_the_shortcut_works_only_with_a_conversation_open(self):
		self.assertIn("this.shown && this.thread.data", self.js)

	def test_new_messages_animate_but_the_first_render_does_not(self):
		self.assertIn("this.last_count > 0 && count > this.last_count", self.js)
		self.assertIn(".waba-msg.waba-new { animation:", self.css)

	def test_motion_is_switched_off_for_reduced_motion(self):
		self.assertIn("@media (prefers-reduced-motion: reduce)", self.css)
		block = self.css[self.css.index("@media (prefers-reduced-motion: reduce)"):]
		self.assertIn("animation: none !important", block)
		self.assertIn("transition: none !important", block)

	def test_shadow_tokens_exist_for_both_themes(self):
		self.assertEqual(self.css.count("--w-elev-2:"), 2)


class TestW1SenderTagAndSidebarCount(unittest.TestCase):
	"""W1: the tiny sender tag under every outgoing message, and the red count on the sidebar Inbox label."""

	def setUp(self):
		base = os.path.join(os.path.dirname(__file__), "..")
		with open(os.path.join(base, "public", "js", "waba_inbox_app.js"), encoding="utf-8") as handle:
			self.app = handle.read()
		with open(os.path.join(base, "public", "js", "waba_alerts_core.js"), encoding="utf-8") as handle:
			self.alerts = handle.read()
		with open(os.path.join(base, "api", "inbox.py"), encoding="utf-8") as handle:
			self.api = handle.read()

	def test_every_outgoing_message_shows_who_sent_it(self):
		self.assertIn("WabaLib.senderLabel(m)", self.app)
		self.assertNotIn("run.first ? `<div class=\"waba-sender\">", self.app)  # no longer only on the first bubble of a run

	def test_the_message_rows_carry_the_origin(self):
		self.assertIn('"origin",', self.api)

	def test_the_unread_endpoint_is_whitelisted_and_follows_visibility(self):
		self.assertIn("def unread_total() -> int:", self.api)
		self.assertIn("unread_chats()", self.api)
		body = self.api[self.api.index("def unread_chats("):self.api.index("def unread_total(")]
		self.assertIn('_conversation_query("unread", "all")', body)  # the same set as the Unread chip, so the sidebar and the inbox agree

	def test_the_badge_is_redrawn_when_the_sidebar_is_rebuilt_and_on_every_change(self):
		for fragment in ("MutationObserver", 'waba.api.inbox.unread_total', 'a[href$="waba-inbox"]', "refresh_unread", "frappe.boot.waba_unread"):
			self.assertIn(fragment, self.alerts, fragment)

	def test_the_inbox_tells_the_badge_when_counts_change(self):
		self.assertIn("window.waba_alerts.refresh_unread()", self.app)


@unittest.skipUnless(NODE, "node is not installed")
class TestW1Helpers(unittest.TestCase):
	def test_sender_label(self):
		def run(expression):
			return js("waba_inbox_lib.js", expression)

		self.assertEqual(run('m.senderLabel({direction:"Out", sent_by_name:"Asha K", origin:"Person"})'), "Asha K")
		self.assertEqual(run('m.senderLabel({direction:"Out", sent_by:"a@x.com"})'), "a@x.com")
		self.assertEqual(run('m.senderLabel({direction:"Out", origin:"Notification"})'), "Notification")
		self.assertEqual(run('m.senderLabel({direction:"Out", origin:"Campaign"})'), "Campaign")
		self.assertEqual(run('m.senderLabel({direction:"Out"})'), "Sent")
		self.assertEqual(run('m.senderLabel({direction:"In", sent_by_name:"x"})'), "")

	def test_badge_text(self):
		run = lambda e: js("waba_alerts_core.js", e)
		self.assertEqual(run("m.badgeText(0)"), "")
		self.assertEqual(run("m.badgeText(7)"), "7")
		self.assertEqual(run("m.badgeText(100)"), "99+")
		self.assertEqual(run("m.badgeText(null)"), "")


class TestAlertSound(unittest.TestCase):
	def test_the_chime_is_louder_and_has_three_notes(self):
		base = os.path.join(os.path.dirname(__file__), "..", "public", "js", "waba_alerts_core.js")
		with open(base, encoding="utf-8") as handle:
			source = handle.read()
		body = source[source.index("function beep()"):source.index("function open(conversation)")]
		for note in ("659.25", "783.99", "1046.5"):
			self.assertIn(note, body)
		self.assertIn("createDynamicsCompressor", body)
		self.assertNotIn("0.18, t + i * 0.16", body)  # the old quiet beep


class TestW2FloatingChat(unittest.TestCase):
	"""W2: the floating chat window on Lead / Contact / Customer (source checks; the look is checked in the browser)."""

	def setUp(self):
		base = os.path.join(os.path.dirname(__file__), "..")
		read = lambda *p: open(os.path.join(base, *p), encoding="utf-8").read()
		self.dock = read("public", "js", "waba_dock.js")
		self.app = read("public", "js", "waba_inbox_app.js")
		self.party = read("public", "js", "waba_party.js")
		self.css = read("public", "css", "waba_inbox.css")
		self.api = read("api", "inbox.py")

	def test_the_inbox_runs_in_a_docked_mode_without_list_or_toolbar(self):
		self.assertIn("constructor(page, wrapper, opts = {})", self.app)
		self.assertIn("this.dock = opts.dock || null", self.app)
		self.assertIn("thread_handlers()", self.app)
		for guard in ("if (!this.list) return Promise.resolve();", "if (this.list) this.list.select(name);", "if (this.$panels) this.$panels.addClass"):
			self.assertIn(guard, self.app, guard)

	def test_the_dock_reuses_the_inbox_and_its_server_checks_only(self):
		self.assertIn("new window.WabaInbox(null, null, { dock: this })", self.dock)
		self.assertIn("frm.__waba.conversations", self.dock)  # what this person may open comes from waba.api.party.context
		for forbidden in ("frappe.db.", "frappe.call({ method: \"waba.api.send", "get_value("):
			self.assertNotIn(forbidden, self.dock, forbidden)

	def test_alerts_stay_quiet_only_while_the_chat_is_really_on_screen(self):
		self.assertIn("get visible()", self.dock)
		self.assertIn("this._open && !this.minimised", self.dock)
		self.assertIn("const visible = this.dock ? !!this.dock.visible : !!this.shown;", self.app)

	def test_it_closes_when_you_leave_the_record(self):
		self.assertIn('frappe.router.on("change"', self.dock)
		self.assertIn('r[0] !== "Form"', self.dock)

	def test_a_customer_with_no_chat_can_start_one(self):
		self.assertIn("waba-dock-start", self.dock)
		self.assertIn("frm.__waba_start", self.dock)
		self.assertIn("frm.__waba_start = () => message_dialog(frm, ctx)", self.party)

	def test_the_header_icon_is_added_once_and_opens_the_dock(self):
		self.assertIn('find(".waba-dock-btn").remove()', self.party)
		self.assertIn("window.WabaDock.toggle(frm)", self.party)
		self.assertIn("add_chat_icon(frm);", self.party)

	def test_the_dock_script_is_covered_by_the_assets_stamp(self):
		self.assertIn('"js/waba_dock.js"', self.api)

	def test_the_styles_exist_and_the_phone_layout_is_full_screen(self):
		self.assertIn(".waba-shell.waba-dock {", self.css)
		self.assertIn(".waba-dock .waba-back, .waba-dock .waba-open-record { display: none !important; }", self.css)
		self.assertIn("inset: 0; width: 100%; height: 100%", self.css)


@unittest.skipUnless(NODE, "node is not installed")
class TestW2bDockGeometry(unittest.TestCase):
	def g(self, expression):
		return js("waba_dock_geometry.js", expression)

	def test_the_default_is_the_bottom_right_corner(self):
		self.assertEqual(self.g("m.defaults(1440, 900)"), {"x": 1020, "y": 220, "w": 400, "h": 660})

	def test_the_default_shrinks_on_a_small_screen(self):
		d = self.g("m.defaults(500, 500)")
		self.assertLessEqual(d["w"], 468)
		self.assertLessEqual(d["h"], 468)
		self.assertGreaterEqual(d["x"], 0)

	def test_a_move_keeps_the_header_reachable(self):
		far = self.g("m.move({x:100,y:100,w:400,h:500}, 99999, 99999, 1440, 900)")
		self.assertEqual((far["x"], far["y"]), (1440 - 80, 900 - 50))
		away = self.g("m.move({x:100,y:100,w:400,h:500}, -99999, -99999, 1440, 900)")
		self.assertEqual((away["x"], away["y"]), (80 - 400, 0))  # mostly off the left edge, header still grabbable, never above the top

	def test_resize_respects_minimum_and_maximum(self):
		small = self.g('m.resize({x:500,y:200,w:400,h:500}, "se", -9999, -9999, 1440, 900)')
		self.assertEqual((small["w"], small["h"]), (320, 320))
		big = self.g('m.resize({x:0,y:0,w:400,h:500}, "se", 9999, 9999, 1440, 900)')
		self.assertEqual((big["w"], big["h"]), (1440 - 32, 900 - 32))

	def test_dragging_the_left_or_top_edge_keeps_the_opposite_edge_fixed(self):
		before = {"x": 1000, "y": 200, "w": 400, "h": 600}
		after = self.g('m.resize({x:1000,y:200,w:400,h:600}, "nw", -100, -50, 1440, 900)')
		self.assertEqual(after["x"] + after["w"], before["x"] + before["w"])
		self.assertEqual(after["y"] + after["h"], before["y"] + before["h"])
		self.assertEqual((after["w"], after["h"]), (500, 650))

	def test_a_single_edge_changes_only_its_own_dimension(self):
		e = self.g('m.resize({x:500,y:200,w:400,h:500}, "e", 60, 999, 1440, 900)')
		self.assertEqual((e["x"], e["y"], e["w"], e["h"]), (500, 200, 460, 500))

	def test_a_saved_place_that_no_longer_fits_is_brought_back(self):
		fitted = self.g('m.fit({x: 3000, y: 2000, w: 5000, h: 4000}, 1280, 720)')
		self.assertLessEqual(fitted["w"], 1280 - 32)
		self.assertLessEqual(fitted["h"], 720 - 32)
		self.assertLessEqual(fitted["x"], 1280 - 80)
		self.assertLessEqual(fitted["y"], 720 - 50)

	def test_damaged_saved_data_gives_the_default(self):
		d = self.g("m.defaults(1440, 900)")
		for bad in ('null', '{"x":"a"}', '{"x":1,"y":2,"w":3}', '{"x":NaN}'):
			self.assertEqual(self.g(f"m.fit(m.parse({json.dumps(bad)}), 1440, 900)"), d, bad)
		self.assertIsNone(self.g('m.parse("{not json")'))
		self.assertIsNone(self.g("m.parse(null)"))

	def test_phone_width(self):
		self.assertTrue(self.g("m.isPhone(390)"))
		self.assertTrue(self.g("m.isPhone(600)"))
		self.assertFalse(self.g("m.isPhone(601)"))


class TestW2bDockWiring(unittest.TestCase):
	def setUp(self):
		base = os.path.join(os.path.dirname(__file__), "..")
		read = lambda *p: open(os.path.join(base, *p), encoding="utf-8").read()
		self.dock = read("public", "js", "waba_dock.js")
		self.css = read("public", "css", "waba_inbox.css")
		self.api = read("api", "inbox.py")

	def test_drag_and_resize_use_pointer_events_with_capture(self):
		for fragment in ('addEventListener("pointerdown"', "setPointerCapture", "releasePointerCapture", '"pointercancel"'):
			self.assertIn(fragment, self.dock, fragment)
		self.assertIn("G.move(op.start, dx, dy, vw, vh)", self.dock)
		self.assertIn("G.resize(op.start, op.handle, dx, dy, vw, vh)", self.dock)

	def test_the_stylesheet_has_no_rule_outside_the_inbox_scope(self):
		self.assertNotIn("body.waba-dock-drag", self.css)

	def test_there_are_eight_handles(self):
		self.assertIn('["n", "s", "e", "w", "nw", "ne", "sw", "se"]', self.dock)

	def test_the_place_is_remembered_and_every_storage_call_is_guarded(self):
		self.assertIn('const GEOM_KEY = "waba_dock_geom_v1";', self.dock)
		for call in ("window.localStorage.getItem(GEOM_KEY)", "window.localStorage.setItem(GEOM_KEY", "window.localStorage.removeItem(GEOM_KEY)"):
			i = self.dock.index(call)
			self.assertIn("try {", self.dock[max(0, i - 80):i], call)

	def test_double_click_resets_and_the_keyboard_moves_it(self):
		self.assertIn('.on("dblclick"', self.dock)
		self.assertIn("window.localStorage.removeItem(GEOM_KEY)", self.dock)
		self.assertIn("ev.altKey", self.dock)
		self.assertIn('tabindex="0"', self.dock)

	def test_a_phone_stays_full_screen(self):
		self.assertIn("G.isPhone(window.innerWidth)", self.dock)
		self.assertIn("left: 0 !important; top: 0 !important; width: 100% !important; height: 100% !important;", self.css)

	def test_a_minimised_window_keeps_its_header_only_and_has_no_handles(self):
		self.assertIn(".waba-dock.min { height: auto !important; }", self.css)
		self.assertIn(".waba-dock.min .waba-dock-h { display: none; }", self.css)

	def test_the_geometry_file_loads_with_the_dock_and_is_in_the_stamp(self):
		self.assertIn("waba_dock_geometry.js", self.dock)
		self.assertIn('"js/waba_dock_geometry.js"', self.api)
