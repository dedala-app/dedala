<!-- SPDX-FileCopyrightText: 2026 Julien Malka -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->

# Footguns

Things that went wrong once, why, and what we do now.

## Push and Live Activities

- **APNs answers 200 even when nothing shows.** A push to an activity you swiped
  away is accepted and dropped. Watch the device log (`idevicesyslog` on the Mac)
  or the app's `activity-report`, never the status code alone.
- **iOS drops Live Activity updates sent by the app from the background**, after
  about three in a row, silently; only `end` gets through. Updates go by push.
- **`ViewThatFits` keeps the first child's height in a Live Activity**: the
  fallback is drawn inside the height measured for the full view. The lock
  region uses `FirstFitting` (`Shared/ActivityViews.swift`) instead.
- **The lock screen gives about 160pt, padding included**, and reports nothing
  when content overflows. Hence `lockCompact` and the reports.
- **The start token changes when the app is reinstalled.** Read it again with
  `./mac tokens`.
- **The process that draws Live Activities cannot reach the keychain**
  (`deny mach-lookup com.apple.securityd`): a sealed activity came out as a
  black box. The key that opens what the agent sends lives in the app group
  instead; the device's private key stays in the keychain.
- **Swiping a Live Activity away ends it for good**; to keep updating, start a
  new one.

## Drawing

- **Cards grow after they appear** (maps, images, carousels). Scrolling to the
  bottom when the message arrives left the bottom of the card hidden, and
  `defaultScrollAnchor(.bottom, for: .sizeChanges)` missed the first card of an
  empty conversation. The conversation now tracks whether you are at its end
  and, if so, follows anything that grows.
- **`LazyVStack` estimates the height of what it has not drawn**: jumping to the
  end of a conversation landed past it, leaving the newest card under the
  header above an empty screen. Conversations use a `VStack`.
- **A `say` with an id already in the conversation added a second message**
  with the same id, and their reports measured each other's position. A known
  id now replaces its message, as the protocol says.
- **Measurements outlived the elements they measured**: after a patch removed
  elements, their old frames were still reported as sticking out, and the agent
  patched ghosts. Each measured path now declares itself as a preference on
  every render, and only those are reported. `.preference` replaces what the
  children declared; `.transformPreference` adds to it.
- **A score can wrap without being cut**: "3 –" over "0" passed every check. A
  text of a few characters spread over several lines is now reported, and so is
  one squeezed narrower than its line.
- **A card drawn without a `Card` floated on the conversation's background**,
  and the vision review did not mind. Cards without a surface of their own now
  get one, without doubling the padding.
- **ForEach items need unique identities** across the whole card; the renderer
  prefixes them with the ForEach's id. Duplicates broke a neighbouring card.
- **`ImageRenderer` cannot draw a system `ProgressView`** (it shows a yellow bar
  with a 🚫). Linear progress is drawn by `ProgressBar` in plain SwiftUI.
- **Wikimedia only serves thumbnails at standard widths** (e.g. 330px); other
  widths answer with an HTML error page.

## Development loop

- **The drive server only listens while the app is in the foreground.** Open the
  app before `./mac draw`.
- **`iproxy` goes stale** after the Mac sleeps or the app is reinstalled
  (`Connection reset by peer`). Kill it; the next `./mac` command restarts it.
- **`./mac events` empties the queue.** Reading events to peek loses them for
  whoever else was waiting on them.
- **The Mac mini sleeps** and drops off Tailscale; keep it awake.
- **A generated Info.plist ignores `INFOPLIST_KEY_UIBackgroundModes`**; such keys
  need a real Info.plist merged in.
- **Everything in `Hermes/UI` is compiled into the widget and notification
  extensions too.** What needs the hub or the app's window (the hub itself, a
  page's screen, the drive server) lives outside it, in `Hermes/Hub` and
  `Hermes/Pages`.
- **Only debug builds had ever been compiled**, so code kept for release called
  code that exists only in debug, and a Release build failed. The drive server
  and its routes are debug-only as a whole; a Release build for the simulator
  (`xcodebuild -configuration Release`) checks it.
- **Tests ran on the app's own files** in the simulator: a test's edits landed in
  the outbox a paired app sends. Under test, `Storage` keeps everything in a
  folder of its own.

## The agent

- **An agent told only "Platform: app" answers in text.** Its skills sit in a
  long index and nothing says the platform draws. The plugin's `platform_hint`
  says so in the system prompt.
- **A clean render report is not a good card.** Nothing cut or broken still
  allows a flat, cramped, badly wrapped card. Each capture now comes back with a
  `review` for `vision_analyze`, which a vision model answers as a designer.
- **The skills on the agent's machine are copied once** so the agent can edit them; a
  deploy does not update them. Compare the installed `SKILL.md` with the
  version that was installed before replacing it, and merge if the agent
  changed it.
