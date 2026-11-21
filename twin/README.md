<!-- SPDX-FileCopyrightText: 2026 Julien Malka -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->

# The layout twin

The twin lays a card or a page out the way the phone will, without the phone:
every view's frame and every text's lines, at the text size and widths the
phone reported, in about a millisecond. The plugin runs it before a card or a
page leaves (`plugin/dedala/twin/`), so the agent hears about a cut text, a
wrapping button or a word broken across lines before the user sees it. A card
the twin cannot lay out is sent unchecked; the phone's own report on what it
drew comes back either way.

This folder holds the twin's tests and the data they read: cards and pages with
the frames the phone reported for them (`calibration/`), at every text size,
and lines laid out by the phone's own text engine (`calibration/text/`).

## What it needs

The twin lays out with the phone's own system fonts and symbol measurements,
which the phone sends the plugin; nothing of Apple's is in this repository. To
run it here:

| Variable | What it names |
|---|---|
| `BENCH_FONTS` | a folder of the phone's fonts (`SFUI.ttf`, `SFUIItalic.ttf`, `SFUIRounded.ttf`, `SFUIMono.ttf`, `NewYork.ttf`), as the plugin keeps them in `twin/fonts/` of its home |
| `BENCH_SYMBOLS` | a symbol catalog to compare with the phone's frames |
| `BENCH_GLYPHS` | a folder of symbol pictures for the drawings |
| `BENCH_CALIBRATION` | another calibration set |
| `BENCH_TZ` | the time zone dates are laid out in (the tests use the calibration's) |

Tests that need what is missing are skipped.

## Running it

In `nix-shell relay/shell.nix`, from the root of the repository:

| Command | What it does |
|---|---|
| `python -m pytest twin/tests` | the tests: the twin against the phone's frames at every text size, its line breaking and hyphenation against the phone's lines, the faults it reports, and every view and modifier of the grammar |
| `cd plugin && python -m dedala.twin.calibrate all` | every calibration card, with the views that are off |
| `cd plugin && python -m dedala.twin.calibrate sizes` | the same at every text size |
| `cd plugin && python -m dedala.twin.textcheck` | the text engine against the phone's lines |
| `cd plugin && python -m dedala.twin.hyphenate word` | where a word may break |

The test thresholds are what the twin scores today: a regression fails, and an
improvement is kept by raising them.
