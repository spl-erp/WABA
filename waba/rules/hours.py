"""Business hours for a number: is "now" inside them? Pure; the caller passes the local time of the number."""

import datetime

from waba.rules.config_validation import parse_days

_DAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def is_within_hours(now_local, start, end, working_days, hours_enabled=True):
	"""True when the number should answer: hours are off, or `now_local` falls on a working day between start
	(inclusive) and end (exclusive). `start` and `end` are datetime.time."""
	if not hours_enabled:
		return True
	days = parse_days(working_days)
	if not days or start is None or end is None:
		return True  # a mis-set schedule never blocks conversations
	if _DAY_NAMES[now_local.weekday()] not in days:
		return False
	return start <= now_local.time() < end


def as_time(value):
	"""Frappe hands a Time field over as timedelta, time or text; datetime.time (or None) back."""
	if value is None or value == "":
		return None
	if isinstance(value, datetime.time):
		return value
	if isinstance(value, datetime.timedelta):
		seconds = int(value.total_seconds()) % 86400
		return datetime.time(seconds // 3600, seconds % 3600 // 60, seconds % 60)
	parts = str(value).split(":")
	try:
		numbers = [int(float(p)) for p in parts[:3]]
	except ValueError:
		return None
	numbers += [0] * (3 - len(numbers))
	try:
		return datetime.time(*numbers)
	except ValueError:
		return None
