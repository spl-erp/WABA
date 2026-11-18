"""Run without a site:  python -m unittest waba.tests.test_calls

WhatsApp voice calls (Meta's Business Calling API), stage 1: parsing Meta's `calls` events, the call's statuses, who rings, Meta's limits for
calling a customer, and the wiring (webhook, hooks, permissions, the browser calls, the ERP hook)."""

import datetime
import json
import os
import unittest

from waba.rules import calls as rules

APP = os.path.join(os.path.dirname(__file__), "..")
SDP = "v=0\no=- 1 2 IN IP4 127.0.0.1\ns=-\nt=0 0\nm=audio 9 UDP/TLS/RTP/SAVPF 111\n"


def read(*parts):
	with open(os.path.join(APP, *parts), encoding="utf-8") as handle:
		return handle.read()


def value(**call):
	item = {"id": "wacid.AAA", "from": "919876543210", "to": "919684032155", "event": "connect", "direction": "USER_INITIATED", "timestamp": "1794650615", "session": {"sdp_type": "offer", "sdp": SDP}}
	item.update(call)
	return {"messaging_product": "whatsapp", "metadata": {"display_phone_number": "919684032155", "phone_number_id": "111"}, "contacts": [{"wa_id": "919876543210", "profile": {"name": "Rahul"}}], "calls": [item]}


class TestParse(unittest.TestCase):
	def test_an_incoming_call_has_the_customer_as_the_caller(self):
		(c,) = rules.parse_calls(value())
		self.assertEqual((c["call_id"], c["event"], c["direction"]), ("wacid.AAA", "connect", rules.USER_INITIATED))
		self.assertEqual((c["phone"], c["profile_name"], c["sdp_type"]), ("+919876543210", "Rahul", "offer"))
		self.assertTrue(c["sdp"].startswith("v=0"))

	def test_an_outgoing_call_has_the_customer_as_the_recipient(self):
		(c,) = rules.parse_calls(value(direction="BUSINESS_INITIATED", **{"from": "919684032155", "to": "919876543210"}))
		self.assertEqual(c["phone"], "+919876543210")

	def test_a_user_id_is_never_taken_as_a_phone(self):
		v = value(**{"from": "IN.12345"})
		v["contacts"] = [{"user_id": "IN.12345"}]
		(c,) = rules.parse_calls(v)
		self.assertIsNone(c["phone"])
		self.assertEqual(c["bsuid"], "IN.12345")

	def test_terminate_carries_status_and_times(self):
		(c,) = rules.parse_calls(value(event="terminate", status="COMPLETED", start_time="100", end_time="160", duration="60", session=None))
		self.assertEqual((c["status"], c["start_time"], c["end_time"], c["duration"]), ("COMPLETED", 100, 160, 60))

	def test_a_recording_reference_is_read_tolerantly(self):
		(c,) = rules.parse_calls(value(event="call_recording_available", recording={"url": "https://x.fbcdn.net/a", "mime_type": "audio/ogg"}))
		self.assertEqual(c["recording"]["url"], "https://x.fbcdn.net/a")
		(c,) = rules.parse_calls(value(event="call_recording_available"))
		self.assertIsNone(c["recording"])

	def test_entries_without_an_id_and_non_dicts_are_skipped(self):
		v = value()
		v["calls"] += [{"event": "connect"}, "x"]
		self.assertEqual(len(rules.parse_calls(v)), 1)
		self.assertEqual(rules.parse_calls({}), [])
		self.assertEqual(rules.parse_calls(None), [])

	def test_status_reports_of_our_own_calls(self):
		out = rules.parse_call_statuses({"statuses": [{"id": "w1", "type": "call", "status": "ringing", "recipient_id": "919876543210"}, {"id": "m1", "status": "sent"}]})
		self.assertEqual([(x["call_id"], x["status"], x["phone"]) for x in out], [("w1", "RINGING", "+919876543210")])


class TestSdp(unittest.TestCase):
	def test_only_a_real_description_goes_on(self):
		text, problem = rules.clean_sdp(SDP)
		self.assertIsNone(problem)
		self.assertTrue(text.endswith("\r\n"))
		for bad in (None, "", "hello", "x" * 70000, "v=0\x00"):
			self.assertTrue(rules.clean_sdp(bad)[1], repr(bad)[:20])


