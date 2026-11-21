# Hermes UI

The language an agent uses to draw on the phone. A card is a tree of nodes written
in JSON; the app interprets it with real SwiftUI views. Nothing is compiled or
downloaded: the tree is data, the views are Apple's.

Three ideas carry the whole design:

1. **Nodes mirror SwiftUI.** `VStack`, `Text`, `Chart`, `Map`, `Toggle`… with the
   modifiers you would write in Swift. If you know SwiftUI you can read a card.
2. **Components are written in the language itself.** The agent defines `Flight`
   once, then sends `{"Flight": {…}}`. The app ships with no card types.
3. **Values are expressions over data and state.** Cards carry their own state
   (`$slot`), react to input without a round trip, and update in place when the
   server patches their data.

## Nodes

A node is one of:

- a **string**: a `Text`. `"Gate ${gate}"` interpolates; a string that is only a
  reference (`"$content"`) renders whatever the reference holds, so a node can be
  passed as data.
- an **array**: a `VStack(alignment: .leading, spacing: 12)` of its items.
- an **object** with exactly one capitalised key, the view. Its value is the view's
  main argument; the other keys are the view's arguments and modifiers.

```json
{"VStack": ["Hello", {"Text": "World", "font": "title.bold"}], "spacing": 4, "padding": 16}
```

### Layout

| Node | Main argument | Arguments |
|---|---|---|
| `VStack`, `HStack`, `ZStack` | children | `spacing`, `alignment` |
| `Grid` | rows, each an array of cells | `hSpacing`, `vSpacing`, `alignment` |
| `Columns` | children, flowed into a grid | `count` (default 2) or `minWidth` (adaptive), `spacing` |
| `ScrollView` | children | `axis` (`vertical`, `horizontal`), `paging` |
| `Carousel` | children, one page each | `spacing`, `pageWidth` (0…1 of the container, default 0.85) |
| `Pages` | children, swiped like a photo album | `height`, `dots` |
| `Group` | children | |
| `Card` | children | `spacing`. A padded, rounded, card-coloured `VStack` |
| `Section` | title | `content` (children), `footer` |
| `DisclosureGroup` | title | `content` (children), `expanded` (state reference) |
| `GlassGroup` | children | `spacing`. A `GlassEffectContainer` |
| `Spacer` | minimum length or `{}` | |
| `Divider` | `{}` | |

### Content

| Node | Main argument | Arguments |
|---|---|---|
| `Text` | string, or `{"date": …, "style": …}`, `{"timer": date}`, `{"countdown": date}` | Markdown is honoured inline |
| `Label` | `[title, symbol]` | |
| `Image` | SF Symbol name, or `{"asset": …}` (sent with the `assets` op), or `{"url": …}`, or `{"symbol": …, "variable": 0…1}` | `contentMode` (`fit`, `fill`) |
| `Color` | colour | |
| `Gradient` | colours | `direction` (`down`, `up`, `right`, `left`, `diagonal`), `kind` (`linear`, `radial`, `angular`) |
| `Circle`, `Capsule`, `Rectangle`, `Ellipse` | `{}` | `fill`, `stroke`, `lineWidth` |
| `RoundedRectangle` | corner radius | `fill`, `stroke`, `lineWidth` |
| `Path` | points `[[x, y], …]` in 0…1 of the frame | `closed`, `smooth`, `fill`, `stroke`, `lineWidth` |
| `Chart` | marks | `xAxis`, `yAxis` (false hides), `yDomain`, `legend` |
| `Map` | `{"markers": […], "route": […], "distance": metres}` | `style` (`standard`, `imagery`, `hybrid`), `interactive`. One place, or a `distance`, puts the camera that high above it (1.5km by default); several places are framed together |
| `Gauge` | value | `in`, `label`, `current`, `min`, `max`, `style` (`circular`, `capacity`, `linear`, `bar`) |
| `ProgressView` | value, or `null` for a spinner | `total`, `label` |
| `Link` | title | `url` |
| `QRCode` | the text to encode | Drawn on the phone, 160 points square unless framed |
| `Face` | size in points (56 by default), or `{"size": …}` | The agent's own face, alive: it looks up while he works |
| `Said` | a card's id | A card you said, drawn as in the conversation and answerable here: the answer goes to its conversation. Once dealt with, its receipt. For what `$waiting` lists: `{"ForEach": "$waiting", "as": "w", "content": {"Said": "${w.card}"}}` |
| `File` | a record's `file` (protocol.md, Data), a text store or a folder record, or a text | The file drawn natively by its format: PDF pages, Markdown and Org rendered (headings, lists and tasks, tables, folding), an image, plain text, any other document through Quick Look. A file not yet on the phone is fetched when first shown, with its progress; one over 50 MB waits for a tap on Download. Links are live: a web address opens outside, a link to another file of a folder store (`[[denote:ID]]`, `[[file:…]]`, `[[wikilink]]`, `[…](x.md)`) opens that record's declared screen on the same stack. A record's own title and keywords are its fields (`title`, `date`, `tags`…), for the screen to draw, so the file shows its body. `height` caps it, scrolling inside; without it the file takes its height, which is what a screen wants |

