"""Ready-made bots a Waba Admin can start from. Pure data: no database, no Frappe.

Every starter is a graph the builder can open and change, and every one passes `rules.bot.validate_graph`. The first one
(Welcome + menu) is always offered; the others are preview features and appear only while Waba Settings > "Bot builder:
preview blocks" is switched on (`catalog(extras)`)."""

from waba.rules import bot as rules

WELCOME_MENU = "welcome_menu"
AFTER_HOURS = "after_hours"
MENU_FAQ = "menu_faq"
ENQUIRY = "enquiry"
ORDER_STATUS = "order_status"


def _n(node_id, kind, x, y, data):
	return {"id": node_id, "type": kind, "position": {"x": x, "y": y}, "data": data}


def _e(i, source, target, handle=rules.OUT):
	return {"id": f"e{i}", "source": source, "sourceHandle": handle, "target": target}


def after_hours():
	"""Inside business hours: a short hello and the chat goes to the team. Outside: say so, take the customer's message as an
	internal note for the morning, and end."""
	nodes = [
		_n("trigger", rules.TRIGGER, 40, 200, {"mode": rules.NEW_CHAT}),
		_n("hours", rules.CONDITION, 320, 200, {"kind": "working_hours"}),
		_n("open", rules.MESSAGE, 620, 60, {"text": "Hello {{customer_name}}! Thank you for contacting {{number_name}}. Our team will reply shortly."}),
		_n("to_team", rules.HANDOVER, 920, 60, {"text": ""}),
		_n("closed", rules.MESSAGE, 620, 340, {"text": "Hello {{customer_name}}! We are closed right now and will reply when we reopen."}),
		_n("ask", rules.ASK, 920, 340, {"text": "Please write your message and we will get back to you.", "var": "message", "validate": "text", "retry_text": "Sorry, please write your message again."}),
		_n("note", rules.NOTE, 1220, 340, {"text": "After-hours message from {{customer_name}} ({{customer_phone}}): {{message}}"}),
		_n("bye", rules.END, 1520, 340, {"text": "Thank you. We have your message and will reply when we reopen."}),
	]
	edges = [
		_e(1, "trigger", "hours"),
		_e(2, "hours", "open", rules.YES),
		_e(3, "hours", "closed", rules.NO),
		_e(4, "open", "to_team"),
		_e(5, "closed", "ask"),
		_e(6, "ask", "note"),
		_e(7, "note", "bye"),
	]
	return {"nodes": nodes, "edges": edges}


def menu_faq():
	"""A keyword (menu, help) opens a list of common questions. The answers are samples to edit."""
	rows = [{"id": "delivery", "title": "Delivery time", "description": ""}, {"id": "payment", "title": "Payment terms", "description": ""}, {"id": "person", "title": "Talk to a person", "description": ""}]
	nodes = [
		_n("trigger", rules.TRIGGER, 40, 160, {"mode": rules.KEYWORD, "keywords": "menu, help", "match": rules.CONTAINS}),
		_n("list", rules.LIST, 320, 160, {"text": "What would you like to know?", "button_text": "Choose", "rows": rows}),
		_n("a_delivery", rules.MESSAGE, 640, 20, {"text": "Edit this answer: most orders are delivered in 3 to 5 working days."}),
		_n("a_payment", rules.MESSAGE, 640, 200, {"text": "Edit this answer: payment is due within 30 days of the invoice."}),
		_n("to_person", rules.HANDOVER, 640, 380, {"text": "Connecting you with one of our team. Someone will reply shortly."}),
		_n("end", rules.END, 960, 110, {"text": "Anything else? Send \"menu\" at any time."}),
	]
	edges = [
		_e(1, "trigger", "list"),
		_e(2, "list", "a_delivery", "delivery"),
		_e(3, "list", "a_payment", "payment"),
		_e(4, "list", "to_person", "person"),
		_e(5, "a_delivery", "end"),
		_e(6, "a_payment", "end"),
	]
	return {"nodes": nodes, "edges": edges}