class TestStatuses(unittest.TestCase):
	def test_a_picked_up_call_is_completed(self):
		self.assertEqual(rules.status_after_terminate(rules.ANSWERED, rules.USER_INITIATED, "COMPLETED", 60), rules.COMPLETED)
		self.assertEqual(rules.status_after_terminate(rules.RINGING, rules.USER_INITIATED, "COMPLETED", 12), rules.COMPLETED)

	def test_an_unanswered_call_is_missed_or_no_answer(self):
		self.assertEqual(rules.status_after_terminate(rules.RINGING, rules.USER_INITIATED, "FAILED", None), rules.MISSED)
		self.assertEqual(rules.status_after_terminate(rules.RINGING, rules.BUSINESS_INITIATED, None, 0), rules.NO_ANSWER)

	def test_rejected_and_cancelled_stay(self):
		self.assertEqual(rules.status_after_terminate(rules.REJECTED, rules.BUSINESS_INITIATED, "FAILED", 0), rules.REJECTED)
		self.assertEqual(rules.status_after_terminate(rules.CANCELLED, rules.USER_INITIATED, None, 0), rules.CANCELLED)

	def test_progress_of_an_outgoing_call(self):
		self.assertEqual(rules.status_after_progress(rules.RINGING, "ACCEPTED"), rules.ANSWERED)
		self.assertEqual(rules.status_after_progress(rules.RINGING, "REJECTED"), rules.REJECTED)
		self.assertEqual(rules.status_after_progress(rules.COMPLETED, "RINGING"), rules.COMPLETED)

	def test_only_a_ringing_call_can_be_taken(self):
		self.assertTrue(rules.can_accept(rules.RINGING))
		for status in set(rules.STATUSES) - {rules.RINGING}:
			self.assertFalse(rules.can_accept(status), status)

	def test_the_timeline_sentences(self):
		self.assertEqual(rules.event_line(rules.USER_INITIATED, rules.COMPLETED, "Priyal", 130), "Incoming call answered by Priyal, 2m 10s.")
		self.assertEqual(rules.event_line(rules.USER_INITIATED, rules.MISSED, None, 0), "Missed call.")
		self.assertIn("did not answer", rules.event_line(rules.BUSINESS_INITIATED, rules.NO_ANSWER, None, 0))
		self.assertEqual(rules.duration_text(7), "7s")


class TestRing(unittest.TestCase):
	TAKERS = {"a", "b", "c"}
	OVERSEERS = {"lead", "admin"}

	def ring(self, mode, assignee="a", available=None):
		return rules.ring_recipients(mode, assignee, self.OVERSEERS, self.TAKERS, available)

	def test_default_is_the_assigned_agent_and_the_team_leads(self):
		self.assertEqual(self.ring(rules.RING_ASSIGNED_AND_LEADS), ["a", "admin", "lead"])

	def test_the_assigned_agent_must_take_calls_and_be_available(self):
		self.assertEqual(self.ring(rules.RING_ASSIGNED_AND_LEADS, assignee="zed"), ["admin", "lead"])
		self.assertEqual(self.ring(rules.RING_ASSIGNED_AND_LEADS, available={"lead", "admin", "b"}), ["admin", "lead"])

	def test_assigned_only_and_leads_only(self):
		self.assertEqual(self.ring(rules.RING_ASSIGNED), ["a"])
		self.assertEqual(self.ring(rules.RING_LEADS), ["admin", "lead"])
		self.assertEqual(self.ring(rules.RING_ASSIGNED, assignee=None), [])

	def test_every_available_call_taker(self):
		self.assertEqual(self.ring(rules.RING_EVERYONE, available={"a", "c", "lead", "admin"}), ["a", "c", "admin", "lead"])

	def test_an_unknown_mode_falls_back_to_the_default(self):
		self.assertEqual(self.ring("nonsense"), self.ring(rules.RING_ASSIGNED_AND_LEADS))

	def test_nobody_twice(self):
		self.assertEqual(rules.ring_recipients(rules.RING_EVERYONE, "lead", {"lead"}, {"lead"}, None), ["lead"])


