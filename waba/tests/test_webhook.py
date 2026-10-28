"""Run without a site:  python -m unittest waba.tests.test_webhook"""

import json
import unittest

from waba.rules import webhook as wh


def delivery(**value):
	return {
		"object": "whatsapp_business_account",
		"entry": [
			{
				"id": "111",
				"changes": [
					{"field": "messages", "value": {"metadata": {"phone_number_id": "222"}, **value}}
				],
			}
		],
	}


class TestHandshake(unittest.TestCase):
	def test_accepts_matching_token(self):
		self.assertTrue(wh.verify_handshake("subscribe", "abc", "abc"))

	def test_rejects_everything_else(self):
		for mode, token, expected in (
			("unsubscribe", "abc", "abc"),
			("subscribe", "abd", "abc"),
			("subscribe", "", "abc"),
			("subscribe", None, "abc"),
			("subscribe", "abc", ""),
			("subscribe", "abc", None),
			(None, "abc", "abc"),
		):
			self.assertFalse(wh.verify_handshake(mode, token, expected), (mode, token, expected))


class TestBodyHash(unittest.TestCase):
	def test_same_bytes_same_id_different_bytes_different_id(self):
		self.assertEqual(wh.body_hash(b'{"a":1}'), wh.body_hash('{"a":1}'))
		self.assertNotEqual(wh.body_hash(b'{"a":1}'), wh.body_hash(b'{"a": 1}'))
		self.assertEqual(len(wh.body_hash(b"x")), 64)


class TestTitle(unittest.TestCase):
	def test_title(self):
		s = wh.summarise(delivery(messages=[{"id": "m1"}]))
		self.assertEqual(wh.title(s), "messages: 1 message(s), 0 status update(s)")
		self.assertEqual(wh.title(wh.summarise({})), "event: 0 message(s), 0 status update(s)")


class TestParse(unittest.TestCase):
	def test_object_only(self):
		self.assertEqual(wh.parse(b'{"a": 1}'), {"a": 1})
		for bad in (b"", b"not json", b"[1, 2]", b'"text"', None):
			self.assertIsNone(wh.parse(bad), bad)


class TestSummarise(unittest.TestCase):
	def test_message_delivery(self):
		s = wh.summarise(delivery(messages=[{"id": "m1"}, {"id": "m2"}], contacts=[{"wa_id": "9"}]))
		self.assertEqual(
			s,
			{
				"is_whatsapp": True,
				"waba_ids": ["111"],
				"phone_number_ids": ["222"],
				"fields": ["messages"],
				"message_count": 2,
				"status_count": 0,
			},
		)

	def test_status_delivery(self):
		s = wh.summarise(delivery(statuses=[{"id": "m1", "status": "read"}]))
		self.assertEqual((s["message_count"], s["status_count"]), (0, 1))

	def test_account_level_field_has_no_metadata(self):
		payload = {"object": wh.OBJECT, "entry": [{"id": "111", "changes": [{"field": "account_update", "value": {"event": "x"}}]}]}
		s = wh.summarise(payload)
		self.assertEqual((s["waba_ids"], s["phone_number_ids"], s["fields"]), (["111"], [], ["account_update"]))

	def test_several_entries_and_duplicates_are_collected_once(self):
		payload = {
			"object": wh.OBJECT,
			"entry": [
				delivery(messages=[{}])["entry"][0],
				delivery(statuses=[{}, {}])["entry"][0],
				{"id": "333", "changes": []},
			],
		}
		s = wh.summarise(payload)
		self.assertEqual(s["waba_ids"], ["111", "333"])
		self.assertEqual(s["phone_number_ids"], ["222"])
		self.assertEqual((s["message_count"], s["status_count"]), (1, 2))

	def test_other_object_is_flagged_not_a_whatsapp_delivery(self):
		self.assertFalse(wh.summarise({"object": "page", "entry": []})["is_whatsapp"])

	def test_survives_garbage_shapes(self):
		for payload in (
			{},
			{"entry": "x"},
			{"entry": [None, 1, "x"]},
			{"entry": [{"id": 5, "changes": "x"}]},
			{"entry": [{"changes": [None, {"field": "messages", "value": "x"}]}]},
			{"entry": [{"changes": [{"value": {"metadata": "x", "messages": "x", "statuses": 7}}]}]},
		):
			s = wh.summarise(payload)
			self.assertEqual((s["message_count"], s["status_count"]), (0, 0), payload)
		self.assertEqual(wh.summarise({"entry": [{"id": 5}]})["waba_ids"], ["5"])

	def test_round_trip_through_json(self):
		raw = json.dumps(delivery(messages=[{"id": "m1"}])).encode()
		self.assertEqual(wh.summarise(wh.parse(raw))["message_count"], 1)


if __name__ == "__main__":
	unittest.main()
