"""What a message is for, and which numbers may send it. Pure rules: no database, fully testable offline.

Every outgoing message carries an ORIGIN (who or what sent it). Every business number has four purpose switches
(conversations, documents, notifications, campaigns). A send is allowed only when the number is switched on for the
purpose its origin needs, so a number kept for ERP notifications is never used for a rep's chat, and a campaign can
never go out of a support number.
"""

PERSON = "Person"
NOTIFICATION = "Notification"
REMINDER = "Reminder"
CAMPAIGN = "Campaign"
AUTO_REPLY = "Auto-reply"
PHONE_APP = "Phone app"
SYSTEM = "System"
ORIGINS = (PERSON, NOTIFICATION, REMINDER, CAMPAIGN, AUTO_REPLY, PHONE_APP, SYSTEM)

CONVERSATIONS = "conversations"
DOCUMENTS = "documents"
NOTIFICATIONS = "notifications"
CAMPAIGNS = "campaigns"
PURPOSES = (CONVERSATIONS, DOCUMENTS, NOTIFICATIONS, CAMPAIGNS)

LABELS = {
	CONVERSATIONS: "conversations with customers",
	DOCUMENTS: "sending documents",
	NOTIFICATIONS: "ERP notifications and reminders",
	CAMPAIGNS: "campaigns",
}

# the purpose a number must be switched on for, by origin. A message typed in the phone app never goes through Waba's send.
PURPOSE_OF_ORIGIN = {
	PERSON: CONVERSATIONS,
	AUTO_REPLY: CONVERSATIONS,
	NOTIFICATION: NOTIFICATIONS,
	REMINDER: NOTIFICATIONS,
	SYSTEM: NOTIFICATIONS,
	CAMPAIGN: CAMPAIGNS,
}

NOT_ALLOWED = "purpose_off"
UNKNOWN_ORIGIN = "unknown_origin"

# what to do with a customer's reply on a number that is not switched on for conversations
REPLY_NORMAL = "Route normally"
REPLY_POOL = "Pool for supervisors"
REPLY_POLICIES = (REPLY_NORMAL, REPLY_POOL)


def purpose_for(origin):
	"""The purpose a send of this origin needs, or None for an origin Waba does not send."""
	return PURPOSE_OF_ORIGIN.get(origin)


def check(flags, purpose):
	"""(ok, code, message). `flags` maps each purpose name to a truthy/falsy value (the number's tick boxes)."""
	if purpose not in PURPOSES:
		return False, UNKNOWN_ORIGIN, "This kind of message cannot be sent from this number."
	if flags and flags.get(purpose):
		return True, None, None
	return False, NOT_ALLOWED, (
		f"This number is not set up for {LABELS[purpose]}. Choose another number, or switch that purpose on for this "
		"number under Numbers."
	)


def check_origin(flags, origin):
	"""Like check(), starting from the origin of the message."""
	purpose = purpose_for(origin)
	if not purpose:
		return False, UNKNOWN_ORIGIN, "This kind of message cannot be sent from the ERP."
	return check(flags, purpose)


def replies_go_to_pool(flags, policy):
	"""True when a customer's reply on this number should wait for a supervisor instead of being routed by the rules.

	Only a number that is NOT switched on for conversations can have such a policy (a notification-only number, whose
	replies should not land in a rep's chat by chance)."""
	return (not (flags or {}).get(CONVERSATIONS)) and policy == REPLY_POOL
