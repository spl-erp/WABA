import unittest

from waba.rules import inbound, media, outbound


def msg(kind, **part):
	return {"messages": [{"id": "wamid.1", "from": "919876543210", "type": kind, kind: part}]}


class TestMediaRules(unittest.TestCase):
	def test_kind_and_extension_come_from_the_mime_type(self):
		self.assertEqual(media.kind_for_mime("image/jpeg"), "image")
		self.assertEqual(media.kind_for_mime("image/webp"), "sticker")
		self.assertEqual(media.kind_for_mime("audio/ogg; codecs=opus"), "audio")
		self.assertEqual(media.kind_for_mime("application/pdf"), "document")
		self.assertIsNone(media.kind_for_mime("application/x-msdownload"))
		self.assertEqual(media.extension_for("audio/ogg; codecs=opus"), ".ogg")
		self.assertEqual(media.extension_for("video/quicktime"), ".mov")
		self.assertEqual(media.extension_for("nonsense"), "")

	def test_upload_limits_in_words(self):
		self.assertEqual(media.check_upload("image/png", 1000)[0], True)
		ok, kind, why = media.check_upload("image/png", 6 * media.MB)
		self.assertFalse(ok)
		self.assertIn("This image is 6.0 MB", why)
		self.assertIn("at most 5.0 MB for an image", why)
		self.assertFalse(media.check_upload("application/pdf", 0)[0])
		self.assertFalse(media.check_upload("application/zip", 10)[0])
		self.assertTrue(media.check_upload("application/pdf", 99 * media.MB)[0])
		self.assertFalse(media.check_upload("application/pdf", 101 * media.MB)[0])

	def test_captions(self):
		self.assertEqual(media.check_caption("image", "hello"), (True, ""))
		self.assertFalse(media.check_caption("audio", "hello")[0])
		self.assertFalse(media.check_caption("document", "x" * 1025)[0])
		self.assertEqual(media.check_caption("audio", "  "), (True, ""))

	def test_safe_filename(self):
		self.assertEqual(media.safe_filename("../../etc/passwd", "text/plain"), "passwd.txt")
		self.assertEqual(media.safe_filename("my quote?.PDF", "application/pdf"), "my quote.pdf")
		self.assertEqual(media.safe_filename("photo.jpeg", "image/jpeg"), "photo.jpeg")
		self.assertEqual(media.safe_filename("", "image/png"), "file.png")
		self.assertEqual(media.safe_filename("a.exe", "image/png"), "a.png")
		self.assertEqual(media.safe_filename("C:\\dir\\inv.pdf", "application/pdf"), "inv.pdf")

	def test_human_size(self):
		self.assertEqual(media.human_size(512), "512 B")
		self.assertEqual(media.human_size(2048), "2 KB")
		self.assertEqual(media.human_size(5 * media.MB), "5.0 MB")


class TestInboundDetails(unittest.TestCase):
	def first(self, kind, **part):
		return inbound.parse_messages(msg(kind, **part))[0]

	def test_file_reference_is_kept(self):
		m = self.first("document", id="M9", mime_type="application/pdf", sha256="abc", filename="q.pdf", caption="Quote")
		self.assertEqual((m["media_id"], m["media_mime"], m["media_sha256"], m["media_filename"]), ("M9", "application/pdf", "abc", "q.pdf"))
		self.assertEqual(m["body"], "[document] Quote")

	def test_voice_note_flag(self):
		self.assertEqual(self.first("audio", id="A1", mime_type="audio/ogg", voice=True)["voice"], 1)
		self.assertEqual(self.first("audio", id="A1", mime_type="audio/mpeg")["voice"], 0)

	def test_location_coordinates(self):
		m = self.first("location", latitude=19.07, longitude="72.87")
		self.assertEqual((m["latitude"], m["longitude"]), (19.07, 72.87))
		self.assertIsNone(self.first("location", latitude="x")["latitude"])

	def test_reaction_target_and_reply_ids(self):
		self.assertEqual(self.first("reaction", message_id="wamid.T", emoji="👍")["reaction_to"], "wamid.T")
		self.assertEqual(self.first("interactive", button_reply={"id": "b1", "title": "Yes"})["interactive_id"], "b1")
		self.assertEqual(self.first("button", payload="P", text="Go")["interactive_id"], "P")

	def test_contact_cards(self):
		value = {"messages": [{"id": "w", "from": "919876543210", "type": "contacts", "contacts": [{"name": {"formatted_name": "Asha"}, "phones": [{"phone": "+91 98"}]}]}]}
		m = inbound.parse_messages(value)[0]
		self.assertEqual(m["contacts"], [{"name": "Asha", "phones": ["+91 98"]}])
		self.assertEqual(m["body"], "[contacts] Asha")

	def test_plain_text_has_the_same_shape(self):
		m = self.first("text", body="Hi")
		self.assertIsNone(m["media_id"])
		self.assertEqual(m["voice"], 0)


