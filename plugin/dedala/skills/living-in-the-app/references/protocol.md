# Dedala protocol

The contract between the app and an agent. The agent sends **ops**; the app sends
back **events**. When the app is not running, the agent reaches the phone by
**push**. Views inside ops are written in [Hermes UI](hermes-ui.md).

The app ships no screens of its own beyond a conversation, Search and
settings. Everything else (pages, screens, cards, the data they show, Live
Activities, the agent's name) comes from these ops.

## Transport

**The relay** ([relay.md](relay.md)). The plugin shows a QR code, the app scans
it and both sides exchange keys. Ops and events then travel sealed through the
relay's mailbox, each side connecting out; the relay holds them for a phone that
is away and sends pushes with the app's APNs key. Each side numbers its
messages and sends the next once the relay holds the one before; the phone keeps
what you did on disk until then.

**Over USB, for development:** a server inside the app on the phone's loopback,
reached from the Mac through `iproxy`. Debug builds only, and only while the
app is in the foreground. The same ops, unsealed.

| Request | |
|---|---|
| `POST /ops` | one op or an array, applied in order and animated together. Answers `{ok, applied, errors, rendered, previews}` once cards have drawn (about a second) |
| `GET /events` | every event since the last read, then forgets them |
| `GET /tokens` | `{start, activities}`: the push tokens below |
| `GET /captures/<key>` | a PNG named in a report |
| `GET /snapshot` | the whole screen |
| `GET /show?tab=` | shows a tab, for looking at the app from the Mac |
| `GET /components` | the components defined |
| `POST /lines` | measures text as the phone lays it out, for the layout twin |
| `POST /reset` | empties every conversation |

`./mac draw`, `./mac events`, `./mac tokens`, `./mac capture` and `./mac reset` wrap these.

## Ops

Every op is a JSON object with `"op"`. Ids are chosen by the agent and stable:
sending an id again updates what it names. An unknown op, or one missing what it
needs, is an error in the answer and in the activity log; the rest of the batch
still applies.

### Who the agent is

| Op | |
|---|---|
| `{"op": "profile", "name", "avatar": {"asset"}}` | the name shown everywhere and, optionally, a face from the assets |

### Conversations

`conversation` is `"main"` (the default) or a topic id.

| Op | |
|---|---|
| `{"op": "say", "conversation", "id", "text", "card", "topic", "record", "night", "at"}` | a message. `card` is `{view, data, state, script, derive}` in Hermes UI (`script` and `derive`: see Scripts there). `topic` makes it a link to that topic (use it in `main` to point at a topic). `record` (`{store, id}`) hands you a record of a declared store, drawn under the line with its title; a tap opens its screen (Data). `night` is `{remembered, overnight}`: the boundary between two days. `from: "you"` makes it yours, drawn as if you had written it: words of yours that reached the agent another way (a voice note). `shared` (`[{type, url, title, name, size, text, item}]`) with `share` (its id) is what you shared from another app with those words, drawn above them: links and files as rows, photos from the small images the share extension left under that id. `notice` (`{title, symbol, details, warning}`) instead of `text` is Hermes speaking for itself, a command's reply or a warning, drawn as an event between messages. `steps` (`[{text, symbol, failed}]`, added by the plugin) is what the agent did before saying it, shown as a quiet "4 steps" line that opens on a tap. An `id` the app already has replaces that message where it is when you have not written since, else moves it to the end of `conversation` as a new message |
| `{"op": "patch", "id", "data", "view", "state", "say"}` | updates the card of message `id`: merges `data` (`null` removes a key), replaces `view`, `script`, `derive` or the text. Keeps its place and your input; changes animate. `state` sets those state values over yours. A new text (`say`) once you have written below it moves it to the end, as a `say` of the same id would |
| `{"op": "presence", "conversation", "typing", "since", "steps", "doing", "symbol", "tokens"}` | the agent's turn as it happens, refreshed every couple of seconds: `steps` done so far (`[{text, symbol, failed}]`, said in the present, "Reading notes.org", where the `say` that ends the turn says "Read notes.org"), what it is `doing` now ("Reading Marta's email", "Thinking", "Building a page") with the SF `symbol` of the tool at work when there is one (the pill shows the symbol, three dots without), the `tokens` it wrote, since when. Shown where the answer will appear. Neither `typing` nor `doing` means idle; any `say` clears it |
| `{"op": "topic", "id", "title", "symbol", "color", "outcome", "closed"}` | opens a topic, or updates it. `closed: true` files it under Closed |
| `{"op": "receipt", "conversation", "message", "text"}` | replaces a card with a one-line receipt once it is dealt with |
| `{"op": "notify", "title", "body", "open", "collapse", "kind", "actions"}` | rings the phone with that line, app open or not, the relay seeing only the agent's name: the notification extension opens the sealed op and shows `title` and `body`; a tap opens `open`, `{page: id}`, `{show: Name, with: {…}}` or `{conversation: id}`. `collapse` replaces an earlier notification with the same key. The app icon counts the notifications waiting, cleared when the app opens. `kind` names a declared set of buttons (`buttons` op) and `actions` maps each button's id to what it does, an action object as a page writes it (`{command, args}`, `{edit}`, `{page}`, `{show, with}`, `{conversation}`): the button runs it with the app in the background, nothing opens unless the action opens something. Sent by the agent (`app_ops`) or by a program through the plugin's inbox listener (`POST /notify`, signed as `/in/<source>` is). The app itself does nothing with the op when it arrives in the mailbox |
| `{"op": "history", "topics", "messages"}` | the conversations given back to a newly paired phone, sent by the plugin after what the agent built, in ops of about 120KB: `topics` (`{id, title, symbol, color, started, closed, outcome}`) it does not have, then `messages`, each a `say` as it stands now with its `conversation` and `at`, its card patched, and `receipt`, `answered` (when you answered its card) and `loved` folded in. A message whose id the phone has is left as it is; the others take their place by date. Not one of the agent's ops |
| `{"op": "arrangement", "pinned", "tabNames", "pageStates", "pages", "look"}` | how you arranged the app on a phone paired before, sent by the plugin first to a newly paired phone: the pages in the bar in their order, the names you gave tabs, what you set on each page, the pages you had (`pages`), which then come in without being offered as new, and the face you made for the agent. Not one of the agent's ops |
| `{"op": "buttons", "kinds": {"bill": [{"id": "paid", "title": "Mark paid", "destructive": false}, …]}}` | the buttons a notification of that `kind` shows, declared ahead: iOS learns button titles when the app runs, not when a notification arrives, so the titles are declared once and a `notify` names the kind and gives each button its action. At most four buttons a kind; `null` removes a kind. Kept and sent again to a newly paired phone |

### Data

Everything the agent builds is a file on his machine, under `dedala/`:
`pages/<id>.json`, `components/<Name>.json`, `scripts/<name>.js`,
`commands/<id>.json`, `widgets/<id>.json`, `buttons.json`, `assets.json`,
`profile.json`, `search.json` (the declarations below), `tokens.json` (the
keys programs hold for the inbox listener, each with its scope),
`triggers.json` (the jobs run when a store's file is written from outside),
and the stores. The plugin watches them all and sends what changes, checked;
the tools write them, and so may anything else. Everything the agent keeps for you is a
store: a file `dedala/stores/<id>.json`, or a symlink there to a file or
folder of his own (`app_data {id, path}`). The file is the truth. What the agent sends
is written to it; what anything else writes to it (his editor, a script, a job
with no model, a flow, a command) reaches the phone within seconds when the
app is open, or when it next opens. Every store is in scope on every page and
card under its id (`$trip.days`). The phone shows a store as the plugin last
sent it, with your edits the plugin has not confirmed made to it.

A store is one of three shapes, said by `kind`:

| `kind` | The file | `data` |
|---|---|---|
| (none) | JSON, any value | the value |
| `text` | a text file (Org, Markdown, plain) | `{path, name, exists, text, updated}`; the phone adds `sync` (`pending`, `synced`, `failed`) and `error`. Its structure is read on the phone: `org(text)` and `markdown(text)` (hermes-ui.md, Expressions) |
| `folder` | a folder of files | `[{id, name, path, title, tags, updated, identifier?, date?, signature?, links, backlinks, text? or file?}]`, one record per file (dotfiles and dot-folders left out, and what the store's `ignore` patterns name: `app_data {id, ignore: ["npins/", "*.nix"]}`, kept in `dedala/ignore.json`), `id` its path inside the folder (`2026/notes.org`). A text file (Org, Markdown, plain) carries `text`, `title` from `#+title` or the first heading, `tags` from `#+filetags`, `identifier`, `date` (ISO) and `signature` from the Org keywords, Markdown front matter or a Denote file name. Any other file (a PDF, an image, a document) carries `file`, its attachment, drawn by `{"File": …}`, with `size`, and its `title`, `tags`, `identifier`, `date`, `signature` from a Denote name (`20260101T090000==phd--tosem-paper__paper.pdf`), else the title is its stem. `links` are the ids of the records a text file links to (`[[denote:ID]]`, `[[id:UUID]]`, `[[file:…]]`, Markdown `[…](x.pdf)` and `[[wikilinks]]`), `backlinks` the ids of the records that link to it, a PDF's too; the phone adds `sync` and `error` to each |

A store whose value is a list of objects with an `id` holds **records**. A
record's `file` field, a path on the agent's machine, is an attachment: the
plugin sends the file sealed and the phone keeps it, so a page reads
`$documents[0].file` as `{path, name, format, ready, size, store, id}` and
draws it with `{"File": "$it.file"}` (Hermes UI). A **declaration** makes a
store's records findable: the phone's Search lists them under `name`, with
`symbol`, each shown by `title` and `subtitle` (expressions over the record,
`"$name"`), found by them and by `words` (`["$email", "$text"]`), and opened
as the screen named `screen` with `{"id": the record's id}`; without a
`screen`, a plain sheet lists the record's fields and its file.

| Op | |
|---|---|
| `{"op": "store", "id", "data", "kind", "declare"}` | the store whole; `data: null` deletes it. `declare` is `{name, symbol, screen, title, subtitle, words}`, kept until a `declare: null`; a `store` op without it keeps the declaration the phone has |
| `{"op": "store", "id", "patch"}` | merges into a JSON store that holds an object (`null` removes a key) |
| `{"op": "store", "id", "kind": "folder", "record"}` | one file of a folder store as it now stands, added or replaced by its `id`; `"drop": id` instead removes it |
| `{"op": "attachment", "store", "id", "name", "size", "version"}` | describes the file a record's `file` names: sent when the record appears and each time the file changes (`version` tells), nothing uploaded. `"missing": true` instead when the file cannot be read. The app asks for the file itself when a page shows it (Events: `fetch`), and it comes as `{"op": "attachment", …, "part": n, "of": m, "blobs"}`: one part of up to 16 MB as sealed blobs (docs/relay.md), which the app fetches, deletes and appends, ready when the last part is in. The app keeps fetched files up to 2 GB, the least recently opened going first; a record keeps saying whether its file is here (`ready`) |

### Pages

| Op | |
|---|---|
| `{"op": "page", "id", "title", "symbol", "view", "toolbar", "state", "script", "derive", "focus"}` | creates or replaces a page (`toolbar`: up to three Buttons or Menus for its bar, Hermes UI, Screens); it reads stores by name and has no data of its own. A new page joins the end of the bar and is announced in the main conversation; you order the bar and hide pages in Search. `focus: true` opens it. Every page op is answered by a `rendered` event with `page` instead of `card`: the app draws the page off screen at the phone's width and full height (up to 4000pt) and reports and captures it like a card. `{"op": "page", "id", "remove": true}` deletes it. The plugin adds `maintained_by` and `handled_by`, the ids of the cron jobs that keep it up to date and handle what you do on it; the phone ignores them |
| `{"op": "upkeep", "page", "state"}` | how a page is kept up to date, from the plugin, which reads the cron job the agent linked to it (`app_page` `maintained_by`): `{schedule, last, next, status, error, paused, missing, refreshing, watching, checked}`. A job with a change detector (`watching`) checks at each tick (`checked`) and runs the agent only when what it watches changed (`last`). The page shows when it was updated and will be next, and warns when an update failed or, once synced, is overdue. No `state`: nothing maintains it anymore |
| `{"op": "synced"}` | from the plugin each time the app comes online, after the state of every maintained page and the background work: what the app shows is now the agent's, and pages can say an update is overdue |
| `{"op": "background", "jobs", "runs"}` | what the agent does on his own, from the plugin, which reads Hermes cron and sees each run's tool calls and stream: `jobs` `[{id, name, schedule, next, last, status, error, paused, done, silent, page, watching, checked}]` (`done`: a one-time job that ran and will not run again), `runs` (the last 20, without a change detector's ticks that woke no agent) `[{id, job, name, started, finished, status: running/ok/failed, error, steps, tokens, doing}]`. Sent when it changes, every 2 seconds at most while a run is under way. The app shows it in Activity |
| `{"op": "check", "id"}` | last in a batch whose result a tool waits for: the app answers with a `checked` event carrying that id and the errors of the batch, empty when all of it applied. The plugin adds it when the app is open; a batch without it reports only its errors (`errors`) |
| `{"op": "acked", "ids", "failed", "answers"}` | the plugin has these events (`edits`, `file`, `command` and `share`, by id): the app stops sending them again. `answers` maps an id to the ops that settle it, applied before the ack: the store as its file now holds it after an edit, a folder record after a line edit, a command's outcome with the stores it wrote, a share said back as your message. `failed` maps an id to why it was refused, shown on the store's pages until the next edit, or under `$commands.<name>`. An event sent again is answered the same way and never made twice |
| `{"op": "command", "name", "status", "result", "error", "at", "duration", "args"}` | what came of a command you ran: `done` with the program's `result` (its stdout, JSON when it is) or `failed` with why. The phone keeps the last run of each command under `$commands.<name>` (Hermes UI, Time and live values) |
| `{"op": "define", "components": {…}, "scripts": {…}}` | components and shared script modules for cards and pages (see Hermes UI); a component with a `title` opens as a screen, with `toolbar` buttons in its bar (Hermes UI, Screens); `null` deletes one |

### Widgets

| Op | |
|---|---|
| `{"op": "widget", "id", "store", "component", "families"}` | a Home Screen widget: the component drawn over the store's value as its `data`, in the sizes named (`small`, `medium`, `large`; all three without `families`). The phone keeps a snapshot for the widget extension and redraws it when the store changes while the app runs; the plugin wakes the app with a silent push when the store's file changes while it is closed, at most every few minutes. A widget's component is drawn by WidgetKit: stacks, `Text`, `Image`, `Gauge`, `ProgressView`, `Spacer`, `Divider`, shapes; no inputs, no scrolling, a `Button` opens the app on its `open`, `page`, `show` or `conversation`. `{"op": "widget", "id", "remove": true}` removes it. Kept and sent again to a newly paired phone; the widget itself is added by you on the Home Screen, where it picks one of the agent's widgets by name |

### Images

| Op | |
|---|---|
| `{"op": "assets", "assets": {"ol": "https://…/ol.png"}}` | downloaded once, shrunk, kept where widgets and Live Activities can draw them: `{"Image": {"asset": "ol"}}`. A value that is a file on the agent's machine (`"take-12": "/var/lib/hermes/…/12.jpg"`) never goes public: the plugin sends it through the relay as sealed blobs (`{"blobs", "size"}`), again only once the file changed, and the app keeps it up to 1600px, replacing the one it had |

### Live Activities

An activity's **design** is a set of Hermes UI regions over its data:

```json
{"views": {"lock": …, "lockCompact": …, "leading": …, "trailing": …, "center": …,
           "bottom": …, "compactLeading": …, "compactTrailing": …, "minimal": …},
 "components": {…}, "background": "#0B1B2B", "tint": "#FF9F0A"}
```

The lock screen leaves about 128pt of height inside its padding. When `lock` does
not fit, `lockCompact` is drawn instead and the activity shrinks to it; always
send one. Compact regions hold a symbol or a few characters.

Activities live by **push** (below), bound to a store: the plugin starts one
with a store's value as its data and pushes an update each time the store's
file changes, the end when the store holds `"ended": true`, and an alert once
per distinct `"alert": {title, body}` in it (`app_activity`). While the app is
open it can also run them itself, which is handy for trying a design:

| Op | |
|---|---|
| `{"op": "activity", "id", "views", "components", "background", "tint", "assets", "data", "alert", "end"}` | starts (with `views`), updates (`data` merges) or ends an activity. iOS throttles updates the app sends from the background; use push for anything live |
| `{"op": "preview", "id", "design", "data"}` | draws the design at the sizes iOS gives it and answers in `previews`: which lock layout shows, what overflows, and captures |

## Events

| Event | |
|---|---|
| `{"kind": "message", "conversation", "text", "yours", "at"}` | you wrote; `yours` is the id the phone gave your message |
| `{"kind": "action", "conversation", "message", "payload", "say", "yours", "at"}` | you acted on a card in a message (`say` is the line shown as your reply, `yours` its id) |
| `{"kind": "action", "page", "payload", "say", "at"}` | you acted on a page |
| `{"kind": "stop", "conversation", "at"}` | you stopped what the agent was doing |
| `{"kind": "share", "id", "conversation", "text", "items", "at"}` | you shared something from another app through the share sheet, with a note (`text`) saying what to do with it. `items` are `{type: "link", url, title, selection, page}` (`page`: the blobs of the page's text as Safari showed it), `{type: "image", item, mime, blobs}` (a JPEG), `{type: "file", name, mime, size, blobs}` and `{type: "text", text}` (or `blobs` when long). The share extension sends it itself and the app sends it again until the plugin acknowledges its `id` (`acked`). The plugin keeps it under `shared/<id>/`, says it back as your message, and gives it to the agent as yours, photos attached |
| `{"kind": "rendered", "card", "size", "issues", "notes", "diagnostics", "capture", "visible", "derived"}` | about a second after a card is said or patched: what its layout measured, what it noticed that is not a defect (a card taller than the screen), what the renderer did not understand, how it looks, and each derived value as the phone computed it. A script that threw or ran out of time is in `diagnostics` |
| `{"kind": "flag", "conversation", "yours", …}` | you long-pressed a card and chose "Looks off"; same fields, with the id of the line it adds as yours |
| `{"kind": "arrangement", "pinned", "tabNames", "pageStates", "pages", "look"}` | how you arranged the app, a few seconds after it changed: the plugin keeps it as `dedala/phone.json` and gives it back as an `arrangement` op to the next phone paired |
| `{"kind": "failed", "card" \| "page": id, "tapped", "problem", "at"}` | an action that could not do what it says when you ran it: a card, screen or conversation that is not there, an edit the phone refused, a handler that threw or ran out of time. `tapped` is the button's or the menu entry's title, when it has one. Sent once per problem until the card or page is sent again. The plugin tells the agent in the card's conversation, `main` for a page |
| `{"kind": "errors", "errors", "at"}` | the ops of a batch the phone could not apply, each as `op N: reason`, sent as soon as the batch is applied; the others applied. The plugin tells the agent in a message |
| `{"kind": "checked", "id", "errors", "at"}` | the answer to a batch ending with `check`: the same errors, or none, for the tool call that waits for them. The tool's answer then says what the phone found; when the phone is closed or silent for 3 seconds it says so instead (`phone`), and an answer that comes after the wait is told like `errors` |
| `{"kind": "display", "textSize", "boldText", "cardWidth", "pageWidth", "viewport", "language"}` | how this phone draws cards and pages, sent when the app opens and when the text size changes: the plugin lays cards out with it before sending them |
| `{"kind": "refresh", "page"}` | you pulled the page down or chose "Refresh now": the plugin runs the page's cron job now; one with a change detector checks, and wakes the agent only if what it watches changed |
| `{"kind": "edits", "id", "changes": [{"store", "patch"} \| {"store", "id", "patch"} \| {"store", "add"} \| {"store", "remove", "from"}], "at"}` | what you changed on the phone with `edit` actions on JSON stores, sent once you stopped for a few seconds or left the app: a patch merged into the store, or into the record `id` of it, a record added, a record removed; the patches to one object merged into one, `from` the page or card it happened on. The phone already applied them. A field whose value is a file you picked or took on the phone (`Photo`) travels as `{"blobs", "name", "size", "type"}`, sealed: the plugin fetches it, keeps it under `dedala/attachments/<store>/<record>/<name>` and writes that path in the field, so a record's `file` set from a photo is an attachment like any other. The plugin writes each store's file, merged into what the file holds then, logs them for `app_events`, runs the jobs linked to the pages touched (`handled_by`), and answers in the `acked` with each store as its file now holds it: the phone drops your edit and shows the file |
| `{"kind": "command", "id", "name", "args", "from", "at"}` | you tapped a `command` action: the plugin runs what the agent bound to that name (`app_command`: a script, a Windmill flow or a cron job), with no model, and answers in the `acked` with the command's outcome and the stores it wrote; sent again, it is answered as it ended, never run twice. A name nothing is bound to fails on the phone and is told to the agent; a tap while the command runs is refused in the `acked` |
| `{"kind": "fetch", "id", "store", "record", "at"}` | the phone asks for the file of a record (shown by a page, or a tap on a big one): the plugin queues it and sends its parts while the phone is open, one part a turn, waiting when the relay is full; acknowledged when queued, refused when the record names no file |
| `{"kind": "file", "id", "store", "record", "edit", "from", "at"}` | an edit you made to a text store, or to the file `record` of a folder store: `edit` is `{append: item or [items], done?}`, `{change: item, to}`, `{remove: item}`, `{toggle: item, done?}` or `{text, base}`, a list item named by its `text` as `org()` reads it (whole across wrapped lines); on a folder store also `{add: name, text}` (a new file) and `{delete: true}` (the record's file). Sent at once. The plugin makes it to the file with no model, merging a whole text with what changed there since `base`, logs it for `app_events`, then sends the file back and acknowledges the edit, or refuses it with the reason; a file it cannot write also tells the agent |
| `{"kind": "job", "job", "action"}` | you ran (`run`), paused (`pause`) or resumed (`resume`) one of the agent's jobs in Activity |
| `{"kind": "loved", "card", "conversation", "text", "view", "data", "capture", …}` | you long-pressed a card and chose "Love it": the card as it stands. The plugin puts it in the agent's card bank (`bank/` in the drawing-cards skill) and tells the agent |
| `{"kind": "activity-report", "id", "shown", "issues", "regions", "captures"}` | the app redrew a running activity when it opened and something did not fit; once per design |
| `{"kind": "activity-token", "id", "token"}` | the update token of an activity the app started |

Through the relay, `capture` is `{"blob", "type": "image/jpeg"}`: the image as a
sealed blob to fetch (see [relay.md](relay.md)); over USB it is the name to read
from `/captures`.

`issues` are measured, not guessed: an element sticking out, text cut short of
the height it needs, a view collapsed to nothing, a tap target under 28pt. Each
names the node by its path, e.g. `VStack › 2.HStack › 1.Text`. How the agent uses
them is its drawing skill, [docs/hermes-ui/skill/SKILL.md](hermes-ui/skill/SKILL.md).

## Push

The phone takes pushes signed with the app's APNs key, sent by the relay when
the plugin asks; `tools/apns.py` sends the same from the Mac, for trying a
design. Payloads stay under about 4KB.

**Starting a Live Activity** goes to the install's **start token** (`GET /tokens`;
it changes when the app is reinstalled), with the design compressed inside, and
subscribes the activity to a broadcast channel:

```json
{"aps": {"timestamp": 1793000000, "event": "start",
         "attributes-type": "HermesActivityAttributes",
         "attributes": {"id": "flight-tp1235", "design": "<base64 of raw-deflated design JSON>"},
         "content-state": {"data": "{\"gate\":\"F32\",…}"},
         "alert": {"title": "TP 1235 · Paris → Lisbon", "body": "Check-in is open", "sound": "default"},
         "input-push-channel": "<channel id>"}}
```

A full design compresses to about 1KB. **Updates and the end** are broadcast on
the channel, data only: `{"aps": {"timestamp", "event": "update" | "end",
"content-state": {"data": "…"}, "alert", "dismissal-date"}}`. Use one channel per
activity and delete it when the activity ends; an app has 10,000.

```
./mac push channel                          # creates a channel, prints its id
./mac push start <start-token> < start.json # {"id", "design", "channel", "data", "alert"}
./mac push broadcast <channel> < update.json
```

## Conventions

- **Sessions.** `main` is the agent's main session; nights mark where it starts
  a new one. Topics are its other sessions, opened from `main` and linked from it.
- **What the phone keeps.** Conversations, pages, stores with their
  declarations and attachments, components, and the bar's order, names and hidden pages persist across
  launches. Activities are kept by iOS.
- **Drawing well.** Every card comes back as a `rendered` report; fix what it
  says with `patch`. Activities come back as `activity-report` when the app next
  opens.
- **Traps.** What went wrong once and how it was fixed is in
  [docs/footguns.md](footguns.md).
