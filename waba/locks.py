"""A lock per conversation, so two customer messages arriving together (two workers) are handled one after the other.

Without it both could read "nobody is assigned" and give the conversation to two different agents. The lock lives in
Redis with a time limit, so a worker that dies never blocks a conversation for long. If Redis cannot give a lock the
work goes ahead without one (a rare double handling is better than a lost message); the caller is told through the
`held` value."""

import contextlib

import frappe


def _key(name):
	return f"{getattr(frappe.local, 'site', 'site')}|waba_lock|{name}"


@contextlib.contextmanager
def conversation(name, timeout=30, wait=10):
	"""`with locks.conversation(name) as held:`; `held` is True when the lock was taken."""
	lock, held = None, False
	try:
		cache = frappe.cache() if callable(frappe.cache) else frappe.cache
		lock = cache.lock(_key(name), timeout=timeout)
		held = bool(lock.acquire(blocking=True, blocking_timeout=wait))
	except Exception:
		lock, held = None, False
	try:
		yield held
	finally:
		if held and lock is not None:
			try:
				lock.release()
			except Exception:
				pass
