# Sensitive details in outgoing messages (W3)

What is blocked, for messages written by a person (never for automatic notifications, reminders or campaigns):

| Kind | How it is recognised |
|---|---|
| Aadhaar number | 12 digits that pass Aadhaar's own checksum (spaces or hyphens allowed) |
| PAN | the PAN shape, with a valid entity letter |
| Card number | 13 to 19 digits that pass the card checksum and start like a real card network |
| Bank account number | 9 to 18 digits with a word such as a/c, account, bank or IFSC next to it |
| UPI ID | name@handle (an email address is not blocked) |
| One-time code or PIN | digits next to OTP, one-time password, verification code, CVV, password or PIN (a postal PIN code is not blocked) |

What happens: nothing is sent or stored. An agent is told why and to ask a Team Lead. A Team Lead, Waba Supervisor or Waba Admin may send it anyway after giving a reason. Every block and every override is written to **Logs > Privacy Log** with masked samples only (never the full value) and leaves a note in the chat.

Settings (Waba Settings > Privacy): the check is on unless "Switch the privacy check off" is ticked; each kind can be switched off; **Allowed identifiers** lists the company's own bank accounts, UPI IDs and PAN, which always pass.

Limits: a PDF's contents are not scanned; a long number can look like an account number only when a bank word is next to it; checksums remove most false alarms but not all. A Team Lead can always override.

## Coexistence: messages typed in the WhatsApp Business app
On a number that is also used in the WhatsApp Business app, what the team types in the phone app reaches Waba as "Phone app" messages and is shown in the chat to everyone who may open that conversation (the same visibility as any message). The ERP does not know which person typed it, so no name is shown. The privacy check above runs only on messages sent through Waba, so sensitive details typed on the phone are stored without a block or warning. The raw delivery from Meta is kept in the Waba Webhook Event, including these messages. Meta's one-time history and contact list (`history`, `smb_app_state_sync`) are kept only as raw deliveries and are not imported.


## WhatsApp calls
Every WhatsApp call is recorded (Meta plays a spoken notice to both people before it starts). The audio is kept as a private file on the call and on the ERP Call Log, visible only to people who may see the call: the person who took it, Team Leads over the number and administrators. Meta keeps its copy for 7 days. A call from a number nobody knows is logged without opening a chat. The calls record holds the number, the times, who answered and the recording; nothing of what was said is written down.

A person without a microphone may take or place a call listen-only (Waba Settings > WhatsApp calls). The customer then hears silence, and the call is recorded like any other.
