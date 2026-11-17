"""WhatsApp bots, the database side. The decisions are in waba.rules.bot (pure); this module gathers the facts, sends, and keeps
the customer's place.

  on_inbound      called for every customer message (inside the webhook job, after STOP / START, before routing). It only
                  DECIDES, cheaply: when a bot should act it creates the Active session (so the routing that follows leaves the
                  chat alone) and queues `advance`. No call to Meta happens here.
  advance         the background job: under the conversation's lock, re-checks every guard, walks the bot for this message,
                  writes the log, sends what the bot says (as origin Auto-reply, nobody recorded as the sender) and, when the
                  bot is over, gives the chat to the right people through the normal routing (or a named team)
  stop            a person took over (replied, was assigned, transferred it): the bot ends quietly, nothing is routed
  expire_sessions every two minutes: a customer who went quiet mid-bot is released to the normal routing

Nothing runs unless Bots are switched on in Waba Settings, the bot is enabled and published, and the number allows
conversations. A chat is never stranded: whenever a session ends for any reason except "a person has it", the normal
routing runs at once.
"""

import json

import frappe
from frappe import _
from frappe.utils import add_to_date, now_datetime

from waba import assignment, bot_records, locks, notify, templating
from waba.api import send
from waba.rules import bot as rules
from waba.rules import hours as rules_hours
from waba.rules import notify as rules_notify
from waba.rules import purposes

BOT = "Waba Bot"
SESSION = "Waba Bot Session"
LOG = "Waba Bot Log"
_CLASH = (frappe.DuplicateEntryError, frappe.UniqueValidationError)
EXPIRE_LIMIT = 200
SESSION_FIELDS = ["name", "bot", "current_node", "variables", "retries", "messages_sent", "timeouts"]


def _commit():
	if not frappe.flags.get("waba_no_commit"):
		frappe.db.commit()  # nosemgrep


def switched_on():
	return bool(frappe.db.get_single_value("Waba Settings", "bots_enabled"))


def _parse(text):
	try:
		value = json.loads(text) if text else None
	except ValueError:
		return None
	return value if isinstance(value, dict) else None


def _active(conversation):
	return frappe.db.get_value(SESSION, {"conversation": conversation, "status": rules.ACTIVE}, "name")


# ------------------------------------------------------------------------------------------------ the inbound hook


def on_inbound(conversation, message):
	"""Decide whether a bot acts on this customer message. `conversation` is the (already updated) Waba Conversation,
	`message` the name of the stored Waba Message. Cheap and never sends."""
	if not switched_on():
		return
	session = _active(conversation.name)
	if session:
		if conversation.assigned_to:
			stop(session, rules.STOPPED, _("A person has taken the chat."), conversation.name)
			return
		_enqueue(conversation.name, message)
		return
	bots = frappe.get_all(
		BOT,
		filters={"enabled": 1, "waba_number": conversation.waba_number, "published_json": ["is", "set"]},
		fields=["name", "published_json", "cooldown_hours"],
		order_by="creation asc",
	)
	if not bots:
		return
	number = frappe.db.get_value("Waba Number", conversation.waba_number, ["enabled", "receive_only", "purpose_conversations"], as_dict=True) or {}
	text = frappe.db.get_value("Waba Message", message, "body") or ""
	first = frappe.db.count("Waba Message", {"conversation": conversation.name, "direction": "In"}) <= 1
	last_ended = frappe.db.get_value(SESSION, {"conversation": conversation.name, "status": ["!=", rules.ACTIVE]}, "ended_on", order_by="ended_on desc")
	now = now_datetime()
	test_ok = rules_notify.in_test_list(conversation.customer_phone, frappe.db.get_single_value("Waba Settings", "test_phones"))
	candidates, skipped, start_of = [], [], {}
	for b in bots:
		trigger = rules.trigger_of(_parse(b.published_json) or {})
		start = rules.match_start(trigger, first_message=first, text=text)
		if not start:
			continue
		held = rules.hold_reason(
			switch_on=True,
			published=True,
			opted_out=bool(conversation.opted_out),
			assigned=bool(conversation.assigned_to),
			receive_only=bool(number.get("receive_only")),
			number_ok=bool(number.get("enabled") and number.get("purpose_conversations")),
			test_ok=test_ok,
			cooling_down=rules.is_cooling_down(last_ended, now, b.cooldown_hours if b.cooldown_hours is not None else rules.DEFAULT_COOLDOWN_HOURS),
		)
		if held:
			skipped.append((b.name, held[1]))
		else:
			candidates.append((b.name, start.get("mode")))
			start_of[b.name] = start["id"]
	chosen = rules.pick_bot(candidates)
	if not chosen:
		if skipped:  # the message matched a bot, but a guard held it back: say so in the chat, so nobody has to guess why it stayed silent
			assignment.add_event(conversation.name, _("Bot {0} did not answer: {1}").format(skipped[0][0], skipped[0][1]))
		return
	try:
		frappe.get_doc(
			{
				"doctype": SESSION,
				"bot": chosen,
				"conversation": conversation.name,
				"status": rules.ACTIVE,
				"started_on": now,
				"last_activity": now,
				"active_key": conversation.name,
				"variables": json.dumps({"_start": start_of[chosen]}),  # which of the bot's starts the customer hit
			}
		).insert(ignore_permissions=True)
	except _CLASH:
		return  # another worker started it a moment ago
	assignment.add_event(conversation.name, _("Bot {0} started.").format(chosen))
	assignment.notify(conversation, "bot")
	_enqueue(conversation.name, message)


