# Waba: decisions log

Everything the owner decided while planning, in the owner's own terms, with the points deliberately left open. Kept so no decision depends on a chat. Last updated 28 October 2026.

## Decisions recorded (the owner's answers)

| Topic | Decision |
|---|---|
| Top priority of release 1 | **Rep and customer conversations** (shared inbox in the ERP) |
| Who starts conversations | **The rep writes first** (templates matter; business-started messages cost money and need opt-in) |
| Volume | **1,000 to 10,000 customers a month** (needs a verified Meta business; 2,000/day tier is enough) |
| Languages | English, Hindi, other Indian languages (templates per language) |
| First contact | **An approved template sent from the ERP**; the customer's reply opens the 24-hour window |
| First-contact messages | Lead/enquiry follow-up, quotation follow-up, order and dispatch updates, payment reminders |
| Messaging from | **Lead, Contact, Customer** records |
| Inbox users (v1) | **Inside sales / telecallers and the accounts / collections team.** Field reps keep their own WhatsApp; **full field-rep access later** (design leaves room, probably in the Android app) |
| Number structure | **Fully configurable and freely customisable**; no fixed starting layout |
| Accounts | **Multi-WABA configuration required** (feasibility answered in section 6) |
| Visibility | A user sees **only their own** conversations; **their manager reads their team through the Sales Person hierarchy** |
| Inbox features in v1 | Internal notes, quick replies, **reminders and scheduled follow-ups**, **transfer and mark done** (plus reply, attachments, templates, assignment, unread counts) |
| Reports in v1 | Activity per agent; response time and backlog; template delivery and failures; monthly cost |
| First-response target | **None yet**: track the times, set a target from real data |
| Notifications (order, dispatch, payment reminders) | **Both**: a per-message-type switch for automatic (from the ERP event) or manual (a person clicks Send) |
| AI | **Not in v1** |
| Campaigns (bulk to segments) | **Version 2**, right after the inbox works |
| Retention | **Keep everything** (the ERP is the only history; Meta keeps nothing beyond 30 days) |
| Sale model | **Splashjet only for now, maybe sell later**: build clean and portable, no multi-company hosting |
| DoubleTick | **Not used for a very long time**: no live chats there. This lowers the risk of reusing the existing number (see Phase 0) |
| Test number | **A company-owned test number is available** for UAT |
| Timeline | **No fixed date** |

### OPEN items (the owner deferred; ask again at the stated point)

1. **Unknown sender** (a number not in the ERP writes to a company number): triage list, auto-create Lead, or auto-reply then triage. Ask before Phase 2 matching is finished.
2. **Where consent is stored.** The owner says it is "in the enquiry"; the code search found **no consent field**, only the opt-out flags `unsubscribed` (Lead, Contact) and `custom_unsubscribe_do_not_disturb` (Lead); "the enquiry" is the Lead (source values such as IndiaMART). The owner asked why this matters: because Meta requires documented opt-in naming the business before business-started templates, and violations restrict the **whole account** (every agent on every number). Ask before any template goes to a real customer.
3. **KPI / DILO link**: should WhatsApp chat counts feed the daily KPI and DILO? Decide before Phase 7.
4. **Attachments in v1**: which files (quotation PDF, invoice PDF, brochure library, uploads)? Not confirmed. Ask before the attachments phase.
5. **After-hours auto-reply**: decide later (the option is built, off by default).
6. **Meta account status** (verification, who owns the current WABA, payment method, INR): the owner will provide. Gates Phase 2 live tests.
7. **The existing DoubleTick number**: reuse it (needs the WABA to be Splashjet-owned and DoubleTick to release it) or register a new number. Decide after item 6.

## Documentation first

On 28 October the owner decided that the documentation comes before any building: full feature documentation (business level, no field-level specification yet), a data-flow document with diagrams, and a user-flow document with diagrams and simple screen sketches, delivered as a review page plus these files. **Nothing is built until the owner has confirmed the documentation in words.** The foundation code already written in the app (pure rules, six configuration records, 99 offline tests) is uncommitted and stays untouched until then.