def enquiry():
	"""Asks name, need and city, saves the answers as an internal note, and hands the chat to the team. No Lead is created."""
	nodes = [
		_n("trigger", rules.TRIGGER, 40, 120, {"mode": rules.NEW_CHAT}),
		_n("hello", rules.MESSAGE, 300, 120, {"text": "Hello {{customer_name}}! Thank you for contacting {{number_name}}. A few quick questions so we can help you better."}),
		_n("q_name", rules.ASK, 580, 120, {"text": "What is your name?", "var": "name", "validate": "text", "retry_text": "Sorry, please tell us your name."}),
		_n("q_need", rules.ASK, 860, 120, {"text": "What are you looking for?", "var": "need", "validate": "text", "retry_text": "Sorry, please tell us what you need."}),
		_n("q_city", rules.ASK, 1140, 120, {"text": "Which city are you in?", "var": "city", "validate": "text", "retry_text": "Sorry, please tell us your city."}),
		_n("note", rules.NOTE, 1420, 120, {"text": "Enquiry from {{customer_phone}}: name {{name}}, looking for {{need}}, city {{city}}."}),
		_n("done", rules.HANDOVER, 1700, 120, {"text": "Thank you {{name}}. Our team will contact you shortly."}),
	]
	edges = [_e(1, "trigger", "hello"), _e(2, "hello", "q_name"), _e(3, "q_name", "q_need"), _e(4, "q_need", "q_city"), _e(5, "q_city", "note"), _e(6, "note", "done")]
	return {"nodes": nodes, "edges": edges}


def order_status():
	"""A keyword (status, my order) tells the customer the status of their own latest Sales Order."""
	nodes = [
		_n("trigger", rules.TRIGGER, 40, 160, {"mode": rules.KEYWORD, "keywords": "status, order status, my order", "match": rules.CONTAINS}),
		_n("lookup", rules.STATUS_LOOKUP, 320, 160, {"doctype": "Sales Order", "text": "Your order {{doc_name}} dated {{doc_date}} is {{doc_status}}. Total: {{doc_total}}."}),
		_n("done", rules.END, 660, 60, {"text": "Anything else? Reply \"agent\" to talk to a person."}),
		_n("missing", rules.MESSAGE, 660, 260, {"text": "We could not find an order for this number."}),
		_n("to_person", rules.HANDOVER, 940, 260, {"text": "Connecting you with one of our team. Someone will reply shortly."}),
	]
	edges = [_e(1, "trigger", "lookup"), _e(2, "lookup", "done", rules.FOUND), _e(3, "lookup", "missing", rules.NONE), _e(4, "missing", "to_person")]
	return {"nodes": nodes, "edges": edges}


STARTERS = {
	WELCOME_MENU: {"title": "Welcome + menu", "description": "Greets a new chat by name and offers Sales, Accounts or Talk to a person.", "preview": False},
	AFTER_HOURS: {"title": "After-hours reply", "description": "Inside business hours a short hello; outside them, says you are closed and keeps the customer's message as a note for the morning.", "preview": True},
	MENU_FAQ: {"title": "Menu and FAQ", "description": "The words menu or help open a list of common questions with answers you edit.", "preview": True},
	ENQUIRY: {"title": "Enquiry capture", "description": "Asks name, need and city, saves them as an internal note, then hands the chat to your team.", "preview": True},
	ORDER_STATUS: {"title": "Order status", "description": "The words status or my order tell the customer where their own latest order stands.", "preview": True},
}


def catalog(extras):
	"""The starters on offer: all of them while preview features are on, otherwise only the first."""
	return [{"key": key, "title": s["title"], "description": s["description"], "preview": s["preview"]} for key, s in STARTERS.items() if extras or not s["preview"]]


def build(key, sales_team=None, accounts_team=None):
	"""The starter's graph, or None for an unknown key."""
	if key == WELCOME_MENU:
		return rules.starter_graph(sales_team, accounts_team)
	return {AFTER_HOURS: after_hours, MENU_FAQ: menu_faq, ENQUIRY: enquiry, ORDER_STATUS: order_status}.get(key, lambda: None)()
