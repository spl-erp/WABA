# Waba: how the information moves

**Document 2 of 3: data flow.** Draft for your confirmation, 28 October 2026. Nothing described here has been built yet. Each diagram has a short walk-through underneath.

Documents: [1 Features](01_FEATURES.md) · [2 Data flow](02_DATA_FLOW.md) · [3 User flow](03_USER_FLOW.md)

**How to read the diagrams.** Boxes are steps or places; cylinders are stored data; a diamond is a decision; arrows show the direction information travels. Open items from document 1 are marked where a diagram depends on one.

---

## 1. The big picture

```mermaid
flowchart LR
  subgraph ERP["The ERP: Waba app"]
    W["Webhook endpoint"] --> Q["Background queue"]
    Q --> DB[("Messages, conversations, identities, files")]
    DB --> I["Shared inbox"]
    I --> S["Send service"]
    S -->|"API calls"| M
    R[("Leads, Contacts, Customers, Sales Person tree")] --- Q
    R --- I
    DB --> REP["Reports and alerts"]
  end
  C["Customer on WhatsApp"] <-->|messages and files| M["WhatsApp and Meta Cloud API"]
  M -->|"events (webhook)"| W
  A["Agents: inside sales, accounts"] --> I
  G["Managers"] --> REP
```

**Walk-through.** A customer and WhatsApp exchange messages. Whenever something happens (a message arrives, a message is delivered, a template is approved) Meta sends an event to one web address in the ERP. The ERP never works on it at once: it saves it and hands it to a background queue, so a busy moment never loses a message. The queue matches the customer to a record in the ERP, saves the message and decides which agent gets it. Agents work in the inbox; whatever they send leaves through the send service to Meta. Managers read the reports built from the saved data.

---

## 2. A customer writes to us (incoming)

```mermaid
flowchart TD
  A["Meta sends an event to the webhook"] --> B{"Signature valid?"}
  B -- no --> X["Reject, nothing stored"]
  B -- yes --> C["Store the raw event and answer OK at once"]
  C --> D["Background job picks it up"]
  D --> E["Find the account by WABA id and the number by phone number id"]
  E --> F{"Already processed? same message id and status"}
  F -- yes --> Z["Ignore the duplicate"]
  F -- no --> G{"Message or status update?"}
  G -- status --> H["Update the sent message: delivered, read or failed, with the Meta code"]
  G -- message --> I["Find or create the conversation for this number and customer"]
  I --> J["Refresh the 24-hour window"]
  J --> K{"Who is the customer?"}
  K -- "known by WhatsApp ID" --> L["Link to the record"]
  K -- "known by phone number" --> L
  K -- unknown --> T["Waiting list: rule still to be decided, open item 1"]
  L --> M2["Download any attachment into a private file"]
  T --> M2
  M2 --> N["Routing rules choose the agent"]
  N --> O["Inbox updates live and the unread count rises"]
  H --> P["Message ticks update in the inbox"]
```

**Walk-through.**
1. **Signature.** Meta signs every event with a secret only Meta and the ERP know. An event with a wrong or missing signature is thrown away, so nobody else can feed messages into the ERP.
2. **Saved first.** The raw event is stored before anything else, so if later steps fail it can be replayed. The ERP answers "OK" immediately; otherwise Meta resends for up to 7 days.
3. **Which account and number.** Every event names the WhatsApp account and the number it concerns. With several accounts and numbers this is how the ERP knows where it belongs.
4. **Duplicates.** Meta can send the same event twice. The same message id and status is processed once.
5. **Message or status.** A status event (sent, delivered, read, failed) updates a message we sent. A real message opens or continues a conversation and restarts the 24-hour window.
6. **Who is the customer.** First by WhatsApp's anonymous ID (used when the customer hides their number), then by phone number against Leads, Contacts and Customers. If neither finds anyone the message waits in a list (open item 1).
7. **Attachment.** Files are downloaded at once into private storage, because Meta's links last about five minutes.
8. **Routing.** The number's rules choose the agent (see document 1, section 4.7). The inbox updates without a refresh.

---

## 3. We write to a customer (outgoing)

```mermaid
flowchart TD
  A["Agent presses Send, or an automatic rule fires"] --> B{"Is the 24-hour window open?"}
  B -- yes --> C["Free text and files allowed"]
  B -- no --> D["Only an approved template is allowed"]
  D --> E{"Consent recorded and not opted out?"}
  E -- no --> X["Blocked with a clear reason"]
  E -- yes --> F{"Template approved, number allowed for this purpose, daily new-contact limit left?"}
  F -- no --> X
  F -- yes --> G["Queue the send"]
  C --> G
  G --> H["Call the Meta Cloud API"]
  H --> I{"Accepted?"}
  I -- no --> J["Error table decides: use a template, wait 24 hours, back off, fix the request, or alert an admin"]
  I -- yes --> K["Message saved as sent with Meta's message id"]
  K --> L["Status events: delivered, read, failed"]
  L --> M["Ticks update in the inbox and the cost counter updates"]
```

**Walk-through.**
1. **Window decides what is allowed.** Open: anything. Closed: only a template. The ERP keeps its own clock for each number and customer, because Meta offers no way to ask.
2. **Safety checks for templates:** consent recorded and not opted out (open item 2), template approved by Meta, the number allowed for this purpose, and the daily limit of new contacts not used up. If a check fails the user gets a plain reason.
3. **Queued.** The send happens in the background so the screen stays quick.
4. **If Meta refuses,** a fixed table of Meta's error codes decides what happens: switch to a template (window closed), do not retry for 24 hours (Meta is holding back marketing messages), slow down (too fast), stop (the customer cannot receive), fix the request, or alert an admin (payment problem, restricted account, expired key).
5. **Afterwards,** status events tick the message sent, delivered, read, or failed with the code, and the billing information Meta attaches feeds the cost report.

