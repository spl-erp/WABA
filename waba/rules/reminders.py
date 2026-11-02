"""Rules for 'Remind me' on a conversation (no Frappe, tested offline)."""

import datetime

PENDING = "Pending"
FIRED = "Fired"
DONE = "Done"
CANCELLED = "Cancelled"
MAX_DAYS_AHEAD = 366
MAX_NOTE = 500
GRACE_SECONDS = 90  # a time that was "now" a moment ago is accepted


def check_remind_at(when, now):
	"""(ok, plain-words message). A reminder needs a time that has not passed and is within a year."""
	if not isinstance(when, datetime.datetime):
		return False, "Choose the date and time for the reminder."
	if when < now - datetime.timedelta(seconds=GRACE_SECONDS):
		return False, "That time has already passed."
	if when > now + datetime.timedelta(days=MAX_DAYS_AHEAD):
		return False, "A reminder can be at most a year ahead."
	return True, ""


def clean_note(note):
	text = " ".join(str(note or "").split())
	return text[:MAX_NOTE]


def is_due(status, remind_at, now):
	return status == PENDING and isinstance(remind_at, datetime.datetime) and remind_at <= now


def recipients(creator, assignee, enabled_users):
	"""Who is told when it fires: the person who set it, and the conversation's current assignee if that is someone else
	(a transferred conversation reaches its new owner). Only enabled users, creator first, no duplicates."""
	out = []
	for user in (creator, assignee):
		if user and user in enabled_users and user not in out:
			out.append(user)
	return out


def subject(customer, note):
	customer = (customer or "").strip() or "a customer"
	note = clean_note(note)
	return f"WhatsApp reminder: {customer}" + (f" - {note}" if note else "")


def status_after(action, current):
	"""The new status for done or cancel; None when the action does not apply."""
	if action == "done" and current in (PENDING, FIRED):
		return DONE
	if action == "cancel" and current == PENDING:
		return CANCELLED
	return None