**Chart marks** are objects: `type` (`line`, `area`, `bar`, `point`, `rule`,
`sector`), `data` (an array of objects, or a reference), `x` and `y` (keys in each
object), and optionally `series` (a key, one colour per value), `colors` (series
name → colour, `{"Desktop": "blue", "Mobile": "teal"}`), `color`, `grouped` (bars of
a series side by side instead of stacked), `smooth`, `gradient` (areas),
`innerRadius` (sectors, 0…1), `label` (a key whose value is written above each bar
or point), `xLabel` (a key shown on the x axis in place of `x`, so twelve months can
read `J F M…` while each bar keeps its own `x`). A `rule` with `value` draws a
horizontal threshold.

**Map markers**: `lat`, `lon`, `title`, `symbol`, `color`. `route` is an array of
`[lat, lon]`, drawn as a line.

### Input

Every input binds to a state variable with `bind: "$name"`. Given `onChange`,
an action, it runs it with the new value as `$value` each time it changes. An
input can also bind to a field of something in scope (`bind: "$item.done"`):
it then shows the field and changes nothing itself, so it needs an `onChange`
that does, an `edit` of the store the field belongs to. Inside a
`ForEach`, an input can bind to its own entry of a state object, keyed by the row:
`bind: "$on[row.id]"` with `"state": {"on": {}}` gives every row its own toggle,
and a `DisclosureGroup`'s `expanded: "$open[row.id]"` its own fold.

| Node | Main argument | Arguments |
|---|---|---|
| `Button` | title, or a node for the label | `action`, `symbol`, `style` (`prominent`, `glass`, `bordered`, `borderedProminent`, `plain`, `borderless`), `role` (`destructive`, `cancel`) |
| `Menu` | title, `""` with a `symbol` for an icon alone (the `…` of a row), or a node for the label | `items` (titled actions, as `actions` below: `title`, `symbol`, `role`, the action), `symbol`, `style` (`bordered`, `borderedProminent`, `glass`). Opens on a tap |
| `Toggle` | title | `bind` |
| `Picker` | title | `bind`, `options` (strings, or `{label, value, symbol}`), `style` (`segmented`, `menu`, `wheel`, `inline`, `palette`) |
| `Slider` | title | `bind`, `in`, `step` |
| `Stepper` | title | `bind`, `in`, `step` |
| `TextField` | placeholder | `bind`, `multiline`, `lines` (reserves that many lines and grows to 8), `style` (`filled` by default: a soft grey field that reads anywhere; `plain` for a field that is a row of a panel, beside its label, as in Settings; `bordered`), `secure` (a password: dots, never shown) |
| `DatePicker` | title | `bind`, `components` (`date`, `time`, `both`), `style` (`compact`, `graphical`, `wheel`) |
| `TextEditor` | placeholder | `bind`, `height` (its height; without it, 200pt, growing with the text), `font` (`body` by default, `mono` for a note or code). A whole text, with the keyboard's toolbar; the cursor stays where it is when the page is redrawn |
| `Photo` | title | `bind`, `source` (`camera`, `library`, or both by default). A button that takes or picks a photo and shows it; the bound value is the picture on the phone (`{name, size, type, local}`), shown by `File` and `Image`, and sent to the agent's machine when an `edit` carries it (protocol.md, Events: `edits`), where it lands as an attachment |
| `Dictate` | title | `bind`, `append` (true adds to what the state holds, with a space). A microphone button; while it listens, what you say is recognised on the phone and written to the bound state as you speak |

### Flow

```json
{"If": "count(items) == 0", "then": "All done", "else": {"ForEach": "$items", "as": "item", "content": "${item.name}"}}
```