class TestMediaPayloads(unittest.TestCase):
	def test_document_with_caption_and_name(self):
		p = outbound.media_payload("+919876543210", "document", "M1", " Quote ", "q.pdf", "wamid.R")
		self.assertEqual(p["document"], {"id": "M1", "caption": "Quote", "filename": "q.pdf"})
		self.assertEqual(p["to"], "919876543210")
		self.assertEqual(p["context"], {"message_id": "wamid.R"})

	def test_audio_never_carries_a_caption(self):
		self.assertEqual(outbound.media_payload("+919876543210", "audio", "A1", "hello")["audio"], {"id": "A1"})

	def test_reaction_payload_and_removal(self):
		self.assertEqual(outbound.reaction_payload("+919876543210", "wamid.X", "👍")["reaction"], {"message_id": "wamid.X", "emoji": "👍"})
		self.assertEqual(outbound.reaction_payload("+919876543210", "wamid.X", None)["reaction"]["emoji"], "")


if __name__ == "__main__":
	unittest.main()


class TestServeAs(unittest.TestCase):
	def test_only_known_safe_kinds_are_inline(self):
		self.assertEqual(media.serve_as("image/png"), ("image/png", "inline"))
		self.assertEqual(media.serve_as("audio/ogg; codecs=opus"), ("audio/ogg", "inline"))
		self.assertEqual(media.serve_as("image/webp"), ("image/webp", "inline"))
		self.assertEqual(media.serve_as("application/pdf"), ("application/pdf", "attachment"))
		for risky in ("text/html", "image/svg+xml", "application/javascript", "", "application/x-msdownload"):
			self.assertEqual(media.serve_as(risky), ("application/octet-stream", "attachment"), risky)


class TestContentChecks(unittest.TestCase):
	def test_sniff_known_signatures(self):
		self.assertEqual(media.sniff(b"\xff\xd8\xff\xe0rest"), "image/jpeg")
		self.assertEqual(media.sniff(b"\x89PNG\r\n\x1a\nxx"), "image/png")
		self.assertEqual(media.sniff(b"%PDF-1.7"), "application/pdf")
		self.assertEqual(media.sniff(b"RIFF\x00\x00\x00\x00WEBPVP8 "), "image/webp")
		self.assertEqual(media.sniff(b"\x00\x00\x00\x18ftypmp42"), "video/mp4")
		self.assertIsNone(media.sniff(b"MZ\x90\x00"))
		self.assertIsNone(media.sniff(b""))

	def test_name_and_bytes_must_agree(self):
		self.assertTrue(media.check_content("application/pdf", b"%PDF-1.4")[0])
		self.assertFalse(media.check_content("application/pdf", b"MZ\x90\x00 an exe")[0])
		self.assertFalse(media.check_content("image/png", b"%PDF-1.4")[0])
		self.assertFalse(media.check_content("image/jpeg", b"plain text")[0])
		self.assertTrue(media.check_content("text/plain", b"plain text")[0])  # no signature to contradict
		self.assertTrue(media.check_content("application/vnd.openxmlformats-officedocument.wordprocessingml.document", b"PK\x03\x04")[0])
		self.assertTrue(media.check_content("video/mp4", b"\x00\x00\x00\x18ftypmp42")[0])

	def test_library_visibility(self):
		from datetime import date

		today = date(2026, 11, 2)
		row = lambda **k: {"enabled": 1, "scope": "Everyone", "team": None, "valid_until": None, **k}
		self.assertTrue(media.shared_file_visible(row(), today, set()))
		self.assertFalse(media.shared_file_visible(row(enabled=0), today, set()))
		self.assertFalse(media.shared_file_visible(row(valid_until=date(2026, 11, 1)), today, set()))
		self.assertTrue(media.shared_file_visible(row(valid_until=today), today, set()))
		self.assertFalse(media.shared_file_visible(row(scope="Team", team="Sales"), today, {"Marketing"}))
		self.assertTrue(media.shared_file_visible(row(scope="Team", team="Sales"), today, {"Sales", "Common"}))
		self.assertTrue(media.shared_file_visible(row(scope="Team", team="Sales"), today, set(), admin=True))
		self.assertFalse(media.shared_file_visible(row(scope="Team", team="Sales", valid_until=date(2026, 1, 1)), today, set(), admin=True))


