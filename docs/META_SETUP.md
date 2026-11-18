# Setting up a Meta app for the Waba UAT test

Goal: a UAT-only Meta app that sends WhatsApp events to the UAT ERP. Do not use the production app or number.
Meta's screens change often, so the menu names below may differ slightly. The facts that matter (what each ID is, where
each secret goes) do not. Never paste a token or secret into chat or into a file in the repository; type them only into
the ERP forms.

## What you need first
- A Meta Business portfolio (business.facebook.com) that Splashjet owns. Business verification is not needed for the
  test number, only for real customer volume later.
- A Facebook developer account (developers.facebook.com) attached to that portfolio.

## 1. Create the app (developers.facebook.com, My Apps, Create App)
1. Use case: connect with customers on WhatsApp. Business type, portfolio: the Splashjet one.
2. Name it clearly, for example "Splashjet ERP UAT".
3. Add the **WhatsApp** product to the app.
4. Note the **App ID** (App settings, Basic) and the **App Secret** (same page, Show). The secret signs every webhook.

## 2. The test number
- The WhatsApp product page offers a free **test number** and a list of up to 5 recipient numbers you verify by code.
  Add your own mobile as a recipient. This is enough for C2 and C3.
- Later you can add the real company test number (Add phone number) once you decide on number reuse or a new SIM.
- Note the **WABA ID** and the **Phone number ID** shown on that page (both long digit strings).

## 3. A token that does not expire
The temporary token on the test page lasts about 24 hours. For anything lasting:
1. Business Settings, Users, **System users**: add a system user (Admin).
2. Assign the app and the WhatsApp account to it with full control.
3. Generate a token for the app with the permissions **whatsapp_business_management** and **whatsapp_business_messaging**.
4. Copy it once. It is shown only once.

## 4. Enter it in the ERP (UAT)
In the Waba workspace, in this order:
1. **Portfolio**: name, the portfolio ID (optional), paste the token into Access Token.
2. **Meta App**: name, App ID, App Secret, and a **Verify Token** you invent (a long random string). Save: the
   **Callback URL** fills itself in.
3. **WhatsApp Account**: name, environment UAT, the portfolio, the Meta app, the WABA ID.
4. On the Account use **Meta, Test connection**, then **Subscribe webhook**, then **Sync numbers**, then **Sync templates**.
5. Open the synced **Waba Number**. Sync creates it **switched off**: tick **Enabled**, set the display name, and add
   people under **Agents** (at least one with role Supervisor). Without agents nobody can see or answer chats.
6. Give each person a role on their User: **Waba Agent**, **Waba Supervisor** or **Waba Admin**. Then arrange them in the
   **Waba Team** tree and list the number under the team that owns it (see docs/DEMO_SCRIPT.md for the demo layout).
7. Check the stored **Callback URL** starts with `https://`. If it shows `http://`, set `host_name` in the site's
   `site_config.json` to `https://uat-splashjet.sigzencloud.com`, then save the Meta App again.

## 5. Tell Meta where to send events
App dashboard, WhatsApp, Configuration, Webhook: paste the **Callback URL** from the ERP and the same **Verify Token**,
press Verify and save. Then subscribe the **messages** field. Meta verifies at the app level, so one Meta app has one
callback URL: make sure the other WhatsApp apps installed on UAT (frappe_whatsapp, whatsapp_chat) are not using the same app.

## 5b. Development mode and the test number
- An app in **Development** mode only receives webhooks for the test number and for people with a role on the app. Switch
  the app to **Live** before real customers write.
- The free test number can message only the (up to 5) recipients you verified. Free text works only inside the 24-hour
  window; outside it send an approved template. A first message to someone who has never written needs consent recorded
  on their Lead, Contact or Customer, so for the first test, write to the number from your phone first (that opens the window).
- Only **Utility** templates with a text body (and optional text header), no buttons, appear in the ERP picker.

## 5c. A live customer number on a test system: Receive only
If a number that real customers write to (for example one a messaging provider runs for production) is connected to the
test ERP, tick **Receive only (safety)** on its Waba Number. The ERP then listens to it but nothing can be sent from it:
no reply, template, file, reaction or read receipt, and starting a chat from a Lead is refused before anything is
created. A Waba Admin unticks it when the number is meant for real sending. Messages from real customers will still
appear in the inbox, so only people who may see them should have access.

