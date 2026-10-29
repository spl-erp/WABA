"""The only place that talks to Meta's Graph API. The access token travels in an Authorization header and is
never put in a URL, a log line or an error message.

`http` is injectable (a function with requests.request's call shape) so the tests run without a network.
The phone-number field list follows Meta's reference as read on 28 Oct 2026 but was NOT yet exercised against a
live account: if Meta rejects a field (error 100) the call is repeated with the minimal set.
"""

import requests

from waba.constants import DEFAULT_API_VERSION, GRAPH_HOST

TIMEOUT = 20
PAGE_LIMIT = 100
MAX_PAGES = 10

ACCOUNT_FIELDS = "name,currency,timezone_id,account_review_status,business_verification_status"
NUMBER_FIELDS = "id,display_phone_number,verified_name,quality_rating,name_status,status,messaging_limit_tier"
NUMBER_FIELDS_MINIMAL = "id,display_phone_number,verified_name"


class GraphError(Exception):
	def __init__(self, message, code=None, http_status=None):
		super().__init__(message)
		self.message = message
		self.code = code
		self.http_status = http_status


def call(token, method, path, version=None, params=None, data=None, json=None, http=None):
	url = f"{GRAPH_HOST}/{version or DEFAULT_API_VERSION}/{path.lstrip('/')}"
	try:
		response = (http or requests.request)(
			method,
			url,
			params=params,
			data=data,
			json=json,
			headers={"Authorization": f"Bearer {token}"},
			timeout=TIMEOUT,
		)
	except requests.RequestException as e:
		raise GraphError(f"Could not reach Meta ({e.__class__.__name__}).") from None
	try:
		body = response.json()
	except ValueError:
		body = {}
	if response.status_code >= 400 or (isinstance(body, dict) and "error" in body):
		error = body.get("error") if isinstance(body, dict) and isinstance(body.get("error"), dict) else {}
		raise GraphError(
			error.get("message") or f"Meta answered HTTP {response.status_code}.",
			code=error.get("code"),
			http_status=response.status_code,
		)
	return body


def account_info(token, waba_id, version=None, http=None):
	return call(token, "GET", waba_id, version, params={"fields": ACCOUNT_FIELDS}, http=http)


def list_numbers(token, waba_id, version=None, http=None):
	"""All phone numbers of the account (follows paging)."""
	fields = NUMBER_FIELDS
	params = {"fields": fields, "limit": PAGE_LIMIT}
	items = []
	for _page in range(MAX_PAGES):
		try:
			body = call(token, "GET", f"{waba_id}/phone_numbers", version, params=params, http=http)
		except GraphError as e:
			if e.code == 100 and params["fields"] != NUMBER_FIELDS_MINIMAL and not items:
				params = {**params, "fields": NUMBER_FIELDS_MINIMAL}
				continue
			raise
		items += body.get("data") or []
		after = ((body.get("paging") or {}).get("cursors") or {}).get("after")
		if not after or not (body.get("paging") or {}).get("next"):
			break
		params = {**params, "after": after}
	return items


def subscribe_app(token, waba_id, version=None, http=None):
	"""Tell Meta to send this account's events to the app's webhook. Idempotent on Meta's side."""
	return call(token, "POST", f"{waba_id}/subscribed_apps", version, http=http)


def subscribed_apps(token, waba_id, version=None, http=None):
	return (call(token, "GET", f"{waba_id}/subscribed_apps", version, http=http).get("data")) or []


def number_values(item):
	"""Our Waba Number fields from one Meta phone-number item (only what Meta sent)."""
	out = {"phone_number_id": str(item.get("id") or "").strip(), "display_number": item.get("display_phone_number")}
	if item.get("verified_name"):
		out["display_name"] = item["verified_name"]
	if item.get("name_status"):
		out["name_status"] = item["name_status"]
	if item.get("status"):
		out["status"] = item["status"]
	rating = str(item.get("quality_rating") or "").upper()
	if rating in ("GREEN", "YELLOW", "RED", "UNKNOWN"):
		out["quality_rating"] = rating
	return out


def explain(error):
	"""A sentence an admin can act on for a failed call."""
	from waba.rules import errors

	action, meaning = errors.classify(error.code)
	if error.code == 190:
		return "Meta rejected the access token (expired or revoked). Create a new system-user token and save it on the Portfolio."
	if error.code == 100:
		return f"Meta rejected the request: {error.message}"
	if action == "unknown":
		return error.message
	return f"{meaning}. ({error.message})"


TEMPLATE_FIELDS = "id,name,language,category,status,components,rejected_reason"
TEMPLATE_FIELDS_MINIMAL = "id,name,language,category,status,components"


def list_templates(token, waba_id, version=None, http=None):
	"""All message templates of the account (follows paging). Unverified field: rejected_reason."""
	params = {"fields": TEMPLATE_FIELDS, "limit": PAGE_LIMIT}
	items = []
	for _page in range(MAX_PAGES):
		try:
			body = call(token, "GET", f"{waba_id}/message_templates", version, params=params, http=http)
		except GraphError as e:
			if e.code == 100 and params["fields"] != TEMPLATE_FIELDS_MINIMAL and not items:
				params = {**params, "fields": TEMPLATE_FIELDS_MINIMAL}
				continue
			raise
		items += body.get("data") or []
		after = ((body.get("paging") or {}).get("cursors") or {}).get("after")
		if not after or not (body.get("paging") or {}).get("next"):
			break
		params = {**params, "after": after}
	return items


def send_message(token, phone_number_id, payload, version=None, http=None):
	"""POST a message payload (see rules/outbound.py); returns Meta's response body."""
	return call(token, "POST", f"{phone_number_id}/messages", version, json=payload, http=http)


def template_values(item):
	"""Our Waba Template fields from one Meta template item."""
	parts = {c.get("type"): c for c in item.get("components") or [] if isinstance(c, dict)}
	header = parts.get("HEADER") or {}
	buttons = (parts.get("BUTTONS") or {}).get("buttons") or []
	return {
		"meta_template_id": str(item.get("id") or ""),
		"template_name": item.get("name"),
		"language": item.get("language"),
		"category": str(item.get("category") or "").upper(),
		"status": str(item.get("status") or "").upper(),
		"rejected_reason": item.get("rejected_reason") if item.get("rejected_reason") not in (None, "NONE") else None,
		"header_format": header.get("format"),
		"header_text": header.get("text") if header.get("format") == "TEXT" else None,
		"body_text": (parts.get("BODY") or {}).get("text") or "",
		"footer_text": (parts.get("FOOTER") or {}).get("text"),
		"button_count": len(buttons),
	}
