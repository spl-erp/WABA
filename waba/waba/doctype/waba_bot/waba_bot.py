"""A bot: a drawn graph of blocks that answers customers on one number. Customers get only the PUBLISHED version, so
editing the draft never changes a live bot. The graph is checked, in plain words, when it is published (waba.rules.bot)."""

import json

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime

from waba.rules import bot as rules


def parse(text):
	"""The graph held in a JSON field, or None when it is empty or not valid JSON."""
	if not text or not str(text).strip():
		return None
	try:
		value = json.loads(text)
	except ValueError:
		return None
	return value if isinstance(value, dict) else None


class WabaBot(Document):
	def validate(self):
		if self.graph_json and parse(self.graph_json) is None:
			frappe.throw(_("The bot design is not valid. Open the builder to fix it, or clear it to start again."))
		self.derive_trigger()
		if self.enabled:
			self.check_can_run()

	def derive_trigger(self):
		"""What starts the bot is set in its Trigger block; it is copied here so lists and the one-bot-per-trigger rule can read it."""
		graph = parse(self.published_json) or parse(self.graph_json) or {}
		starts = rules.starts_of(rules.trigger_of(graph))
		self.trigger = (starts[0].get("mode") if starts else None) or None  # the first start; a bot may have several (see trigger_modes)
		words = [str(x.get("keywords") or "").strip() for x in starts if x.get("mode") == rules.KEYWORD]
		self.trigger_keywords = ", ".join(w for w in words if w) or None

	def check_can_run(self):
		if not self.published_json:
			frappe.throw(_("Publish the bot before switching it on."))
		number = frappe.db.get_value("Waba Number", self.waba_number, ["enabled", "purpose_conversations"], as_dict=True)
		if not number or not number.enabled or not number.purpose_conversations:
			frappe.throw(_("The number {0} must be switched on for conversations before a bot can answer on it.").format(self.waba_number))
		mine = rules.trigger_modes(parse(self.published_json) or parse(self.graph_json) or {}) - {rules.KEYWORD}
		for other in frappe.get_all("Waba Bot", filters={"enabled": 1, "waba_number": self.waba_number, "name": ["!=", self.name]}, fields=["name", "published_json", "graph_json"]):
			shared = mine & (rules.trigger_modes(parse(other.published_json) or parse(other.graph_json) or {}) - {rules.KEYWORD})
			if shared:
				mode = sorted(shared)[0]
				frappe.throw(_("{0} already answers on this number with the same start ({1}). Switch it off first, or choose another start.").format(other.name, rules.TRIGGER_LABELS.get(mode, mode)))

	def publish(self):
		"""Check the draft and make it the live version. Raises with every problem listed."""
		graph = parse(self.graph_json)
		from waba import bot as engine  # imported here: the engine imports the send code

		problems = rules.validate_graph(graph, engine.extras_on())
		if problems:
			frappe.throw("<br>".join(_(p) for p in problems), title=_("The bot cannot be published yet"))
		self.published_json = json.dumps(graph, ensure_ascii=False)
		self.version = (self.version or 0) + 1
		self.published_by = frappe.session.user
		self.published_on = now_datetime()
		self.save()
		return self.version

	def published_graph(self):
		return parse(self.published_json)
