"""May this template be sent to this customer? Pure rules: no database, fully testable offline.

Meta requires the customer's opt-in before a BUSINESS-started message, and restricts the whole account when that is
broken. The rule here is deliberately simple and strict:

  - Only UTILITY templates start a conversation (Marketing arrives with the campaigns release; Authentication is not used).
  - A customer who has opted out (replied STOP, or an opt-out flag on their record) is never sent a template.
  - A customer who has ever written to us needs no stored consent: they contacted the business first.
  - Everyone else needs consent "Yes" on their record (Unknown and No both block).

The business-started limit per portfolio (250 until Meta verifies the business, then 1K, 10K, 100K, unlimited a day) is
checked too, so a rep is told before Meta refuses.
"""

import re

CONSENT_YES = "Yes"
CONSENT_NO = "No"
CONSENT_UNKNOWN = "Unknown"

NOT_UTILITY = "not_utility"
OPTED_OUT = "opted_out"
NO_CONSENT = "no_consent"
LIMIT_REACHED = "limit_reached"

UTILITY = "UTILITY"
DEFAULT_LIMIT = 250  # an unverified business, and what is assumed when the tier is blank or not understood
WARN_AT = 0.8

_STOP = {"stop", "unsubscribe", "stop all", "stopall"}
_START = {"start", "unstop"}
_TIERS = {"TIER_50": 50, "TIER_250": 250, "TIER_1K": 1000, "TIER_2K": 2000, "TIER_10K": 10000, "TIER_100K": 100000}


def check_template(category, has_written_before, consent, opted_out):
	"""(ok, code, message). `category` is the template's Meta category; `consent` is "Yes" / "No" / "Unknown" (or blank)."""
	if (category or "").upper() != UTILITY:
		return False, NOT_UTILITY, (
			"Only Utility templates can be used to start a conversation. Marketing templates need the campaigns release."
		)
	if opted_out or consent == CONSENT_NO:
		return False, OPTED_OUT, "This customer has opted out of WhatsApp messages. Nothing can be sent."
	if has_written_before:
		return True, None, None
	if consent == CONSENT_YES:
		return True, None, None
	return False, NO_CONSENT, (
		"There is no WhatsApp consent on this customer's record. Record it first (who agreed, when and how), "
		"or wait for the customer to message you."
	)


def daily_limit(messaging_tier):
	"""How many business-started conversations a portfolio may open in 24 hours, or None for unlimited."""
	text = (messaging_tier or "").strip().upper().replace(" ", "_")
	if "UNLIMITED" in text:
		return None
	return _TIERS.get(text, DEFAULT_LIMIT)


def check_daily_limit(sent_in_24h, limit):
	"""(ok, code, message_or_warning). ok stays True with a warning message from 80 % of the limit."""
	if limit is None:
		return True, None, None
	if sent_in_24h >= limit:
		return False, LIMIT_REACHED, (
			f"This WhatsApp business has already started {sent_in_24h} conversations in the last 24 hours, "
			f"which is its limit ({limit}). Try again later."
		)
	if sent_in_24h >= limit * WARN_AT:
		return True, None, f"{sent_in_24h} of {limit} business-started conversations used in the last 24 hours."
	return True, None, None


def _normal(text):
	return re.sub(r"[^a-z ]", "", (text or "").lower()).strip()


def is_stop(text):
	"""The customer's whole message is an opt-out keyword. A sentence that merely contains the word does not count."""
	return _normal(text) in _STOP


def is_start(text):
	return _normal(text) in _START