- `If`: an expression; `then`, `else` nodes.
- `ForEach`: a list; `as` names the element (default `item`), `index` names the
  position (default `index`); `content` is the node. Elements with an `id` keep
  their identity across updates, so insertions and removals animate. With
  `onMove`, its rows can be held and dragged into another order: `true` when
  the list is a state or a store (`$tasks`, `$data.tasks`), which takes the new
  order itself, the store edited and so told to the agent; or an action, run with
  `$from`, `$to`, `$item` and `$order` (the whole list, in its new order).
- What else is written on a `ForEach` or a `List` (`onTap`, `actions`,
  `padding`, `background`…) applies to each of its rows, with the row in
  scope, as a modifier on a SwiftUI `ForEach` does: `{"ForEach": "$notes",
  "as": "n", "content": {"NoteRow": {"note": "$n"}}, "onTap": {"show":
  "Note", "with": {"id": "$n.id"}}}` opens the tapped note. Written inside
  `content` it means the same.
- `List`: a `ForEach` for a long list, its rows drawn only as they scroll
  into view, so five hundred notes cost what a screen of them costs. Same
  arguments; no `onMove`. Takes the width; separators between the rows. The
  checks (the plugin's and the phone's) draw its first twelve rows and take
  the rest to look like them, so a page with a List is never "too tall".
  Never box a `List` in a fixed height: the page scrolls, the List with it.

## Modifiers

Written as keys on a node. They apply in this order, which is the order that
reads naturally:

1. **Text and symbols**: `font`, `fontWeight`, `fontDesign`, `bold`, `italic`,
   `foregroundStyle` (alias `color`), `lineLimit`, `truncationMode` (`tail`,
   `middle` for file names, `head`), `lineSpacing`,
   `multilineTextAlignment`, `minimumScaleFactor`, `monospacedDigit`, `monospaced`,
   `textCase`, `tracking`, `contentTransition` (`numericText`, `opacity`,
   `interpolate`), `symbolRenderingMode`, `symbolVariant`, `symbolEffect`
   (`bounce`, `pulse`, `variableColor`, `breathe`, `wiggle`, `rotate`; repeating),
   `imageScale`, `tint`, `controlSize`, `labelStyle`, `aspectRatio`.
2. **Size**: `frame` (`width`, `height`, `minWidth`, `maxWidth`, `minHeight`,
   `maxHeight`, `alignment`; `"infinity"` fills), or the shorthands `width`, `height`,
   `maxWidth`, `maxHeight`. `fixedSize` (`"vertical"`: wraps and grows taller;
   `"horizontal"`; `true`: both, on one line), `layoutPriority`.
3. **Padding**: a number, `true`, or `{"horizontal", "vertical", "top", "leading",
   "bottom", "trailing"}`.
4. **Surface**: `background` (a colour, a gradient, a material, or a node),
   `glassEffect` (`true`, `"regular"`, `"clear"`, or `{variant, tint, interactive,
   shape}`), `cornerRadius`, `clipShape` (`circle`, `capsule`, a radius), `border`
   (a colour or `{color, width, dash}`; `dash: true` or `[6, 4]` dashes it, for a
   drop zone or an empty slot), `overlay` (a node, with `overlayAlignment`),
   `shadow` (`true`, `"soft"`, or `{color, radius, x, y}`).
5. **Margin**: `margin`, padding outside the surface.
6. **Effects**: `opacity`, `scale`, `rotation` (degrees), `offset` (`{x, y}`),
   `blur`, `saturation`, `grayscale`, `zIndex`.
7. **Behaviour**: `onTap` (an action), `disabled`, `transition` (`opacity`,
   `scale`, `slide`, `blur`, `push`, `move:top|bottom|leading|trailing`),
   `accessibilityLabel`.

`hidden` and `visible` take an expression and remove the node. `padding`,
`alignment` and a control's `style` also take one: `"padding": "${compact ? 4 : 12}"`.

When the order matters, `modifiers` takes an ordered array, applied after the
keyed ones: `"modifiers": [{"padding": 8}, {"background": "blue"}, {"padding": 4}]`.

### Tokens

**Colours**: `accent`, `primary`, `secondary`, `tertiary`, `quaternary`,
`background`, `card`, `groupedBackground`, `fill`, `separator`, the system colours
(`red`, `orange`, `yellow`, `green`, `mint`, `teal`, `cyan`, `blue`, `indigo`,
`purple`, `pink`, `brown`, `gray`), `white`, `black`, `clear`. `blue@0.3` sets an
opacity. `#RRGGBB` works but tokens adapt to dark mode and should be preferred.
Materials: `ultraThinMaterial`, `thinMaterial`, `regularMaterial`,
`thickMaterial`. Gradients: `{"gradient": [colours], "direction": …, "kind": …}`.
`tertiary` and `quaternary` are for symbols, chevrons and fills: text never goes
fainter than `secondary`, and a Text or Label set to them shows as `secondary`.