class TestPermission(unittest.TestCase):
	NOW = datetime.datetime(2026, 11, 18, 12, 0)

	def test_the_state_of_a_reply(self):
		self.assertEqual(rules.permission_state(None, self.NOW), (rules.PERMISSION_NONE, None))
		self.assertEqual(rules.permission_state({"response": "reject"}, self.NOW)[0], rules.PERMISSION_DECLINED)
		self.assertEqual(rules.permission_state({"response": "accept", "permanent": True}, self.NOW)[0], rules.PERMISSION_PERMANENT)
		fresh = {"response": "accept", "at": self.NOW - datetime.timedelta(days=2)}
		self.assertEqual(rules.permission_state(fresh, self.NOW)[0], rules.PERMISSION_TEMPORARY)
		old = {"response": "accept", "at": self.NOW - datetime.timedelta(days=8)}
		self.assertEqual(rules.permission_state(old, self.NOW)[0], rules.PERMISSION_NONE)

	def test_a_request_once_a_day_and_twice_a_week(self):
		hour = datetime.timedelta(hours=1)
		ok, _ = rules.may_request_permission(rules.PERMISSION_NONE, [], self.NOW)
		self.assertTrue(ok)
		self.assertFalse(rules.may_request_permission(rules.PERMISSION_NONE, [self.NOW - 5 * hour], self.NOW)[0])
		self.assertTrue(rules.may_request_permission(rules.PERMISSION_NONE, [self.NOW - 30 * hour], self.NOW)[0])
		self.assertFalse(rules.may_request_permission(rules.PERMISSION_NONE, [self.NOW - 30 * hour, self.NOW - 100 * hour], self.NOW)[0])
		self.assertFalse(rules.may_request_permission(rules.PERMISSION_PERMANENT, [], self.NOW)[0])

	def test_before_an_outgoing_call(self):
		self.assertFalse(rules.may_place_call(rules.PERMISSION_NONE, 0, 0)[0])
		self.assertTrue(rules.may_place_call(rules.PERMISSION_TEMPORARY, 0, 0)[0])
		self.assertFalse(rules.may_place_call(rules.PERMISSION_PERMANENT, 100, 0)[0])
		self.assertFalse(rules.may_place_call(rules.PERMISSION_PERMANENT, 0, 4)[0])
		self.assertTrue(rules.may_place_call(rules.PERMISSION_PERMANENT, 99, 3)[0])

	def test_the_recording_object_asks_meta_to_announce_it(self):
		r = rules.recording_request("hi")
		self.assertEqual((r["status"], r["announcement_language"]), ("ENABLED", "hi"))
		self.assertLessEqual(len(r["purpose"]), 250)


class TestWiring(unittest.TestCase):
	WEBHOOK = read("api", "webhook.py")
	CALLS = read("calls.py")

	def test_the_webhook_handles_the_calls_field(self):
		self.assertIn("calls_rules.CALLS_FIELD", self.WEBHOOK)
		self.assertIn("calls.handle_changes(payload, account, doc.name)", self.WEBHOOK)

	def test_the_doctype_and_fields_exist_and_calling_is_off_by_default(self):
		call = json.loads(read("waba", "doctype", "waba_call", "waba_call.json"))
		fields = {f["fieldname"]: f for f in call["fields"]}
		self.assertEqual(fields["status"]["options"].split("\n"), list(rules.STATUSES))
		self.assertEqual(fields["call_id"].get("unique"), 1)
		settings = {f["fieldname"]: f for f in json.loads(read("waba", "doctype", "waba_settings", "waba_settings.json"))["fields"]}
		self.assertIn(settings["calls_enabled"].get("default"), (None, "0", 0))
		self.assertEqual(settings["call_ring_mode"]["options"].split("\n"), list(rules.RING_MODES))
		self.assertEqual(settings["call_ring_mode"]["default"], rules.RING_ASSIGNED_AND_LEADS)
		access = {f["fieldname"]: f for f in json.loads(read("waba", "doctype", "waba_agent_access", "waba_agent_access.json"))["fields"]}
		for name in ("may_take_calls", "may_make_calls"):
			self.assertIn(access[name].get("default"), (None, "0", 0), name)

	def test_nothing_is_dialled_or_rung_before_the_migrate_or_while_off(self):
		self.assertIn('has_field("calls_enabled")', self.CALLS)
		self.assertIn("recipients = ring_list(number, conversation) if enabled() else []", self.CALLS)

	def test_an_unknown_caller_gets_no_conversation(self):
		body = self.CALLS.split("def _incoming(")[1].split("\ndef _open_conversation")[0]
		self.assertIn("if not conversation and party:", body)

	def test_accepting_is_one_winner_under_a_lock_and_asks_for_recording(self):
		body = self.CALLS.split("def answer(")[1].split("\ndef decline")[0]
		self.assertIn("with locks.conversation(", body)
		self.assertLess(body.index("rules.can_accept("), body.index('"pre_accept"'))
		self.assertLess(body.index('"pre_accept"'), body.index('"accept"'))
		self.assertIn("recording=_recording_object()", body)

	def test_the_browser_calls_are_guarded_by_role_and_the_switch(self):
		api = read("api", "calls.py")
		for fn in ("offer", "answer", "decline", "hangup"):
			body = api.split(f"def {fn}(")[1].split("\n@frappe.whitelist")[0]
			self.assertIn("_check()", body, fn)
		self.assertIn("has_waba_role", api)
		self.assertIn("calls.enabled()", api)

	def test_a_missed_call_alerts_the_overseers_and_the_erp_is_told(self):
		self.assertIn("teams.number_overseers(call.waba_number, None)", self.CALLS)
		self.assertIn('frappe.get_hooks("waba_call_ended")', self.CALLS)

	def test_the_sweeps_are_scheduled_and_permissions_registered(self):
		hooks = read("hooks.py")
		for text in ("waba.calls.expire_stale", "waba.calls.retry_recordings", '"Waba Call": "waba.permissions.call_query_conditions"', '"Waba Call": "waba.permissions.call_has_permission"'):
			self.assertIn(text, hooks)

	def test_the_graph_helpers_exist(self):
		graph = read("meta", "graph.py")
		self.assertIn("def call_action(", graph)
		self.assertIn('f"{phone_number_id}/calls"', graph)
		self.assertIn("def calling_settings(", graph)

	def test_splinh_hook_is_declared_only_in_the_hook_name_not_imported(self):
		self.assertNotIn("splinh", self.CALLS)


