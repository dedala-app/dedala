# SPDX-FileCopyrightText: 2026 Julien Malka
# SPDX-License-Identifier: MIT

"""A card as the phone will show it, without the phone: the twin lays it out, a no-break space goes before every lone
last word, the twin's faults are listed, and the painter's page is rendered to a PNG by a headless Chromium.

    echo '{"card": {...}, "png": "/path/out.png", "display": {...}}' | python -m dedala.twin.preview   →   {"card", "faults", "png", "size", "fixed"}

Runs with the twin's Python (uharfbuzz, fonttools, pyicu)."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from . import layout, paint, twincheck

CHROMIUM = (os.environ.get("CHROMIUM") or shutil.which("chromium")
            or "/nix/store/cfxpl6qy25sgq5sa7shj4dbdsxwwp286-chromium-156.0.8078.73/bin/chromium")
# Headless Chromium paints a window between about 70 and 160 pixels tall only in part, or not at all.
MIN_HEIGHT = 200


def widows(card: dict, widths, components=None, derived=None, page=False) -> set[str]:
    found = set()
    for width in widths:
        engine = layout.Engine(card, components, width, derived, page=page)
        engine.run()
        for box in engine.texts:
            lines = box.extra.get("lines_text") or []
            if len(lines) > 1 and len(lines[-1].split()) == 1:
                font = box.font
                widths_ = [layout.advance(line.rstrip(), font["design"], font["weight"], font["size"], font["italic"]) for line in lines]
                if widths_[-1] < 0.3 * max(widths_):
                    found.add(box.text)
    return found


def tie(node, texts: set[str]) -> int:
    """A no-break space before the last word of each literal text that ends on a lone word."""
    fixed = 0
    if isinstance(node, list):
        return sum(tie(item, texts) for item in node)
    if not isinstance(node, dict):
        return 0
    value = node.get("Text")
    if isinstance(value, str) and "$" not in value and value in texts and " " in value.strip():
        head, _, last = value.rstrip().rpartition(" ")
        node["Text"] = head + "\u00a0" + last
        fixed += 1
    return fixed + sum(tie(item, texts) for key, item in node.items() if key != "Text")


def render(card: dict, png: str, width: float, components=None, derived=None, whole=False) -> list[float]:
    page, result = paint.paint(card, components, width, derived, whole)
    width, height = result["size"]
    with tempfile.TemporaryDirectory() as profile:
        html = Path(profile) / "card.html"
        html.write_text(page)
        subprocess.run([CHROMIUM, "--headless=new", "--no-sandbox", "--disable-gpu", "--hide-scrollbars", f"--user-data-dir={profile}",
                        "--force-device-scale-factor=2", f"--window-size={int(width + 16)},{max(int(height + 16), MIN_HEIGHT)}",
                        "--virtual-time-budget=2000", f"--screenshot={png}", f"file://{html}"],
                       capture_output=True, timeout=120)
    return [round(width), round(height)]


def look(card: dict, display: dict | None = None, components: dict | None = None, derived: dict | None = None,
         png: str | None = None, page: bool = False) -> dict:
    """The card tied, its faults (what is broken), notes (what is worth a look) and picture at the phone's text size and
    card width, or for a page (`page`, its view as is) at the width of the page's content; raises when the twin cannot
    lay it out."""
    card = json.loads(json.dumps(card if "view" in card else {"view": card}))
    widths = twincheck.widths(display, page)
    layout.set_text_size((display or {}).get("textSize") or "large")
    layout.set_time_zone((display or {}).get("timeZone") or os.environ.get("BENCH_TZ"), (display or {}).get("utcOffset"))
    fixed = 0
    for _ in range(3):
        lone = widows(card, widths, components, derived, page)
        if not lone or not tie(card, lone):
            break
        fixed += len(lone)
    faults, notes = twincheck.found(card, display, components, derived, page)
    size = error = None
    if png:
        try:
            size = render(card, png, widths[0], components, derived, page)
        except Exception as failure:
            png, error = None, f"the preview could not be drawn ({type(failure).__name__}: {failure})"
    return {"card": card, "faults": faults, "notes": notes, "png": png, "size": size, "fixed": fixed, "error": error}


if __name__ == "__main__":
    request = json.load(sys.stdin)
    try:
        answer = look(request["card"], request.get("display"), request.get("components"), request.get("derived"), request.get("png"),
                      bool(request.get("page")))
        answer["faults"] += answer.pop("notes") + ([answer["error"]] if answer["error"] else [])
    except Exception as error:
        card = request["card"] if "view" in request["card"] else {"view": request["card"]}
        answer = {"card": card, "faults": [f"the twin could not lay this card out ({type(error).__name__}: {error})"],
                  "png": request.get("png"), "size": None, "fixed": 0}
    print(json.dumps(answer, ensure_ascii=False))
