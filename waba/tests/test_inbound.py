"""Run without a site:  python -m unittest waba.tests.test_inbound"""

import unittest

from waba.rules import inbound


def value(messages, contacts=None):
	return {"messages": messages, "contacts": contacts or []}


TEXT = {"id": "wamid.1", "from": "919876543210", "timestamp": "1790000000", "type": "text", "text": {"body": "Hello"}}
CONTACT = {"wa_id": "919876543210", "profile": {"name": "Rahul"}}


class TestIdentity(unittest.TestCase):
	def test_phone_sender(self):
		m = inbound.parse_messages(value([TEXT], [CONTACT]))[0]
		self.assertEqual((m["phone"], m["bsuid"], m["profile_name"]), ("+919876543210", None, "Rahul"))

	def test_bsuid_is_never_mistaken_for_a_phone(self):
		self.assertTrue(inbound.is_bsuid("IN.1234567890123"))
		self.assertFalse(inbound.is_bsuid("919876543210"))
		m = inbound.parse_messages(value([{**TEXT, "from": "IN.1234567890123"}], [{"user_id": "IN.1234567890123", "profile": {"name": "Asha"}}]))[0]
		self.assertEqual((m["phone"], m["bsuid"]), (None, "IN.1234567890123"))

	def test_phone_and_bsuid_together(self):
		m = inbound.parse_messages(value([{**TEXT, "from_user_id": "IN.abc"}], [CONTACT]))[0]
		self.assertEqual((m["phone"], m["bsuid"]), ("+919876543210", "IN.abc"))

	def test_contact_is_matched_by_sender_else_single_contact(self):
		contacts = [{"wa_id": "111111111", "profile": {"name": "Other"}}, CONTACT]
		self.assertEqual(inbound.parse_messages(value([TEXT], contacts))[0]["profile_name"], "Rahul")
		self.assertEqual(inbound.parse_messages(value([{**TEXT, "from": "x"}], [CONTACT]))[0]["profile_name"], "Rahul")
		self.assertIsNone(inbound.parse_messages(value([{**TEXT, "from": "x"}], contacts))[0]["profile_name"])

	def test_unusable_sender_gives_neither(self):
		m = inbound.parse_messages(value([{**TEXT, "from": "12"}]))[0]
		self.assertEqual((m["phone"], m["bsuid"]), (None, None))


class TestBodies(unittest.TestCase):
	def body(self, kind, **part):
		return inbound.parse_messages(value([{"id": "w", "from": "919876543210", "type": kind, kind: part}]))[0]["body"]

	def test_kinds(self):
		self.assertEqual(self.body("text", body="Hi there"), "Hi there")
		self.assertEqual(self.body("image", caption="Invoice"), "[image] Invoice")
		self.assertEqual(self.body("document", filename="q.pdf"), "[document] q.pdf")
		self.assertEqual(self.body("audio"), "[audio]")
		self.assertEqual(self.body("button", text="Yes"), "Yes")
		self.assertEqual(self.body("reaction", emoji="👍"), "👍")
		self.assertEqual(self.body("location", name="Shop", address="Pune"), "[location] Shop Pune")
		self.assertEqual(inbound.parse_messages(value([{"id": "w", "from": "919876543210", "type": "interactive", "interactive": {"list_reply": {"title": "Option 2"}}}]))[0]["body"], "Option 2")
		self.assertEqual(self.body("order"), "[order]")


class TestShapes(unittest.TestCase):
	def test_skips_messages_without_an_id_and_bad_entries(self):
		self.assertEqual(inbound.parse_messages(value([{"from": "9"}, None, "x", {**TEXT, "id": ""}])), [])
		self.assertEqual(inbound.parse_messages({}), [])
		self.assertEqual(inbound.parse_messages({"messages": "x", "contacts": "y"}), [])

	def test_timestamp_and_reply_context(self):
		m = inbound.parse_messages(value([{**TEXT, "context": {"id": "wamid.0"}}]))[0]
		self.assertEqual((m["timestamp"], m["reply_to"]), (1790000000, "wamid.0"))
		self.assertIsNone(inbound.parse_messages(value([{**TEXT, "timestamp": "soon"}]))[0]["timestamp"])

	def test_order_is_kept(self):
		ids = [m["message_id"] for m in inbound.parse_messages(value([{**TEXT, "id": "a"}, {**TEXT, "id": "b"}]))]
		self.assertEqual(ids, ["a", "b"])


class TestHelpers(unittest.TestCase):
	def test_preview_collapses_space_and_truncates(self):
		self.assertEqual(inbound.preview("a \n  b"), "a b")
		self.assertEqual(len(inbound.preview("x" * 500)), inbound.PREVIEW_LIMIT)
		self.assertEqual(inbound.preview(None), "")

	def test_conversation_key(self):
		self.assertEqual(inbound.conversation_key("+911", "+9198", "IN.a"), "+911|+9198")
		self.assertEqual(inbound.conversation_key("+911", None, "IN.a"), "+911|IN.a")
		self.assertIsNone(inbound.conversation_key("+911", None, None))
		self.assertIsNone(inbound.conversation_key(None, "+9198", None))


if __name__ == "__main__":
	unittest.main()
