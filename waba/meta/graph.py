"""The only place that talks to Meta's Graph API. The access token travels in an Authorization header and is
never put in a URL, a log line or an error message.

`http` is injectable (a function with requests.request's call shape) so the tests run without a network.
The phone-number field list follows Meta's reference as read on 28 Oct 2026 but was NOT yet exercised against a
live account: if Meta rejects a field (error 100) the call is repeated with the minimal set.
"""

import json

import requests

from waba.constants import DEFAULT_API_VERSION, GRAPH_HOST
from waba.rules import templates

TIMEOUT = 20
UPLOAD_TIMEOUT = 120
DOWNLOAD_TIMEOUT = 120
MEDIA_HOST_SUFFIXES = (".facebook.com", ".fbcdn.net", ".fbsbx.com", ".whatsapp.net", ".whatsapp.com")  # UNVERIFIED list: where Meta serves media
PAGE_LIMIT = 100
MAX_PAGES = 10

ACCOUNT_FIELDS = "name,currency,timezone_id,account_review_status,business_verification_status"
NUMBER_FIELDS = "id,display_phone_number,verified_name,quality_rating,name_status,status,messaging_limit_tier"
NUMBER_FIELDS_MINIMAL = "id,display_phone_number,verified_name"
NUMBER_STATE_FIELDS = "id,display_phone_number,verified_name,quality_rating,name_status,status,code_verification_status"
NUMBER_STATE_MINIMAL = "id,display_phone_number,verified_name,status,code_verification_status"


class GraphError(Exception):
	def __init__(self, message, code=None, http_status=None, subcode=None, user_message=None, user_title=None):
		super().__init__(message)
		self.message = message
		self.code = code
		self.http_status = http_status
		self.subcode = subcode
		self.user_message = user_message  # Meta's own sentence for a person, when it gives one (template refusals do)
		self.user_title = user_title


