"""Run without a site:  python -m unittest waba.tests.test_templates"""

import json
import unittest

from waba.rules import templates as t


def structure(*components, fmt=None):
	return t.parse(list(components), fmt)


BODY1 = {"type": "BODY", "text": "Hi {{1}}, order {{2}} shipped."}
NAMED = {"type": "BODY", "text": "Hi {{customer_name}}, order {{order_id}} shipped."}


class TestParse(unittest.TestCase):
	def test_plain_body_only(self):
		s = structure({"type": "BODY", "text": "Hello there"})
		self.assertEqual(s["slots"], [])
		self.assertEqual(t.components_for_send(s, {}), [])
		self.assertEqual(t.validate(s, {}), [])

	def test_positional_body(self):
		s = structure(BODY1)
		self.assertEqual(t.slot_ids(s), ["body.1", "body.2"])
		self.assertEqual(s["parameter_format"], "POSITIONAL")
		self.assertEqual(t.components_for_send(s, {"body.1": " Rahul ", "body.2": "SO-1"}), [{"type": "body", "parameters": [{"type": "text", "text": "Rahul"}, {"type": "text", "text": "SO-1"}]}])

	def test_positional_values_go_in_numeric_order_whatever_the_text_order(self):
		s = structure({"type": "BODY", "text": "{{2}} then {{1}}"})
		self.assertEqual(t.slot_ids(s), ["body.1", "body.2"])

	def test_named_body_carries_parameter_names(self):
		s = structure(NAMED)
		self.assertEqual(s["parameter_format"], "NAMED")
		out = t.components_for_send(s, {"body.customer_name": "Rahul", "body.order_id": "SO-1"})
		self.assertEqual(out[0]["parameters"][0], {"type": "text", "text": "Rahul", "parameter_name": "customer_name"})

	def test_declared_parameter_format_wins(self):
		self.assertEqual(structure(BODY1, fmt="POSITIONAL")["parameter_format"], "POSITIONAL")
		self.assertEqual(structure(NAMED, fmt="NAMED")["parameter_format"], "NAMED")

	def test_text_header_with_a_variable(self):
		s = structure({"type": "HEADER", "format": "TEXT", "text": "Order {{1}}"}, {"type": "BODY", "text": "Hi"})
		self.assertEqual(t.slot_ids(s), ["header.1"])
		out = t.components_for_send(s, {"header.1": "SO-9"})
		self.assertEqual(out[0], {"type": "header", "parameters": [{"type": "text", "text": "SO-9"}]})

	def test_media_headers_need_a_file_and_send_it_by_id(self):
		for fmt in ("IMAGE", "VIDEO", "DOCUMENT"):
			s = structure({"type": "HEADER", "format": fmt, "example": {"header_handle": ["h"]}}, {"type": "BODY", "text": "Hi"})
			self.assertEqual(t.slot_ids(s), ["header.media"], fmt)
			self.assertIn("Choose the", t.validate(s, {})[0])
			self.assertEqual(t.components_for_send(s, {"header.media": "MID"}), [{"type": "header", "parameters": [{"type": fmt.lower(), fmt.lower(): {"id": "MID"}}]}])

	def test_buttons(self):
		s = structure(
			{"type": "BODY", "text": "Hi"},
			{"type": "BUTTONS", "buttons": [
				{"type": "URL", "text": "Track", "url": "https://x.com/t/{{1}}"},
				{"type": "URL", "text": "Site", "url": "https://x.com"},
				{"type": "QUICK_REPLY", "text": "Thanks"},
				{"type": "PHONE_NUMBER", "text": "Call", "phone_number": "+91 1"},
				{"type": "COPY_CODE", "example": "ABC"},
			]},
		)
		self.assertEqual(t.slot_ids(s), ["button.0", "button.4"])
		self.assertEqual(s["unsupported"], [])
		out = t.components_for_send(s, {"button.0": "abc", "button.4": "SAVE10"})
		self.assertEqual(out[0], {"type": "button", "sub_type": "url", "index": "0", "parameters": [{"type": "text", "text": "abc"}]})
		self.assertEqual(out[1], {"type": "button", "sub_type": "copy_code", "index": "4", "parameters": [{"type": "coupon_code", "coupon_code": "SAVE10"}]})

	def test_shapes_the_erp_cannot_send_say_why(self):
		for comp, word in (
			({"type": "CAROUSEL", "cards": []}, "carousel"),
			({"type": "LIMITED_TIME_OFFER"}, "limited time offer"),
			({"type": "HEADER", "format": "LOCATION"}, "location header"),
			({"type": "BUTTONS", "buttons": [{"type": "FLOW", "text": "Open"}]}, "flow button"),
			({"type": "BUTTONS", "buttons": [{"type": "OTP", "otp_type": "COPY_CODE"}]}, "otp button"),
		):
			s = structure({"type": "BODY", "text": "Hi"}, comp)
			ok, why = t.sendable(s)
			self.assertFalse(ok, word)
			self.assertIn(word, why)
			self.assertEqual(t.validate(s, {}), [why])

	def test_odd_input_never_raises(self):
		for bad in (None, [], [None], ["x"], [{"type": None}], [{"type": "BUTTONS", "buttons": [None, "x"]}]):
			t.parse(bad)


