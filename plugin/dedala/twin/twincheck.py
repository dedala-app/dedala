# SPDX-FileCopyrightText: 2026 Julien Malka
# SPDX-License-Identifier: MIT

"""The twin's faults for a card read on stdin ({view, data, state, …}), as a JSON list of lines on stdout: what a
reader would notice on the phone, read from every text and button the twin lays out at the phone's card widths, or at
the text size and card width the phone reported when the request carries them as `display`."""

import json
import sys

from . import layout

PAGE_MARGIN = 16.0
PAGE_WIDTHS = (370.0, 408.0)
PADDED = {"bordered": 12.0, "borderedProminent": 12.0, "glass": 12.0, "prominent": 12.0}


def short(text: str, n: int = 40) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[: n - 1] + "…"


def boxes(box):
    yield box
    for child in box.children or []:
        if child is not None:
            yield from boxes(child)


def broken(text: str, lines: list[str]) -> str | None:
    """The word a line break falls inside, hyphenated or not; a break after a dash or a slash is not one."""
    words = set(text.split())
    for left, right in zip(lines, lines[1:]):
        head, tail = left.rstrip().split(), right.lstrip().split()
        if not head or not tail or left != left.rstrip():
            continue
        if head[-1].endswith("-") and head[-1][:-1] + tail[0] in words:
            return head[-1][:-1] + tail[0]
        if head[-1][-1] not in "-–—/" and head[-1] + tail[0] in words:
            return head[-1] + tail[0]
    return None


def spill(engine, box, parent) -> str | None:
    """A symbol wider than its frame reaches the element beside it."""
    natural = engine.symbol_size(box.extra["symbol"], box.font)[0]
    x, _, width, _ = box.frame
    if natural <= width + 0.5 or parent is None:
        return None
    frame = box.node.get("frame") if isinstance(box.node.get("frame"), dict) else {}
    share = {"leading": 0.0, "trailing": 1.0}.get(str(frame.get("alignment") or "center").split()[-1].lower(), 0.5)
    left = x + (width - natural) * share
    right = left + natural
    for sibling in parent.children or []:
        if sibling is None or sibling is box or not sibling.frame:
            continue
        sx, _, sw, _ = sibling.frame
        if sw > 0 and left < sx + sw - 0.5 and right > sx + 0.5:
            return f"the symbol {box.extra['symbol']} is {natural:.0f} pt wide in a {width:.0f} pt frame: it runs into what is beside it"
    return None


def walk(box, parent=None):
    yield box, parent
    for child in box.children or []:
        if child is not None:
            yield from walk(child, box)


def past_the_edge(box, width: float):
    """The texts and symbols that run past the card's or the page's edges, but
    those in a carousel, pages or a horizontal scroll view."""
    if box.kind in ("Carousel", "Pages") or box.kind == "ScrollView" and isinstance(box.node, dict) and box.node.get("axis") in ("horizontal", "both"):
        return
    if box.kind in ("Text", "Label", "Image") and box.frame and box.frame[2] >= 0.5:
        x, _, w, _ = box.frame
        if x < -0.5 or x + w > width + 0.5:
            yield box
        return
    for child in box.children or []:
        if child is not None:
            yield from past_the_edge(child, width)


def faults(card: dict, width: float, components: dict | None = None, derived: dict | None = None,
           page: bool = False) -> tuple[list[str], list[str]]:
    """What a reader would see as broken (a text cut by a line or so, a word broken across lines, a label or a
    button wrapping, a button too small to tap, a symbol spilling out of its frame, text under 11 pt), and what is only worth a look (a text shown
    on purpose as a preview of a longer one). A lone last word is no fault: the preview ties it where the text is
    the view's own, and leaves it where the text is data."""
    engine = layout.Engine(card, components, width, derived, page=page)
    engine.run()
    found, notes = [], []
    for box, parent in walk(engine.root):
        source = box.node.get("Text") if box.kind == "Text" and isinstance(box.node, dict) else None
        if isinstance(source, str) and "$" in source and not (box.text or "").strip():
            found.append(f"“{short(source)}” is empty: the text shows nothing")
        if box.kind == "Label" and box.text and box.lines and box.lines[0] > 1 and len(box.text.split()) <= 3:
            found.append(f"the label “{short(box.text)}” wraps onto {box.lines[0]} lines")
        if box.kind in ("Text", "Label") and box.text and (word := broken(box.text, box.extra.get("lines_text") or [])):
            found.append(f"“{word}” is broken across two lines in “{short(box.text)}”")
        if (box.kind == "Image" and box.frame and box.extra.get("symbol") and not box.extra.get("resizable")
                and not box.extra.get("bitmap") and (fault := spill(engine, box, parent))):
            found.append(fault)
    for box in past_the_edge(engine.root, width):
        what = f"“{short(box.text)}”" if box.text else f"the symbol {box.extra.get('symbol') or ''}".rstrip()
        found.append(f"{what} runs past the edge of the screen: {box.frame[2]:.0f} pt wide where there are {width:.0f} "
                     "(a fixedSize true holds a text on one line; \"vertical\" lets it wrap)")
    for box in engine.texts:
        shown, needed = box.lines or (1, 1)
        lines = box.extra.get("lines_text") or [box.text]
        font = box.font
        if needed > shown and box.node.get("lineLimit") is not None and needed > shown + 1:
            notes.append(f"“{short(box.text)}” shows {shown} of its {needed} lines")
        elif needed > shown:
            found.append(f"“{short(box.text)}” is cut: it needs {needed} lines and shows {shown}")
        if font["size"] < 11:
            found.append(f"“{short(box.text)}” is {font['size']:g} pt, under the 11 pt minimum")
    for box in boxes(engine.root):
        if box.kind == "Button" and box.frame and box.frame[2] >= 0.5 and (box.frame[2] < 28 or box.frame[3] < 28):
            found.append(f"the button “{short(box.text or box.extra.get('symbol') or '')}” is a small tap target: "
                         f"{box.frame[2]:.0f}×{box.frame[3]:.0f} pt, under 28")
        if box.kind in ("Button", "Menu") and box.text and box.frame and box.node.get("labelStyle") != "iconOnly":
            font = box.font
            size = font.get("controlSize") or "regular"
            padded = box.node.get("style") in PADDED
            pad = {"small": 10.0, "mini": 10.0, "large": 20.0, "extraLarge": 20.0}.get(size, 12.0) if padded else 0.0
            points = float(layout.STYLES["subheadline"][0]) if size in ("small", "mini") and padded else font["size"]
            room = box.frame[2] - 2 * pad
            if layout.advance(box.text, font["design"], font["weight"], points, font["italic"]) > room + 1.0:
                found.append(f"the button “{short(box.text)}” does not fit on one line ({room:.0f} pt of room)")
    return found, notes


