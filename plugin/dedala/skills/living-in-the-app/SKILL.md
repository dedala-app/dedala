---
name: living-in-the-app
description: How to live in the user's iPhone app - conversations and topics, choosing between a card, a page, a notification, a Live Activity and a widget, pictures, what arrives from outside, and what you cannot do. Use whenever you talk to the user through the app or make something in it.
---

# Living in the app

The app is your home with the user: they read and answer you there, and it is
yours to shape. It ships almost nothing (a conversation, Search, settings);
everything else you make with the `app_*` tools, which are the only way to it.
How to draw is the `drawing-cards` skill; pages and the data behind them are
`building-pages`; the protocol underneath is `references/protocol.md` beside this skill.

When a call's JSON is long, build it in `execute_code`, `json.dump` the
arguments to a file and pass its path as `from_file`, instead of copying JSON
back by hand. When a tool says the JSON does not parse, the mistake is in what
you wrote, where it shows.

## Conversations

- **Main** is where you talk day to day. Your replies land there and ring the
  phone when the app is closed: answer in one message rather than three.
- **Topics** are the register of what you raised and what the user decided: a
  thing that needs them, a trip, a repair, a project. Each is a session of its
  own. `app_topic` opens one with a `brief` (the facts its session starts from;
  it does not see main), an `opening` line, and a `link_line`: one sentence in
  main pointing to it, the only thing main shows.
- **A tap on a card** comes back as their message with the button's payload.
  Act on it, then settle the card: `app_patch` it, or turn it into a one-line
  receipt (`app_ops` `{"op": "receipt", "message": id, "text": "Booked for
  20:30"}`).
- **What they share from another app** (a link, photos, a file, some text)
  arrives in main as their message: their note first, then each item and where
  it is kept. A link comes with the page's text as they saw it: read that rather
  than fetching a page that may need their login.

### Raising things

When something needs the user (a failure, a bill, a deadline they may miss),
raise it once, as a person would, in a topic of its own:

1. **Look first.** `app_topic` without arguments lists every topic, open or
   closed, with its outcome. That list is the truth, not what you remember or
   read earlier in the session: read it before saying what you will do about a
   subject, not only before raising one. Covered by an open topic: add to it
   only when something changed. Closed: say nothing, unless something its
   outcome did not cover happened; then reopen it (`closed: false`) and say what.
2. **Otherwise open one**: a short title ("Backups failing"), a brief with what
   you know, an opening that says what happened and what you suggest, a
   `link_line`. Talk it through there; a card with choices only when it really
   is a choice.
3. **When they decide** ("we don't care", "handle it", "remind me Monday"), act
   and close the topic with the decision as its `outcome`. A reply that names
   neither the thing nor the change ("let's accept") is a decision too: find the
   open topic it answers instead of asking which. "Remind me" keeps it open with
   a one-off job that brings it back.

**A topic is only as good as its premise.** A deadline is not a decision: before
a topic asserts what the user intends (renewing, applying, attending), read their
own words; where they do not say it, ask in the opening rather than assume in
the title. When they correct the premise, close the topic with the corrected fact
as its outcome, and fix every other place that stores the old fact (their
profile, your memory, page data, job prompts) in the same pass.

**What speaks on its own reads the topics first.** A morning brief, a page's
summary, a nudge: nothing closed comes back, and an open topic gets one line
pointing to it, never a retelling. A line that would say the same unresolved
thing a third morning belongs in a topic. In a job's prompt, put `app_topic`
on the first line, before anything is gathered: a check at the end is reached
after the message is already written.

## Choosing the object

- **A message** for what a sentence says best.
- **A card** (`app_card`, drawing-cards skill) when a sentence is not the best
  shape: a choice, things to compare, a place, a time, a document to act on.
  The card is the answer: after it, one short line that adds what it does not
  show, or nothing. Its `text` is what the notification shows, so it carries the
  gist.
- **A page** (`app_page`, building-pages skill) for what the user comes back to:
  a team's results, a budget, a project's state. A new page joins the end of
  their bar; Search finds them all. Never delete a page they use without asking.
- **A record** when they ask for a document or a person: `app_data {id:
  "documents", record: "lease", say: "Here is the lease"}` hands it over, one
  tap from its screen.
- **A notification** (`notify`, below) for what they must know now and is not a
  message.
- **A Live Activity** for something live and time-bound they would otherwise
  keep checking: a flight, a delivery, a match, a deploy.
- **A widget** for a glance at a store from the Home Screen.

## Pictures

A picture on this machine (a screenshot they shared, a chart you made) reaches
the phone privately: `app_ops` `{"op": "assets", "assets": {"take-12":
"/path/to/12.jpg"}}`, then `{"Image": {"asset": "take-12"}}` in the card or
page. It travels encrypted, and again whenever the file changes. Never put a
file on a public URL to show it; `{"Image": {"url"}}` is for pictures that are
public already. The pre-send check does not see the picture itself, so the
reviewer judges its place, not its content.

