"""Run without a site:  python -m unittest waba.tests.test_call_phone_js

The browser phone's pure helpers (timer, status words, microphone problems) and its safety rules, run in Node."""

import json
import os
import shutil
import subprocess
import unittest

NODE = shutil.which("node")
JS = os.path.join(os.path.dirname(__file__), "..", "public", "js", "waba_call_phone.js")


def run(expr):
	code = f"const m = require({json.dumps(os.path.abspath(JS))}); console.log(JSON.stringify({expr}));"
	return json.loads(subprocess.run([NODE, "-e", code], capture_output=True, text=True, check=True).stdout)


@unittest.skipUnless(NODE, "node is not installed")
class TestPhone(unittest.TestCase):
	def test_the_timer(self):
		self.assertEqual(run("[m.timerText(0), m.timerText(7), m.timerText(130), m.timerText(3723), m.timerText(-5), m.timerText('x')]"), ["00:00", "00:07", "02:10", "1:02:03", "00:00", "00:00"])

	def test_the_words_for_each_status(self):
		self.assertEqual(run("[m.statusText('Ringing','Outgoing'), m.statusText('Ringing','Incoming'), m.statusText('Answered'), m.statusText('No answer'), m.statusText('Rejected'), m.statusText('Failed')]"),
		                 ["Ringing...", "Incoming call", "Connected", "No answer", "Declined", "The call failed"])

	def test_which_statuses_are_over(self):
		self.assertEqual(run("['Completed','Missed','No answer','Rejected','Failed','Cancelled','Ringing','Answered'].map(m.isFinished)"), [True] * 6 + [False, False])

	def test_microphone_problems_are_explained(self):
		self.assertIn("blocked the microphone", run("m.micProblem({name:'NotAllowedError'})"))
		self.assertIn("No microphone", run("m.micProblem({name:'NotFoundError'})"))
		self.assertIn("another program", run("m.micProblem({name:'NotReadableError'})"))
		self.assertIn("could not be started", run("m.micProblem(null)"))

	def test_the_offer_is_audio_only(self):
		self.assertEqual(run("m.offerOptions()"), {"offerToReceiveAudio": True, "offerToReceiveVideo": False})

	def test_support_is_detected(self):
		self.assertFalse(run("m.supported({})"))
		self.assertTrue(run("m.supported({RTCPeerConnection: function(){}, navigator: {mediaDevices: {getUserMedia: function(){}}}})"))


@unittest.skipUnless(NODE, "node is not installed")
class TestRingAndListenOnly(unittest.TestCase):
	def test_the_ring_label_prefers_the_servers_label(self):
		self.assertEqual(run("[m.ringLabel({label:'Acme', name:'x', phone:'+91'}), m.ringLabel({name:'Rahul'}), m.ringLabel({phone:'+9198'}), m.ringLabel(null)]"), ["Acme", "Rahul", "+9198", "WhatsApp"])

	def test_the_countdown_never_goes_below_zero(self):
		self.assertEqual(run("[m.ringLeft(30, 1000, 11000), m.ringLeft(30, 0, 99000), m.ringLeft(undefined, 0, 0)]"), [20, 0, 30])

	def test_listen_only_is_offered_for_a_missing_microphone_only_when_allowed(self):
		self.assertTrue(run("m.listenOnlyAllowed({name:'NotFoundError'}, {listen_only:1})"))
		self.assertTrue(run("m.listenOnlyAllowed({name:'NotReadableError'}, {listen_only:1})"))
		self.assertFalse(run("m.listenOnlyAllowed({name:'NotAllowedError'}, {listen_only:1})"))  # a blocked microphone is the person's choice
		self.assertFalse(run("m.listenOnlyAllowed({name:'NotFoundError'}, {listen_only:0})"))
		self.assertFalse(run("m.listenOnlyAllowed(null, null)"))

	def test_what_each_realtime_event_does(self):
		ctx = "{activeCall: null, ringing: ['c1']}"
		self.assertEqual(run(f"['ring','taken','dismiss','missed','answer'].map(k => m.routeEvent({{call: 'c2', kind: k}}, {ctx}))"), ["ring", "ignore", "ignore", "missed", "ignore"])
		self.assertEqual(run(f"['ring','taken','dismiss','missed'].map(k => m.routeEvent({{call: 'c1', kind: k}}, {ctx}))"), ["ignore", "taken", "close-ring", "missed"])
		self.assertEqual(run(f"m.routeEvent({{call: 'c1', kind: 'ended', status: 'Missed'}}, {ctx})"), "close-ring")
		self.assertEqual(run("m.routeEvent({call: 'x', kind: 'answer'}, {activeCall: 'x', ringing: []})"), "active-answer")
		self.assertEqual(run("m.routeEvent({call: 'x', kind: 'ended', status: 'Completed'}, {activeCall: 'x', ringing: []})"), "active-progress")
		self.assertEqual(run(f"m.routeEvent(null, {ctx})"), "ignore")


class TestSource(unittest.TestCase):
	SRC = open(JS, encoding="utf-8").read()

	def test_the_server_decides_and_the_browser_never_talks_to_meta(self):
		self.assertNotIn("graph.facebook.com", self.SRC)
		for call in ("waba.api.calls.can_call", "waba.api.calls.place", "waba.api.calls.answer_sdp", "waba.api.calls.hangup", "waba.api.calls.request_permission"):
			self.assertIn(call, self.SRC)

	def test_the_microphone_is_released_at_the_end(self):
		self.assertIn("getTracks().forEach((t) => t.stop())", self.SRC)
		self.assertIn("pc.close()", self.SRC.replace("state.pc.close()", "pc.close()"))

	def test_taking_a_call_follows_offer_then_answer_and_declining_goes_to_the_server(self):
		body = self.SRC.split("async function accept(")[1].split("function openMissed")[0]
		self.assertLess(body.index("waba.api.calls.offer"), body.index("setRemoteDescription"))
		self.assertLess(body.index("createAnswer"), body.index("waba.api.calls.answer"))
		self.assertIn("waba.api.calls.decline", self.SRC)
		self.assertIn("waba.api.calls.my_calls", self.SRC)

	def test_the_silent_track_is_really_silent_and_the_microphone_wins(self):
		body = self.SRC.split("function silentStream()")[1].split("/** The audio we send")[0]
		self.assertIn("gain.gain.value = FAINT_GAIN", body)
		self.assertIn("await ctx.resume()", body)
		self.assertIn("createMediaStreamDestination", body)
		import re

		gain = float(re.search(r"const FAINT_GAIN = ([0-9.]+);", self.SRC).group(1))
		self.assertGreater(gain, 0)  # real signal: digital silence was not recorded by Meta
		self.assertLess(gain, 0.002)  # but far below anything audible
		audio = self.SRC.split("async function getAudio()")[1].split("function newPeer")[0]
		self.assertLess(audio.index("getUserMedia"), audio.index("silentStream()"))
		self.assertIn("listenOnlyAllowed(e, flags())", audio)
		self.assertIn("return await silentStream()", audio)

	def test_nothing_is_called_without_the_server_flags_and_a_confirmation(self):
		self.assertIn("!f.enabled || !f.make", self.SRC)
		self.assertIn("frappe.confirm(", self.SRC)


if __name__ == "__main__":
	unittest.main()