# A widget's width, height and WidgetKit's margin around its content, by size, on the smaller iPhones (393 pt
# wide): what fits these fits the larger phones' too.
WIDGETS = {"small": (158.0, 158.0, 16.0), "medium": (338.0, 158.0, 16.0), "large": (338.0, 354.0, 16.0),
           "rectangular": (160.0, 72.0, 0.0), "circular": (72.0, 72.0, 0.0), "inline": (234.0, 26.0, 0.0)}


def widget(component: str, data: dict, family: str, display: dict | None = None, components: dict | None = None,
           stores: dict | None = None) -> list[str]:
    """What would look broken in a widget at one size: the component laid out as the widget extension draws it,
    over the store's value with `family` in scope, then held to the widget's height."""
    width, height, margin = WIDGETS[family]
    props = {**data, "data": data, "family": family}
    card = {"view": {component: props}, "data": {**data, "family": family}, "stores": stores or {}}
    layout.set_text_size((display or {}).get("textSize") or "large")
    room = (width - 2 * margin, height - 2 * margin)
    engine = layout.Engine(card, components, room[0], page=True)
    engine.run()
    found, _ = faults(card, room[0], components, page=True)
    tall = engine.root.frame[3] if engine.root is not None and engine.root.frame else 0.0
    if tall > room[1] + 0.5:
        found.append(f"it is {tall:.0f} pt tall where the widget holds {room[1]:.0f}: the bottom is cut")
    return [f"{fault} (at {family})" for fault in found]


def widths(display: dict | None, page: bool = False) -> tuple[float, ...]:
    """The phone's card width when it reported one (`cardWidth`), else the widths phones give cards; for a page, the
    width of its content (`pageWidth` less the page's margins)."""
    if page:
        return (float(display["pageWidth"]) - 2 * PAGE_MARGIN,) if (display or {}).get("pageWidth") else PAGE_WIDTHS
    return (float(display["cardWidth"]),) if (display or {}).get("cardWidth") else layout.CARD_WIDTHS


def found(card: dict, display: dict | None = None, components: dict | None = None,
          derived: dict | None = None, page: bool = False) -> tuple[list[str], list[str]]:
    """The faults and the notes at the text size and card (or page) width the phone reported; raises when the twin
    cannot lay the card out."""
    card = card if "view" in card else {"view": card}
    layout.set_text_size((display or {}).get("textSize") or "large")
    seen, noted = {}, {}
    for width in widths(display, page):
        flagged, notes = faults(card, width, components, derived, page)
        for fault in flagged:
            seen.setdefault(fault, width)
        for note in notes:
            noted.setdefault(note, width)
    return ([f"{fault} (at {width:.0f} pt wide)" for fault, width in seen.items()],
            [f"{note} (at {width:.0f} pt wide)" for note, width in noted.items()])


def check(card: dict, display: dict | None = None, components: dict | None = None, derived: dict | None = None) -> list[str]:
    """`display` is what the phone reported (`textSize`, `cardWidth`); without it the default text size at both widths."""
    try:
        flagged, notes = found(card, display, components, derived)
        return flagged + notes
    except Exception as error:
        return [f"the twin could not lay this card out ({type(error).__name__}: {error})"]


if __name__ == "__main__":
    request = json.load(sys.stdin)
    display = request.pop("display", None) if isinstance(request, dict) else None
    print(json.dumps(check(request, display), ensure_ascii=False))
