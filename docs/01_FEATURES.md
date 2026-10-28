# Waba: what WhatsApp in the ERP will do

**Document 1 of 3: features.** Draft for your confirmation, 28 October 2026. Nothing described here has been built yet. Written for the project owner, in plain language; technical detail comes after you confirm this.

Documents: [1 Features](01_FEATURES.md) · [2 Data flow](02_DATA_FLOW.md) · [3 User flow](03_USER_FLOW.md)

## Items still open (we will ask you again before they matter)

| # | Open item | Why it matters |
|---|---|---|
| 1 | **Unknown sender:** what to do when a number that is not in the ERP writes to a company number (hold in a list, create a Lead, or send an automatic question first). | Decides whether strangers and spam can create records, and how enquiries from new customers are picked up. Needed before incoming messages are finished. |
| 2 | **Where consent is stored.** You said it is kept in the enquiry. In the ERP we found only opt-out flags on the Lead and Contact ("Unsubscribed", "Unsubscribe - Do not Disturb"), and no field that records who agreed, when, or how. | Meta requires documented opt-in, naming the company, before we start a conversation with a template. Breaking this lowers the number's quality rating and can restrict the **whole account**, so every agent on every number stops at once. Needed before any template goes to a real customer. |
| 3 | **KPI and DILO link:** should WhatsApp chat counts feed the daily KPI and DILO? | Today the WhatsApp Chat numbers on the KPI entry are typed by hand. Decide before the reports are built. |
| 4 | **Attachments in version 1:** which files agents must send (quotation PDF, invoice PDF, a brochure library, files from the agent's computer). | Decides how much work the attachment part needs. |
| 5 | **Out-of-hours automatic reply:** switch it on or leave it off. | The feature will exist but stay off until you decide. |
| 6 | **Meta account status:** is the business verified, who owns the current WhatsApp account, is a payment method attached, is billing in rupees. | Gates every live test. Rupee billing is compulsory from 31 December 2026. |
| 7 | **The old DoubleTick number:** reuse it, or register a new number. | Depends on item 6. DoubleTick has not been used for a long time, so no live chats are at risk. |

---

## 1. What this is, and why

The company's sales and accounts staff will talk to customers on WhatsApp **from inside the ERP**. The ERP connects **directly to Meta's WhatsApp Business platform** (the official "Cloud API"), with no middle provider. Every conversation is saved on the customer's Lead, Contact or Customer record, so it sits beside calls, quotations and visits. Management can see who spoke to whom, how fast they answered, and what it costs.

The product is a separate app called **Waba**, kept apart from the Splashjet-specific code so it stays clean and could be sold later. Anything particular to Splashjet (how a phone number finds a customer, who owns a Lead, the Sales Person hierarchy) connects through a small bridge.

**The most important thing the first release must do well:** rep and customer conversations in a shared inbox.

**How conversations start:** the rep usually writes first, using an approved template; the customer's reply opens a free conversation.

## 2. Who uses it

| Role | What they do | In version 1 |
|---|---|---|
| **Inside sales and telecallers** | Answer customers, follow up Leads and enquiries, send quotation follow-ups | Yes, they work the inbox |
| **Accounts and collections** | Payment reminders, payment questions | Yes, they work the inbox |
| **Supervisor** | Takes unassigned conversations, reassigns, covers absent agents | Yes |
| **Manager** | Sees their own team's conversations and reports, through the Sales Person hierarchy | Yes, read and reports |
| **Admin** | Connects Meta, sets up accounts, numbers, agents, templates and rules | Yes |
| **Field sales reps** | Today they use their own WhatsApp numbers with customers | **Not in version 1.** Full access later, probably in the Android app |
| **Customer** | Writes to or receives messages from a company number | n/a |

Field reps keep their own personal WhatsApp for now. The ERP never reads personal chats: that is not possible through the official platform, and doing it by other means would break WhatsApp's terms and risk the reps' numbers.

## 3. What is in each release

| | Version 1 (first release) | Version 2 | Not planned |
|---|---|---|---|
| Conversations | Receive, reply, shared inbox, first contact by template, attachments, notes, quick replies, transfer, mark done, reminders and scheduled follow-ups | Field-rep access (read-only, then request a message, then an inbox in the Android app) | Reading reps' personal chats |
| Messages from the ERP | Dispatch, order and payment-reminder messages, automatic or manual per type | Campaigns to saved lists of Leads or Customers | Groups; customer-facing chatbots |
| Control | Consent and opt-out checks, permissions, audit trail, health alerts | KPI and DILO link (if decided) | AI features (revisit after version 1) |
| Reporting | Activity per agent, response time and backlog, template delivery and failures, monthly cost | Extra reports | History from before go-live (Meta keeps none) |
| Setup | Several accounts, many numbers, agents per number, routing rules, all configured in the ERP | Hosting for other companies (not decided) | WhatsApp Calling API |

## 4. The features, one by one

Each feature says what the user can do and what the system guarantees.

### 4.1 Setup and configuration (Admin)
- **You can** connect the company's Meta account, add one or several WhatsApp accounts (WABAs), register their numbers, and say for each number who works it and how new conversations are shared out. All of it is done in the ERP; adding another account or number needs no developer.
- **Three levels, matching how Meta works:** the *Meta portfolio* (the company's Meta account, which holds the access key), the *Meta app* (holds the secret and the one address Meta sends messages to), and the *WhatsApp account* (owns templates and billing). Numbers sit under an account.
- **Every number** has a type: **Shared** (a team or region) or **Personal** (a company-issued number given to one agent; it stays company property if the agent leaves). It also has purposes (conversations, documents, notifications, campaigns), business hours, how long a conversation stays with its agent, a default limit of open conversations per agent, and who can see what.
- **Guarantees:** secrets (keys, app secret) are visible only to Admins. Each account shows its environment (test or live) so a test account is never mistaken for the live one. A *Test connection* button checks the connection and shows verification, currency and time zone. An account can be switched off without deleting anything.

### 4.2 Receiving messages and files
- **You can** see everything customers send to a company number, text, images, documents and voice notes, on the customer's record and in the inbox.
- **Guarantees:** every message is saved once, even if Meta sends it twice. The message is attached to the right customer (by phone number, or by WhatsApp's anonymous user ID when the number is hidden). Files are downloaded immediately, because Meta's links expire in minutes. If the customer is not known, the message waits in a list for a decision (open item 1).

### 4.3 The shared inbox
- **You can** see your conversations in one list, with unread counts, filtered by number, assigned to me or unassigned, open or done, and searched by name, number or text. New messages appear without refreshing.
- **Guarantees:** you only see your own conversations; your manager sees their team's. Opening a conversation marks the customer's messages as read.

### 4.4 Replying
- **You can** reply with text and files while the customer's **24-hour window** is open. The screen shows how much time is left.
- **Guarantees:** when the window is closed the screen offers only approved templates, so a message that WhatsApp would refuse is never attempted. Each message shows sent, delivered, read, or failed with the reason.

### 4.5 Starting a conversation (first contact by template)
- **You can** press **WhatsApp** on a Lead, Contact or Customer, pick an approved template (for example a follow-up on a quotation), see the variables filled from the record, and send.
- **Guarantees:** before sending, the system checks consent and opt-out, that the template is approved, that the number is allowed for this purpose, and that today's limit of new contacts is not used up. If something blocks it, you are told why. The customer's reply opens a free conversation.

### 4.6 Templates
- **You can** create templates (text, with an image or document header), see whether Meta has approved them, and see their quality. You pick a template, and the variables are filled from the record. Templates exist per language (English, Hindi and other Indian languages).
- **Guarantees:** only approved templates can be sent. A paused or rejected template is shown as such. Meta decides the category (marketing, utility, authentication), which changes the price; the system shows the category and the cost.

### 4.7 Assignment and routing
- **You can** choose, per number, how a new or returning conversation finds an agent. The rules are tried in order and the first that fits wins:
    1. **Stays with its agent** while that agent is available.
    2. **Personal number:** goes to its owner; if the owner is away, to an available supervisor.
    3. **Rep code from a QR code or link:** goes to that rep.
    4. **The owner of the Lead or customer,** if they work this number.
    5. **Language:** an agent who speaks the customer's language.
    6. **Least busy** available agent below their limit.
    7. **Unassigned list,** with supervisors alerted after a set time.
- **Guarantees:** an agent who is away or at their limit is skipped for new conversations. A personal number never hands its conversations to someone else for no reason. The inbox can show why an agent was chosen.

### 4.8 Working tools: notes, quick replies, transfer, done, reminders
- **Internal notes** on a conversation, never sent to the customer.
- **Quick replies:** saved snippets agents insert into a message.
- **Transfer** a conversation to a colleague on the same number, with a note. A conversation cannot move from one number to another (WhatsApp does not allow it); the screen explains the options.
- **Mark done** closes a conversation; a new customer message reopens it.
- **Reminders and scheduled follow-ups:** wake a conversation at a set time, or schedule a message to go out then. Before a scheduled message leaves, the system re-checks the window and consent.

### 4.9 Notifications from the ERP
- **You can** send dispatch updates, order updates and payment reminders. For **each type** an admin chooses **Automatic** (sent when the ERP event happens, for example a delivery note is submitted or an invoice becomes overdue) or **Manual** (a person sees a preview and presses Send).
- **Guarantees:** both kinds go through the same checks as any outbound message. A customer's reply to a notification lands with the owner of that record.

### 4.10 Consent and opt-out
- **Guarantees:** a customer who says STOP, or who turns off business messages in WhatsApp, can no longer receive templates. Replies inside a window are always allowed. Until consent is recorded in a field the system can read (open item 2), templates are limited.

### 4.11 Reports (version 1)
- **Activity per agent:** messages and conversations per agent, per day, per team.
- **Response time and backlog:** how fast agents reply and which conversations are waiting. There is no fixed target yet; the times are recorded so a target can be set from real numbers.
- **Template delivery and failures:** sent, delivered, read, failed, and which templates work.
- **Monthly cost:** billable messages by Meta's categories against the free allowance, in rupees.
- Managers see their own hierarchy.

### 4.12 Health and alerts
- **You can** see for every account and number whether the connection is healthy: access key valid, payment ok, not restricted by Meta, quality rating, and whether messages are arriving on time.
- **Guarantees:** a problem raises an alert to Admins at once, and **only the affected account stops**; others carry on.

### 4.13 Permissions and visibility
- Three roles: **Admin**, **Supervisor**, **Agent**. Agents see only their own conversations. A manager reads their team's through the Sales Person hierarchy. Reading and sending are recorded (who, when) in an audit trail.
- Everything is **kept** (the ERP is the only history, because Meta keeps nothing beyond 30 days).

### 4.14 QR codes and links
- **You can** create, for a number and a rep, a QR code or link that opens WhatsApp with a ready message ending in the rep's code, for example "Hello, I would like a quotation [R12]". Print it on quotations, invoices and email signatures. When the customer sends it, the conversation goes to that rep.

### 4.15 Attachments
- Documents up to 100 MB; images only JPEG or PNG up to 5 MB; audio and video up to 16 MB. Which files agents pick from the ERP (quotation or invoice PDF, a brochure library) is **open item 4**.

## 5. The rules in plain language

- **The 24-hour window.** When a customer writes to a number, a 24-hour window opens and restarts with each new customer message. Inside it we can send anything. Outside it only an approved template. The window belongs to one number and one customer.
- **Templates and cost.** Meta classes each template as marketing, utility or authentication. Anything promotional or unclear is marketing. Prices in India (rupees per message, from 1 Oct 2026): **marketing 0.8631, utility 0.115, authentication 0.115**, and free-form replies cost **0.115 after the first 1,000 a month per number**. Marketing therefore costs about 7.5 times a utility message.
- **Daily limit for new contacts.** A new account may start conversations with 250 different people in 24 hours. After business verification, or after sending 2,000 template messages successfully, the limit is 2,000, then it grows automatically. Replies and in-window messages do not count. The limit is shared by every number in the same Meta portfolio.
- **How many numbers.** A new portfolio may register 2 numbers. After business verification it is 20. Beyond 20 needs a request to Meta.
- **Opt-in.** Meta requires clear opt-in, naming the company, before business-started messages. Customers can switch business messages off, and then we must stop.
- **Quality.** Customers who block or report us lower a number's quality rating. A poor rating pauses templates or restricts sending for the whole account.
- **Unanswered conversations.** No fixed response target yet. The system records times and can alert supervisors when a conversation waits too long once a time is chosen.
- **Who sees what.** Agents: their own. Managers: their team. Admins: configuration, and any conversation with a logged reason.

## 6. What Meta forces, and what Waba adds

| Meta's rule | What Waba does about it |
|---|---|
| Templates are required to start a conversation or after 24 hours | A template picker, approval tracking, and a closed-window message that explains |
| No history, no list of agents, no shared inbox | Our own message log, assignment, inbox and notes |
| The same customer has different WhatsApp IDs in different Meta portfolios, and may hide their phone number | An identity store, matching by ID first and phone second, and a list for unmatched senders |
| Webhooks can arrive twice, late or out of order | Every message and status is saved once and in the right order |
| One badly behaving number can slow the whole account | Quality alerts and the ability to pause campaigns on one number |
| Individual customers can switch business messages off | Opt-out is recorded and respected everywhere |

## 7. Can there be several WhatsApp accounts? (the check you asked for)

**Yes.** Several accounts (WABAs) in the same Meta portfolio, served by one Meta app, is documented. Each account has its own templates and billing; all share the portfolio's access key, verification, number cap and daily limit. A separate legal entity or brand with its own verification can be a **second portfolio** with its own key and number cap; its customers get different WhatsApp IDs, and templates are recreated by hand. Meta can copy approved templates between accounts of the same portfolio.

**Still to confirm in a test setup:** whether one app can serve several portfolios or each needs its own; whether a payment failure on one account affects the others; whether the 20-number cap can be raised; whether the 24-hour window is strictly per number; where a ban applies (a number, an account or the whole portfolio).

## 8. What we will not do

Read reps' personal WhatsApp chats; recover history from before go-live; run groups or the calling feature; run customer-facing chatbots or AI in version 1; message anyone the system cannot show consent for, outside an open window.

## 9. What has to be true first

- A Meta business portfolio, ideally verified (open item 6).
- A payment method on the WhatsApp account, and billing in rupees before 31 December 2026.
- Numbers for the pilot. A company-owned test number is available for the test system.
- Consent recorded in a place the system can read (open item 2) before real templates go out.

## 10. Glossary

| Term | Meaning |
|---|---|
| **WABA** | WhatsApp Business Account (Meta now says "Messaging account"). Owns templates and billing; holds numbers. |
| **Portfolio** | The company's Meta business account. Holds the access key, verification, number cap and daily limit. |
| **Meta app** | The app registered with Meta that receives messages at one address and signs them with a secret. |
| **Number** | A phone number registered on the WhatsApp platform, with its own display name and quality rating. |
| **Window (24 hours)** | The period after a customer's last message when free replies are allowed. |
| **Template** | A pre-approved message required to start a conversation or write after the window closes. |
| **BSUID** | WhatsApp's anonymous user ID for a customer, used when their phone number is hidden. |
| **Tier** | The daily limit of new people we may start conversations with. |
| **Quality rating** | Green, yellow or red, from customers' feedback on a number. |
| **Opt-in / opt-out** | A customer's agreement to receive messages, and their withdrawal of it. |

## To confirm

1. The roles and what each can do (section 2).
2. The version 1 scope (section 3), especially what is left for version 2.
3. The rules for routing and visibility (4.7 and 4.13).
4. That the open items above stay open until the stated point.