---

## 4. How the settings are arranged

```mermaid
flowchart TD
  P["Meta Portfolio: access key, verification, number cap, daily limit"] --> A1["WhatsApp Account A: templates and billing"]
  P --> A2["WhatsApp Account B: templates and billing"]
  AP["Meta App: app secret and one webhook address"] -.->|"serves events for"| A1
  AP -.->|"serves events for"| A2
  A1 --> N1["Number 1"]
  A1 --> N2["Number 2"]
  A2 --> N3["Number 3"]
  N1 --> AG1["Agents and roles"]
  N1 --> RR1["Routing rules"]
  N2 --> AG2["Agents and roles"]
  N3 --> AG3["Agents and roles"]
```

**Walk-through.** Settings are stored at the level where Meta scopes them. The **portfolio** holds the access key that covers all its accounts, the verification, the cap on numbers and the daily limit shared by all its numbers. The **Meta app** holds the secret that signs events and the single address Meta sends them to; it serves every account it is connected to, and each event says which account it is for. Each **account** owns its templates and its billing. **Numbers** sit under an account; each has its own agents with roles and its own routing rules. Because the levels are linked, any arrangement works: one account for everything, several accounts for several brands, or a second portfolio for a separate company.

---

## 5. Notifications from the ERP

```mermaid
flowchart TD
  A["ERP event: order confirmed, delivery note submitted, invoice overdue"] --> B{"Message type switch"}
  B -- Automatic --> C["Pick the approved template and fill it from the record"]
  B -- Manual --> D["Show a preview to the user"]
  D --> E{"User presses Send?"}
  E -- no --> Z["Nothing sent"]
  E -- yes --> C
  C --> F["Same checks as any outgoing message"]
  F --> G["Send and track status"]
  G --> H["Customer reply lands in the conversation of the record owner"]
```

**Walk-through.** Each message type (dispatch update, order update, payment reminder) has a switch. Automatic means the ERP event itself starts the send. Manual means a person sees a preview first. After that both follow the outgoing path in section 3, so consent, approval, limits and the number's purposes are checked either way. If the customer replies to a notification, the reply goes to whoever owns that record (or follows the number's routing rules).

---

## 6. Keeping watch (health and alerts)

```mermaid
flowchart LR
  S1["Access key expired or rejected"] --> H
  S2["Payment problem"] --> H
  S3["Account restricted or disabled by Meta"] --> H
  S4["Quality rating drops"] --> H
  S5["Webhook silent or backlog growing"] --> H
  H["Health panel for each account and number"] --> AL["Alert to Admins"]
  H --> ST["Only the affected account stops sending, others continue"]
```

**Walk-through.** Several signals feed one health panel: events Meta sends about the account, errors returned when sending, and the ERP's own check of whether messages are still arriving. A serious one raises an alert to Admins immediately. Because each account has its own key, billing and status, a problem on one account does not stop the others.

---

## 7. Where the reports come from

```mermaid
flowchart LR
  M[("Message log")] --> R1["Activity per agent"]
  M --> R2["Response time and backlog"]
  M --> R3["Template delivery and failures"]
  ST[("Status events with Meta pricing information")] --> R4["Monthly cost"]
  C[("Conversations and assignments")] --> R1
  C --> R2
  T[("Template list and status")] --> R3
```

**Walk-through.** Reports are built only from data the ERP already keeps. *Activity per agent* and *response time and backlog* come from the message log and the conversations (who was assigned, when they replied). *Template delivery and failures* come from the status events and the template list. *Monthly cost* uses the pricing information Meta attaches to each delivered message, grouped by category against the free allowance. Managers see only their own hierarchy.

---

## 8. What is stored, where, and who can read it

| Data | Kept where | Who can read it | How long |
|---|---|---|---|
| Access key, app secret, verify token | Encrypted password fields | Admins only | Until changed |
| Raw events from Meta | Event log | Admins | Kept (needed to replay) |
| Messages (text, status, Meta ids) | Message log, linked to the customer record | The assigned agent; the manager of that agent; Admins with a logged reason | **Kept** |
| Attachments | Private files attached to the message | Same as the message | **Kept** |
| Conversations (number, customer, window, agent, status) | Conversation records | Same as the message | **Kept** |
| WhatsApp anonymous IDs and phone pairs | Identity store | Admins and the system | Kept |
| Templates and their status | Template list | Admins and agents allowed to send templates | Kept |
| Notes, reminders, quick replies | Own records | Notes: the conversation's users; quick replies: the team | Kept |
| Consent and opt-out | Fields on the Lead and Contact (design after open item 2) | Staff who can see the record | Kept |
| Audit trail (who read, sent, transferred, exported) | Audit log | Admins | Kept |

**Security in one paragraph.** Events are accepted only with Meta's signature. Keys and secrets are never shown or put in code. Each user's view is limited by the permission rules, including for lists, reports and exports. Meta keeps nothing beyond about 30 days and offers no history, so the ERP's own log is the only record; it is backed up with the rest of the system and everything is kept.

## To confirm

1. That the pictures match how you expect messages to travel.
2. The checks before a template goes out (section 3).
3. Who can read what (section 8), and that everything is kept.
4. That the open items (document 1) stay open until the stated point.
