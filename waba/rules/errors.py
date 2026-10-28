"""What to do when Meta rejects a send, by error code (Meta's error-code reference, 27 Oct 2026).

`classify(code)` answers with an Action the sender and the inbox act on; unknown codes are reported, never
silently retried. A code arrives as an int or a numeric string.
"""

TEMPLATE_REQUIRED = "template_required"  # outside the 24-hour window: send an approved template instead
DO_NOT_RETRY_24H = "do_not_retry_24h"  # withheld to keep the ecosystem healthy (marketing frequency)
BACKOFF_RETRY = "backoff_retry"  # our throughput was reached: slow down, retry
RETRY_LATER = "retry_later"  # pair rate limit or maintenance: retry that recipient shortly
NO_RETRY = "no_retry"  # recipient cannot receive: use another channel
FIX_REQUEST = "fix_request"  # our request was wrong (type, media, variables)
TEMPLATE_PROBLEM = "template_problem"  # template paused, disabled or not approved: edit or replace it
ALERT_BILLING = "alert_billing"  # payment problem: tell the owner at once
ALERT_ACCOUNT = "alert_account"  # account restricted or disabled: tell the admins at once
ALERT_TOKEN = "alert_token"  # access token expired: rotate it
FALLBACK_TO_PHONE = "fallback_to_phone"  # a BSUID recipient is not supported for this message: use the phone

ACTIONS = {
	131047: (TEMPLATE_REQUIRED, "More than 24 hours since the customer last wrote"),
	131049: (DO_NOT_RETRY_24H, "Message withheld to keep the ecosystem healthy"),
	130429: (BACKOFF_RETRY, "Throughput limit reached"),
	131056: (RETRY_LATER, "Too many messages to the same recipient"),
	131057: (RETRY_LATER, "Account in maintenance"),
	131026: (NO_RETRY, "Recipient cannot receive (not on WhatsApp, terms not accepted, old client)"),
	131051: (FIX_REQUEST, "Unsupported message type"),
	131053: (FIX_REQUEST, "Media upload or MIME type problem"),
	132000: (FIX_REQUEST, "Template variable count mismatch"),
	132001: (TEMPLATE_PROBLEM, "Template does not exist or is not approved"),
	132012: (FIX_REQUEST, "Template parameter format mismatch"),
	132015: (TEMPLATE_PROBLEM, "Template paused for quality"),
	132016: (TEMPLATE_PROBLEM, "Template permanently disabled"),
	131042: (ALERT_BILLING, "Payment or billing problem"),
	131031: (ALERT_ACCOUNT, "Account restricted"),
	368: (ALERT_ACCOUNT, "Account restricted or disabled for policy"),
	190: (ALERT_TOKEN, "Access token expired"),
	131062: (FALLBACK_TO_PHONE, "BSUID recipient not supported for this message type"),
}

# Actions that must reach a human immediately rather than just change how one send is retried.
ALERT_ACTIONS = frozenset({ALERT_BILLING, ALERT_ACCOUNT, ALERT_TOKEN})
# Actions after which the same message must NOT be sent again unchanged.
NEVER_RETRY_SAME = frozenset({NO_RETRY, FIX_REQUEST, TEMPLATE_PROBLEM, DO_NOT_RETRY_24H, TEMPLATE_REQUIRED})


def classify(code):
	"""(action, meaning) for an error code; ("unknown", "...") when not in the table."""
	try:
		number = int(code)
	except (TypeError, ValueError):
		return ("unknown", f"Unrecognised error code {code!r}")
	return ACTIONS.get(number, ("unknown", f"Unrecognised error code {number}"))


def needs_alert(code):
	return classify(code)[0] in ALERT_ACTIONS
