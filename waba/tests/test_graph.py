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

	def __call__(self, method, url, params=None, data=None, json=None, headers=None, timeout=None, files=None, stream=None):
		self.calls.append({"method": method, "url": url, "params": params, "json": json, "headers": headers, "timeout": timeout, "files": files, "data": data, "stream": stream})
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


class TestTemplatesAndSend(unittest.TestCase):
	ITEM = {"id": 7, "name": "order_update", "language": "en", "category": "utility", "status": "approved",
		"components": [{"type": "HEADER", "format": "TEXT", "text": "Order"}, {"type": "BODY", "text": "Hi {{1}}, order {{2}} shipped"},
			{"type": "FOOTER", "text": "Splashjet"}, {"type": "BUTTONS", "buttons": [{"type": "QUICK_REPLY", "text": "OK"}]}]}

	def test_template_values(self):
		v = graph.template_values(self.ITEM)
		self.assertEqual((v["template_name"], v["language"], v["category"], v["status"]), ("order_update", "en", "UTILITY", "APPROVED"))
		self.assertEqual((v["body_text"], v["header_text"], v["footer_text"], v["button_count"]), ("Hi {{1}}, order {{2}} shipped", "Order", "Splashjet", 1))
		self.assertIsNone(v["rejected_reason"])
		self.assertEqual(graph.template_values({"name": "x"})["body_text"], "")

	def test_list_templates_pages_and_falls_back(self):
		http = Fake(error(100, "bad field"), Resp({"data": [self.ITEM]}))
		self.assertEqual(len(graph.list_templates("t", "123", http=http)), 1)
		self.assertEqual(http.calls[0]["params"]["fields"], graph.TEMPLATE_FIELDS_FULL)
		self.assertEqual(http.calls[1]["params"]["fields"], graph.TEMPLATE_FIELDS)  # keeps rejected_reason when only the newer fields are refused

	def test_list_templates_steps_down_to_the_minimal_set_and_then_gives_up(self):
		http = Fake(error(100, "bad"), error(100, "bad"), Resp({"data": [self.ITEM]}))
		graph.list_templates("t", "123", http=http)
		self.assertEqual(http.calls[2]["params"]["fields"], graph.TEMPLATE_FIELDS_MINIMAL)
		with self.assertRaises(graph.GraphError):
			graph.list_templates("t", "123", http=Fake(error(100, "a"), error(100, "b"), error(100, "c")))

	def test_template_values_keep_the_whole_template_and_its_shape(self):
		item = dict(self.ITEM, parameter_format="POSITIONAL", quality_score={"score": "green"})
		v = graph.template_values(item)
		self.assertEqual(v["parameter_format"], "POSITIONAL")
		self.assertEqual(v["quality"], "GREEN")
		self.assertIsNone(v["unsendable_reason"])
		import json as _json
		self.assertEqual(_json.loads(v["components_json"]), item["components"])

	def test_template_values_say_why_a_template_cannot_be_sent(self):
		item = dict(self.ITEM, components=[{"type": "BODY", "text": "Hi"}, {"type": "BUTTONS", "buttons": [{"type": "FLOW", "text": "Open"}]}])
		v = graph.template_values(item)
		self.assertIn("flow button", v["unsendable_reason"])
		self.assertIsNone(graph.template_values({"name": "x"})["quality"])

	def test_send_message_posts_json_to_the_number(self):
		http = Fake(Resp({"messages": [{"id": "wamid.X"}]}))
		out = graph.send_message("t", "555", {"type": "text"}, http=http)
		self.assertEqual(out["messages"][0]["id"], "wamid.X")
		self.assertEqual((http.calls[0]["method"], http.calls[0]["json"], http.calls[0]["url"].endswith("/555/messages")), ("POST", {"type": "text"}, True))


class TestExplain(unittest.TestCase):
	def test_token_and_other_messages(self):
		self.assertIn("token", graph.explain(graph.GraphError("x", code=190)).lower())
		self.assertEqual(graph.explain(graph.GraphError("plain", code=None)), "plain")
		self.assertIn("billing", graph.explain(graph.GraphError("x", code=131042)).lower())


if __name__ == "__main__":
	unittest.main()


class Bytes(Resp):
	def __init__(self, content, status=200, headers=None):
		super().__init__({}, status)
		self.content, self.headers = content, headers or {}