class TestTeamsOwnTheCallFlags(unittest.TestCase):
	"""The teams write the Number's agent rows, so the call flags are set on the Team member and copied (a hand edit on the Number would be lost)."""

	def test_the_team_member_has_the_flags_off_by_default(self):
		fields = {f["fieldname"]: f for f in json.loads(read("waba", "doctype", "waba_team_member", "waba_team_member.json"))["fields"]}
		for name in ("may_take_calls", "may_make_calls"):
			self.assertEqual(fields[name]["fieldtype"], "Check")
			self.assertIn(fields[name].get("default"), (None, "0", 0), name)

	def test_apply_copies_them_to_the_agent_rows(self):
		from waba.rules import team_setup

		members = [("IT", "lead@x", "Team Lead"), ("IT", "a@x", "Agent"), ("IT", "b@x", "Agent")]
		rows = team_setup.derive_agents(
			"N1", parents={"IT": None}, members=members, team_numbers={"IT": ["N1"]},
			settings={"a@x": {"may_take_calls": 1, "may_make_calls": 0}, "b@x": {"may_make_calls": 1}},
		)
		by = {r["user"]: r for r in rows}
		self.assertEqual((by["a@x"]["may_take_calls"], by["a@x"]["may_make_calls"]), (1, 0))
		self.assertEqual((by["b@x"]["may_take_calls"], by["b@x"]["may_make_calls"]), (0, 1))
		self.assertEqual((by["lead@x"]["may_take_calls"], by["lead@x"]["may_make_calls"]), (0, 0))
		self.assertIn("may_take_calls", team_setup.SETTINGS)

	def test_reading_the_settings_waits_for_the_migrate(self):
		self.assertIn("has_field(f)", read("teams.py"))


