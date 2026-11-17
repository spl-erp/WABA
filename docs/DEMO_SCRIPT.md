# Waba demo script (about 15 minutes)

Before the team arrives: Meta test connection green, number Enabled, templates synced, three test users created, one
customer phone that is a verified recipient of the number.

## Demo layout (Waba Team tree)
Common > Sales Domestic (Team Lead: one user, number owner) > Telecallers (Agent: one user). Add the number under Sales Domestic.

## Steps
1. As Admin, show the Waba Account: Test connection, last webhook time.
2. From the customer phone, write "Hello" to the number. Show the message appear live for the agent (the inbox shows the
   customer as Triage until matched), the window banner (24 hours) and who it was assigned to and why.
3. As the agent, reply with text; watch the ticks turn sent, delivered, read. Use a quick reply (type /).
4. Add an internal note (the customer never sees it). Mark as done, then write again: it reopens.
5. Transfer the chat to another agent with a note; log in as that agent and show only their chats are visible.
6. As the department lead, show the Unassigned tab and the whole team's chats; as an agent, show you cannot see sideways.
7. From the customer phone send STOP: show the opt-out chip; send START to lift it.

## Files and message types (needs the Meta sending fix)
8. Customer sends a photo, a voice note and a PDF: the photo shows in the chat (click for full size), the voice note plays, the PDF is a card to open.
9. Customer shares a location and a contact: a map card and a contact card show.
10. Rep presses the paperclip: send a device file (see the preview and caption first), an ERP quotation as PDF, or a file from Shared Files.
11. Hover a customer message and react with an emoji; a failed message has Send again.

## Say this plainly to the team
- Sending files, reactions and the shared library need the Meta sending fix first (see the Meta billing note).
- First contact by template needs the customer's consent; media sending comes later; marketing messages are blocked on purpose.
