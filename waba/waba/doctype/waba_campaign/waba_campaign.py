"""A campaign: a locked Set, a number, an approved template and a schedule. Everything after Draft is done by buttons
(waba.api.campaigns) and the engine (waba.campaign_engine); the form is locked once the campaign has left Draft."""

import frappe
from frappe import _
from frappe.model.document import Document

from waba.rules import campaign as rules

LOCKED_FIELDS = ("title", "recipient_set", "waba_number", "template", "template_values", "schedule_mode", "start_at", "recurrence", "ends_on", "max_runs", "speed_per_minute", "hours_start", "hours_end")


class WabaCampaign(Document):
	def validate(self):
		if not self.is_new() and self.status != rules.DRAFT and not self.flags.get("from_engine"):
			before = self.get_doc_before_save()
			changed = [f for f in LOCKED_FIELDS if before and self.has_value_changed(f)]
			if changed:
				frappe.throw(_("A campaign that has been submitted cannot be edited. Cancel it and copy it, or use Reschedule."))
		self.check_setup()
		self.check_schedule()

	def check_setup(self):
		number = frappe.db.get_value("Waba Number", self.waba_number, ["enabled", "purpose_campaigns", "account"], as_dict=True) if self.waba_number else None
		if number and not number.purpose_campaigns:
			frappe.throw(_("The number {0} is not switched on for Campaigns. Tick \"Campaigns\" on the number first.").format(self.waba_number))
		if self.template:
			tpl = frappe.db.get_value("Waba Template", self.template, ["status", "category", "account"], as_dict=True)
			if not tpl or tpl.status != "APPROVED":
				frappe.throw(_("The template must be approved by Meta."))
			if (tpl.category or "").upper() not in (rules.MARKETING, rules.UTILITY):
				frappe.throw(_("A campaign can use Marketing or Utility templates only."))
			if number and tpl.account != number.account:
				frappe.throw(_("That template belongs to a different WhatsApp account than the number."))
		if self.recipient_set and not frappe.has_permission("Waba Recipient Set", "read", self.recipient_set):
			frappe.throw(_("You may not use that Set."), frappe.PermissionError)

	def check_schedule(self):
		for field in ("hours_start", "hours_end"):
			value = self.get(field)
			if value not in (None, "") and not 0 <= int(value) <= 23:
				frappe.throw(_("Hours are from 0 to 23."))
		if self.schedule_mode in (rules.LATER, rules.RECURRING) and not self.start_at:
			frappe.throw(_("Choose when the campaign starts."))
		if self.schedule_mode == rules.RECURRING:
			if not self.recurrence:
				frappe.throw(_("Choose how often it repeats: daily, weekly or monthly."))
			if not (self.ends_on or self.max_runs):
				frappe.throw(_("A repeating campaign needs an end: a last date or a number of runs."))

	def on_trash(self):
		if self.status in (rules.RUNNING, rules.SCHEDULED):
			frappe.throw(_("Cancel the campaign before deleting it."))
		frappe.db.delete("Waba Campaign Recipient", {"campaign": self.name})
