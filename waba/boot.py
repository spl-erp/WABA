"""Added to the page data of every Desk session: does this user get the inbox alerts? The browser loader only
looks at this flag, so who gets alerts is decided here (and tested here), never in a cached browser file."""

import frappe

# the people who may use the inbox (see waba.api.send.SENDERS) plus the agent role that arrives with routing
ALERT_ROLES = frozenset({"Waba Admin", "Waba Supervisor", "Waba Agent"})


def wants_alerts(user, roles):
	return user != "Guest" and bool(ALERT_ROLES & set(roles))


def boot_session(bootinfo):
	bootinfo.waba_alerts = wants_alerts(frappe.session.user, frappe.get_roles())
	bootinfo.waba_unread = 0
	bootinfo.waba_calls = call_flags(frappe.session.user)
	bootinfo.waba_extra_blocks = int(bool(frappe.db.get_single_value("Waba Settings", "bot_extra_blocks"))) if bootinfo.waba_alerts else 0  # the bot builder's hidden preview blocks (off until released)
	if bootinfo.waba_alerts:
		try:  # the first value of the sidebar count, so it does not flash in late; never blocks a login
			from waba.api import inbox

			bootinfo.waba_unread = int(inbox.unread_total() or 0)
		except Exception:
			bootinfo.waba_unread = 0


def call_flags(user):
	"""{"enabled", "make", "take"}: is WhatsApp calling switched on, may this person place calls, may they take them. Decided here (and tested
	here), never in a cached browser file. All False before the migrate or for someone without a Waba role."""
	off = {"enabled": 0, "make": 0, "take": 0}
	try:
		from waba import calls, teams

		if not wants_alerts(user, frappe.get_roles(user)) or not calls.enabled():
			return off
		if user == "Administrator" or teams.is_admin(user):
			make = 1 if user == "Administrator" else int(bool(frappe.db.exists("Waba Agent Access", {"user": user, "may_make_calls": 1})))
		else:
			make = int(bool(frappe.db.exists("Waba Agent Access", {"user": user, "may_make_calls": 1})))
		take = int(bool(frappe.db.exists("Waba Agent Access", {"user": user, "may_take_calls": 1})) or teams.is_admin(user) or bool(teams.user_scope(user).lead_numbers))
		from frappe.utils import cint

		return {
			"enabled": 1, "make": make, "take": take,
			"listen_only": int(calls.listen_only_on()),
			"ring_seconds": max(10, cint(frappe.db.get_single_value("Waba Settings", "call_ring_seconds")) or 30),
		}
	except Exception:
		return off
