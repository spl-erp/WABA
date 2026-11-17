"""Run without a site:  python -m unittest waba.tests.test_template_author"""

import json
import unittest

from waba.rules import template_author as a
from waba.rules import templates as anatomy


def draft(**k):
	base = {
		"template_name": "order_update", "language": "en", "category": "UTILITY", "header_format": "", "header_text": "",
		"body_text": "Hello {{1}}, your order {{2}} has been dispatched and will reach you soon.", "footer_text": "", "buttons": [],
		"examples": {"body.1": "Rahul", "body.2": "SO-0001"},
	}
	base.update(k)
	return base


class TestNameAndBasics(unittest.TestCase):
	def test_a_good_draft_has_no_problems(self):
		self.assertEqual(a.check(draft()), [])

	def test_name_rules(self):
		for bad in ("", "Order", "order update", "order-update", "x" * 513, "orderé"):
			self.assertTrue(a.check_name(bad), repr(bad))
		for good in ("order_update", "a", "q2_2026_promo"):
			self.assertEqual(a.check_name(good), [])

	def test_language_and_category(self):
		self.assertTrue(a.check(draft(language="English")))
		self.assertTrue(a.check(draft(language="")))
		self.assertEqual(a.check(draft(language="en_US")), [])
		self.assertEqual(a.check(draft(language="hi")), [])
		self.assertIn("Authentication", " ".join(a.check(draft(category="AUTHENTICATION"))))
		self.assertEqual(a.check(draft(category="MARKETING")), [])


class TestBody(unittest.TestCase):
	def test_required_and_length(self):
		self.assertIn("required", " ".join(a.check(draft(body_text="", examples={}))))
		self.assertIn("longer than 1024", " ".join(a.check(draft(body_text="x" * 1025, examples={}))))

	def test_numbered_values_must_be_sequential(self):
		self.assertIn("without gaps", " ".join(a.check(draft(body_text="Hello there {{1}} and order {{3}} is on its way to you", examples={"body.1": "a", "body.3": "b"}))))

	def test_mixed_styles_are_refused(self):
		self.assertIn("not both", " ".join(a.check(draft(body_text="Hello {{1}} and {{name}} welcome to our shop today", examples={"body.1": "a", "body.name": "b"}))))

	def test_named_values(self):
		d = draft(body_text="Hi {{customer_name}}, your order {{order_id}} is on its way and will arrive soon.", examples={"body.customer_name": "Rahul", "body.order_id": "SO-1"})
		self.assertEqual(a.check(d), [])
		self.assertTrue(a.check(draft(body_text="Hi {{Customer}} your order is here and we are glad you chose us", examples={"body.Customer": "x"})))

	def test_cannot_start_or_end_with_a_value(self):
		self.assertIn("start or end", " ".join(a.check(draft(body_text="{{1}} your order has been dispatched and will arrive soon", examples={"body.1": "x"}))))
		self.assertIn("start or end", " ".join(a.check(draft(body_text="Your order has been dispatched and will arrive soon {{1}}", examples={"body.1": "x"}))))

	def test_enough_fixed_text_per_value(self):
		self.assertIn("too little fixed text", " ".join(a.check(draft(body_text="Hi {{1}} {{2}} {{3}} ok", examples={"body.1": "a", "body.2": "b", "body.3": "c"}))))

	def test_every_value_needs_an_example(self):
		self.assertIn("example", " ".join(a.check(draft(examples={"body.1": "Rahul"}))))
		self.assertIn("example", " ".join(a.check(draft(examples={}))))


class TestHeaderFooter(unittest.TestCase):
	def test_text_header(self):
		self.assertEqual(a.check(draft(header_format="TEXT", header_text="Order update")), [])
		self.assertIn("Write the header", " ".join(a.check(draft(header_format="TEXT", header_text=""))))
		self.assertIn("longer than 60", " ".join(a.check(draft(header_format="TEXT", header_text="x" * 61))))
		self.assertIn("only one value", " ".join(a.check(draft(header_format="TEXT", header_text="{{1}} {{2}}", examples={"body.1": "a", "body.2": "b", "header.1": "c", "header.2": "d"}))))

	def test_header_value_needs_its_example_and_the_same_style(self):
		d = draft(header_format="TEXT", header_text="Order {{1}}")
		self.assertIn("header value", " ".join(a.check(d)))
		self.assertEqual(a.check(dict(d, examples={"body.1": "a", "body.2": "b", "header.1": "SO-9"})), [])
		self.assertIn("same kind", " ".join(a.check(dict(d, header_text="Order {{name}}", examples={"body.1": "a", "body.2": "b", "header.name": "x"}))))

	def test_media_header_needs_a_sample_only_when_submitting(self):
		self.assertEqual(a.check(draft(header_format="IMAGE")), [])
		self.assertIn("sample file", " ".join(a.check(draft(header_format="IMAGE"), for_submit=True)))
		self.assertEqual(a.check(draft(header_format="IMAGE", header_handle="4::aW1h"), for_submit=True), [])

	def test_footer(self):
		self.assertEqual(a.check(draft(footer_text="Splashjet")), [])
		self.assertIn("footer", " ".join(a.check(draft(footer_text="x" * 61))))
		self.assertIn("footer cannot have values", " ".join(a.check(draft(footer_text="Hi {{1}}"))))


