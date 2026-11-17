"""What Meta tells us about a template after we send it for review (no Frappe, tested offline).

Meta posts these webhook fields: message_template_status_update, message_template_quality_update, template_category_update and
message_template_components_update. `parse` turns one of them into: which template it is about (Meta's id, or name and language),
the changes to make on our record, and a plain sentence for the admins when it needs attention. The field names follow Meta's
reference as of Oct 2026 and are UNVERIFIED against live events.
"""

FIELDS = (
	"message_template_status_update",
	"message_template_quality_update",
	"template_category_update",
	"message_template_components_update",
)

# status event -> the status we keep. Events we do not recognise leave the status alone.
STATUS_OF_EVENT = {
	"APPROVED": "APPROVED",
	"REINSTATED": "APPROVED",
	"REJECTED": "REJECTED",
	"PENDING": "PENDING",
	"IN_APPEAL": "PENDING",
	"PAUSED": "PAUSED",
	"DISABLED": "DISABLED",
	"DELETED": "DELETED",
	"PENDING_DELETION": "PENDING",
}

REASONS = {
	"INCORRECT_CATEGORY": "Meta says the category is wrong for this content.",
	"INVALID_FORMAT": "Meta says the format or the examples are not valid.",
	"ABUSIVE_CONTENT": "Meta says the content breaks its abusive-content policy.",
	"SCAM": "Meta says the content looks like a scam.",
	"TAG_CONTENT_MISMATCH": "Meta says the content does not match the category it was sent under.",
}
ATTENTION = ("REJECTED", "PAUSED", "DISABLED")


def _text(value):
	return str(value).strip() if value not in (None, "") else ""


def identify(value):
	"""(Meta's template id or '', name, language) from an event value."""
	return _text(value.get("message_template_id")), _text(value.get("message_template_name")), _text(value.get("message_template_language"))


def reason_text(code):
	code = _text(code).upper()
	if not code or code == "NONE":
		return None
	return REASONS.get(code, f"Meta gave the reason {code.replace('_', ' ').lower()}.")


def parse(field, value):
	"""{id, name, language, updates: {...}, alert: str|None} for one change, or None when it is not a template event or has no identity."""
	if field not in FIELDS or not isinstance(value, dict):
		return None
	template_id, name, language = identify(value)
	if not (template_id or (name and language)):
		return None
	updates, alert = {}, None
	label = f"{name} ({language})" if name else template_id
	if field == "message_template_status_update":
		event = _text(value.get("event")).upper()
		status = STATUS_OF_EVENT.get(event)
		if status:
			updates["status"] = status
		reason = reason_text(value.get("reason"))
		if event == "REJECTED":
			updates["rejected_reason"] = reason or "Meta rejected the template."
		elif status == "APPROVED":
			updates["rejected_reason"] = None
		if event in ATTENTION:
			alert = f"WhatsApp template {label} was {event.lower()} by Meta." + (f" {reason}" if reason else "")
		elif event == "FLAGGED":
			alert = f"WhatsApp template {label} was flagged by Meta: its quality is at risk."
	elif field == "message_template_quality_update":
		score = _text(value.get("new_quality_score")).upper()
		if score:
			updates["quality"] = score
			if score == "RED":
				alert = f"The quality of WhatsApp template {label} fell to red; Meta may pause it."
	elif field == "template_category_update":
		category = _text(value.get("new_category")).upper()
		if category:
			updates["category"] = category
			alert = f"Meta changed the category of WhatsApp template {label} to {category.lower()}."
			if category == "MARKETING":
				alert += " Marketing templates cannot be used for first messages from here."
	elif field == "message_template_components_update":
		pass  # the new text arrives with the next Sync templates; nothing to change from this event alone
	return {"id": template_id, "name": name, "language": language, "updates": updates, "alert": alert, "field": field}