def _enqueue(conversation, message):
	frappe.enqueue("waba.bot.advance", queue="short", conversation=conversation, message=message, enqueue_after_commit=True)


# ------------------------------------------------------------------------------------------------ the job


def advance(conversation, message):
	"""Walk the bot for one customer message and send its answer."""
	with notify.as_system():
		with locks.conversation(conversation):
			_advance(conversation, message)
		_commit()


def extras_on():
	"""Waba Settings > "Bot builder: preview blocks". Off until the preview features are released."""
	return bool(frappe.db.get_single_value("Waba Settings", "bot_extra_blocks"))


def _needs(graph):
	"""What the graph's blocks need looked up before it is walked: the document types, and the library files."""
	docs, files = set(), set()
	for n in graph.get("nodes") or []:
		d = n.get("data") or {}
		if n.get("type") == rules.STATUS_LOOKUP and d.get("doctype"):
			docs.add(d["doctype"])
		if n.get("type") == rules.SEND_FILE:
			if d.get("source") == "library" and d.get("shared_file"):
				files.add(d["shared_file"])
			elif d.get("source") == "erp_pdf" and d.get("doctype"):
				docs.add(d["doctype"])
	return sorted(docs), sorted(files)


def _facts(conv, number, graph=None):
	now = now_datetime()
	open_now = rules_hours.is_within_hours(
		now,
		rules_hours.as_time(number.get("hours_start")),
		rules_hours.as_time(number.get("hours_end")),
		number.get("working_days"),
		bool(number.get("hours_enabled")),
	)
	ctx = templating.context_for(conv.party_doctype, conv.party, conv.customer_label, conv.profile_name)
	facts = {
		"customer_name": ctx.get("customer_name") or "",
		"customer_phone": conv.customer_phone or "",
		"number_name": number.get("display_name") or number.get("display_number") or "",
		"open_now": open_now,
		"matched": bool(conv.party),
	}
	docs, files = _needs(graph or {})
	if docs:
		facts["docs"] = bot_records.latest_documents(conv, docs)  # only this chat's own documents (see waba.bot_records)
	if files:
		facts["files"] = bot_records.files_status(files)
	return facts