def call(token, method, path, version=None, params=None, data=None, json=None, http=None, files=None, headers=None):
	url = f"{GRAPH_HOST}/{version or DEFAULT_API_VERSION}/{path.lstrip('/')}"
	extra = {"files": files} if files else {}  # only passed for an upload, so simple fakes need not accept it
	try:
		response = (http or requests.request)(
			method,
			url,
			params=params,
			data=data,
			json=json,
			headers={"Authorization": f"Bearer {token}", **(headers or {})},
			timeout=UPLOAD_TIMEOUT if files or (isinstance(data, (bytes, bytearray)) and data) else TIMEOUT,
			**extra,
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
			subcode=error.get("error_subcode"),
			user_message=error.get("error_user_msg"),
			user_title=error.get("error_user_title"),
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
	if getattr(error, "user_message", None):  # Meta wrote this for a person: it is the clearest thing to show
		title = f"{error.user_title}: " if getattr(error, "user_title", None) else ""
		return f"{title}{error.user_message}"
	if error.code == 190:
		return "Meta rejected the access token (expired or revoked). Create a new system-user token and save it on the Portfolio."
	if error.code == 100:
		return f"Meta rejected the request: {error.message}"
	if action == "unknown":
		return error.message
	return f"{meaning}. ({error.message})"


TEMPLATE_FIELDS_FULL = "id,name,language,category,status,components,rejected_reason,parameter_format,quality_score"
TEMPLATE_FIELDS = "id,name,language,category,status,components,rejected_reason"
TEMPLATE_FIELDS_MINIMAL = "id,name,language,category,status,components"
_TEMPLATE_FIELD_SETS = (TEMPLATE_FIELDS_FULL, TEMPLATE_FIELDS, TEMPLATE_FIELDS_MINIMAL)  # asked in this order; error 100 moves to the next


def list_templates(token, waba_id, version=None, http=None):
	"""All message templates of the account (follows paging). Unverified fields: rejected_reason, parameter_format, quality_score;
	if Meta refuses a field (error 100) the list is asked again with fewer fields."""
	params = {"fields": TEMPLATE_FIELDS_FULL, "limit": PAGE_LIMIT}
	items = []
	for _page in range(MAX_PAGES):
		try:
			body = call(token, "GET", f"{waba_id}/message_templates", version, params=params, http=http)
		except GraphError as e:
			position = _TEMPLATE_FIELD_SETS.index(params["fields"]) if params["fields"] in _TEMPLATE_FIELD_SETS else len(_TEMPLATE_FIELD_SETS)
			if e.code == 100 and position + 1 < len(_TEMPLATE_FIELD_SETS) and not items:
				params = {**params, "fields": _TEMPLATE_FIELD_SETS[position + 1]}
				continue
			raise
		items += body.get("data") or []
		after = ((body.get("paging") or {}).get("cursors") or {}).get("after")
		if not after or not (body.get("paging") or {}).get("next"):
			break
		params = {**params, "after": after}
	return items


def media_info(token, media_id, version=None, http=None):
	"""Where to fetch a customer's file: {"url", "mime_type", "sha256", "file_size", "id"} (field names UNVERIFIED live)."""
	return call(token, "GET", str(media_id), version, http=http)


def media_host_allowed(url):
	"""The access token is only ever sent to https hosts that belong to Meta."""
	from urllib.parse import urlparse

	parts = urlparse(str(url or ""))
	host = (parts.hostname or "").lower()
	return parts.scheme == "https" and any(host.endswith(suffix) for suffix in MEDIA_HOST_SUFFIXES)


def download_media(token, url, max_bytes, http=None):
	"""The bytes of a customer's file. Refuses a foreign host (so the token cannot leak) and anything over max_bytes."""
	if not media_host_allowed(url):
		raise GraphError("Meta gave a file address that is not on a Meta host, so it was not fetched.")
	try:
		response = (http or requests.request)(
			"GET", url, headers={"Authorization": f"Bearer {token}"}, timeout=DOWNLOAD_TIMEOUT, stream=True
		)
	except requests.RequestException as e:
		raise GraphError(f"Could not reach Meta ({e.__class__.__name__}).") from None
	if response.status_code >= 400:
		raise GraphError(f"Meta answered HTTP {response.status_code} for the file.", http_status=response.status_code)
	declared = response.headers.get("Content-Length") if getattr(response, "headers", None) else None
	if declared and str(declared).isdigit() and int(declared) > max_bytes:
		raise GraphError("The file is larger than the limit and was not downloaded.")
	content = response.content
	if len(content) > max_bytes:
		raise GraphError("The file is larger than the limit and was not downloaded.")
	return content


def upload_media(token, phone_number_id, filename, content, mime, version=None, http=None):
	"""Upload bytes to Meta and return the media id it will accept in a send."""
	body = call(
		token,
		"POST",
		f"{phone_number_id}/media",
		version,
		data={"messaging_product": "whatsapp", "type": mime},
		files={"file": (filename, content, mime)},
		http=http,
	)
	media_id = body.get("id") if isinstance(body, dict) else None
	if not media_id:
		raise GraphError("Meta did not return a file id for the upload.")
	return str(media_id)


def send_message(token, phone_number_id, payload, version=None, http=None):
	"""POST a message payload (see rules/outbound.py); returns Meta's response body."""
	return call(token, "POST", f"{phone_number_id}/messages", version, json=payload, http=http)


def template_values(item):
	"""Our Waba Template fields from one Meta template item."""
	parts = {c.get("type"): c for c in item.get("components") or [] if isinstance(c, dict)}
	header = parts.get("HEADER") or {}
	buttons = (parts.get("BUTTONS") or {}).get("buttons") or []
	quality = item.get("quality_score") if isinstance(item.get("quality_score"), dict) else {}
	structure = templates.parse(item.get("components"), item.get("parameter_format"))
	ok, why = templates.sendable(structure)
	return {
		"parameter_format": structure["parameter_format"],
		"quality": str(quality.get("score") or "").upper() or None,
		"unsendable_reason": None if ok else why,
		"components_json": json.dumps(item.get("components") or [], ensure_ascii=False),
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


# ------------------------------------------------------------------------------------------------ writing templates
# Field names and shapes follow Meta's template reference as of Oct 2026 and are UNVERIFIED against live Meta.


def create_template(token, waba_id, payload, version=None, http=None):
	"""POST a new template for review. Returns Meta's answer: {"id", "status", "category"}."""
	return call(token, "POST", f"{waba_id}/message_templates", version, json=payload, http=http)


def edit_template(token, template_id, components, category=None, version=None, http=None):
	"""POST new components for an existing template (Meta limits how often a template may be edited)."""
	body = {"components": components}
	if category:
		body["category"] = category
	return call(token, "POST", str(template_id), version, json=body, http=http)


def delete_template(token, waba_id, name, template_id=None, version=None, http=None):
	"""DELETE a template by name (every language of that name), or one language when its id is given."""
	params = {"name": name}
	if template_id:
		params["hsm_id"] = str(template_id)
	return call(token, "DELETE", f"{waba_id}/message_templates", version, params=params, http=http)


def upload_sample(token, app_id, filename, content, mime, version=None, http=None):
	"""Meta's resumable upload for the sample file of a media header. Returns the handle ("4::...") a template refers to.
	Two steps: open a session on the app, then send the bytes (this second call authorises with OAuth, not Bearer)."""
	session = call(
		token, "POST", f"{app_id}/uploads", version,
		params={"file_name": filename, "file_length": len(content), "file_type": mime}, http=http,
	)
	upload_id = session.get("id") if isinstance(session, dict) else None
	if not upload_id:
		raise GraphError("Meta did not open an upload for the sample file.")
	done = call(token, "POST", str(upload_id), version, data=bytes(content), headers={"Authorization": f"OAuth {token}", "file_offset": "0"}, http=http)
	handle = done.get("h") if isinstance(done, dict) else None
	if not handle:
		raise GraphError("Meta did not return a handle for the sample file.")
	return str(handle)


# --- registering a phone number (verification code, then the two-step PIN). The PIN and the code are sent to Meta and never kept here.


def number_state(token, phone_number_id, version=None, http=None):
	"""One number's verification and registration state (a read)."""
	try:
		return call(token, "GET", str(phone_number_id), version, params={"fields": NUMBER_STATE_FIELDS}, http=http)
	except GraphError as e:
		if e.code != 100:
			raise
		return call(token, "GET", str(phone_number_id), version, params={"fields": NUMBER_STATE_MINIMAL}, http=http)


def request_code(token, phone_number_id, method="SMS", language="en_US", version=None, http=None):
	"""Ask Meta to send a one-time code to the number by SMS or voice call."""
	return call(token, "POST", f"{phone_number_id}/request_code", version, json={"code_method": method, "language": language}, http=http)


def verify_code(token, phone_number_id, code, version=None, http=None):
	return call(token, "POST", f"{phone_number_id}/verify_code", version, json={"code": code}, http=http)


def register_number(token, phone_number_id, pin, version=None, http=None):
	"""Register the number for the Cloud API with a 6-digit two-step PIN. The PIN is needed later to change or delete the number."""
	return call(token, "POST", f"{phone_number_id}/register", version, json={"messaging_product": "whatsapp", "pin": pin}, http=http)


# ------------------------------------------------------------------------------------------------ voice calls (Business Calling API)
# Signalling is HTTPS: POST /<phone number id>/calls with an action. The field names follow Meta's reference as read on 18 Nov 2026
# and are UNVERIFIED against a live call.


def call_action(token, phone_number_id, action, call_id=None, sdp=None, sdp_type=None, to=None, recording=None, version=None, http=None):
	"""One call action: connect (place an outgoing call: `to` and an offer), pre_accept / accept (an incoming call: an answer),
	reject, terminate. Returns Meta's answer (success true, or for connect the call id)."""
	payload = {"messaging_product": "whatsapp", "action": action}
	if call_id:
		payload["call_id"] = call_id
	if to:
		payload["to"] = to
	if sdp:
		payload["session"] = {"sdp_type": sdp_type or ("offer" if action == "connect" else "answer"), "sdp": sdp}
	if recording:
		payload["recording"] = recording
	return call(token, "POST", f"{phone_number_id}/calls", version, json=payload, http=http)


def calling_settings(token, phone_number_id, version=None, http=None):
	"""What Meta has set for calling on a number (status, call icon, callback permission, permission mode)."""
	return call(token, "GET", f"{phone_number_id}/settings", version, http=http)


def call_permissions(token, phone_number_id, user_wa_id, version=None, http=None):
	"""Whether we may call this customer now (permission status, start_call / send_call_permission_request allowed, usage limits)."""
	return call(token, "GET", f"{phone_number_id}/call_permissions", version, params={"user_wa_id": str(user_wa_id).lstrip("+")}, http=http)
