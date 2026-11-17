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
NO_MARKETING_CONSENT = "no_marketing_consent"
MARKETING_OPTED_OUT = "marketing_opted_out"
OPTED_OUT = "opted_out"
NO_CONSENT = "no_consent"
LIMIT_REACHED = "limit_reached"

UTILITY = "UTILITY"
DEFAULT_LIMIT = 250  # an unverified business, and what is assumed when the tier is blank or not understood
WARN_AT = 0.8

_STOP = {"stop", "unsubscribe", "stop all", "stopall"}
_STOP_MARKETING = {"stop promo", "stop promos", "stop promotions", "stop offers", "stop marketing"}
_START_MARKETING = {"start promo", "start promos", "start promotions", "start offers", "start marketing"}
_START = {"start", "unstop"}
_TIERS = {"TIER_50": 50, "TIER_250": 250, "TIER_1K": 1000, "TIER_2K": 2000, "TIER_10K": 10000, "TIER_100K": 100000}


def check_template(category, has_written_before, consent, opted_out, allow_marketing=False, marketing_blocked=False):
	"""(ok, code, message). `category` is the template's Meta category; `consent` is "Yes" / "No" / "Unknown" (or blank).

	`allow_marketing` lets MARKETING templates through the same checks as Utility (an admin switch, on for now);
	`marketing_blocked` is a STOP PROMO or a marketing "No", which still stops a Marketing template. Authentication never goes."""
	category = (category or "").upper()
	if category == "MARKETING" and allow_marketing:
		if marketing_blocked:
			return False, MARKETING_OPTED_OUT, "This customer has opted out of marketing messages."
	elif category != UTILITY:
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
	return " ".join(re.sub(r"[^a-z ]", "", (text or "").lower()).split())


def is_stop(text):
	"""The customer's whole message is an opt-out keyword. A sentence that merely contains the word does not count."""
	return _normal(text) in _STOP


def is_start(text):
	return _normal(text) in _START


def is_stop_marketing(text):
	"""STOP PROMO and its variants: the customer keeps service and order messages but wants no marketing."""
	return _normal(text) in _STOP_MARKETING


def is_start_marketing(text):
	return _normal(text) in _START_MARKETING


def check_marketing(marketing_consent, opted_out, marketing_opted_out):
	"""(ok, code, message) for a MARKETING message. Marketing needs its own agreement ("Yes" on the marketing consent);
	a general STOP, a STOP PROMO or a marketing "No" always blocks. Nothing sends marketing until campaigns are built;
	this is the rule they will call."""
	if opted_out or marketing_opted_out or marketing_consent == CONSENT_NO:
		return False, MARKETING_OPTED_OUT, "This customer has opted out of marketing messages."
	if marketing_consent == CONSENT_YES:
		return True, None, None
	return False, NO_MARKETING_CONSENT, (
		"There is no marketing consent on this customer's record. Record it first (who agreed, when and how)."
	)
