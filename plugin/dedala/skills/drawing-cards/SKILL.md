---
name: drawing-cards
description: How to draw Hermes UI cards in the user's app well - what to draw for a kind of answer, how the check and the reviewer judge it, how to update it, and the lessons drawing has taught. Use before drawing any card, and whenever app_card holds one back, the phone reports a problem, or a card comes back flagged.
---

# Drawing cards

A card is a Hermes UI tree: the language is `references/hermes-ui.md` beside
this skill, with working cards in `references/examples/`. Draw freely, any layout, any composition.
This skill is about drawing well and noticing when you did not.

## What to draw

Decide for the user, and draw the decision well.

- **Draw the thing the way Apple's own app draws it.** An email as Mail shows it
  (the sender as title, the subject, then your note), a route as Maps shows it,
  days as Calendar shows them (date tiles), a choice as a segmented control, a
  timer as Clock shows it. A familiar object beats an invented layout.
- **Your call lives inside that object:** a warning line, the recommended option
  first and selected, the next item highlighted. Never a giant headline or a
  slogan ("Ignore it", "18:30").
- **Curate.** Only the facts that matter for the decision, the alternatives a tap
  away. Show everything only when asked ("a table of…", "all my…").
- **Structure over volume:** tiles, icons, colour that means something, clear
  rows, room to breathe; not huge type or walls of text.
- **Fit the question.** These are habits, not boxes to tick: the calmer card
  that answers what was asked wins.

Shapes that have worked for common questions:

- **"What is X?"**: the name with its licence or version as a small tag beside
  it, one sentence saying what it is, two to four rows of what sets it apart (the
  point in `subheadline.semibold`, one `caption` of how), the caveat that decides
  whether to use it as an orange-icon row at `primary`, the vendor's own numbers
  as a pair of tiles, and one `Link` at the foot. Read the docs, not only the
  landing page, and attribute a benchmark to whoever ran it.
