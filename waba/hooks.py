app_name = "waba"
app_title = "Waba"
app_publisher = "erp@splashjetink.com"
app_description = "End-to-end WhatsApp Cloud API integration for Frappe/ERPNext: accounts, numbers, agents, shared inbox, templates and CRM-linked conversations."
app_email = "erp@splashjetink.com"
app_license = "mit"

# Apps
# ------------------

# required_apps = []

# Each item in the list will be shown as an app in the apps page
# add_to_apps_screen = [
# 	{
# 		"name": "waba",
# 		"logo": "/assets/waba/logo.png",
# 		"title": "Waba",
# 		"route": "/waba",
# 		"has_permission": "waba.api.permission.has_app_permission",
# 	}
# ]

# The dock, the rail down the left of the desk, is a document rather than a hook. Author it in
# Manage Dock on a developer-mode site and press Export to App, and it is written to
# `waba/dock/waba/waba.json` for git to carry. An app that ships none has no
# rail: its sidebar gets a switcher in the header instead.
#
# A companion app, one that extends a host app rather than standing on its own, says so with
# `mount_on` on that same record, and its entries are appended to the host's rail. Mounting keeps
# the companion off the apps screen, so it takes precedence over any add_to_apps_screen above.

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/waba/css/waba.css"
# app_include_js = "/assets/waba/js/waba.js"

# include js, css files in header of web template
# web_include_css = "/assets/waba/css/waba.css"
# web_include_js = "/assets/waba/js/waba.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "waba/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
# doctype_js = {"doctype" : "public/js/doctype.js"}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_kanban_js = {"doctype" : "public/js/doctype_kanban.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "waba/public/icons.svg"

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# automatically load and sync documents of this doctype from downstream apps
# importable_doctypes = [doctype_1]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "waba.utils.jinja_methods",
# 	"filters": "waba.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "waba.install.before_install"
# after_install = "waba.install.after_install"

# Uninstallation
# ------------

# before_uninstall = "waba.uninstall.before_uninstall"
# after_uninstall = "waba.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "waba.utils.before_app_install"
# after_app_install = "waba.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "waba.utils.before_app_uninstall"
# after_app_uninstall = "waba.utils.after_app_uninstall"

# Build
# ------------------
# To hook into the build process

# after_build = "waba.build.after_build"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "waba.notifications.get_notification_config"

# Awesome Bar
# -----------
# Extra search results: list of dicts with label, description, route, index.
# route: ["List", "ToDo"], "/desk/docs/some/page", or "https://example.com"
# awesomebar_search = ["waba.search.awesomebar_results"]

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
# 	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
# 	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# Document Events
# ---------------
# Hook on document methods and events

# doc_events = {
# 	"*": {
# 		"on_update": "method",
# 		"on_cancel": "method",
# 		"on_trash": "method"
# 	}
# }

# Scheduled Tasks
# ---------------

# scheduler_events = {
# 	"all": [
# 		"waba.tasks.all"
# 	],
# 	"daily": [
# 		"waba.tasks.daily"
# 	],
# 	"hourly": [
# 		"waba.tasks.hourly"
# 	],
# 	"weekly": [
# 		"waba.tasks.weekly"
# 	],
# 	"monthly": [
# 		"waba.tasks.monthly"
# 	],
# }

# Testing
# -------

# before_tests = "waba.install.before_tests"

# Extend DocType Class
# ------------------------------
#
# Specify custom mixins to extend the standard doctype controller.
# extend_doctype_class = {
# 	"Task": "waba.custom.task.CustomTaskMixin"
# }

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "waba.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "waba.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["waba.utils.before_request"]
# after_request = ["waba.utils.after_request"]

# Job Events
# ----------
# before_job = ["waba.utils.before_job"]
# after_job = ["waba.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"waba.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
# export_python_type_annotations = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }

# Translation
# ------------
# List of apps whose translatable strings should be excluded from this app's translations.
# ignore_translatable_strings_from = []

before_install = "waba.setup.install.ensure_roles"
after_install = "waba.setup.install.execute"
# the inbox page names the roles, so they must exist before the pages and doctypes are synced
before_migrate = ["waba.setup.install.ensure_roles"]
after_migrate = ["waba.setup.install.execute"]

scheduler_events = {
	"cron": {
		"*/2 * * * *": [
			"waba.api.webhook.retry_waiting",
			"waba.assignment.assign_waiting",
			"waba.assignment.alert_unanswered",
		],
	},
}

# new-message alerts on every Desk page (a loader that does nothing for users without a Waba role)
app_include_js = ["/assets/waba/js/waba_alerts.js"]

# tells the browser whether this user gets the new-message alerts (waba.boot)
boot_session = "waba.boot.boot_session"

# who may see which conversation (the team tree): applies to Desk lists, reports and links as well as the inbox
permission_query_conditions = {
	"Waba Conversation": "waba.permissions.conversation_query_conditions",
	"Waba Message": "waba.permissions.message_query_conditions",
	"Waba Note": "waba.permissions.note_query_conditions",
	"Waba Quick Reply": "waba.permissions.quick_reply_query_conditions",
}
has_permission = {
	"Waba Conversation": "waba.permissions.conversation_has_permission",
	"Waba Message": "waba.permissions.message_has_permission",
	"Waba Note": "waba.permissions.note_has_permission",
}

# the Lead, Contact and Customer forms get a WhatsApp button and a WhatsApp section (added to, never replacing, any other script)
doctype_js = {
	"Lead": ["public/js/waba_party.js"],
	"Contact": ["public/js/waba_party.js"],
	"Customer": ["public/js/waba_party.js"],
}
