"""Meta signs every webhook: X-Hub-Signature-256 = "sha256=" + HMAC-SHA256(raw body, app secret).

The check must use the RAW request bytes (re-serialised JSON differs) and a constant-time comparison.
A missing header, a missing secret or a malformed value is simply "not valid"; this never raises.
"""

import hashlib
import hmac

PREFIX = "sha256="


def sign(raw_body, app_secret):
	"""The header value Meta would send for this body (used by tests and by a local mock sender)."""
	digest = hmac.new(_b(app_secret), _b(raw_body), hashlib.sha256).hexdigest()
	return PREFIX + digest


def verify_signature(raw_body, header_value, app_secret):
	if not app_secret or not header_value or raw_body is None:
		return False
	header_value = str(header_value).strip()
	if not header_value.startswith(PREFIX):
		return False
	return hmac.compare_digest(header_value.lower(), sign(raw_body, app_secret))


def _b(value):
	return value if isinstance(value, bytes) else str(value).encode("utf-8")
