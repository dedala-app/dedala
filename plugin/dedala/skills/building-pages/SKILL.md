---
name: building-pages
description: How to build and keep the user's pages in the app - stores and records, a page built widget by widget with app_page, screens, a job or a program that keeps it up to date, pages on the user's own files, pages they write in, commands, and handling what they do. Use before any app_page call that sends a view, components or a job link, before app_data on a new store, and before writing a job or program that keeps a page.
---

# Building pages

A page is a screen the user comes back to, made with `app_page`. When to make
one is in `living-in-the-app`; how to draw a widget is `drawing-cards`.

**The app is a directory.** Everything you build is a file under
`dedala/`, which every answer names: `pages/<id>.json`,
`components/<Name>.json`, `scripts/<name>.js`, `stores/<id>.json` (a linked one
a symlink there), `search.json`, `commands/<id>.json`, `widgets/<id>.json`,
`buttons.json`. The tools write and check these files; you may edit them in
place too: a saved file is checked and reaches the phone within seconds, and one
that would not draw stays off it and is told to you, with its problems.

## Stores

A page has no data of its own: every page and card reads stores by name, and a
store is a file here (`app_data`). Give what belongs to no one page (tasks, a
trip, people) a store named after the subject, and let each page read it; read
what another page holds rather than copying it, where it goes stale. Every
answer says who reads what: `app_page` returns the stores a page reads with the
other pages reading them, `app_data` alone lists the stores, and a change says
when a page reads a key the new data lacks.

- **A JSON store** holds a value, or records: a list of objects with an `id`.
  People, invoices, documents are records: one per real thing, a stable id, a
  `name` or `title` as the user says it, small, linking to others by id. Write it
  with `data`, or `patch` an existing one.
- **A text store** is a file of theirs, Org or Markdown, linked by `path` (Pages
  on their files, below).
- **A folder store** is a folder of their files, linked by `path`: one record per
  file (`id` its path inside, `title`, `tags`, `date`, `updated`, `links`,
  `backlinks`, `text` for a text file, `file` for anything else), kept in sync
  file by file. `ignore: ["npins/", "*.nix"]` leaves out what is not theirs to
  read.

A record's `file`, a path here, is an attachment: the phone fetches it when a
page shows it and draws it with `{"File": "$it.file"}` (PDF, Markdown, Org, an
image, other documents). A document is a record with a file. Never paste a
file's content into a tool call: write the file, name its path.

**Declared, a store's records are in the user's Search**: `app_data {id:
"people", name: "People", symbol: "person", screen: "Person", title: "$name",
subtitle: "$role", words: ["$email"]}`. `screen` is the component a record opens
as, from Search, a row or a card. Declare a store when the user asks, or says yes
to it when you propose it. `app_search` finds what you built as their Search
does: look before adding, and patch a record they already have.

## Building a page

Build it in steps, never as one big call: a long call is slow, and when it fails
the whole page is lost.

1. Put what it shows in a store first: `app_data {id: "committee", data:
   {election: {…}, prs: […]}}`.
2. Start with one widget: a component in `components`, the `view` a short list
   of them: `{"VStack": [{"Election": {"election": "$committee.election"}}],
   "spacing": 16}`. Components see only their props, so pass what they need.
3. Add the next widget: its component and the view with one more line. Refine
   one by sending only its component.

To change a page, look first: `app_page` with only its `id` returns its view,
its components, what the check finds, and the stores it reads. `app_page` alone
lists your pages.

Every call lays the page out as the user's phone will, at their text size and
width. What would look broken (a text cut, a word broken across lines, a button
too small to tap) holds it back: fix what it lists and send the change again.
Every screen the page opens is laid out too, over a sample record
(`screens`). No reviewer judges a page: its look is yours, and change only what
was asked. The phone checks it again when it arrives and tells you what it
finds.

When the page is done, your reply is one line: what the user can do with it, or
what is left to decide. Never retell it.

## Screens

What one row holds is a screen of its own, not a second page and not a card: a
component with a `title`, opened with `show`.

```json
{"components": {
  "InvoiceRow": {"props": ["invoice"], "body": {"HStack": [{"Text": "$invoice.number"}, {"Spacer": {}}, {"Text": "${currency(invoice.total)}"}]}},
  "Invoice": {"props": ["id"], "title": "Invoice ${find(invoices.items, 'id', $id).number}",
    "body": {"VStack": [
      {"Text": "${find(invoices.items, 'id', $id).client}", "font": "title"},
      {"Button": "Mark paid", "action": {"run": "markPaid", "args": "$id", "close": true}}
    ]}}
 },
 "view": {"ForEach": "$invoices.items", "as": "it", "content":
   {"InvoiceRow": {"invoice": "$it"}, "onTap": {"show": "Invoice", "with": {"id": "$it.id"}}}}}
```