class TestOutgoing(unittest.TestCase):
	def test_the_permission_request_is_the_free_form_interactive_message(self):
		p = rules.permission_request_payload("+919876543210", "  Can we   call you?  ")
		self.assertEqual((p["to"], p["type"]), ("919876543210", "interactive"))
		self.assertEqual(p["interactive"], {"type": "call_permission_request", "action": {"name": "call_permission_request"}, "body": {"text": "Can we call you?"}})
		self.assertLessEqual(len(rules.permission_request_payload("1", "x" * 999)["interactive"]["body"]["text"]), rules.MAX_REQUEST_TEXT)

	def test_the_customers_answer_is_read_from_the_interactive_reply(self):
		def msg(**reply):
			return {"interactive": {"type": "call_permission_reply", "call_permission_reply": reply}}
		self.assertEqual(rules.parse_permission_reply(msg(response="accept", is_permanent=False, expiration_timestamp="1800000000", response_source="user_action")),
		                 {"response": "accept", "permanent": False, "expires": 1800000000, "source": "user_action"})
		self.assertTrue(rules.parse_permission_reply(msg(response="accept", is_permanent=True))["permanent"])
		self.assertEqual(rules.parse_permission_reply(msg(response="reject"))["response"], "reject")
		self.assertIsNone(rules.parse_permission_reply(msg(response="maybe")))
		self.assertIsNone(rules.parse_permission_reply({"interactive": {"type": "button_reply"}}))
		self.assertIsNone(rules.parse_permission_reply({}))
		self.assertEqual(rules.permission_reply_text(None), "Declined WhatsApp calls.")
		self.assertIn("no time limit", rules.permission_reply_text({"response": "accept", "permanent": True}))

	def test_inbound_parsing_carries_the_reply_and_a_readable_body(self):
		from waba.rules import inbound

		value = {"metadata": {}, "contacts": [{"wa_id": "919876543210"}], "messages": [{"from": "919876543210", "id": "wamid.P", "type": "interactive", "timestamp": "1",
		         "interactive": {"type": "call_permission_reply", "call_permission_reply": {"response": "accept", "is_permanent": False}}}]}
		(m,) = inbound.parse_messages(value)
		self.assertEqual(m["permission_reply"]["response"], "accept")
		self.assertEqual(m["body"], "Allowed WhatsApp calls for 7 days.")
		value["messages"][0]["interactive"] = {"type": "button_reply", "button_reply": {"id": "1", "title": "Yes"}}
		(m,) = inbound.parse_messages(value)
		self.assertIsNone(m["permission_reply"])
		self.assertEqual(m["body"], "Yes")

	def test_the_call_id_and_permission_status_of_metas_answers(self):
		self.assertEqual(rules.connect_call_id({"messaging_product": "whatsapp", "calls": [{"id": "wacid.X"}]}), "wacid.X")
		self.assertIsNone(rules.connect_call_id({"calls": []}))
		self.assertIsNone(rules.connect_call_id(None))
		st = rules.parse_permission_status({"permission": {"status": "temporary", "expiration_time": 1800000000},
		                                    "actions": [{"action_name": "start_call", "can_perform_action": True, "limits": [{"time_period": "PT24H", "max_allowed": 100, "current_usage": 1}]},
		                                                {"action_name": "send_call_permission_request", "can_perform_action": False}]})
		self.assertEqual((st["status"], st["can_call"], st["can_request"], st["expires"]), ("temporary", True, False, 1800000000))
		self.assertEqual(rules.why_not_call(st), "")
		none = rules.parse_permission_status({"permission": {"status": "no_permission"}, "actions": [{"action_name": "start_call", "can_perform_action": False}]})
		self.assertIn("not allowed calls", rules.why_not_call(none))
		self.assertEqual(rules.parse_permission_status(None)["status"], "no_permission")

	def test_recordings_use_metas_call_recording_shape(self):
		(c,) = rules.parse_calls(value(event="call_recording_available", call_recording={"type": "audio", "audio": {"id": "M1", "sha256": "abc", "mime_type": "audio/ogg; codecs=opus", "url": "https://lookaside.fbsbx.com/x"}}))
		self.assertEqual((c["recording"]["id"], c["recording"]["mime"], c["recording"]["url"]), ("M1", "audio/ogg", "https://lookaside.fbsbx.com/x"))

	def test_an_unanswered_outgoing_call_arrives_as_terminate_without_times(self):
		self.assertEqual(rules.status_after_terminate(rules.RINGING, rules.BUSINESS_INITIATED, "COMPLETED", None), rules.NO_ANSWER)