class TestValidate(unittest.TestCase):
	def test_missing_and_blank_values(self):
		s = structure(BODY1)
		self.assertEqual(len(t.validate(s, {})), 2)
		self.assertEqual(t.validate(s, {"body.1": "  ", "body.2": "x"}), ["Body value 1 is empty."])

	def test_bad_characters_and_length(self):
		s = structure(BODY1)
		self.assertIn("line break", t.validate(s, {"body.1": "a\nb", "body.2": "x"})[0])
		self.assertIn("line break", t.validate(s, {"body.1": "a     b", "body.2": "x"})[0])
		self.assertIn("longer than 1024", t.validate(s, {"body.1": "x" * 1025, "body.2": "x"})[0])

	def test_header_value_is_shorter(self):
		s = structure({"type": "HEADER", "format": "TEXT", "text": "{{1}}"}, {"type": "BODY", "text": "Hi"})
		self.assertIn("longer than 60", t.validate(s, {"header.1": "x" * 61})[0])

	def test_button_values(self):
		s = structure({"type": "BODY", "text": "Hi"}, {"type": "BUTTONS", "buttons": [{"type": "URL", "text": "T", "url": "https://x/{{1}}"}, {"type": "COPY_CODE"}]})
		self.assertIn("spaces", t.validate(s, {"button.0": "a b", "button.1": "OK1"})[0])
		self.assertIn("letters and digits", t.validate(s, {"button.0": "ab", "button.1": "no way!"})[0])
		self.assertEqual(t.validate(s, {"button.0": "ab", "button.1": "OK1"}), [])


class TestRender(unittest.TestCase):
	def test_values_are_put_in_and_missing_ones_stay_visible(self):
		s = structure({"type": "HEADER", "format": "TEXT", "text": "Order {{1}}"}, NAMED, {"type": "FOOTER", "text": "Splashjet"}, {"type": "BUTTONS", "buttons": [{"type": "QUICK_REPLY", "text": "Thanks"}]})
		r = t.render(s, {"header.1": "SO-9", "body.customer_name": "Rahul"})
		self.assertEqual(r["header"], "Order SO-9")
		self.assertEqual(r["body"], "Hi Rahul, order {{order_id}} shipped.")
		self.assertEqual((r["footer"], r["buttons"]), ("Splashjet", ["Thanks"]))

	def test_media_header_shows_its_kind(self):
		self.assertEqual(t.render(structure({"type": "HEADER", "format": "IMAGE"}, {"type": "BODY", "text": "x"}), {})["header"], "[image]")

	def test_buttons_without_text_get_friendly_names(self):
		s = structure({"type": "BODY", "text": "x"}, {"type": "BUTTONS", "buttons": [{"type": "COPY_CODE"}, {"type": "URL", "url": "https://x"}, {"type": "QUICK_REPLY", "text": "Thanks"}]})
		self.assertEqual(t.render(s, {})["buttons"], ["Copy code", "Open link", "Thanks"])

	def test_old_list_form_maps_to_body_slots(self):
		self.assertEqual(t.from_positional(structure(BODY1), ["Rahul", "SO-1"]), {"body.1": "Rahul", "body.2": "SO-1"})
		self.assertEqual(t.from_positional(structure(BODY1), ["Rahul"]), {"body.1": "Rahul"})


class TestJsonSafe(unittest.TestCase):
	def test_the_structure_can_be_sent_to_the_browser(self):
		json.dumps(structure({"type": "HEADER", "format": "IMAGE"}, NAMED, {"type": "BUTTONS", "buttons": [{"type": "URL", "text": "T", "url": "https://x/{{1}}"}]}))




