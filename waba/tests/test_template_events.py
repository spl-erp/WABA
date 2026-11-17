"""Run without a site:  python -m unittest waba.tests.test_template_events"""

import os
import unittest

from waba.rules import template_events as ev

BASE = os.path.join(os.path.dirname(__file__), "..")


def status(event, **k):
	return {"event": event, "message_template_id": 123, "message_template_name": "order_update", "message_template_language": "en", **k}


class TestParse(unittest.TestCase):
	def test_approved_clears_an_old_rejection(self):
		p = ev.parse("message_template_status_update", status("APPROVED", reason="NONE"))
		self.assertEqual((p["id"], p["name"], p["language"]), ("123", "order_update", "en"))
		self.assertEqual(p["updates"], {"status": "APPROVED", "rejected_reason": None})
		self.assertIsNone(p["alert"])

	def test_rejected_keeps_a_plain_reason_and_alerts(self):
		p = ev.parse("message_template_status_update", status("REJECTED", reason="INVALID_FORMAT"))
		self.assertEqual(p["updates"]["status"], "REJECTED")
		self.assertIn("examples are not valid", p["updates"]["rejected_reason"])
		self.assertIn("order_update (en) was rejected", p["alert"])

	def test_rejected_with_no_reason_still_says_something(self):
		self.assertEqual(ev.parse("message_template_status_update", status("REJECTED", reason="NONE"))["updates"]["rejected_reason"], "Meta rejected the template.")
		self.assertIn("reason", ev.parse("message_template_status_update", status("REJECTED", reason="NEW_THING"))["updates"]["rejected_reason"])

	def test_paused_and_disabled_alert_without_losing_the_template(self):
		for event in ("PAUSED", "DISABLED"):
			p = ev.parse("message_template_status_update", status(event))
			self.assertEqual(p["updates"]["status"], event)
			self.assertIn(event.lower(), p["alert"])

	def test_reinstated_and_pending_and_unknown_events(self):
		self.assertEqual(ev.parse("message_template_status_update", status("REINSTATED"))["updates"]["status"], "APPROVED")
		self.assertEqual(ev.parse("message_template_status_update", status("PENDING"))["updates"]["status"], "PENDING")
		self.assertEqual(ev.parse("message_template_status_update", status("SOMETHING_NEW"))["updates"], {})
		self.assertIn("flagged", ev.parse("message_template_status_update", status("FLAGGED"))["alert"])

	def test_quality_and_category(self):
		q = ev.parse("message_template_quality_update", {"message_template_id": 1, "message_template_name": "a", "message_template_language": "en", "new_quality_score": "red"})
		self.assertEqual(q["updates"], {"quality": "RED"})
		self.assertIn("red", q["alert"])
		self.assertIsNone(ev.parse("message_template_quality_update", {"message_template_id": 1, "new_quality_score": "GREEN"})["alert"])
		c = ev.parse("template_category_update", {"message_template_id": 1, "message_template_name": "a", "message_template_language": "en", "new_category": "marketing"})
		self.assertEqual(c["updates"], {"category": "MARKETING"})
		self.assertIn("Marketing templates cannot be used", c["alert"])

	def test_identity_by_id_or_by_name_and_language(self):
		self.assertEqual(ev.parse("message_template_status_update", {"event": "APPROVED", "message_template_id": 9})["id"], "9")
		self.assertEqual(ev.parse("message_template_status_update", {"event": "APPROVED", "message_template_name": "n", "message_template_language": "en"})["name"], "n")

	def test_not_a_template_event_or_no_identity_gives_nothing(self):
		self.assertIsNone(ev.parse("messages", {"event": "APPROVED"}))
		self.assertIsNone(ev.parse("message_template_status_update", {"event": "APPROVED"}))
		self.assertIsNone(ev.parse("message_template_status_update", {"event": "APPROVED", "message_template_name": "n"}))
		self.assertIsNone(ev.parse("message_template_status_update", None))
		self.assertIsNone(ev.parse("message_template_status_update", "x"))

	def test_a_components_update_changes_nothing_by_itself(self):
		p = ev.parse("message_template_components_update", {"message_template_id": 1, "message_template_element": "x"})
		self.assertEqual(p["updates"], {})


class TestWiring(unittest.TestCase):
	def test_the_webhook_applies_template_events(self):
		with open(os.path.join(BASE, "api", "webhook.py"), encoding="utf-8") as handle:
			src = handle.read()
		self.assertIn("template_events.apply_changes(payload, account)", src)

	def test_unknown_templates_are_noted_and_admins_are_alerted(self):
		with open(os.path.join(BASE, "template_events.py"), encoding="utf-8") as handle:
			src = handle.read()
		self.assertIn("is not in the ERP yet", src)
		self.assertIn("ROLE_ADMIN", src)
		self.assertIn("update_modified=False", src)


if __name__ == "__main__":
	unittest.main()