**Fonts**: `largeTitle`, `title`, `title2`, `title3`, `headline`, `subheadline`,
`body`, `callout`, `footnote`, `caption`, `caption2`, followed by any of
`.bold`, `.semibold`, `.medium`, `.heavy`, `.black`, `.light`, `.rounded`,
`.serif`, `.monospaced`, `.italic`: `"title.bold.rounded"`. Or
`{"size": 48, "weight": "bold", "design": "rounded"}`. Text styles scale with
Dynamic Type; fixed sizes do not, so keep them for display numbers.

**Alignments**: `leading`, `center`, `trailing`, `top`, `bottom`, `topLeading`,
`topTrailing`, `bottomLeading`, `bottomTrailing`, `firstTextBaseline`.

## Expressions

Anywhere a value is expected:

- `"$name"` or `"$flight.gate"` is the value itself, of any type.
- `"${expr}"` alone is the value of the expression, of any type.
- `"Gate ${gate} · ${format(price, 'currency:EUR')}"` interpolates into text.

`If`, `hidden`, `visible` and `disabled` take a bare expression.

Expressions have literals (`12`, `'text'`, `true`, `null`, `[1, 2]`), paths
(`flight.gate`, `items[0]`), arithmetic (`+ - * / %`; `+` joins strings),
comparisons, `a && b`, `a || b`, `!a`, and `cond ? a : b`.

| Function | |
|---|---|
| `format(x, spec)` | `number`, `number:1` (fraction digits), `percent`, `currency:EUR`, `currency:USD:2` (always two decimals: `$0.00`), `compact`, `duration` (seconds), `bytes`. Grouping and symbols follow the phone's locale |
| `date(x, style)` | `time`, `date`, `datetime`, `weekday`, `day`, `month`, `dayMonth` (`1 Apr`), `monthYear` (`Apr 2026`), `relative` |
| `count(list)`, `sum(list, key?)`, `avg(list, key?)`, `min(…)`, `max(…)` | `list.length` and `text.length` work too |
| `round(x, digits?)`, `abs(x)`, `clamp(x, lo, hi)` | |
| `upper(s)`, `lower(s)`, `join(list, sep?)`, `pluck(list, key)`, `contains(a, b)` | |
| `filter(list, key, value?)` | elements whose `key` is truthy, or equals `value` |
| `find(list, key, value?)` | the first of them, or null |
| `org(text, type?)`, `markdown(text, type?)` | the text read as a document: the whole tree, or the list of its nodes of one `type` (`org(n.text, 'item')`, `org(n.text, 'headline')`). See The tree of a text |
| `now()` | the current date |

Dates are ISO 8601 strings.

### The tree of a text

`org(text)` and `markdown(text)` read a note into one tree, in the words of
Org's own element API: every node is `{"type", …, "begin", "end", "children"}`,
`begin`/`end` its byte range in the text, `text` its words as read aloud
(markup dropped, a wrapped line joined). The same tree on the phone, in the
plugin's previews and in its edits, so an item a screen shows is the item an
edit names. `org(text, 'item')` is every list item anywhere in the note, in
order; filter it on `checkbox`.

| `type` | properties | holds |
|---|---|---|
| `org-data` | `title`, `keywords` (`{TITLE, FILETAGS, DATE, …}`, Markdown front matter too), `properties` | a `section` of what comes before the first headline, then `headline`s |
| `headline` | `level`, `title`, `todoKeyword`, `todoType` (`todo`/`done`), `priority`, `tags`, `scheduled`/`deadline`/`closed` (timestamps), `properties` (its drawer), `archived`, `commented` | `objects` of its title; `children`: its `section`, then the headlines below it |
| `section` | | elements |
| `paragraph` | `text` | objects |
| `plain-list` | `listType` (`unordered`, `ordered`, `descriptive`) | `item`s |
| `item` | `bullet`, `checkbox` (`on`, `off`, `trans`, or absent), `counter`, `tag` (`term :: text`), `indent`, `text` (its first paragraph, whole) | elements: its paragraph, then nested lists |
| `table` | `tableType`, `hasHeader`, `tblfm` | `table-row`s (`rowType` `standard` or `rule`) of `table-cell`s (`text`, objects) |
| `src-block` | `language`, `parameters`, `value` | |
| `example-block`, `export-block` (`backend`), `comment-block`, `fixed-width`, `comment`, `latex-environment` | `value` | |
| `quote-block`, `center-block`, `verse-block`, `special-block` (`blockType`), `drawer` (`drawerName`), `footnote-definition` (`label`) | | elements |
| `keyword` | `key`, `value` | |
| `clock` | `status`, `duration`, `value` | |
| `horizontal-rule`, `babel-call` | | |
| objects: `plain-text` (`value`), `bold`, `italic`, `underline`, `strike-through`, `superscript`, `subscript` | | objects |
| `link` | `linkType` (`https`, `denote`, `id`, `file`, `fuzzy`…), `path`, `rawLink`, `searchOption`, `isImage`, `text` | objects of its description |
| `timestamp` | `timestampType` (`active`, `inactive`, `-range`, `diary`), `start`, `end` (ISO), `rawValue`, `repeater`, `warning` | |
| `code`, `verbatim`, `statistics-cookie`, `latex-fragment`, `target`, `inline-src-block` (`language`), `export-snippet` (`backend`) | `value` | |
| `entity` (`name`, `utf8`), `footnote-reference` (`label`), `macro` (`key`, `args`), `line-break`, `radio-target` | | |