class TestMediaCalls(unittest.TestCase):
	def test_media_info_is_a_get_by_id(self):
		http = Fake(Resp({"url": "https://lookaside.fbsbx.com/x", "mime_type": "image/jpeg", "id": "M1"}))
		out = graph.media_info("TOK", "M1", http=http)
		self.assertEqual(out["mime_type"], "image/jpeg")
		self.assertTrue(http.calls[0]["url"].endswith("/M1"))
		self.assertEqual(http.calls[0]["headers"], {"Authorization": "Bearer TOK"})

	def test_download_only_from_meta_hosts_with_the_token(self):
		http = Fake(Bytes(b"abc"))
		self.assertEqual(graph.download_media("TOK", "https://lookaside.fbsbx.com/a?b=1", 10, http=http), b"abc")
		self.assertEqual(http.calls[0]["headers"], {"Authorization": "Bearer TOK"})
		for bad in ("http://lookaside.fbsbx.com/a", "https://evil.example.com/a", "https://facebook.com.evil.io/a", "file:///etc/passwd", ""):
			with self.assertRaises(graph.GraphError):
				graph.download_media("TOK", bad, 10, http=Fake(Bytes(b"x")))
		self.assertEqual(len(http.calls), 1)  # nothing was requested for the refused addresses' own fake either

	def test_download_size_cap_and_errors(self):
		with self.assertRaises(graph.GraphError):
			graph.download_media("T", "https://x.fbcdn.net/a", 2, http=Fake(Bytes(b"abc")))
		with self.assertRaises(graph.GraphError):
			graph.download_media("T", "https://x.fbcdn.net/a", 2, http=Fake(Bytes(b"a", headers={"Content-Length": "99"})))
		with self.assertRaises(graph.GraphError):
			graph.download_media("T", "https://x.fbcdn.net/a", 20, http=Fake(Bytes(b"", status=404)))

	def test_upload_is_multipart_and_returns_the_id(self):
		http = Fake(Resp({"id": "U1"}))
		self.assertEqual(graph.upload_media("TOK", "PN1", "q.pdf", b"%PDF", "application/pdf", http=http), "U1")
		call = http.calls[0]
		self.assertTrue(call["url"].endswith("/PN1/media"))
		self.assertEqual(call["files"]["file"], ("q.pdf", b"%PDF", "application/pdf"))
		self.assertEqual(call["data"], {"messaging_product": "whatsapp", "type": "application/pdf"})
		self.assertEqual(call["timeout"], graph.UPLOAD_TIMEOUT)
		with self.assertRaises(graph.GraphError):
			graph.upload_media("TOK", "PN1", "q.pdf", b"x", "application/pdf", http=Fake(Resp({})))


class TestWritingTemplates(unittest.TestCase):
	def test_errors_keep_metas_own_explanation(self):
		body = {"error": {"message": "Invalid parameter", "code": 100, "error_subcode": 2388023, "error_user_title": "Template Content Invalid", "error_user_msg": "The body has too many variables for its length."}}
		with self.assertRaises(graph.GraphError) as ctx:
			graph.call("t", "POST", "x", http=Fake(Resp(body, 400)))
		e = ctx.exception
		self.assertEqual((e.code, e.subcode, e.user_title), (100, 2388023, "Template Content Invalid"))
		self.assertEqual(graph.explain(e), "Template Content Invalid: The body has too many variables for its length.")

	def test_errors_without_a_user_message_explain_as_before(self):
		with self.assertRaises(graph.GraphError) as ctx:
			graph.call("t", "POST", "x", http=Fake(error(190, "expired", 401)))
		self.assertIn("access token", graph.explain(ctx.exception))
		self.assertIsNone(ctx.exception.user_message)

	def test_create_template_posts_the_request_to_the_account(self):
		http = Fake(Resp({"id": "99", "status": "PENDING", "category": "UTILITY"}))
		out = graph.create_template("TOK", "WABA1", {"name": "n", "language": "en", "category": "UTILITY", "components": []}, http=http)
		self.assertEqual(out["status"], "PENDING")
		c = http.calls[0]
		self.assertEqual((c["method"], c["json"]["name"]), ("POST", "n"))
		self.assertTrue(c["url"].endswith("/WABA1/message_templates"))

	def test_edit_and_delete(self):
		http = Fake(Resp({"success": True}), Resp({"success": True}), Resp({"success": True}))
		graph.edit_template("T", "55", [{"type": "BODY", "text": "x"}], category="UTILITY", http=http)
		self.assertTrue(http.calls[0]["url"].endswith("/55"))
		self.assertEqual(http.calls[0]["json"], {"components": [{"type": "BODY", "text": "x"}], "category": "UTILITY"})
		graph.delete_template("T", "WABA1", "old_one", http=http)
		graph.delete_template("T", "WABA1", "old_one", template_id=77, http=http)
		self.assertEqual((http.calls[1]["method"], http.calls[1]["params"]), ("DELETE", {"name": "old_one"}))
		self.assertEqual(http.calls[2]["params"], {"name": "old_one", "hsm_id": "77"})

	def test_sample_upload_is_two_steps_and_the_second_uses_oauth(self):
		http = Fake(Resp({"id": "upload:MTph"}), Resp({"h": "4::aW1hZ2U"}))
		handle = graph.upload_sample("TOK", "APP1", "hdr.png", b"\x89PNGdata", "image/png", http=http)
		self.assertEqual(handle, "4::aW1hZ2U")
		first, second = http.calls
		self.assertTrue(first["url"].endswith("/APP1/uploads"))
		self.assertEqual(first["params"], {"file_name": "hdr.png", "file_length": 8, "file_type": "image/png"})
		self.assertTrue(second["url"].endswith("/upload:MTph"))
		self.assertEqual(second["data"], b"\x89PNGdata")
		self.assertEqual(second["headers"]["Authorization"], "OAuth TOK")
		self.assertEqual(second["headers"]["file_offset"], "0")
		self.assertEqual(first["headers"]["Authorization"], "Bearer TOK")
		self.assertEqual(second["timeout"], graph.UPLOAD_TIMEOUT)

	def test_sample_upload_fails_plainly_when_meta_gives_no_session_or_handle(self):
		with self.assertRaises(graph.GraphError):
			graph.upload_sample("T", "A", "f.png", b"x", "image/png", http=Fake(Resp({})))
		with self.assertRaises(graph.GraphError):
			graph.upload_sample("T", "A", "f.png", b"x", "image/png", http=Fake(Resp({"id": "upload:1"}), Resp({})))