class TestButtons(unittest.TestCase):
	def b(self, *buttons):
		return a.check(draft(buttons=list(buttons)))

	def test_valid_set(self):
		self.assertEqual(self.b({"type": "URL", "text": "Track", "url": "https://x.com/t/{{1}}", "example": "https://x.com/t/abc"}, {"type": "PHONE_NUMBER", "text": "Call us", "phone_number": "+91 98765 43210"}, {"type": "QUICK_REPLY", "text": "Thanks"}), [])

	def test_url_rules(self):
		self.assertIn("https://", " ".join(self.b({"type": "URL", "text": "T", "url": "http://x.com"})))
		self.assertIn("only at the very end", " ".join(self.b({"type": "URL", "text": "T", "url": "https://x.com/{{1}}/more", "example": "e"})))
		self.assertIn("only at the very end", " ".join(self.b({"type": "URL", "text": "T", "url": "https://x.com/{{2}}", "example": "e"})))
		self.assertIn("example web address", " ".join(self.b({"type": "URL", "text": "T", "url": "https://x.com/t/{{1}}"})))
		self.assertEqual(self.b({"type": "URL", "text": "T", "url": "https://x.com"}), [])

	def test_counts_and_texts(self):
		many = [{"type": "QUICK_REPLY", "text": f"B{i}"} for i in range(11)]
		self.assertIn("At most 10", " ".join(self.b(*many)))
		self.assertIn("At most 2", " ".join(self.b(*[{"type": "URL", "text": f"U{i}", "url": "https://x.com"} for i in range(3)])))
		self.assertIn("one call", " ".join(self.b(*[{"type": "PHONE_NUMBER", "text": f"P{i}", "phone_number": "+919876543210"} for i in range(2)])))
		self.assertIn("longer than 25", " ".join(self.b({"type": "QUICK_REPLY", "text": "x" * 26})))
		self.assertIn("needs a text", " ".join(self.b({"type": "QUICK_REPLY", "text": ""})))

	def test_phone_and_copy_code(self):
		self.assertIn("international form", " ".join(self.b({"type": "PHONE_NUMBER", "text": "Call", "phone_number": "9876543210"})))
		self.assertIn("example code", " ".join(self.b({"type": "COPY_CODE"})))
		self.assertIn("letters and digits", " ".join(self.b({"type": "COPY_CODE", "example": "no way!"})))
		self.assertEqual(self.b({"type": "COPY_CODE", "example": "SAVE10"}), [])

	def test_quick_replies_stay_together_and_at_an_end(self):
		qr = lambda t: {"type": "QUICK_REPLY", "text": t}
		url = {"type": "URL", "text": "Site", "url": "https://x.com"}
		self.assertEqual(self.b(qr("A"), qr("B"), url), [])
		self.assertEqual(self.b(url, qr("A"), qr("B")), [])
		self.assertTrue(self.b(qr("A"), url, qr("B")))