class TestOutboundChecks(unittest.TestCase):
	def test_files_need_the_window(self):
		from datetime import datetime, timedelta

		now = datetime(2026, 11, 2, 12, 0)
		self.assertTrue(outbound.check_media_send(now - timedelta(hours=1), now)[0])
		ok, code, message = outbound.check_media_send(now - timedelta(hours=30), now)
		self.assertFalse(ok)
		self.assertIn("template", message)
		self.assertFalse(outbound.check_media_send(None, now)[0])


class TestSendSource(unittest.TestCase):
	"""The browser must never choose an origin: no whitelisted sender takes one."""

	def test_no_whitelisted_function_has_an_origin_argument(self):
		import ast, os

		path = os.path.join(os.path.dirname(__file__), "..", "api", "send.py")
		tree = ast.parse(open(path).read())
		for node in tree.body:
			if isinstance(node, ast.FunctionDef) and any("whitelist" in ast.dump(d) for d in node.decorator_list):
				self.assertNotIn("origin", [a.arg for a in node.args.args], node.name)

	def test_every_whitelisted_function_is_type_annotated(self):
		import ast, os

		path = os.path.join(os.path.dirname(__file__), "..", "api", "send.py")
		tree = ast.parse(open(path).read())
		for node in tree.body:
			if isinstance(node, ast.FunctionDef) and any("whitelist" in ast.dump(d) for d in node.decorator_list):
				for a in node.args.args:
					self.assertIsNotNone(a.annotation, f"{node.name}({a.arg})")


class TestInboxWiring(unittest.TestCase):
	"""The inbox page is plain browser code that cannot run here, so its links to the server and between its own parts
	are checked from the source: no call to a method that does not exist, no handler used but never provided."""

	def setUp(self):
		import os

		base = os.path.join(os.path.dirname(__file__), "..")
		self.js = open(os.path.join(base, "public", "js", "waba_inbox_app.js"), encoding="utf-8").read()
		self.base = base

	def whitelisted(self, module):
		import ast, os

		tree = ast.parse(open(os.path.join(self.base, "api", module + ".py"), encoding="utf-8").read())
		return {n.name for n in tree.body if isinstance(n, ast.FunctionDef) and any("whitelist" in ast.dump(d) for d in n.decorator_list)}

	def test_every_server_method_the_page_calls_exists_and_is_whitelisted(self):
		import re

		calls = set(re.findall(r"waba\.api\.(\w+)\.(\w+)", self.js))
		calls |= {("send", m) for m in re.findall(r'this\.send\("(\w+)"', self.js)}
		self.assertTrue(calls)
		for module, name in calls:
			self.assertIn(name, self.whitelisted(module), f"waba.api.{module}.{name}")

	def test_every_handler_used_is_provided(self):
		import re

		used = set(re.findall(r"this\.handlers\.(\w+)", self.js))
		provided = set(re.findall(r"^\s{3}(on\w+|draftsFor):", self.js, re.M))
		for name in used:
			self.assertIn(name, provided, f"handler {name} is used but never provided")

	def test_user_data_is_escaped_before_it_goes_into_html(self):
		for fragment in ("waba_e(mv.name", "waba_e(mv.error", "waba_e(m.name)", "waba_e(r.emoji)", "waba_e(c.name"):
			self.assertIn(fragment, self.js, fragment)
		self.assertNotIn("scrollIntoView", self.js)


class TestInboundRaceSource(unittest.TestCase):
	"""Two deliveries from a new customer in the same second must not lose a message (seen live on 31 Oct)."""

	def setUp(self):
		import os

		self.src = open(os.path.join(os.path.dirname(__file__), "..", "inbound.py"), encoding="utf-8").read()

	def test_both_kinds_of_unique_clash_are_handled(self):
		self.assertIn("_CLASH = (frappe.DuplicateEntryError, frappe.UniqueValidationError)", self.src)
		self.assertNotIn("except frappe.DuplicateEntryError", self.src)

	def test_conversation_creation_is_serialised_and_re_read_with_a_locking_read(self):
		self.assertIn('locks.conversation(f"create:{key}")', self.src)
		self.assertIn("for_update=True", self.src)
