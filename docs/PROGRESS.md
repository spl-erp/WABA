# Waba build progress

Status values: Not started, In progress, Accepted. A chunk is Accepted only when the owner says so after the demo.
Plan: 12 chunks, each shown on UAT before the next starts. Sizes are relative (S/M/L), there are no dates.

| # | Chunk | Status | What you can try when it is done | Needs from the owner | Size |
|---|---|---|---|---|---|
| C1 | Setup screens | Verified on UAT (15 checks pass), awaiting owner acceptance | Waba workspace; create Portfolio, Meta App, Account, Number, Agent Access, Routing Rule; validation messages | Docs confirmed in words | S |
| C2 | Connect Meta | Verified on UAT offline (19 checks pass); live Meta test pending |  Webhook URL and verify token; Meta "Verify" succeeds; Test connection, Sync numbers; raw events logged | Meta test app and company test number | M |
| C3 | Conversations (read-only) | Verified on UAT (22 checks pass), awaiting acceptance | Messages and Conversations lists; inbound text on the right record or in Triage; window state | Rule for unknown senders | M |
| C4 | Send and templates | Not started | Send inside the window; sent/delivered/read ticks; failures in plain words; Sync templates | None | M |
| C5 | The Inbox | Not started | The real inbox page with live updates, reply box, window indicator, template picker | None | L |
| C6 | Routing and teamwork | Not started | Assignment rules, away/capacity, transfer, done, notes, quick replies, own-only and manager visibility | None | L |
| C7 | WhatsApp from Lead / Contact / Customer | Not started | Button and dialog on the forms, timeline, first contact by template, consent checks | Where consent is stored | M |
| C8 | Reminders and scheduled follow-ups | Not started | Set a reminder or scheduled message; it fires at the time with re-checks | None | S |
| C9 | Attachments | Not started | PDF and image both ways; limits explained | Which documents to send | M |
| C10 | Notifications | Not started | Automatic/Manual switch per type; dispatch update from a Delivery Note; payment reminder preview | After-hours reply decision | M |
| C11 | Reports, cost and health | Not started | Four reports, monthly cost, health panel, alerts | KPI/DILO decision | L |
| C12 | Pilot and production | Not started | Small real team; production setup and rollback runbook | Owner sign-off | M |

Every chunk ends with: offline tests green, migrate on UAT, a demo script, a CHANGELOG.md entry, this table updated, owner commits and pushes, owner says "accepted".
