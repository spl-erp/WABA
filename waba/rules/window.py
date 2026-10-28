"""The 24-hour customer service window.

It opens when the customer messages (or calls) us and refreshes on each new inbound message. Inside it any
message type may be sent; outside it only an approved template. Meta has no API that reports the window, so
the ERP tracks the last inbound time per (number, customer) and computes the state here.
"""

import datetime

WINDOW = datetime.timedelta(hours=24)


def window_expires_at(last_inbound_at):
	"""When the window closes, or None if the customer never wrote to this number."""
	return last_inbound_at + WINDOW if last_inbound_at else None


def is_window_open(last_inbound_at, now):
	expires = window_expires_at(last_inbound_at)
	return bool(expires and now < expires)


def seconds_left(last_inbound_at, now):
	"""Whole seconds until the window closes; 0 when closed."""
	expires = window_expires_at(last_inbound_at)
	if not expires or now >= expires:
		return 0
	return int((expires - now).total_seconds())