class TestRequest(unittest.TestCase):
	def test_positional_request(self):
		r = a.request(draft(footer_text="Splashjet", buttons=[{"type": "QUICK_REPLY", "text": "Thanks"}]))
		self.assertEqual((r["name"], r["language"], r["category"], r["parameter_format"]), ("order_update", "en", "UTILITY", "POSITIONAL"))
		body = next(c for c in r["components"] if c["type"] == "BODY")
		self.assertEqual(body["example"], {"body_text": [["Rahul", "SO-0001"]]})
		self.assertEqual(r["components"][-1], {"type": "BUTTONS", "buttons": [{"type": "QUICK_REPLY", "text": "Thanks"}]})
		self.assertEqual([c["type"] for c in r["components"]], ["BODY", "FOOTER", "BUTTONS"])

	def test_named_request(self):
		d = draft(body_text="Hi {{customer_name}}, your order {{order_id}} is on its way and will arrive soon.", examples={"body.customer_name": "Rahul", "body.order_id": "SO-1"})
		r = a.request(d)
		self.assertEqual(r["parameter_format"], "NAMED")
		self.assertEqual(r["components"][0]["example"], {"body_text_named_params": [{"param_name": "customer_name", "example": "Rahul"}, {"param_name": "order_id", "example": "SO-1"}]})

	def test_headers_and_buttons_in_the_request(self):
		d = draft(header_format="TEXT", header_text="Order {{1}}", examples={"body.1": "a", "body.2": "b", "header.1": "SO-9"}, buttons=[{"type": "URL", "text": "Track", "url": "https://x.com/t/{{1}}", "example": "https://x.com/t/abc"}, {"type": "COPY_CODE", "example": "SAVE10"}, {"type": "PHONE_NUMBER", "text": "Call", "phone_number": "+91 98765 43210"}])
		c = a.components(d)
		self.assertEqual(c[0], {"type": "HEADER", "format": "TEXT", "text": "Order {{1}}", "example": {"header_text": ["SO-9"]}})
		self.assertEqual(c[-1]["buttons"][0], {"type": "URL", "text": "Track", "url": "https://x.com/t/{{1}}", "example": ["https://x.com/t/abc"]})
		self.assertEqual(c[-1]["buttons"][1], {"type": "COPY_CODE", "example": "SAVE10"})
		self.assertEqual(c[-1]["buttons"][2]["phone_number"], "+919876543210")
		img = a.components(draft(header_format="IMAGE", header_handle="4::abc"))
		self.assertEqual(img[0], {"type": "HEADER", "format": "IMAGE", "example": {"header_handle": ["4::abc"]}})

	def test_what_we_write_is_what_we_can_read_back(self):
		"""The request must parse with the same anatomy the sender uses, with the slots the examples table needs."""
		d = draft(header_format="TEXT", header_text="Order {{1}}", examples={"body.1": "a", "body.2": "b", "header.1": "SO-9"}, buttons=[{"type": "URL", "text": "Track", "url": "https://x.com/t/{{1}}", "example": "e"}])
		self.assertEqual([s["id"] for s in a.slots(d)], ["header.1", "body.1", "body.2", "button.0"])
		json.dumps(a.request(d))
		structure = anatomy.parse(a.request(d)["components"], "POSITIONAL")
		self.assertTrue(anatomy.sendable(structure)[0])


if __name__ == "__main__":
	unittest.main()


class TestCopyAsDraft(unittest.TestCase):
	def test_round_trip_keeps_the_text_buttons_and_examples(self):
		d = draft(
			header_format="TEXT", header_text="Order {{1}}", footer_text="Splashjet",
			examples={"body.1": "Rahul", "body.2": "SO-0001", "header.1": "SO-9", "button.0": "https://x.com/t/abc"},
			buttons=[{"type": "URL", "text": "Track", "url": "https://x.com/t/{{1}}", "example": "https://x.com/t/abc"}, {"type": "COPY_CODE", "example": "SAVE10"}, {"type": "QUICK_REPLY", "text": "Thanks"}],
		)
		back = a.from_components(a.components(d))
		for key in ("header_format", "header_text", "body_text", "footer_text"):
			self.assertEqual(back[key], d[key], key)
		self.assertEqual(back["examples"], d["examples"])
		self.assertEqual([(b["type"], b["text"]) for b in back["buttons"]], [("URL", "Track"), ("COPY_CODE", ""), ("QUICK_REPLY", "Thanks")])
		self.assertEqual(back["buttons"][1]["example"], "SAVE10")
		again = dict(draft(), **{k: back[k] for k in ("header_format", "header_text", "body_text", "footer_text", "buttons", "examples")})
		self.assertEqual(a.components(again), a.components(d))
		self.assertEqual(a.check(again), [])

	def test_named_values_round_trip(self):
		d = draft(body_text="Hi {{customer_name}}, your order {{order_id}} is on its way and will arrive soon.", examples={"body.customer_name": "Rahul", "body.order_id": "SO-1"})
		self.assertEqual(a.from_components(a.components(d))["examples"], d["examples"])

	def test_a_media_header_keeps_its_kind_but_not_the_sample_handle(self):
		back = a.from_components(a.components(draft(header_format="IMAGE", header_handle="4::old")))
		self.assertEqual(back["header_format"], "IMAGE")
		self.assertNotIn("header_handle", back)

	def test_odd_input_never_raises(self):
		for bad in (None, [], [None], ["x"], [{"type": "BODY"}], [{"type": "BUTTONS", "buttons": [None, "x"]}]):
			a.from_components(bad)