def _advance(conversation, message):
	conv = frappe.get_doc("Waba Conversation", conversation)
	session = frappe.db.get_value(SESSION, {"conversation": conversation, "status": rules.ACTIVE}, SESSION_FIELDS, as_dict=True)
	if not session or frappe.db.exists(LOG, {"session": session.name, "message": message}):
		return  # nothing to do, or this message was already handled (a retried job)
	if conv.assigned_to:
		return stop(session.name, rules.STOPPED, _("A person has taken the chat."), conversation)
	if conv.opted_out:
		return stop(session.name, rules.STOPPED, _("The customer asked not to be messaged."), conversation)
	msg = frappe.db.get_value("Waba Message", message, ["body", "interactive_id"], as_dict=True)
	if not msg:
		return
	_step(conv, session, message, "reply", {"text": msg.body or "", "interactive_id": msg.interactive_id})


def _step(conv, session, key, event, reply):
	"""Walk the bot once (for a customer's message, or because a customer stayed silent) and perform the result.
	`key` is what makes the step run once: the message name, or timeout-<session>-<n>."""
	conversation = conv.name
	bot = frappe.db.get_value(BOT, session.bot, ["name", "enabled", "published_json", "stuck_limit", "handover_words"], as_dict=True)
	graph = _parse(bot.published_json) if bot else None
	if not switched_on() or not bot or not bot.enabled or not graph:
		return finish(session, conv, rules.HANDED_OVER, _("the bot was switched off"))
	if rules.uses_extras(graph) and not extras_on():  # published while the preview features were on, then they were switched off
		return finish(session, conv, rules.HANDED_OVER, _("the bot uses preview blocks, which are switched off"))
	number = frappe.db.get_value("Waba Number", conv.waba_number, ["display_name", "display_number", "hours_enabled", "hours_start", "hours_end", "working_days"], as_dict=True) or {}
	state = {"node": session.current_node or None, "vars": _parse(session.variables) or {}, "retries": session.retries or 0}
	result = rules.run(
		graph,
		state,
		_facts(conv, number, graph),
		reply if state["node"] or event == "timeout" else None,
		human_words=bot.handover_words or rules.DEFAULT_HUMAN_WORDS,
		stuck_limit=bot.stuck_limit or rules.DEFAULT_STUCK_LIMIT,
		event=event,
	)
	speaking = [a for a in result.actions if a["do"] != "note"]
	if rules.over_cap(session.messages_sent or 0, len(speaking)):
		result.actions, result.ended, result.kind, result.reason, result.team = [], rules.HANDED_OVER, "cap", "the bot sent as many messages as it may", None
	for entry in result.log:
		frappe.get_doc({"doctype": LOG, "session": session.name, "bot": bot.name, "conversation": conversation, "message": key, "node_id": entry["node"], "node_type": entry["type"], "customer_input": entry["input"], "result": entry["result"]}).insert(ignore_permissions=True)
	_commit()  # the decision is recorded before anything is sent: a retried job will not run it again
	sent, failure = _perform(conv, bot.name, result.actions)
	if failure:
		result.ended, result.kind, result.team = rules.HANDED_OVER, "send_failed", None
		result.reason = _("a message could not be sent ({0})").format(failure)
		result.state["node"] = None
	waiting_again = bool(result.timeout_minutes) and not result.ended
	frappe.db.set_value(
		SESSION,
		session.name,
		{
			"current_node": result.state["node"],
			"variables": json.dumps(result.state["vars"], ensure_ascii=False),
			"retries": result.state["retries"],
			"messages_sent": (session.messages_sent or 0) + sent,
			"last_activity": now_datetime(),
			"timeout_at": add_to_date(now_datetime(), minutes=result.timeout_minutes) if waiting_again else None,
			"timeouts": (session.timeouts or 0) + (1 if event == "timeout" else 0),
		},
		update_modified=False,
	)
	if result.ended:
		finish(session, conv, result.ended, result.reason, result.team, result.agent)
	_commit()