Each `item` also carries `checkboxBegin`/`checkboxEnd` and `contentBegin`/`contentEnd`,
the places an edit rewrites; a screen has no use for them.

## State and data

A card has **data**, sent by the server and patched by it, and **state**, owned by
the card on the phone. `state` on any node declares variables for its subtree:

```json
{"VStack": [
  {"Picker": "Slot", "bind": "$slot", "options": ["09:00", "11:00", "14:00"], "style": "segmented"},
  "You picked ${slot}"
], "state": {"slot": "11:00"}}
```

Names resolve from the innermost scope out, the same on a card and a page:
`ForEach` variables and component props, then state, then derived values, then
a card's own data, then a store of that name, then a live value. A page has no
data of its own: it reads stores by name, `$note.echo`, as any card does,
`${note.echo_at}`. A card's own data keeps what it was sent; what it reads
from a store changes with the store.

What each is, on a card that splits a bill:

- **data** is what the agent knows and sends: `{"total": 84.5, "people": ["Alex", "Manon", "Théo"]}`.
  The phone only reads it; a patch from the agent merges into it.
- **state** is the card's memory on the phone, your choices: `{"tip": 10, "left_out": []}`.
  The agent gives its first values; your taps change it. It is kept, through
  scrolling and restarts, and stays on the phone unless an action sends it. A
  patch with `state` sets those values over yours; on a page, yours stay.
- **derived values** follow from both, computed on the phone by a script (below):
  each person's share, recomputed on every tap.

## Time and live values

`now()` is the current time, and it moves: a view that reads it is drawn again
every minute, or every second with `now('seconds')`. `until(date)` reads "in 3
days", "in 12 min", "now"; `ago(date)` reads "2 h ago", "yesterday";
`isToday(date)` and `isPast(date)` are booleans.

The app also keeps a few values up to date from what it holds. Any card or page
reads them by name; a component receives them as props.

| Value | What it is |
|---|---|
| `$waiting` | Cards still asking you something, newest first: they have a button that sends to the agent, are not answered, and are less than 7 days old. `[{card, conversation, topic, said, at}]` |
| `$running` | What is under way: `{turns: [{conversation, topic, doing, since, tokens}], runs: [{id, job, name, doing, since}]}` |
| `$today` | Since midnight: `{answered: [{card, said, at}], runs: [{job, name, status, finished}], messages}` |
| `$pages` | Every page: `[{id, title, symbol, store, bar, updated}]`; `bar` says whether it is in the bar |
| `$commands` | The last run of each command, by name: `{<name>: {status, result, error, at, duration, args}}`. `status` is `running` from the tap, then `done` or `failed` as the plugin answers (Actions, `command`) |

They are computed on the phone and never sent anywhere. A card drawn by the
notification extension, while the app is closed, sees them empty.

## Scripts

A card or page can carry a **script**: JavaScript functions that compute from what
is already on the phone. Scripts never reach the network, never read the clock
(they are given the time), and never see anything but their own card or page and
the live values. New facts only come from the agent.

```json
{"op": "say", "id": "split", "text": "Last night's dinner",
 "card": {
   "data": {"total": 84.5, "currency": "EUR", "people": ["Alex", "Manon", "Théo"]},
   "state": {"tip": 10, "paid_by": "Alex", "left_out": []},
   "script": "function shares({data, state}) { const who = data.people.filter(p => !state.left_out.includes(p)); const each = data.total * (1 + state.tip / 100) / who.length; return who.map(p => ({name: p, owes: p == state.paid_by ? 0 : h.round(each, 2)})) }\nfunction ask(input) { return {send: {split: shares(input)}, say: 'Ask them'} }",
   "derive": {"shares": "shares"},
   "view": {"Split": {"shares": "$shares", "currency": "$currency"}}
 }}
```

