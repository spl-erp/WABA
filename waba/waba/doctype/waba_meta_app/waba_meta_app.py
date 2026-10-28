"""One Meta app. Meta allows ONE webhook endpoint and ONE app secret per app, so those live here; every
account that the app is subscribed to is told apart by its WABA id inside each event."""

import secrets

import frappe
from frappe import _
from frappe.model.document import Document

from waba.constants import WEBHOOK_PATH
from waba.rules.config_validation import is_numeric_id


class WabaMetaApp(Document):
	def before_insert(self):
		self._ensure_webhook_key()

	def validate(self):
		if self.app_id and not is_numeric_id(self.app_id):
			frappe.throw(_("The Meta App ID is the number shown in the app dashboard (digits only)."))
		self._ensure_webhook_key()
		self.callback_url = f"{frappe.utils.get_url()}{WEBHOOK_PATH}?app={self.webhook_key}"

	def _ensure_webhook_key(self):
		if not self.webhook_key:
			self.webhook_key = secrets.token_urlsafe(24)