def _perform(conv, bot_name, actions):
	"""Send / write what the bot says. Returns (messages sent, the first failure in words or None)."""
	sent = 0
	for a in actions:
		try:
			if a["do"] == "note":
				assignment.add_note(conv.name, a["text"], user="Administrator")
				continue
			extra = {"bot": bot_name}
			if a["do"] == "text":
				outcome = send.send_automatic_text(conv.name, a["body"], purposes.AUTO_REPLY, extra)
			elif a["do"] == "buttons":
				outcome = send.send_automatic_interactive(conv.name, "buttons", a["body"], a["buttons"], None, purposes.AUTO_REPLY, extra)
			elif a["do"] == "list":
				outcome = send.send_automatic_interactive(conv.name, "list", a["body"], a["rows"], a["button"], purposes.AUTO_REPLY, extra)
			elif a["do"] == "cta":
				outcome = send.send_automatic_cta(conv.name, a["body"], a["button"], a["url"], purposes.AUTO_REPLY, extra)
			elif a["do"] in ("file", "pdf"):
				outcome = _send_document(conv, a, extra)
			else:
				continue
		except (frappe.ValidationError, frappe.PermissionError) as e:
			return sent, frappe.utils.strip_html_tags(str(e))[:200]
		if not outcome.get("ok"):
			return sent, str(outcome.get("error") or _("Meta refused it"))[:200]
		sent += 1
	return sent, None


def _send_document(conv, action, extra):
	"""A library file or the PDF of one of the customer's own documents, sent as the bot (nobody recorded as the sender)."""
	if action["do"] == "file":
		found = bot_records.library_file(action["file"])
		if not found:
			return {"ok": False, "error": _("the library file is no longer there")}
		content, filename = found
		doctype = name = None
	else:
		doctype, name = action["doctype"], action["name"]
		content = bot_records.pdf_of(doctype, name)
		filename = f"{name}.pdf"
		if not content:
			return {"ok": False, "error": _("the document could not be prepared")}
	outcome = send._send_media(conv.name, content, filename, send._mime_of(filename), action.get("caption") or "", None, purposes.AUTO_REPLY, person=False, extra=extra)
	if outcome.get("ok") and doctype:
		send._log_shared_document(conv.name, doctype, name, who=_("the bot {0}").format(extra.get("bot")))
	return outcome


# ------------------------------------------------------------------------------------------------ ending


def finish(session, conv, status, reason, team=None, agent=None):
	"""The bot is over: record it and give the chat to the right people. A named team gets it (least busy available agent);
	otherwise the number's normal routing takes it. `session` is the session row (or its name)."""
	name = session if isinstance(session, str) else session.name
	bot = frappe.db.get_value(SESSION, name, "bot")
	frappe.db.set_value(SESSION, name, {"status": status, "ended_on": now_datetime(), "ended_reason": reason, "active_key": None, "current_node": None}, update_modified=False)
	assignment.add_event(conv.name, _("Bot {0} ended: {1}.").format(bot, reason))
	conv.reload()
	if team:
		assignment.assign_to_team(conv, team, agent)
	else:
		assignment.assign(conv)
	assignment.notify(conv, "message")


def stop(session, status, reason, conversation):
	"""A person has the chat: end the session and route nothing."""
	name = session if isinstance(session, str) else session.name
	bot = frappe.db.get_value(SESSION, name, "bot")
	frappe.db.set_value(SESSION, name, {"status": status, "ended_on": now_datetime(), "ended_reason": reason, "active_key": None, "current_node": None}, update_modified=False)
	assignment.add_event(conversation, _("Bot {0} stopped: {1}").format(bot, reason))
	assignment.notify(conversation, "bot")


def active_session(conversation):
	"""The name of the conversation's Active bot session, or None."""
	return _active(conversation if isinstance(conversation, str) else conversation.name)


def take_over(conversation):
	"""The explicit Take over button: end the session as stopped by a person and give the chat to them."""
	on_agent_reply(conversation)