Pass an id and look the record up with `find`, so the screen shows the store as
it is after an edit. A screen reads its props and the stores, runs the page's
script and keeps its `state` while open. A flow is screens that open screens,
with no turn of yours: `"replace": true` so the way back skips a form, `"close":
"all"` back to the page; `"as": "sheet"` for a confirmation. From a card, `show`
opens a sheet.

**The bar is yours too.** A page or screen takes `toolbar`: up to three
`Button`s or `Menu`s with a `symbol`, drawn by the system. What is about the
thing goes there (an Info sheet, a call button, a menu of rarer actions); the
body stays the thing itself.

## Keeping a page up to date

A page that shows things that change gets a maintainer, a cron job linked to it:

1. Look at the page for its widgets and stores.
2. Write the refresh recipe where the job can read it: each part of the data,
   its source, how to read it.
3. Create the job: a schedule that fits how often the sources change (propose
   one), `deliver: "local"`, and a self-contained prompt: "Refresh the store
   `<store>` the page `<id>` reads: follow `<recipe>`, then `app_data {id:
   <store>, patch}`. Do not write to the user."
4. Link it: `app_page {id, maintained_by: <job id>}`. The app then shows when it
   was updated and will be next, warns when an update failed or is late, and
   lets the user refresh it.

When what it follows rarely changes but should show soon when it does (a CI, a
parcel, running jobs), give the job a **change detector**: a `monitor_script`
in Hermes's `scripts/`, run often (`every 5m`), printing what matters. Hermes
compares its whole output with the last: the same, and the job does not run;
different, and it runs with the diff. So the output changes only when something
that matters does: sorted ids and statuses, never a time or a duration that
ticks. Unreadable source: exit with an error (a failure is never a change).
Run it yourself twice: the same output both times. A page that changes every
time anyway (a daily brief) keeps a plain schedule.

- **One job owns each key.** A page with two maintainers (a nightly rebuild, a
  5-minute detector) says in each prompt which keys it writes and patches only
  those, or the page flaps.
- **A job that rebuilds from a source merges what the user typed.** A page holds
  what the job fetches and what they wrote (a note, a debrief): the prompt says
  to read the store first and carry their fields over, matched by id. Better
  still, keep what they write in a store of its own.
- **State that outlives midnight needs a day token**: the monitor prints the date
  (`day=20261111`, never a clock time) so the rollover is a change, the store
  keeps the same token in the same format, and the prompt clears the day's
  fields when they differ.
- **The first tick always runs**: it is the baseline; check that run.
- **A manual run still goes through the monitor**: with an unchanged output it
  does nothing and looks like success. To test the job, change what the monitor
  prints, let a tick land, and judge by the store's data, not the run status.
- **A job's script runs with a bare environment**: set `PATH` at its top and try
  it with `env -i` before trusting the job.
- **A pre-run `script` that prints nothing means "nothing to do"**: the run is
  skipped and still reads ok. Right for a nudge, fatal for a maintainer: have it
  always print a line.

What changes only with the time or with what is on the phone (a countdown, what
is waiting on the user) needs no job: put it in the page's script.

## A page a program keeps

A store is a file, and whatever writes it updates the pages reading it within
seconds, with no model: a script job (`no_agent`), a flow, a command. When a
refresh is mechanical, write a program that writes the file and schedule that;
keep a model for what needs judging. The program writes the whole file in one
step (a temporary file renamed over it), reads it first when the user can edit
the page (their edits are in the same file), and can make or delete a store by
making or deleting its file.

A program elsewhere writes through the plugin's inbox: `POST /store/<id>` with
`{"data": value}` or `{"patch": {…}}`, and `POST /notify` with `{"title",
"body", "open", "collapse"}` rings the user. Give each program its own key with
`app_token {id: "pr-flow", stores: ["pr_reviews"], notify: true}` and it sends
`Authorization: Bearer <token>`, able to do only that; `remove` revokes it. A
store a program writes can wake a job of yours: `app_data {id: "pr_reviews",
handled_by: <job id>}`. A store bound to a Live Activity or a widget reaches the
lock screen and the Home Screen the same way.

A page can take a photo, `{"Photo": "Receipt", "bind": "$photo"}`, sent here
when an `edit` carries it (`"file": "$photo"` in an added record), and dictation,
`{"Dictate": "Say a line", "bind": "$text"}`.

