"""The calls the browser phone makes. Every one is checked on the server: the person must hold a Waba role and must be one of the people the
call rang (an admin may end any call). The browser never talks to Meta; it hands its WebRTC answer to `answer` and Waba relays it.

  offer(call)           Meta's SDP offer of a call that is ringing for me
  answer(call, sdp)     take the call (first one wins): pre_accept + accept at Meta, with the browser's answer
  decline(call)         I do not take it (the call keeps ringing for the others; rejected when everyone declined)
  hangup(call)          end a call I have
  my_calls()            calls ringing for me now (a page opened after the ring started still shows the popup)
  can_call(conversation)         may I call this customer now (asks Meta: the customer's permission lives there)
  request_permission(conversation)   ask the customer to allow calls (a message, only inside the 24-hour window)
  place(conversation, sdp)       place a call with the browser's WebRTC offer
  answer_sdp(call)               Meta's SDP answer to a call I placed (None until it arrives)
"""

import frappe
from frappe import _

from waba import calls, teams
from waba.rules import calls as rules


def _check():
	if not teams.has_waba_role(frappe.session.user):
		frappe.throw(_("Not permitted."), frappe.PermissionError)
	if not calls.has_fields() or not calls.enabled():
		frappe.throw(_("WhatsApp calls are not switched on."))


@frappe.whitelist(methods=["POST"])
def offer(call: str):
	_check()
	return calls.offer_for(call, frappe.session.user)


@frappe.whitelist(methods=["POST"])
def answer(call: str, sdp: str):
	_check()
	return calls.answer(call, sdp, frappe.session.user)


@frappe.whitelist(methods=["POST"])
def decline(call: str):
	_check()
	return calls.decline(call, frappe.session.user)


@frappe.whitelist(methods=["POST"])
def hangup(call: str):
	_check()
	return calls.hangup(call, frappe.session.user)


@frappe.whitelist()
def my_calls():
	"""Calls that are ringing for the current person right now: [{call, phone, name, party_doctype, party, conversation, seconds_left}]."""
	if not calls.has_fields() or not teams.has_waba_role(frappe.session.user) or not calls.enabled():
		return []
	out = []
	for c in frappe.get_all(
		"Waba Call",
		filters={"status": rules.RINGING, "ring_recipients": ["like", f"%{frappe.session.user}%"]},
		fields=["name", "caller_phone", "caller_name", "party_doctype", "party", "conversation", "ring_recipients", "started_at", "waba_number"],
		order_by="creation desc",
		limit_page_length=5,
	):
		if frappe.session.user not in set(filter(None, (c.ring_recipients or "").split(", "))):
			continue
		left = calls._ring_seconds() - int((frappe.utils.now_datetime() - c.started_at).total_seconds()) if c.started_at else 0
		if left > 0:
			label = rules.caller_label(c.caller_name, calls._party_name(c.party_doctype, c.party), c.caller_phone)
			out.append({"call": c.name, "phone": c.caller_phone, "name": c.caller_name, "label": label, "party_doctype": c.party_doctype, "party": c.party, "conversation": c.conversation, "number": c.waba_number, "seconds_left": left})
	return out


@frappe.whitelist()
def can_call(conversation: str):
	_check()
	return calls.can_call(conversation, frappe.session.user)


@frappe.whitelist(methods=["POST"])
def request_permission(conversation: str, text: str | None = None):
	_check()
	return calls.request_permission(conversation, frappe.session.user, text)


@frappe.whitelist(methods=["POST"])
def place(conversation: str, sdp: str):
	_check()
	return calls.place(conversation, sdp, frappe.session.user)


@frappe.whitelist(methods=["POST"])
def answer_sdp(call: str):
	_check()
	return calls.answer_for(call, frappe.session.user)