## 6. Try it
Send a WhatsApp message from your verified mobile to the test number. Open **Webhook Events** in the Waba workspace: a
new row should appear within seconds. If it does not, open the Error Log and the row's status, and tell me what you see.

## Things I have not verified against live Meta (tell me what you see)
- API version v25.0 (the account field "Graph API version" can be changed).
- The exact phone-number fields Meta returns for Sync numbers.
- Whether one Meta app can serve several portfolios.

## If something does not work
| What you see | Likely cause |
|---|---|
| Meta's Verify fails | Callback URL not https or not public; Verify Token differs from the Meta App record |
| Webhook Events stay empty | Subscribe the messages field; app in Development mode and the sender is not a test recipient |
| Event row says "Number not set up yet" | Run Sync numbers on the Account |
| Message arrives but no conversation shows | Number is not Enabled, or you have no Agent Access / team membership |
| Event rows stay "Pending" | The background worker (queue `short`) is not running |
| Send fails with "allowed list" (131030) | Recipient not verified on the test number |
| "Save the access token on the portfolio first" | The Portfolio has no token saved |

## Writing templates in the ERP (C10b)

- **Waba Template > New** makes a draft. Saving never contacts Meta. Fill the name (lowercase letters, digits, underscore),
  language, category (Utility or Marketing), header, body, footer and buttons. After the first save a row appears for each
  `{{value}}`; give every one an example, because Meta requires it.
- **Submit to Meta** (Waba Admin or System Manager only) checks the draft, then sends it. Meta's answer or refusal is shown
  in Meta's own words and kept in the Submit note. A rejected template can be edited and submitted again.
- **Copy as new draft** starts from any synced template. **Delete draft** removes a local draft; **More > Delete at Meta**
  asks you to type the template name first.
- Marketing templates can be written and approved, but the ERP will not send them one-to-one (first contact stays Utility only).
- In Meta's webhook configuration subscribe the fields **message_template_status_update**,
  **message_template_quality_update**, **template_category_update** and **message_template_components_update**, so approval,
  rejection and quality changes arrive without a manual sync.


## Coexistence (a number used in the WhatsApp Business app and in Waba)
Only for a number Meta has connected to the API while keeping it in the WhatsApp Business app (needs WhatsApp Business app 2.24.17 or newer; Meta documents the onboarding for Solution Partners and Tech Providers, via Embedded Signup).
1. In the Meta app's WhatsApp webhook settings subscribe these fields as well as `messages`: **smb_message_echoes** (what the team types in the phone app), **account_update** (the phone-app link changed), **history** and **smb_app_state_sync** (kept as received, not imported yet).
2. On the Waba Number tick **Also used in the WhatsApp Business app**. Never use Register number, Send a code or Enter the code on it: that would cut the phone app link (the buttons are switched off).
3. The phone app must be opened at least every 14 days, or Meta disconnects the link; Waba then shows the link as Disconnected and alerts the Team Leads.
4. Meta's throughput for such a number is 20 messages per second (not 80). Messages typed in the phone app are free and do not open or change the 24-hour window.


## WhatsApp calls (Business Calling API) - number 55
Calls are handled in the browser (no phone server). Needs a Cloud API number that is not also in the WhatsApp Business app (a coexistence number cannot take calls), a messaging limit of 2,000 or more and a credit line.
1. In the Meta app's WhatsApp webhook settings subscribe the **calls** field as well as `messages`.
2. Calling must be enabled on the number at Meta (it already is on number 55; the call button is then visible to customers). Meta's call hours are not set by Waba.
3. In Waba Settings > WhatsApp calls tick **WhatsApp calls** only when the browser phone is ready (stage 2); until then calls are only logged and the Team Leads are told about missed calls. Choose who rings.
4. On the Number's agent rows tick **May take WhatsApp calls** for the people who answer (and later **May place WhatsApp calls**).
5. Every call is recorded with Meta's spoken announcement to both people; Meta keeps the audio for 7 days, Waba downloads it as soon as it is ready.
6. Customers calling you is free; calling a customer is billed per minute and needs the customer's permission first.

7. A customer's call shows a ring box (sound, Accept / Decline) in the browser of the people who ring; an unanswered call shows a 'Missed WhatsApp call' notice with an Open button. Browsers play sound only after you have clicked once in the page.
8. No microphone on a computer: Waba Settings > **Allow calls without a microphone (listen only)** (on by default) lets that person take or place a call and only listen.
