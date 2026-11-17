"""Run without a site:  python -m unittest waba.tests.test_coexistence

WhatsApp Business app coexistence, stage 1: what the business types in the phone app arrives as `smb_message_echoes` and is
stored as an outgoing "Phone app" message without running any customer-message logic; `account_update` keeps the link state."""

import json
import os
import unittest

from waba.rules import coexistence, inbound

APP = os.path.join(os.path.dirname(__file__), "..")


def read(*parts):
	with open(os.path.join(APP, *parts), encoding="utf-8") as handle:
		return handle.read()


def echo(**extra):
	message = {"from": "919272091491", "to": "919876543210", "id": "wamid.ECHO1", "timestamp": "1794650615", "type": "text", "text": {"body": "We can send it today."}}
	message.update(extra)
	return {"messaging_product": "whatsapp", "metadata": {"display_phone_number": "919272091491", "phone_number_id": "111"},
	        "contacts": [{"wa_id": "919876543210", "user_id": "IN.123"}], "message_echoes": [message]}


class TestParseEchoes(unittest.TestCase):
	def test_the_customer_is_the_recipient_never_our_own_number(self):
		(m,) = inbound.parse_echoes(echo())
		self.assertEqual(m["phone"], "+919876543210")
		self.assertNotEqual(m["phone"], "+919272091491")
		self.assertEqual(m["bsuid"], "IN.123")
		self.assertEqual(m["action"], "new")
		self.assertEqual(m["body"], "We can send it today.")
		self.assertEqual(m["type"], "text")

	def test_a_customer_known_only_by_user_id(self):
		value = echo(to=None, to_user_id="IN.999")
		value["contacts"] = [{"user_id": "IN.999"}]
		(m,) = inbound.parse_echoes(value)
		self.assertIsNone(m["phone"])
		self.assertEqual(m["bsuid"], "IN.999")
		self.assertEqual(inbound.conversation_key("+91 num", m["phone"], m["bsuid"]), "+91 num|IN.999")

	def test_a_file_keeps_its_reference_and_caption(self):
		(m,) = inbound.parse_echoes(echo(type="image", text=None, image={"id": "MEDIA1", "mime_type": "image/jpeg", "caption": "Price list"}))
		self.assertEqual(m["media_id"], "MEDIA1")
		self.assertEqual(m["body"], "[image] Price list")

	def test_an_edit_carries_the_new_text_and_the_original_id(self):
		(m,) = inbound.parse_echoes(echo(original_message_id="wamid.OLD", message={"type": "text", "text": {"body": "Corrected text"}}))
		self.assertEqual((m["action"], m["original_id"], m["body"]), ("edit", "wamid.OLD", "Corrected text"))

	def test_a_revoke_has_no_text(self):
		(m,) = inbound.parse_echoes(echo(original_message_id="wamid.OLD", type="revoke", text=None))
		self.assertEqual((m["action"], m["original_id"], m["body"]), ("revoke", "wamid.OLD", ""))

	def test_an_entry_without_an_id_is_skipped(self):
		value = echo()
		value["message_echoes"].append({"to": "919876543210"})
		self.assertEqual(len(inbound.parse_echoes(value)), 1)

	def test_nothing_in_the_value_is_nothing(self):
		self.assertEqual(inbound.parse_echoes({}), [])
		self.assertEqual(inbound.parse_echoes({"message_echoes": ["x", 3]}), [])


class TestAccountUpdate(unittest.TestCase):
	def test_events_map_to_states(self):
		self.assertEqual(coexistence.account_event({"event": "PARTNER_REMOVED", "disconnection_info": {"reason": "PRIMARY_INACTIVITY"}})[1], "Disconnected")
		self.assertEqual(coexistence.account_event({"event": "ACCOUNT_OFFBOARDED"})[1], "Offboarded")
		self.assertEqual(coexistence.account_event({"event": "ACCOUNT_RECONNECTED"})[1], "Connected")
		self.assertIsNone(coexistence.account_event({"event": "SOMETHING_NEW"})[1])
		self.assertEqual(coexistence.account_event(None), ("", None, ""))

	def test_the_sentences_say_what_happened(self):
		event, state, reason = coexistence.account_event({"event": "PARTNER_REMOVED", "disconnection_info": {"reason": "PRIMARY_INACTIVITY"}})
		text = coexistence.state_sentence(event, state, reason)
		self.assertIn("not opened for about 14 days", text)
		self.assertIn("restored", coexistence.state_sentence(*coexistence.account_event({"event": "ACCOUNT_RECONNECTED"})))
		self.assertIn("SOMETHING_NEW", coexistence.state_sentence(*coexistence.account_event({"event": "SOMETHING_NEW"})))

	def test_a_deleted_message_stays_readable_and_marked(self):
		self.assertEqual(coexistence.revoked_body("hello"), "[deleted from the phone app] hello")
		self.assertEqual(coexistence.revoked_body(None), "[deleted from the phone app]")

	def test_edit_or_revoke(self):
		self.assertIsNone(coexistence.is_edit_or_revoke({"id": "x"}))
		self.assertEqual(coexistence.is_edit_or_revoke({"original_message_id": "o", "message": {}}), "edit")
		self.assertEqual(coexistence.is_edit_or_revoke({"original_message_id": "o"}), "revoke")