def on_agent_reply(conversation):
	"""A person is sending a message in this chat. If a bot is in the middle of it, the bot stops, and a chat nobody owned
	becomes the replying person's."""
	session = _active(conversation.name)
	if not session:
		return
	stop(session, rules.STOPPED, _("a person replied."), conversation.name)
	if not conversation.assigned_to:
		user = frappe.session.user
		frappe.db.set_value(
			"Waba Conversation",
			conversation.name,
			{"assigned_to": user, "assigned_at": now_datetime(), "assigned_reason": _("took over from the bot"), "assigned_trail": "", "waiting_since": None, "held": 0},
			update_modified=False,
		)
		conversation.reload()
		assignment.add_event(conversation.name, _("{0} took the chat over from the bot.").format(frappe.utils.get_fullname(user)))
		assignment.notify(conversation, "assigned")


def on_phone_reply(conversation):
	"""Someone answered from the WhatsApp Business app (coexistence): an active bot stops. Unlike on_agent_reply the chat is
	not given to anyone (the phone app has no ERP user)."""
	session = _active(conversation.name)
	if session:
		stop(session, rules.STOPPED, _("a person replied from the phone app."), conversation.name)


def on_person_assigned(conversation):
	"""A person was given the chat (a transfer): the bot has nothing left to do."""
	name = conversation if isinstance(conversation, str) else conversation.name
	session = _active(name)
	if session:
		stop(session, rules.STOPPED, _("a person was given the chat."), name)


def fire_timeouts():
	"""Every two minutes (preview feature): a customer who stayed silent at a block with a 'no answer' path gets that path once the
	time has passed. At most MAX_TIMEOUTS per session, then the bot hands over."""
	if not switched_on() or not extras_on():
		return 0
	now, done = now_datetime(), 0
	with notify.as_system():
		for s in frappe.get_all(SESSION, filters={"status": rules.ACTIVE, "timeout_at": ["<=", now]}, fields=["name", "conversation"], limit_page_length=EXPIRE_LIMIT):
			with locks.conversation(s.conversation):
				done += _timeout_one(s.name)
		if done:
			_commit()
	return done


def _timeout_one(name):
	session = frappe.db.get_value(SESSION, name, SESSION_FIELDS + ["status", "timeout_at", "conversation"], as_dict=True)
	if not session or session.status != rules.ACTIVE or not session.timeout_at or session.timeout_at > now_datetime() or not session.current_node:
		return 0
	frappe.db.set_value(SESSION, name, "timeout_at", None, update_modified=False)  # claimed: it cannot fire twice
	_commit()
	conv = frappe.get_doc("Waba Conversation", session.conversation)
	if conv.assigned_to:
		stop(name, rules.STOPPED, _("a person has the chat."), conv.name)
	elif conv.opted_out:
		stop(name, rules.STOPPED, _("The customer asked not to be messaged."), conv.name)
	elif (session.timeouts or 0) >= rules.MAX_TIMEOUTS:
		finish(session, conv, rules.HANDED_OVER, _("the customer did not answer"))
	else:
		_step(conv, session, f"timeout-{name}-{(session.timeouts or 0) + 1}", "timeout", None)
	return 1


def expire_sessions():
	"""Every two minutes: a customer who stopped answering is released to the number's normal routing."""
	fire_timeouts()
	if not switched_on():
		return 0
	now = now_datetime()
	done, minutes = 0, {}
	with notify.as_system():
		for s in frappe.get_all(SESSION, filters={"status": rules.ACTIVE}, fields=["name", "conversation", "bot", "last_activity"], limit_page_length=EXPIRE_LIMIT):
			if s.bot not in minutes:
				minutes[s.bot] = frappe.db.get_value(BOT, s.bot, "session_timeout_minutes")
			limit = minutes[s.bot] if minutes[s.bot] is not None else rules.DEFAULT_TIMEOUT_MINUTES
			if not rules.session_expired(s.last_activity, now, limit):
				continue
			with locks.conversation(s.conversation):
				if frappe.db.get_value(SESSION, s.name, "status") != rules.ACTIVE:
					continue
				conv = frappe.get_doc("Waba Conversation", s.conversation)
				if conv.assigned_to:
					stop(s.name, rules.STOPPED, _("a person has the chat."), s.conversation)
				else:
					finish(s, conv, rules.EXPIRED, _("the customer stopped replying"))
			done += 1
	if done:
		_commit()
	return done