Every function receives one object: `{data, state, stores, now, waiting, running,
today, pages, commands, args}`: on a card, `data` is the card's; on a page it
is empty, and `stores` holds the stores the script names, as the view reads
them, text stores among them:
`stores.daily.lines` or `stores['daily']` gives it `daily`, and its changes run
the script again. `now` is an ISO 8601 date: the
minute a derived value is computed in, the second of the tap for a handler.
Dates are formatted in the phone's time zone. A stopwatch keeps when it started
in state (`{"set": {"started": "${now('seconds')}"}}`) and shows it with
`{"Text": {"timer": "$started"}}`, which counts on its own.

- **Derived values.** `derive` maps a name to a function. Its result is a value the
  view reads by that name, recomputed when the data, the state or a live value
  changes, and every minute. It must be JSON; a name cannot also be a data key.
- **Handlers.** `{"run": "ask", "args": …}` is an action: the function runs and
  returns what happens next, any of `state` (merged into the state, animated),
  `send` and `say` (as the `send` action), `edit`, `command` and `args`, `open`,
  `page`, `conversation`, `card`, `haptic`.
  It can return nothing.
- **Shared modules.** `{"op": "define", "scripts": {"invoices": "function unpaid(documents) { … }\nreturn {unpaid}"}}`
  defines a module once; any script then calls `invoices.unpaid(stores.documents)`. A module
  ends with `return {…}`, what it exports.
- **Limits.** A derived value and a handler have 500 ms each — enough to read a vault of notes with `h.org` once, the trees are then remembered; a result is at most
  256 KB. A script that throws or runs out of time leaves its value `null` and is
  reported to the agent; one that runs out of time twice is switched off until
  the card or page is sent again.

Every script also has `h`:

| Helper | |
|---|---|
| `h.until(date, now)` | `{days, hours, minutes, text}`: `text` is "in 3 days", "in 12 min", "now" |
| `h.ago(date, now)` | "2 h ago", "yesterday" |
| `h.isToday(date, now)`, `h.isPast(date, now)`, `h.startOfDay(now)` | |
| `h.time(date)`, `h.day(date)` | "14:05", "Sun 25 Oct" |
| `h.next(list, key, now)` | the first element whose date `key` is still ahead |
| `h.sortBy(list, key, {desc})`, `h.groupBy(list, key)`, `h.unique(list, key)` | |
| `h.sum(list, key)`, `h.round(x, digits)`, `h.money(x, currency)`, `h.percent(x)` | |
| `h.org(text, type?)`, `h.markdown(text, type?)` | the text read as its tree, or the list of its nodes of one `type` (The tree of a text): `h.org(f.text, 'item').filter(i => i.checkbox == 'off')` |
| `h.waiting.byTopic()`, `h.waiting.oldest(n)`, `h.running.any()` | |

The helpers only know what the app defines. What a record's own fields mean
(an amount, a due date) is for the agent's modules.

**Checked before it reaches the phone.** The plugin runs every script on the
Hermes machine first, in a JavaScript engine with the same inputs: derived values
on the card's data and first state, with a sample of each live value; handlers
on the examples the agent gives (`"examples": [{"run": "ask", "state": {…}, "now": "…"}]`),
or once on the first state. A script that throws, runs out of time or returns
something that is not JSON is not sent; the agent gets the error. The render
report then carries each derived value as the phone computed it, in `derived`.

## Actions

`action` on a `Button` and `onTap` on any node take an action object or an array
of them, run in order. One object can hold several verbs: they run in a fixed
order, what reads the state first (`send`, `edit`, `command`, `run`, `copy`,
`shortcut`), then what changes it (`set`, `toggle`), then `haptic` and what
leaves the screen. So `{"edit": {"store": "daily", "append": "$text"}, "set":
{"text": ""}}` appends what was typed, then clears it.