- **Hermes sends a "⏳ Working — N min" message every three minutes of a long
  turn**, edited in place where a platform can edit. The app could not, so each
  one became a new bubble. Mid-turn status (`_interim_send`) now goes to the
  working line above the composer, edited in place.
- **Hermes hides plugin tools behind `tool_search` / `tool_call`.** Through the
  bridge, arguments travel as a JSON string inside JSON; a 15k-character vault
  note broke it ("calls is not valid JSON"), and the agent went reading the
  plugin's code and keys to find another way. The plugin now adds its `app`
  toolset to the toolsets Hermes keeps direct (`_DIRECT_SURFACE_TOOLSETS`, a
  Hermes internal: check it after a Hermes upgrade). `app_vault` also takes a
  path, so no document goes through a tool call.
- **A card sent while the app is closed was never checked.** No render report,
  no review: a `VStack` given `{"spacing", "children"}` instead of a list
  reached the phone broken. The plugin now checks every view against the app's
  grammar (`plugin/dedala/grammar.json`, kept equal to the app by
  `GrammarTests`) and refuses to send a broken one; reports the phone makes
  later, with nobody waiting, go to the agent instead of the log.
- **The agent writes its workarounds into its skills.** After the vault hack,
  its `living-in-the-app` copy said to build vault ops in `execute_code` and to
  answer "show me my note" with a summary card. Read the installed skills after
  an incident and correct what it learned from a missing tool.
- **A plugin platform without a display tier gets Hermes's loudest defaults**:
  every tool call was sent as a message ("tool_progress: all"), and the app made
  each one a bubble. The plugin turns tool progress off; the adapter declares
  `supports_status_text`, so the running tool shows as the working line, and a
  `post_tool_call` hook keeps each call as a step of the agent's next message.
- **Pages had no feedback, so a page was written blind in one huge call.** The
  model spent 11 minutes on it and the request never came back. Pages are now
  laid out before they leave (`app_page`), and the skill builds them widget by
  widget.
- **A view passed to a component lost its loop variables.** Props were resolved
  deeply in the caller, so `$item` inside a `ForEach` handed to a widget became
  null before the loop could bind it, and a `ForEach` at the root of such a view
  drew "Unknown view". Found by the first page report.
- **What the agent built was only in the plugin's record**, so to answer "do you
  see your pages" or to change a widget, it read `link.json`. `app_page` now
  lists pages and returns a page's view, components and data; `app_vault` lists
  an item's versions. A store `patch` was also recorded in place of the data it
  patched, so a re-paired phone got only the last patch.
- **A long tool call looked like nothing happening.** The working line showed a
  tool only while it ran, and nothing while the model wrote, which for a page
  can last minutes. Presence now carries the turn's steps, what is happening
  now and a token count: text and reasoning from Hermes's stream hooks
  (`plugins.stream_reasoning_deltas` in config), a tool call's arguments from
  the accumulator that assembles them (a Hermes internal).
- **Hermes acknowledges a message sent mid-turn with a chat message** ("⏩ Steered
  into current run…", plus a first-time tip about /busy), indistinguishable
  from a reply. The plugin turns it off for the app (`busy_steer_ack_enabled`),
  and the app notes under your message that it arrives after the current step.
- **A restart left the turn "under way" forever.** The old gateway's last words
  ("⚠ Hermes is shutting down…") arrived as what the agent was doing, and the
  process died without clearing it. The plugin now clears every turn when the
  gateway stops and sends Hermes's warnings as messages; presence is repeated
  every 10 seconds, and the app lets a turn silent for 30 go.
- **The review loop undid what he asked for.** Rounds carried over from one
  request to the next, and on a last round still at FIX (over a widget he had
  not mentioned) the plugin put back an earlier round, the one with the button
  he had just asked to remove. Rounds now restart with each message. The
  designer's review is gone from pages: it judged the whole page on every edit,
  so it flagged widgets nobody touched, and its real catches were already in the
  render report. If pages need a judge, it should judge the layout between
  widgets, not inside them. It came back with the twin's check on
  2026-10-30 without anyone deciding so, and was removed again on 2026-11-06:
  a page is laid out by the twin and nothing else.
- **Putting back "the best round" did more harm than good, on cards too.** It
  chose by the number of points in the critique, so it restored a card three
  times the screen's height over the nearly fitting last round; the agent
  missed the line saying so and told the user it was fixed; and the restored
  card's render report, with nobody waiting, came back as a late problem and
  started the agent again after it had said it was done. Removed: the last
  round stays, and the agent is told not to call it fixed if problems remain.
- **The tab bar sets its selection by itself while laying out.** Taking "the
  same tab set again" as a tap (iOS has no reselect API, and its own reselect
  scrolls to the top, the oldest message) fed a layout loop with the keyboard
  open: scroll to the bottom, layout, selection set again… until the watchdog
  killed the app. A reselect now counts only when isolated (0.3 s since the
  last set), and the selection is written only when it changes. Shared card
  settings are kept in memory and written only on a change, not read on every
  frame.
