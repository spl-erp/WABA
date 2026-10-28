"""Run without a site:  python -m unittest waba.tests.test_graph   (a fake `http` stands in for Meta)"""

import unittest

from waba.meta import graph


class Resp:
	def __init__(self, body, status=200):
		self._body, self.status_code = body, status

	def json(self):
		if self._body is None:
			raise ValueError("no json")
		return self._body


class Fake:
	def __init__(self, *responses):
		self.responses, self.calls = list(responses), []

	def __call__(self, method, url, params=None, data=None, headers=None, timeout=None):
		self.calls.append({"method": method, "url": url, "params": params, "headers": headers, "timeout": timeout})
		return self.responses.pop(0)


def error(code, message="bad", status=400):
	return Resp({"error": {"message": message, "code": code}}, status)


class TestCall(unittest.TestCase):
	def test_token_goes_in_the_header_never_the_url_and_a_timeout_is_set(self):
		http = Fake(Resp({"id": "1"}))
		graph.account_info("SECRET-TOKEN", "123", "v25.0", http=http)
		call = http.calls[0]
		self.assertEqual(call["headers"], {"Authorization": "Bearer SECRET-TOKEN"})
		self.assertNotIn("SECRET-TOKEN", call["url"] + str(call["params"]))
		self.assertEqual(call["url"], "https://graph.facebook.com/v25.0/123")
		self.assertTrue(call["timeout"])

	def test_error_body_becomes_graph_error_without_the_token(self):
		with self.assertRaises(graph.GraphError) as ctx:
			graph.account_info("SECRET-TOKEN", "123", http=Fake(error(190, "Session expired", 401)))
		self.assertEqual((ctx.exception.code, ctx.exception.http_status), (190, 401))
		self.assertNotIn("SECRET-TOKEN", str(ctx.exception))

	def test_non_json_error_page(self):
		with self.assertRaises(graph.GraphError) as ctx:
			graph.account_info("t", "123", http=Fake(Resp(None, 502)))
		self.assertEqual(ctx.exception.http_status, 502)

	def test_network_failure(self):
		import requests

		def boom(*a, **k):
			raise requests.ConnectionError("secret detail")

		with self.assertRaises(graph.GraphError) as ctx:
			graph.account_info("t", "123", http=boom)
		self.assertNotIn("secret detail", str(ctx.exception))


class TestNumbers(unittest.TestCase):
	def test_follows_paging(self):
		http = Fake(
			Resp({"data": [{"id": "1"}], "paging": {"cursors": {"after": "A"}, "next": "x"}}),
			Resp({"data": [{"id": "2"}], "paging": {"cursors": {"after": "B"}}}),
		)
		self.assertEqual([n["id"] for n in graph.list_numbers("t", "123", http=http)], ["1", "2"])
		self.assertEqual(http.calls[1]["params"]["after"], "A")

	def test_unknown_field_falls_back_to_the_minimal_set(self):
		http = Fake(error(100, "Tried accessing nonexisting field"), Resp({"data": [{"id": "1"}]}))
		self.assertEqual(len(graph.list_numbers("t", "123", http=http)), 1)
		self.assertEqual(http.calls[1]["params"]["fields"], graph.NUMBER_FIELDS_MINIMAL)

	def test_other_errors_are_not_swallowed(self):
		with self.assertRaises(graph.GraphError):
			graph.list_numbers("t", "123", http=Fake(error(190)))

	def test_number_values(self):
		v = graph.number_values(
			{"id": 55, "display_phone_number": "+91 98765 43210", "verified_name": "Splashjet", "quality_rating": "green", "status": "CONNECTED", "name_status": "APPROVED"}
		)
		self.assertEqual(v["phone_number_id"], "55")
		self.assertEqual((v["quality_rating"], v["status"], v["display_name"]), ("GREEN", "CONNECTED", "Splashjet"))
		self.assertNotIn("quality_rating", graph.number_values({"id": 1, "quality_rating": "weird"}))


class TestSubscribe(unittest.TestCase):
	def test_subscribe_posts_to_subscribed_apps(self):
		http = Fake(Resp({"success": True}))
		self.assertTrue(graph.subscribe_app("t", "123", http=http)["success"])
		self.assertEqual((http.calls[0]["method"], http.calls[0]["url"].rsplit("/", 2)[-2:]), ("POST", ["123", "subscribed_apps"]))


class TestExplain(unittest.TestCase):
	def test_token_and_other_messages(self):
		self.assertIn("token", graph.explain(graph.GraphError("x", code=190)).lower())
		self.assertEqual(graph.explain(graph.GraphError("plain", code=None)), "plain")
		self.assertIn("billing", graph.explain(graph.GraphError("x", code=131042)).lower())


if __name__ == "__main__":
	unittest.main()