class TestOutgoingWiring(unittest.TestCase):
	CALLS = read("calls.py")
	API = read("api", "calls.py")

	def test_every_outgoing_call_api_is_guarded(self):
		for fn in ("can_call", "request_permission", "place", "answer_sdp"):
			body = self.API.split(f"def {fn}(")[1].split("\n@frappe.whitelist")[0]
			self.assertIn("_check()", body, fn)

	def test_only_marked_callers_on_a_calling_number_may_call(self):
		body = self.CALLS.split("def _conversation_for_call(")[1].split("\ndef can_call")[0]
		for needle in ("may_place(", "receive_only", "coexistence", "customer_phone", "has_permission"):
			self.assertIn(needle, body, needle)

	def test_meta_is_asked_before_a_call_is_placed_and_the_call_is_recorded(self):
		body = self.CALLS.split("def place(")[1].split("\n# ----")[0]
		self.assertLess(body.index("call_permissions("), body.index('"connect"'))
		self.assertIn("recording=_recording_object()", body)
		self.assertIn("started_by", body)
		self.assertIn("one" if False else "already a call in progress", body)

	def test_a_permission_request_only_goes_inside_the_window_and_is_stored_as_a_message(self):
		body = self.CALLS.split("def request_permission(")[1].split("\ndef place")[0]
		self.assertIn("check_free_text(", body)
		self.assertIn("send._deliver(", body)

	def test_the_replies_are_applied_and_the_button_is_flagged_from_the_server(self):
		self.assertIn("calls.apply_permission_reply(conversation.name", read("inbound.py"))
		self.assertIn("bootinfo.waba_calls = call_flags(frappe.session.user)", read("boot.py"))
		js = read("public", "js", "waba_inbox_app.js")
		self.assertIn("can_call_here()", js)
		self.assertIn("frappe.boot.waba_calls", js)
		self.assertIn("waba_call_phone.js", read("public", "js", "waba_alerts_core.js"))


class TestCallerLabelAndListenOnly(unittest.TestCase):
	def test_a_profile_name_without_letters_or_digits_is_not_a_name(self):
		self.assertIsNone(rules.clean_name("."))
		self.assertIsNone(rules.clean_name("  - "))
		self.assertEqual(rules.clean_name("  Rahul   Traders "), "Rahul Traders")
		self.assertIsNone(rules.clean_name(None))

	def test_the_label_prefers_the_record_then_a_real_name_then_the_phone(self):
		self.assertEqual(rules.caller_label(".", "Acme Inks", "+9198"), "Acme Inks")
		self.assertEqual(rules.caller_label("Rahul", None, "+9198"), "Rahul")
		self.assertEqual(rules.caller_label(".", None, "+9198"), "+9198")
		self.assertEqual(rules.caller_label(None, None, None, "IN.123"), "IN.123")
		self.assertEqual(rules.caller_label(None, None, None), "an unknown number")

	def test_listen_only_is_a_setting_on_by_default_and_reaches_the_browser(self):
		fields = {f["fieldname"]: f for f in json.loads(read("waba", "doctype", "waba_settings", "waba_settings.json"))["fields"]}
		self.assertEqual(fields["call_listen_only"]["fieldtype"], "Check")
		self.assertEqual(fields["call_listen_only"]["default"], "1")
		boot = read("boot.py")
		self.assertIn('"listen_only"', boot)
		self.assertIn("listen_only_on", boot)
		self.assertIn("call_listen_only", read("calls.py"))

	def test_an_unsaved_listen_only_setting_means_on_and_a_patch_stores_it(self):
		self.assertIn('return True if stored is None else bool(cint(stored))', read("calls.py"))
		self.assertNotIn('get_value("Singles"', read("calls.py"))
		self.assertIn("calls.listen_only_on()", read("boot.py"))
		patch = read("patches", "v0_1", "default_call_listen_only.py")
		self.assertIn('set_single_value("Waba Settings", "call_listen_only", 1)', patch)
		self.assertIn("tabSingles", patch)
		self.assertIn("waba.patches.v0_1.default_call_listen_only", read("patches.txt"))

	def test_a_changed_phone_script_is_fetched_at_once(self):
		"""The browser caches scripts under a version stamp built from this list: a script missing from it stays old after an update
		(the ring box did not appear because the old phone script was served from the cache)."""
		inbox = read("api", "inbox.py")
		self.assertIn('"js/waba_call_phone.js"', inbox.split("def assets_version")[1].split("def my_numbers")[0])

	def test_a_missed_call_reaches_the_screen_of_everyone_who_was_rung(self):
		body = read("calls.py").split("def _missed(")[1].split("\ndef _tell_erp")[0]
		self.assertIn('_publish(user, "missed", call, status=call.status)', body)
		self.assertIn("ring_recipients", body)
		self.assertIn("number_overseers", body)
		self.assertIn("who = label_of(call)", body)

	def test_the_ring_event_carries_a_readable_label_and_the_direction(self):
		body = read("calls.py").split("def _publish(")[1].split("\ndef _publish_to_call")[0]
		self.assertIn('"label": label_of(call)', body)
		self.assertIn('"direction": call.direction', body)


if __name__ == "__main__":
	unittest.main()