class TestEchoesNeverRunCustomerLogic(unittest.TestCase):
	"""An echo is OUR message: it must not reopen the window, count as unread, opt anyone out, start a bot, assign or ring."""

	BODY = read("inbound.py").split("def store_echoes(")[1].split("\ndef _keyword(")[0]

	def test_none_of_the_customer_message_steps_run(self):
		for forbidden in ("_update_conversation(", "_keyword(", "_campaign_reply(", "_bot(", "_route(", "assignment.assign(", "assignment.notify(", "unread_count", "last_inbound_at\":", "window_expires_at"):
			self.assertNotIn(forbidden, self.BODY, forbidden)

	def test_it_is_stored_as_our_side(self):
		self.assertIn('"direction": "Out"', self.BODY)
		self.assertIn('"origin": "Phone app"', self.BODY)
		self.assertNotIn("sent_by", self.BODY)

	def test_duplicates_of_our_own_sends_are_skipped(self):
		self.assertLess(self.BODY.index('frappe.db.exists("Waba Message", {"message_id"'), self.BODY.index("_conversation(key"))

	def test_a_bot_stops_but_the_chat_is_given_to_nobody(self):
		self.assertIn("bot.on_phone_reply(", self.BODY)
		bot = read("bot.py").split("def on_phone_reply(")[1].split("\ndef ")[0]
		self.assertIn("stop(session", bot)
		self.assertNotIn("assigned_to", bot)

	def test_last_message_only_moves_forward(self):
		self.assertIn("sent_at >= last", self.BODY)


class TestWiring(unittest.TestCase):
	WEBHOOK = read("api", "webhook.py")

	def test_the_echo_field_and_account_updates_are_handled(self):
		self.assertIn("_store_echo_changes(payload, account, doc.name)", self.WEBHOOK)
		self.assertIn("coexistence.apply_account_updates(payload, account)", self.WEBHOOK)
		self.assertIn("HANDLED_FIELDS", self.WEBHOOK)

	def test_history_and_contact_sync_are_marked_not_handled_not_processed(self):
		self.assertIn('status = "Ignored"', self.WEBHOOK)
		self.assertIn("Not handled yet, kept as received", self.WEBHOOK)
		for field in coexistence.NOT_IMPORTED_FIELDS:
			self.assertNotIn(field, ("messages", coexistence.ECHO_FIELD, coexistence.ACCOUNT_FIELD))

	def test_the_number_has_the_coexistence_fields_and_they_are_in_the_form(self):
		doc = json.loads(read("waba", "doctype", "waba_number", "waba_number.json"))
		fields = {f["fieldname"]: f for f in doc["fields"]}
		self.assertEqual(fields["coexistence"]["fieldtype"], "Check")
		self.assertIn(fields["coexistence"].get("default"), (None, "0", 0))
		self.assertEqual(fields["coexistence_state"]["options"].split("\n"), ["", "Connected", "Disconnected", "Offboarded"])
		for name in ("coexistence_section", "coexistence", "coexistence_state", "coexistence_at"):
			self.assertIn(name, doc["field_order"])

	def test_registration_steps_refuse_a_coexistence_number(self):
		numbers = read("api", "numbers.py")
		for fn in ("request_code", "verify_code", "register"):
			body = numbers.split(f"def {fn}(")[1].split("\n@frappe.whitelist")[0]
			self.assertIn("_not_coexistence(doc)", body, fn)
			self.assertLess(body.index("_not_coexistence(doc)"), body.index("graph."), fn)

	def test_the_buttons_are_off_for_a_coexistence_number_and_the_label_is_plain(self):
		self.assertIn("|| frm.doc.coexistence) return;", read("waba", "doctype", "waba_number", "waba_number.js"))
		self.assertIn('"Phone app": "Sent from the phone app"', read("public", "js", "waba_inbox_lib.js"))

	def test_the_account_update_code_waits_for_the_migrate(self):
		self.assertIn('has_field("coexistence")', read("coexistence.py"))


if __name__ == "__main__":
	unittest.main()