| Action | |
|---|---|
| `{"send": payload}` | back to the agent, with the payload resolved, as a message in the conversation: it starts a turn. `say` sets the line shown as your reply (default: the button's title) |
| `{"edit": {"store": id, …fields}}` | changes a store on the phone at once (protocol.md, Data): `{"store": id, …fields}` merges into a JSON store, `{"store": id, "replace": data}` replaces it; `{"store": id, "id": record, …fields}` patches one record, `{"store": id, "add": {…}}` adds one (an `id` of its own, or one the phone makes), `{"store": id, "remove": record}` removes one. The agent hears of it once you stop (protocol.md, Events: `edits`), without a turn. On a text store, or with `id` on a folder store, the fields are line edits: `append: line` (or `[lines]`, with `done` for a ticked or unticked one), `change: line, to: new`, `remove: line`, `toggle: line`, `text: whole`; on a folder store `add: name, text` makes a file and `id, delete: true` deletes one. Shown at once, written to the file by the plugin within a second, the store's `sync` saying `pending`, `synced` or `failed` with its `error` |
| `{"command": name, "args": …}` | runs a command on the agent's machine, a program the agent bound to that name, with no model on the way: sent at once, kept until the plugin answers, never run twice. `$commands.<name>` shows it `running` from the tap, then `done` with its `result` or `failed` with its `error`; what the program writes to a store shows through the store. One run of a command at a time: a tap while it runs does nothing and the agent is told |
| `{"set": {"name": value}}` | changes state, animated |
| `{"toggle": "name"}` | flips a boolean |
| `{"open": url}` | |
| `{"page": id}` | opens one of your pages |
| `{"conversation": id}` | opens a conversation: `main`, or a topic's id |
| `{"card": id}` | opens the conversation holding that card, scrolled to it and lit up |
| `{"call": number}`, `{"message": number}`, `{"mail": address}` | |
| `{"directions": {"lat", "lon", "name"}}` | opens Maps |
| `{"copy": text}` | |
| `{"shortcut": name, "input": text}` | runs a Shortcut |
| `{"haptic": "success"}` | `success`, `warning`, `error`, `light`, `medium`, `heavy`, `selection` |
| `{"run": name, "args": …}` | runs a handler of the card's or page's script (see Scripts) |
| `{"show": Name, "with": props}` | opens a component as a screen over the page (see Screens); `"as": "sheet"` opens it as a sheet instead, `"replace": true` puts it in the place of the screen on top |
| `{"close": true}` | back one screen; `{"close": "all"}` back to the page, and out of the sheet when it is in one |

`"require": "faceid"` on an action asks for Face ID first.

An action, or a step of one, can also be written as a reference: `"action":
"$onPick"` runs the action a component was handed under that name
(Components), and `"$item.action"` one that the data holds; a reference to
nothing does nothing.

An action that cannot do what it says when it runs (a `card` or
`conversation` that is not there, an `edit` the phone refuses, a handler that
throws or runs out of time) does nothing on screen, and the agent is told:
which card or page, what you tapped, and why (protocol.md, Events: `failed`).
Once per problem, until the card or page is sent again.

### Actions on a node

```json
{"TaskRow": {"task": "$item"}, "actions": [
  {"title": "Done", "symbol": "checkmark", "edit": {"store": "tasks", "id": "$item.id", "done": true}},
  {"title": "Later", "symbol": "clock", "edge": "leading", "edit": {"store": "tasks", "id": "$item.id", "due": "tomorrow"}},
  {"title": "Forget", "symbol": "trash", "role": "destructive", "edit": {"store": "tasks", "remove": "$item.id"}}
]}
```

`actions` on any node is a list of titled actions: `title`, `symbol`, `role`
(`destructive`), `edge` (`leading`, else trailing), and the action itself, any
of the table above. Holding the node shows them as a menu. A node that is a row
of a `ForEach` also swipes: pulled a little, the actions of that edge show as
buttons; pulled past half the row, the first one runs when you let go. Rows of a
`ForEach` with `onMove` drag on hold instead of showing the menu, so their
actions are on the swipe.

## Components

```json
{"op": "define", "components": {
  "Flight": {
    "props": {"number": "", "from": "", "to": "", "departs": null, "gate": null},
    "body": {"Card": [
      {"HStack": [{"Text": "$number", "font": "headline"}, {"Spacer": {}}, {"Text": {"timer": "$departs"}, "monospacedDigit": true}]},
      {"HStack": [{"Text": "$from"}, {"Image": "airplane"}, {"Text": "$to"}], "font": "title.bold"},
      {"If": "gate", "then": {"Label": ["Gate ${gate}", "door.left.hand.open"], "foregroundStyle": "secondary"}}
    ]}
  }
}}
```

`props` gives each prop its default. A component's body reads only its props and
its own state, not the data, state or derived values of what draws it: pass
them. Components can use other components; they can declare `state`, kept
through scrolling and restarts like a card's. Its buttons can run the script of
the card or page that draws it: `{"run": "ask", "args": "$name"}` in a
component calls that script's `ask`, and the `state` it returns changes the
card's or page's state.

A prop can be an action. The caller writes it, `{"Chip": {"label": "$item.name",
"onPick": {"toggle": "open"}}}`, and the component runs it by its name,
`{"Button": "$label", "action": "$onPick"}`. It runs where it was written: it
reads the caller's values, changes the caller's state and runs the caller's
script. `$value` in it is the component's own `$value` where it runs it: what
its input changed to, when the component gives it as an `onChange`. A prop left
out runs its default, or nothing.

A prop can be a view, so a component can wrap others (a widget's card around
its `content`): the view is filled in with the caller's values where it is
written, and what it binds itself, like the `$item` of a `ForEach` inside it,
stays for where it is drawn. `ForEach` and `If` can stand on their own as a
view.
Modifiers on the call apply to the component: `{"Flight": {…}, "margin": 8}`.
A component defined as `null` is deleted: `{"op": "define", "components": {"Flight": null}}`.
The plugin refuses while a page or another component still draws it. A view of
the app's own (`Face`, `Said`) wins over a component of the same name.

## Screens

A component opened on its own is a screen: `{"show": "Invoice", "with": {"id":
"$it.id"}}` on a row pushes it over the page, with its `title` in the bar and
the way back; from a card in the conversation, or with `"as": "sheet"`, it opens
as a sheet, with its own stack. `with` is what the component is called with,
resolved where the tap is, so `$it` of the row works; one value instead of an
object is the component's `value`. A screen reads its props and the stores by name,
as a component does, and runs the page's script. Its `state` lasts
while it is open. A page is a screen with no props, in the bar; a component is
a screen when it is shown, a fragment when it is drawn inside another.

```json
{"op": "define", "components": {
  "Invoice": {
    "props": ["id"],
    "title": "Invoice ${find(invoices.items, 'id', $id).number}",
    "body": {"VStack": [
      {"Text": "${find(invoices.items, 'id', $id).client}", "font": "title"},
      {"Button": "Mark paid", "action": {"edit": {"store": "invoices", "items": "…"}, "close": true}}
    ]}
  }
}}
```

A flow is screens that open screens: a list that shows `Amount` with the client
picked, whose button shows `Done` with `"replace": true`, so the way back skips
the form, whose button edits the store and closes `"all"`. Nothing in it costs a
turn until the edit reaches the agent. An action handed in `with` runs where it
was written, as for a component drawn in place.

### The bar

A screen or a page can put buttons in its bar, beside the app's own (the way
back or Close, the page's menu): `toolbar`, a list of up to three `Button`s or
`Menu`s, each with a `symbol`, which is what the bar shows, and a title, which
is the label read aloud. They run in the scope of the body: its props, state,
script and the stores, so `$id` and `set` work, and `hidden` takes one out.
The bar styles them itself; `style` is refused. Without `toolbar` nothing
changes.

```json
"Note": {
  "props": ["id"],
  "title": "${find(notes, 'id', $id).title}",
  "toolbar": [
    {"Button": "Info", "symbol": "info.circle", "action": {"show": "NoteInfo", "with": {"id": "$id"}, "as": "sheet"}},
    {"Menu": "More", "symbol": "ellipsis.circle", "items": [
      {"title": "Copy title", "symbol": "doc.on.doc", "copy": "${find(notes, 'id', $id).title}"},
      {"title": "Delete", "symbol": "trash", "role": "destructive", "edit": {"store": "notes", "id": "$id", "delete": true}, "close": true}
    ]}
  ],
  "body": {"File": "${find(notes, 'id', $id)}"}
}
```

## Surfaces

A card in a conversation always sits on a surface. Unless the view is one (a
`Card`, `Carousel`, horizontal `ScrollView`, a component, or anything with a
`background` or `glassEffect`) or a stack of nothing but those (a list of
cards), the app puts it in a `Card`, whose padding replaces the root's own. A
`Card` inside another is drawn a shade up, as an inset group. A vertical
`ScrollView` at the root draws no surface and the conversation already scrolls,
so the app draws it as a `VStack` and says so in the rendered report's issues.

## Operations

Cards travel in messages (`say`, `patch`), pages in `page` ops, components in
`define`. What each op carries and what comes back is in [protocol.md](protocol.md);
how to draw well with the reports is the skill, `docs/hermes-ui/skill/SKILL.md`.