A picture is sized to be read: a screenshot in a card runs the full width with
`contentMode: "fit"` and no height cap; a thumbnail in a row is a small fill crop
(about 46×60).

## Arrivals

Things can reach you from outside without the user writing: voice notes,
meeting recordings, mail. Whatever posts them (a flow, a hook) sends each to the
plugin's inbox (`inbox_port` in the app platform's settings) under a source name;
the plugin keeps it and, once arrivals pause, runs the job that handles that
source, so a burst is one run.

- A job named `inbox/<source>` handles that source; one named `inbox`, every
  source without its own. Create them with `deliver: "local"`; they run on
  arrival, whatever schedule they are given.
- The job reads what arrived with `app_events {source}`: what it has not read.
  It counts as read once the run ends well; a failed run gets it again. A long
  text stays in its file: read it with your file tools.
- It does the work and speaks only when the user is needed: a card in main, or a
  topic for a decision (Raising things). Otherwise it says nothing.
- With no job for a source, main hears of each arrival: handle it there, and
  give the source a job if more will come.
- A source whose items are the user's own words (dictated notes) needs no model:
  a `no_agent` job that posts `{"source": …}` to the inbox's `/forward` puts them
  in main as their messages. Never reword or summarise what they said.

## Live Activities

An activity is a design bound to a JSON store. Put what it shows in the store
(`app_data {id: "flight", data: {gate, status, until}}`, small: about 3 KB
compressed), then `app_activity {action: "start", id, store: "flight",
design: {views: {region: view}}}`. From then on you never update it: every
write to the store's file is a push within seconds, from you, a flow, a script
or a command. `"ended": true` in the store ends it; `"alert": {title, body}`
rings once per distinct alert, and iOS shows that line unencrypted, so keep it
generic ("Flight update"). Starting again on the same id replaces it.

The design reads the store as `$data.<key>`. Its regions:

- **`lock`** has about 128 pt of height inside its padding, and nothing reports
  an overflow. Budget three short lines: a `caption` label, the main value
  (`largeTitle.bold`, `monospacedDigit`), a `caption` under it. Always add
  **`lockCompact`**, drawn when `lock` does not fit.
- **The compact island** gives each side about 52 pt: one symbol or a few
  characters. A live countdown is wider than that, so put the fixed time
  ("22:00") in `compactTrailing`, and the countdown in `lock` and the expanded
  regions. `minimal` holds one symbol.
- **A countdown to a moment** is `{"Text": {"countdown": "$data.until"}}` with
  the ISO time in the store; `{"timer": date}` counts up. Both tick on their own:
  never write the remaining minutes from a job.
- The design travels compressed with the start (about 1 KB for a full one), so
  keep it lean; updates carry data only.

## Notifications

A message rings the phone when the app is closed. For a line that is not a
message and opens the right place on a tap, `notify`: `app_ops {ops: [{"op":
"notify", "title": "Bill paid", "body": "1 480 €", "open": {"page": "bills"}}]}`,
`open` being `{page}`, `{show: Name, with: {id}}` or `{conversation}`;
`collapse` replaces an earlier one with the same key. It rings even with the app
open. A program rings the same way with no model: `POST /notify` on the inbox.
Ring only for what they must know now; the rest is a store a page shows.

A notification can carry buttons, tapped without opening the app. Declare them
once by kind: `{"op": "buttons", "kinds": {"bill": [{"id": "paid", "title":
"Mark paid"}, {"id": "later", "title": "Tomorrow"}]}}`; then a `notify` names
the kind and gives each button its action: `"kind": "bill", "actions": {"paid":
{"command": "pay_bill", "args": {"id": "n-41"}}, "later": {"edit": {"store":
"bills", "id": "n-41", "due": "tomorrow"}}}`. A command or an edit runs in the
background; `open`, `page`, `show` or `conversation` opens the app. Four buttons
a kind at most.

## Widgets

A widget is a component on the Home Screen over a store, redrawn as the store
changes, app closed too: `app_widget {id: "glance", store: "day", component:
"Glance", families: ["small", "medium"]}`, the component reading `$data.<key>`.
The user adds it themselves and picks yours by name: make it, then say so in one
line. WidgetKit draws it, so stacks, `Text`, `Image`, `Gauge`, `ProgressView`,
`Spacer`, `Divider` and shapes only: no inputs, no scrolling, no long lists. A
`Button` that opens a page, a screen or a conversation opens the app there. Vary
the look with `If` on `$family` (`small`, `medium`, `large`).

## What you cannot do

You cannot erase conversations, read the phone, or act outside what the tools
offer. When the user asks for something the app does not have (a view, an
action written the way they wish it existed), build the closest thing that works
and say in one line what is missing. Never ship a control that does nothing, and
never imply the request was followed to the letter.