class TestTemplateScreensWiring(unittest.TestCase):
	"""The three screens that send a template share one dialog; check their links to the server from the source."""

	FILES = (
		("public", "js", "waba_template_dialog.js"),
		("public", "js", "waba_inbox_app.js"),
		("public", "js", "waba_party.js"),
		("waba", "doctype", "waba_conversation", "waba_conversation.js"),
	)

	def setUp(self):
		import os

		self.base = os.path.join(os.path.dirname(__file__), "..")
		self.src = {}
		for parts in self.FILES:
			with open(os.path.join(self.base, *parts), encoding="utf-8") as handle:
				self.src[parts[-1]] = handle.read()

	def whitelisted(self, module):
		import ast, os

		with open(os.path.join(self.base, "api", module + ".py"), encoding="utf-8") as handle:
			tree = ast.parse(handle.read())
		return {n.name for n in tree.body if isinstance(n, ast.FunctionDef) and any("whitelist" in ast.dump(d) for d in n.decorator_list)}

	def test_every_server_method_called_exists_and_is_whitelisted(self):
		import re

		for name, text in self.src.items():
			for module, fn in set(re.findall(r"waba\.api\.(\w+)\.(\w+)", text)):
				self.assertIn(fn, self.whitelisted(module), f"{name}: waba.api.{module}.{fn}")

	def test_the_three_screens_use_the_shared_dialog_and_no_longer_ask_for_one_value_per_line(self):
		for name in ("waba_inbox_app.js", "waba_party.js", "waba_conversation.js"):
			self.assertTrue("WabaTemplateDialog" in self.src[name] or "WabaTemplateForm" in self.src[name], name)
			self.assertNotIn("One value per line", self.src[name], name)

	def test_the_page_loader_and_cache_stamp_know_the_new_file(self):
		import os

		with open(os.path.join(self.base, "waba", "page", "waba_inbox", "waba_inbox.js"), encoding="utf-8") as handle:
			self.assertIn("waba_template_dialog.js", handle.read())
		with open(os.path.join(self.base, "api", "inbox.py"), encoding="utf-8") as handle:
			self.assertIn("js/waba_template_dialog.js", handle.read())

	def test_dialog_escapes_what_it_shows(self):
		text = self.src["waba_template_dialog.js"]
		for fragment in ("e(s.label)", "e(f.problem)", "e(b.text || BUTTON_NAMES[b.type] || b.type)", "e(x.title)", "e(err.message)"):
			self.assertIn(fragment, text, fragment)
		self.assertNotIn("scrollIntoView", text)


class TestSendSideSource(unittest.TestCase):
	def setUp(self):
		import os

		base = os.path.join(os.path.dirname(__file__), "..")
		with open(os.path.join(base, "api", "send.py"), encoding="utf-8") as handle:
			self.send = handle.read()
		with open(os.path.join(base, "api", "party.py"), encoding="utf-8") as handle:
			self.party = handle.read()

	def test_template_sending_is_guarded_and_validated_before_anything_is_created(self):
		import ast

		tree = ast.parse(self.send)
		fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_send_template")
		text = ast.get_source_segment(self.send, fn)
		for needle in ("refuse_if_receive_only()", "templating.prepare(", "check_conversation_template(", "templating.header_file(", "_deliver("):
			self.assertIn(needle, text, needle)
		self.assertLess(text.index("refuse_if_receive_only()"), text.index("templating.prepare("))
		self.assertLess(text.index("templating.prepare("), text.index("_deliver("))
		self.assertLess(text.index("templating.header_file("), text.index("_deliver("))

	def test_the_upload_of_a_header_file_happens_inside_the_payload_builder(self):
		self.assertIn("def build():", self.send)
		self.assertIn('final["header.media"] = graph.upload_media(', self.send)

	def test_whitelisted_template_functions_take_no_origin(self):
		import ast

		for source in (self.send, self.party):
			for node in ast.parse(source).body:
				if isinstance(node, ast.FunctionDef) and any("whitelist" in ast.dump(d) for d in node.decorator_list):
					self.assertNotIn("origin", [a.arg for a in node.args.args], node.name)
					for a in node.args.args:
						self.assertIsNotNone(a.annotation, f"{node.name}({a.arg})")

	def test_starting_from_a_record_uses_the_same_preparation(self):
		self.assertIn("templating.prepare(tpl, doctype, name", self.party)
		self.assertNotIn("validate_params", self.party)


if __name__ == "__main__":
	unittest.main()
