"""Added to the page data of every Desk session: does this user get the inbox alerts? The browser loader only
looks at this flag, so who gets alerts is decided here (and tested here), never in a cached browser file."""

import frappe

# the people who may use the inbox (see waba.api.send.SENDERS) plus the agent role that arrives with routing
ALERT_ROLES = frozenset({"Waba Admin", "Waba Supervisor", "Waba Agent", "System Manager"})


def wants_alerts(user, roles):
	return user != "Guest" and bool(ALERT_ROLES & set(roles))


def boot_session(bootinfo):
	bootinfo.waba_alerts = wants_alerts(frappe.session.user, frappe.get_roles())
