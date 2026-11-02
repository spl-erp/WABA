# Automatic WhatsApp messages and reminders (C11)

Everything starts **switched off and empty**. Nothing is sent until you do the steps below, in this order.

## 1. Settings (Waba workspace, Notification Settings)
- **Send notifications**: the master switch. Off means nothing runs, whatever the rules say.
- **Most automatic messages per hour**: a brake (default 60).
- **Name shown for "Sender name" values**: an automatic message has no person behind it.
- **Only send to these phone numbers** (test mode): one per line. While filled, nobody else ever receives a message. Use it for the first trial.

## 2. The number
On the Waba Number: tick **Notifications** under its purposes, and leave **Receive only** unticked. A receive-only number never sends, whatever else is set.

## 3. A template whose values can all be filled from the record
Use an approved **Utility** template. Open it, and in **Where each value comes from** choose for every value: the customer's name, a field of the customer's record (`customer_name`, `mobile_no`, ...) or, for a notification, of the document itself written with `doc.` in front (a quotation: `doc.name`, `doc.grand_total`; an invoice: `doc.name`, `doc.outstanding_amount`, `doc.due_date`), fixed text, today's date, or the sender name. A value left on "Ask each time" stops the message (the review shows which).

## 4. A rule (Notification Rules)
One per kind. It cannot be switched on until it is complete; the form says what is still missing.

| Kind | Fill in |
|---|---|
| Quotation follow-up | days after the quotation date; most messages (1 = once) |
| Payment reminder | days after the due date; most reminders; days between them |
| Enquiry acknowledgement | minutes after a new enquiry it may still be sent (the Lead must have WhatsApp consent) |

Also: **Mode** (Manual, the default: a person reviews each message; or Automatic), **Ignore records older than** (default 30 days, so switching a rule on never messages old records), **Most notifications per customer per day** (default 1).
The button **What would it send now?** is a dry run: it lists the records that would get a message and sends nothing.

## 5. Manual mode: Waiting for you
Open the **Notification Log**, press **Waiting for you**, open an entry and press **Review and send**. You see exactly what would go out. You can also press **WhatsApp** on a Quotation, Sales Invoice or Lead form to prepare a message for that one document. Only Waba Supervisor, Waba Admin and System Manager can approve.

## What is checked at the moment of sending (both modes)
The record still qualifies (the quotation is still open, the invoice still unpaid, the lead still fresh); the customer's consent and STOP; the template is still approved and Utility; the number is on, set for notifications and not receive-only; the master switch and the rule are on; business hours (Automatic); the hourly limit (Automatic); the per-customer daily limit (Automatic); test mode. Anything held back is written in the Notification Log with its reason.

## Remind me (conversations)
In the chat's menu: **Remind me...** (a date and time, optional note) and **My reminders**. When it falls due you get a notification, the chat is reopened if it was done, and an Event is written in the chat. A reminder never sends anything to the customer.
