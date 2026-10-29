# Waba build progress

Status values: Not started, In progress, Accepted. A chunk is Accepted only when the owner says so after the demo.
Plan: 12 chunks, each shown on UAT before the next starts. Sizes are relative (S/M/L), there are no dates.

| # | Chunk | Status | What you can try when it is done | Needs from the owner | Size |
|---|---|---|---|---|---|
| C1 | Setup screens | Verified on UAT (15 checks pass), awaiting owner acceptance | Waba workspace; create Portfolio, Meta App, Account, Number, Agent Access, Routing Rule; validation messages | Docs confirmed in words | S |
| C2 | Connect Meta | Verified on UAT offline (19 checks pass); live Meta test pending |  Webhook URL and verify token; Meta "Verify" succeeds; Test connection, Sync numbers; raw events logged | Meta test app and company test number | M |
| C3 | Conversations (read-only) | Accepted | Messages and Conversations lists; inbound text on the right record or in Triage; window state | Rule for unknown senders | M |
| C4 | Send and templates | Accepted (real Meta test postponed by the owner) | Send inside the window; sent/delivered/read ticks; failures in plain words; Sync templates | None | M |
| C5 | The Inbox | Verified on UAT (31 checks + browser walkthrough), awaiting acceptance | The real inbox page with live updates, reply box, window indicator, template picker | None | L |
| C5b | Chat screen redesign and extras | Built and checked on UAT in light/dark and desktop/tablet/phone; awaiting owner acceptance | New look as the owner shows it; new-message alerts anywhere in the ERP (notice with Open button, tone, unread count in the tab title, optional desktop notification); older messages, clickable links, reply shows the message it answers; emoji picker; search inside a chat (/ key). Attach button is shown but disabled until C9; the customer side panel comes after C6 | The owner's reference screenshots | M |
| C6 | Routing and teamwork | Written and tested offline (222 tests); migrate and UAT checks pending | Waba Team tree (Common > departments > sub-teams, each department with its own number); each level sees itself and below, never sideways; conversations assigned on arrival with the reason shown; Unassigned tab for leads; transfer with a note, mark done, internal notes, quick replies, Available / Away; alerts only for the right people | None | L |
| C7 | WhatsApp from Lead / Contact / Customer | Written and tested offline (254 tests); migrate and UAT checks pending | WhatsApp button and dialog on the three forms; consent recorded on the record (Yes / No, date, source); first contact by Utility template only, blocked without consent, after STOP or when the record is marked unsubscribed; Meta's daily limit checked; the conversation appears in the inbox and in the form's WhatsApp section | Where consent is stored: decided (new Waba fields) | M |
| C8 | Reminders and scheduled follow-ups | Not started | Set a reminder or scheduled message; it fires at the time with re-checks | None | S |
| C9 | Attachments | Not started | PDF and image both ways; limits explained | Which documents to send | M |
| C10 | Notifications | Not started | Automatic/Manual switch per type; dispatch update from a Delivery Note; payment reminder preview | After-hours reply decision | M |
| C11 | Reports, cost and health | Not started | Four reports, monthly cost, health panel, alerts | KPI/DILO decision | L |
| C12 | Pilot and production | Not started | Small real team; production setup and rollback runbook | Owner sign-off | M |

Every chunk ends with: offline tests green, migrate on UAT, a demo script, a CHANGELOG.md entry, this table updated, owner commits and pushes, owner says "accepted".