## Pages on the user's files

When a page shows or changes a file here (a daily note, a grocery list), link it
and let the page work on it directly; never relay it through yourself.

1. `app_data {id, path}` on a file that exists (make it first, an Org header is
   enough).
2. The page reads `org($<id>.text, 'item')` (or `markdown(…)`): each item `{text,
   checkbox, tag, …}`; `filter(org(x, 'item'), 'checkbox')` keeps the boxed ones.
   `$<id>.sync` is `pending`, `synced` or `failed` with `$<id>.error`: show it
   only when it is not `synced`.
3. Its controls edit the file: `{"edit": {"store": "daily", "append": "$text"}}`
   (bare text: the bullet is written for you), `toggle`, `change` with `to`,
   `remove`, `text` for the whole file.

Each edit shows at once and is written within a second, merged with what changed
in the file meanwhile; a line edited elsewhere in between is refused and the page
says why. A file that moves (a note per day) keeps its store id: call `app_data`
with the same id and the new path.

A folder of notes is a folder store: a `List` over it, a row opening a screen
that draws the title and a metadata line from the record's fields, then
`{"File": "$note"}` with no height (the screen scrolls), then its backlinks.
Links inside the file open their note's screen. The screen edits list items
(`{"edit": {"store": "notes", "id": "$id", "toggle": …}}`), adds a file (`"add":
"2026/new.org", "text": …`) or deletes one (`"delete": true`).

## Pages the user writes in

A page that exists so the user writes something (a note, a review, a form) is a
miss as a bare form:

- **Bring what they would have to think of**: at most five proposals of what you
  already know (their calendar, mail, the day), one line each, tickable, facts
  only, kept fresh. A proposal already in the file is not a proposal.
- **Show the state**: what is already written, and one status line ("6 lines in
  today's note"). A half-filled page never looks blank.
- **A header says something**: the day, the state, the last time. Decoration
  gets flagged.
- What they type before saving lives in state: clear it in the action that edits
  the file. No "saving" flags: the store's `sync` tells the truth.

## Commands

A button that *does* something here (review a PR, deploy, fetch a bill) is a
command, not a `send`: `{"command": "pr_review", "args": {"pr": "$it.number"}}`
runs what you bound to that name, with no model. Bind it with `app_command`:

```json
{"id": "pr_review", "script": "pr_review.sh",
 "description": "Review PR n of the repo and write the verdict into the pr_reviews store"}
```

- `script`: an executable in Hermes's `scripts/`, with `PATH` set at its top.
  It reads its args as JSON on stdin, writes the stores it changes
  (`$APP_STORES/<id>.json`, whole, through a temporary file); stdout is the
  result, a non-zero exit a failure with the last line of stderr as its reason.
- `flow`: a workflow's path, where one is set up.
- `job`: a cron job's id; every tap runs the model. Start here when you do not
  know yet what the command should do.

The `description` is the contract: what one run must achieve, written as a test.
The page reads `$commands.pr_review` (`status` `running`, then `done` or
`failed`, with `result` or `error`): `${commands.pr_review.status == 'running' ?
'Reviewing…' : 'Review'}`. What lasts goes through a store, never the result.
One run of a command at a time.

**You keep improving it unasked.** Every run is traced, and a supervisor job
made with the command wakes you on a failure, on a sample of the runs, on a run
unlike the others, and once a day when there were runs. Judge them against the
contract and fix the program, or say nothing. A command bound to a job whose
runs look alike becomes a program. `app_command {id}` shows the trace. Never
tell the user what you fixed.

## Handling what they do

A page is used, not only read. Give its rows verbs with `actions` (hold menu,
swipe), its lists an order with `onMove`, its inputs an effect with `onChange`.
What the user does changes a store on the phone with `edit`: at once, offline
too, and it reaches you without a turn: once they pause, one `edits` event, the
plugin writes the files and logs it for `app_events`. No conversation hears of
it.

When something should happen on your side, give the page a handler job:

1. A cron job with `deliver: "local"` and a prompt saying what to do with what
   they did (move the task in its file, update a store with `app_data`), ending
   with "Write to the user only if something needs them; otherwise say nothing."
   Each run is told which changes to read.
2. Link it: `app_page {id, handled_by: <job id>}`.

It runs when their changes settle, again for what changed meanwhile, and a
failed run is given the same changes again. Never put a `send` on a per-row
action: each tap would start a turn in their conversation; what a tap must *do*
is a command. A `send` beside an `edit` only where you must answer right away.
Without a handler, their edits still land: read them with `app_events` when they
come up.
