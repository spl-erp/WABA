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
	bootinfo.waba_extra_blocks = int(bool(frappe.db.get_single_value("Waba Settings", "bot_extra_blocks"))) if bootinfo.waba_alerts else 0  # the bot builder's hidden preview blocks (off until released)
	if bootinfo.waba_alerts:
		try:  # the first value of the sidebar count, so it does not flash in late; never blocks a login
			from waba.api import inbox

			bootinfo.waba_unread = int(inbox.unread_total() or 0)
		except Exception:
			bootinfo.waba_unread = 0
