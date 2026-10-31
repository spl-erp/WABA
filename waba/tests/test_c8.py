"""Run without a site:  python -m unittest waba.tests.test_c8

The C8 foundation: delivery prices, status order, the origin tag on sends, annotated API methods, and the helpers for
locking and claiming. Checked offline from the pure rules and from the source."""

import ast
import os
import unittest

from waba.rules import statuses

ROOT = os.path.join(os.path.dirname(__file__), "..")


def read(*parts):
	with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
		return f.read()


class TestPricing(unittest.TestCase):
	def test_a_billable_utility_message(self):
		item = {"status": "delivered", "pricing": {"billable": True, "pricing_model": "PMP", "category": "utility", "type": "regular"}, "conversation": {"id": "c1"}}
		self.assertEqual(
			statuses.pricing(item),
			{"billing_category": "utility", "billable": 1, "pricing_type": "regular", "meta_conversation_id": "c1"},
		)

	def test_a_free_service_message(self):
		item = {"pricing": {"billable": False, "category": "service", "type": "free_customer_service"}}
		out = statuses.pricing(item)
		self.assertEqual((out["billable"], out["pricing_type"], out["billing_category"]), (0, "free_customer_service", "service"))

	def test_the_older_conversation_shape_gives_the_category(self):
		item = {"conversation": {"id": "x", "origin": {"type": "Marketing"}}}
		self.assertEqual(statuses.pricing(item), {"billing_category": "marketing", "meta_conversation_id": "x"})

	def test_only_what_meta_sent_is_returned(self):
		self.assertEqual(statuses.pricing({}), {})
		self.assertEqual(statuses.pricing({"status": "sent"}), {})
		self.assertEqual(statuses.pricing(None), {})
		self.assertEqual(statuses.pricing({"pricing": "oops", "conversation": 5}), {})

	def test_pricing_model_is_used_when_no_type(self):
		self.assertEqual(statuses.pricing({"pricing": {"pricing_model": "CBP"}})["pricing_type"], "CBP")


class TestStatusOrder(unittest.TestCase):
	def test_a_message_never_goes_backwards(self):
		order = ["sent", "delivered", "read"]
		current = "Queued"
		for report in ["read", "delivered", "sent", "read"]:  # out of order, and repeated
			new = statuses.next_status(current, report)
			if new:
				current = new
		self.assertEqual(current, "Read")

	def test_failed_applies_only_before_delivery(self):
		self.assertEqual(statuses.next_status("Sent", "failed"), "Failed")
		self.assertIsNone(statuses.next_status("Delivered", "failed"))
		self.assertIsNone(statuses.next_status("Failed", "delivered"))


class TestOriginOnSends(unittest.TestCase):
	def test_the_browser_cannot_choose_an_origin(self):
		source = read("api", "send.py")
		tree = ast.parse(source)
		for node in tree.body:
			if isinstance(node, ast.FunctionDef) and node.name in ("send_text", "send_template"):
				names = [a.arg for a in node.args.args]
				self.assertNotIn("origin", names, node.name)
		self.assertIn("def _send_template(conversation, template, params, origin)", source)
		self.assertIn("def _send_text(conversation, body, reply_to, origin)", source)

	def test_every_message_is_stored_with_its_origin(self):
		source = read("api", "send.py")
		self.assertIn('"origin": origin', source)
		self.assertIn("purposes.purpose_for(origin)", source)

	def test_old_messages_are_marked_as_person(self):
		self.assertIn("waba.patches.v0_1.set_origin_person", read("patches.txt"))
		self.assertIn("def execute()", read("patches", "v0_1", "set_origin_person.py"))


class TestAnnotatedApi(unittest.TestCase):
	def test_every_whitelisted_method_with_arguments_is_annotated(self):
		for filename in ("inbox.py", "send.py", "party.py", "webhook.py"):
			tree = ast.parse(read("api", filename))
			for node in ast.walk(tree):
				if not isinstance(node, ast.FunctionDef):
					continue
				decorators = [ast.unparse(d) for d in node.decorator_list]
				if not any("frappe.whitelist" in d for d in decorators):
					continue
				for arg in node.args.args:
					self.assertIsNotNone(arg.annotation, f"{filename}: {node.name}({arg.arg}) has no type annotation")


class TestOptOutFollowsThePhone(unittest.TestCase):
	def test_a_stop_is_held_across_numbers_and_records(self):
		parties = read("parties.py")
		self.assertIn("def phone_opt_outs(phone, waba_number)", parties)
		self.assertIn("phone_opt_outs(conversation.get(\"customer_phone\"), conversation.get(\"waba_number\"))", parties)
		self.assertIn("def _set_phone_flag", parties)
		self.assertIn("_record_consent_everywhere", parties)

	def test_the_matcher_can_list_every_record_holding_a_number(self):
		self.assertIn("def find_all_parties(phone)", read("matching.py"))
		self.assertIn('"waba_party_all"', read("matching.py"))
		with open(os.path.join(ROOT, "..", "..", "splinh", "splinh", "hooks.py"), encoding="utf-8") as f:
			self.assertIn("waba_party_all", f.read())


class TestHelpers(unittest.TestCase):
	def test_the_conversation_lock_wraps_the_whole_handling_of_a_message(self):
		source = read("inbound.py")
		start = source.index("with locks.conversation(conversation.name)")
		block = source[start:source.index("assignment.notify(conversation, \"message\")")]
		for needle in ("_update_conversation", "_keyword", "_route"):
			self.assertIn(needle, block)

	def test_the_claim_uses_bound_values_not_pasted_text(self):
		source = read("claims.py")
		self.assertIn("(to_status, name, from_status)", source)
		self.assertIn("select row_count()", source)

	def test_claim_helper_is_not_named_after_a_standard_library_module(self):
		self.assertFalse(os.path.exists(os.path.join(ROOT, "queue.py")))


if __name__ == "__main__":
	unittest.main()
