"""Names shared across the app. Kept in one place so a path or a label is never typed twice."""

# Public webhook endpoint (guest). One endpoint per Meta app: the `app` query value is the app's webhook key.
WEBHOOK_PATH = "/api/method/waba.api.webhook.receive"

ROLE_ADMIN = "Waba Admin"
ROLE_SUPERVISOR = "Waba Supervisor"
ROLE_AGENT = "Waba Agent"
ROLE_CAMPAIGN = "Waba Campaign Manager"  # may build Sets and run campaigns; given by a Waba Admin

NUMBER_TYPE_SHARED = "Shared"
NUMBER_TYPE_PERSONAL = "Personal"

AGENT_ROLE_AGENT = "Agent"
AGENT_ROLE_SUPERVISOR = "Supervisor"

GRAPH_HOST = "https://graph.facebook.com"
DEFAULT_API_VERSION = "v25.0"
