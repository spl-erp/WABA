"""Run without a site:  python -m unittest waba.tests.test_outbound"""

import datetime
import unittest

from waba.rules import outbound as ob
from waba.rules import statuses as st

NOW = datetime.datetime(2026, 10, 28, 12, 0, 0)
OPEN = NOW - datetime.timedelta(hours=1)
CLOSED = NOW - datetime.timedelta(hours=25)


class TestFreeText(unittest.TestCase):
	def test_allowed_in_open_window(self):
		self.assertEqual(ob.check_free_text("Hello", OPEN, NOW), (True, None, None))

	def test_refusals(self):
		self.assertEqual(ob.check_free_text("  ", OPEN, NOW)[1], ob.EMPTY)
		self.assertEqual(ob.check_free_text(None, OPEN, NOW)[1], ob.EMPTY)
		self.assertEqual(ob.check_free_text("x" * 4097, OPEN, NOW)[1], ob.TOO_LONG)
		self.assertEqual(ob.check_free_text("Hello", CLOSED, NOW)[1], ob.WINDOW_CLOSED)
		self.assertEqual(ob.check_free_text("Hello", None, NOW)[1], ob.WINDOW_CLOSED)
		self.assertTrue(ob.check_free_text("x" * 4096, OPEN, NOW)[0])

	def test_recipient(self):
		self.assertTrue(ob.check_recipient("+919876543210")[0])
		self.assertEqual(ob.check_recipient(None)[1], ob.NO_PHONE)
		self.assertEqual(ob.check_recipient("IN.abc")[1], ob.NO_PHONE)


class TestTemplates(unittest.TestCase):
	def test_variable_count_and_fill(self):
		self.assertEqual(ob.variable_count("Hi {{1}}, order {{2}}"), 2)
		self.assertEqual(ob.variable_count("no variables"), 0)
		self.assertEqual(ob.variable_count("{{ 3 }} only"), 3)
		self.assertEqual(ob.fill("Hi {{1}}, order {{2}}", ["Rahul", "SO-1"]), "Hi Rahul, order SO-1")
		self.assertEqual(ob.fill("Hi {{1}}, order {{2}}", ["Rahul"]), "Hi Rahul, order {{2}}")

	def test_validate_params(self):
		t = "Hi {{1}}, order {{2}}"
		self.assertEqual(ob.validate_params(t, ["Rahul", "SO-1"]), [])
		self.assertTrue(ob.validate_params(t, ["Rahul"]))
		self.assertTrue(any("empty" in e for e in ob.validate_params(t, ["Rahul", " "])))
		self.assertTrue(any("line break" in e for e in ob.validate_params(t, ["a\nb", "x"])))
		self.assertTrue(any("line break" in e for e in ob.validate_params(t, ["a     b", "x"])))
		self.assertEqual(ob.validate_params(t, ["a    b", "x"]), [])  # four spaces are allowed
		self.assertTrue(any("1024" in e for e in ob.validate_params("{{1}}", ["x" * 1025])))
		self.assertEqual(ob.validate_params("no variables", []), [])


class TestPayloads(unittest.TestCase):
	def test_text_payload(self):
		p = ob.text_payload("+91 98765 43210", " Hello ", "wamid.1")
		self.assertEqual(p["to"], "919876543210")
		self.assertEqual((p["type"], p["text"]["body"], p["context"]), ("text", "Hello", {"message_id": "wamid.1"}))
		self.assertNotIn("context", ob.text_payload("+919876543210", "Hi"))

	def test_template_payload(self):
		p = ob.template_payload("+919876543210", "order_update", "en", ["Rahul", " SO-1 "])
		self.assertEqual(p["template"]["name"], "order_update")
		self.assertEqual(p["template"]["language"], {"code": "en"})
		self.assertEqual(p["template"]["components"][0]["parameters"], [{"type": "text", "text": "Rahul"}, {"type": "text", "text": "SO-1"}])
		self.assertNotIn("components", ob.template_payload("+919876543210", "hello", "en", [])["template"])

	def test_read_receipt_and_response(self):
		self.assertEqual(ob.read_receipt_payload("w1")["status"], "read")
		self.assertEqual(ob.sent_message_id({"messages": [{"id": "wamid.9"}]}), "wamid.9")
		for bad in (None, {}, {"messages": []}, {"messages": ["x"]}, "x"):
			self.assertIsNone(ob.sent_message_id(bad))


class TestStatuses(unittest.TestCase):
	def test_forward_only(self):
		self.assertEqual(st.next_status("Queued", "sent"), "Sent")
		self.assertEqual(st.next_status("Sent", "delivered"), "Delivered")
		self.assertEqual(st.next_status("Delivered", "read"), "Read")
		self.assertEqual(st.next_status("Queued", "read"), "Read")  # delivered report lost or late
		for current, meta in (("Read", "delivered"), ("Delivered", "sent"), ("Sent", "sent"), ("Read", "read")):
			self.assertIsNone(st.next_status(current, meta), (current, meta))

	def test_failure_rules(self):
		self.assertEqual(st.next_status("Sent", "failed"), "Failed")
		self.assertEqual(st.next_status("Queued", "failed"), "Failed")
		self.assertIsNone(st.next_status("Delivered", "failed"))
		self.assertIsNone(st.next_status("Read", "failed"))
		self.assertIsNone(st.next_status("Failed", "sent"))
		self.assertIsNone(st.next_status("Failed", "failed"))

	def test_unknown_status_and_none_current(self):
		self.assertIsNone(st.next_status("Sent", "deleted"))
		self.assertEqual(st.next_status(None, "sent"), "Sent")
		self.assertEqual(st.next_status("Sent", "DELIVERED"), "Delivered")

	def test_failure_text(self):
		code, text = st.failure({"errors": [{"code": 131047, "title": "Re-engagement", "message": "m", "error_data": {"details": "More than 24 hours"}}]})
		self.assertEqual(code, 131047)
		self.assertIn("More than 24 hours", text)
		self.assertEqual(st.failure({}), (None, None))
		self.assertEqual(st.failure({"errors": []}), (None, None))
		self.assertEqual(st.failure({"errors": [{"code": 999999}]})[0], 999999)


if __name__ == "__main__":
	unittest.main()
