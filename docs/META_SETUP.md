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
4. On the Account use **Meta, Test connection**, then **Subscribe webhook**, then **Sync numbers**.

## 5. Tell Meta where to send events
App dashboard, WhatsApp, Configuration, Webhook: paste the **Callback URL** from the ERP and the same **Verify Token**,
press Verify and save. Then subscribe the **messages** field. Meta calls the ERP once to verify; the ERP answers.

## 6. Try it
Send a WhatsApp message from your verified mobile to the test number. Open **Webhook Events** in the Waba workspace: a
new row should appear within seconds. If it does not, open the Error Log and the row's status, and tell me what you see.

## Things I have not verified against live Meta (tell me what you see)
- API version v25.0 (the account field "Graph API version" can be changed).
- The exact phone-number fields Meta returns for Sync numbers.
- Whether one Meta app can serve several portfolios.