- **"When is X out?"**: the status as one orange-icon row ("No release date
  yet."), then the claims grouped by how sure they are, one row each with who
  said it in `caption` and the date right-aligned after a `Spacer`, and a closing
  caption saying what you checked and when. A rumour is a row marked as one,
  never the header.
- **"Which of these?"**: rows of three zones, the name in
  `subheadline.semibold`, one detail line in `caption`, a short tag
  right-aligned. Four to six rows. Groups get an uppercase `caption.semibold`
  label instead of dividers.
- **A long roster**: a featured group first, then everyone else one `caption`
  line each (`Name — role`), a size down so the long half does not outweigh the
  first. A count in the header must match the rows.
- **A chain of stages** (how something got from one place to another): one row
  per stage, what it does in `caption`, its time right-aligned. Times down the
  right edge read as a timeline.
- **A question you asked**: when the user answers it in words instead of a
  button, do the work and patch that same card into the outcome (its text, the
  state each row ended in, the buttons gone), rather than sending another card.

## While drawing

- Prefer layout to geometry: stacks, grids, spacers and alignment hold at every
  width and text size; offsets and overlays only at the size you imagined.
- One focal point per card; everything else quieter.
- Start with a `Card` or a `VStack`, never a `ScrollView`: the conversation
  scrolls already, and a scroll view draws no surface.
- A card read top to bottom (an email, a recipe) can be longer than the screen;
  keep your call and its buttons near the top. A card that asks for a decision
  fits on one screen.
- Use tokens (`secondary`, `accent`, text styles) so dark mode and the user's
  text size work. Fixed sizes (`font: {"size": 48}`) are for a big number.
- Give every icon-only button an `accessibilityLabel`.
- Look in the card bank (`dedala/bank/`) for a card of the same kind the
  user loved, and start from it.

## How a card is checked

`app_card` lays the card out before it leaves, as the user's phone will draw it,
at their text size and card width. Then:

- **Not sent, with `problems`**: something they would see as broken (a text cut,
  a word or a short label broken across lines, a button too small to tap or
  whose label wraps, text under 11 pt). Fix it and send the whole card again on
  the same id.
- **Not sent, with a `review` saying FIX**: a vision model looked at it as a
  demanding designer would. Apply its critique, or redraw simpler after two
  tries.
- **Sent**: it passed, or that was the last round. Do what `then` says.

`notes` and `data_check` block nothing but are usually right: a view argument
that does nothing where it is, a name that reads nothing, a key named like one of
the app's live values. Nothing reaches the user before the card is sent; a card
left unsent goes as it stands when your turn ends. The phone checks each card
again when it arrives, and tells you what it finds.

The reviewer's critique is your eye. It judges alignment, collisions, clipping,
proportions, hierarchy and legibility, never what the card says. Its taste
(darker greys, more room) is optional; alignment it names is not.

## Updating a card

`app_patch` changes a card already on the phone, in place and animated: a new
score, a gate change. It keeps the card's place, its text and what the user typed.
A patch is not a message: after fixing a flagged card, say nothing; after a fresh
card, one short line at most. To give a card again, send it with `app_card` on
its id: it comes back at the end, its state afresh.

When the user flags a card, the flag carries the phone's report and a capture:
find what is off and fix it with `app_patch`.

## The card bank

When the user taps "Love it", or tells you they like a card and you call
`app_card` with `keep: true` and a note in their words, the card is kept in
`dedala/bank/` with its capture. When several kept cards share a shape, make
it a component.

## Components

Define a component once a layout has proved useful twice (`app_ops` `define`
before the card that draws it, or `components` with `app_page`).

- **A component's own buttons carry their own frame**: modifiers on the call
  apply to the whole component, so a tap target inside it is fixed in its body.
- **A component that takes a label and an action** is worth having from the
  first use: props `{"label": "", "onTap": null}`, body `{"Button": "$label",
  "action": "$onTap"}`. The action runs where it was written, with the caller's
  state.

## Scripts

A card or page can carry a script (`hermes-ui.md`, Scripts) when it has to stay
right on its own or answer taps without a round trip: a countdown that changes
phase, a split as people are toggled, a chronometer (`references/examples/09-stopwatch.json`).

- **Facts come from you, never from a script.** It only rearranges what is on
  the phone: data, state, the time, the live values. No network.
- **No script when an expression does it**: `${until(closes)}`,
  `${count(waiting)}`, `filter(…)`.
- **A tap that goes somewhere is an action, never a `send`**: `{"page": id}`,
  `{"conversation": id}`, `{"card": id}`, `{"show": Name, "with": {"id"}}`. A
  `send` is a message to you; keep it for answers.
- **A change to a thing is an `edit`, never a `send`**: ticking a task,
  reordering a list (building-pages skill, Handling what they do).
- **Small and pure**: functions of their one input, `now` read from it.
- **A handler returns what happens next**: `{state, edit, send, say, open, page,
  card, command, args, haptic}`. Closing a screen or setting state directly is a
  button's action, not a handler's return.
- **A handler can only change state, so a lock it must undo reads state too**:
  `locked = !!data.echo && !state.reopened`.
- **Over a big store, a derived value returns only what the view reads**
  (`{id, title, updated}` per record): it is capped at 256 KB. A screen looks the
  full record up with `find(store, 'id', $id)`.
- **Check what came back**: every send runs the script here first and answers
  with `script_check`. An empty list where you expected items is usually a name
  that does not match the data. Give `examples` for handlers whose outcome
  depends on taps.

## Lessons

What drawing has taught. Put a new one in its group; correct or cut one that
proves wrong.

### Layout

- **Build a line around what sits on it**: an element on a line is a stack
  (`Capsule`, `Image`, `Capsule`, the capsules `maxWidth: "infinity"`), not an
  overlay on a `Path`. Repeated marks are sized to the width.
- **An enlarged tap frame keeps its content on the edge the rows use**
  (`"alignment": "leading"`).
- **A frame applies before the background**: a pill with `maxWidth: "infinity"`
  stretches; centre it between two `Spacer`s.
- **A centred group inside a `Card` needs both** `alignment: "center"` and
  `frame: {"maxWidth": "infinity"}` on its stack: alignment arranges the
  children, the frame centres the stack. A `Card` takes no `alignment`.
- **A long text beside a fixed-width element gets its own row**: a text sharing a
  row with a face or a button gets one line, and is cut. Paths and URLs too.
  A message with its date is a `VStack` (the message, the date under it in
  `caption`), not an `HStack` with a `lineLimit`.
- **A text that wraps inside a `ForEach` row** can be held to one line on the
  phone even when the check passes: put `"fixedSize": "vertical"` on the text
  and on the row's stack. Never `"fixedSize": true` on a text that should
  wrap: it holds it to one line, wider than the screen.
- **Two team names around a score**: equal flexible columns, both centred. The
  edge gaps stay uneven with names of different lengths; that is inherent.
- **Narrow button columns are title-only or icon-only**; three bordered buttons
  get about 94 pt each.
- **Two tiles side by side put the icon in a `Label`**, not a fixed-width column
  beside a large value.
- **A plain-style button still tints its label**: set `foregroundStyle:
  "primary"` on the texts of a tappable row meant to read as text.
- **Give bordered buttons a `tint`**: the default grey label fades on a dark card.
- **Rows that share an icon column build it the same way**: a `Label` places its
  symbol differently from an `HStack` with a fixed-width image.
- **A box-like symbol in a header reads as an unchecked box** when the rows carry
  status marks: leave the header without one.
- **A tappable row is at least 44 pt tall** (`frame: {"minHeight": 44}`, the
  rows' `spacing` 0); when that makes a long list too tall, make the whole group
  the target.

### Text

- **Text wraps on its own**: never pre-wrap with line breaks, they break at the
  user's text size. A text reported `squeezed` is held to one line by a
  `lineLimit`, a `fixedSize` or what sits beside it.
- **Size a `lineLimit` for the longest the data can hold**, not for the sample.
  For a long unbreakable token, `lineLimit` with `minimumScaleFactor`.
- **A number keeps its unit** in one short token; "N of M" is one statement on
  one baseline, not a big number explained by a faint caption.
- **A URL gets its own row**, shortened to a form that still resolves.
- **A caveat that changes the answer** is one closed phrase at `primary`, the
  icon orange.
- **A section that restates the line above it goes.**
- **Never interpolate a list into text** (`${list}` prints JSON): `${count(list)}`.
- **`ago()` and `until()` carry their preposition**: not "last ${ago(x)}".
- **Every field shown gets a fallback** when the data can be empty.
- **Stoppage time is one token**: `45+4′`.
- **Labels the eye must read are `secondary`**, at `subheadline` or above.

### Building the JSON

- **Build a big view from named parts** (a row, a tile, a header) in a script,
  assembled last, and write the arguments file from it each round
  (`from_file`): editing dumped JSON by hand compounds the escaping.
- **A node with no arguments still needs `{}`**: `{"Spacer": {}}`; in Python
  `{"Spacer"}` is a set.
- **Trust the diagnostics over memory** for SF Symbol names.

## Live Activities

See living-in-the-app, Live Activities.
