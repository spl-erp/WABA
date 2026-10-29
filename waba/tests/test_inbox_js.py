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

		self.assertEqual(ALERT_ROLES, {"Waba Admin", "Waba Supervisor", "Waba Agent", "System Manager"})
		self.assertTrue(wants_alerts("a@x.com", ["Waba Agent"]))
		self.assertTrue(wants_alerts("a@x.com", ["System Manager", "Sales User"]))
		self.assertFalse(wants_alerts("a@x.com", ["Sales User", "Accounts User"]))
		self.assertFalse(wants_alerts("a@x.com", []))
		self.assertFalse(wants_alerts("Guest", ["Waba Admin"]))


if __name__ == "__main__":
	unittest.main()
