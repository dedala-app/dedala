# SPDX-FileCopyrightText: 2026 Julien Malka
# SPDX-License-Identifier: MIT

"""SF Symbols as pictures for the painter: `<name>-<weight>.png` masks with their sizes in `sizes.json`, which the
phone sends the agent with each symbol it measures (plugin/dedala/symbols.py). FOLDER is set to where they are
kept; nothing is drawn from it until then."""

import json
import os

FOLDER = os.environ.get("BENCH_GLYPHS") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "glyphs")


def sizes():
    path = os.path.join(FOLDER, "sizes.json")
    return json.load(open(path)) if os.path.exists(path) else {}


def weight_name(weight):
    return "bold" if weight in ("bold", "heavy", "black") else "semibold" if weight in ("semibold", "medium") else "regular"


def path(name, weight="regular"):
    file = os.path.join(FOLDER, f"{name}-{weight_name(weight)}.png")
    return file if os.path.exists(file) else None


def size(name, weight="regular"):
    """The symbol's size in points at 17 points, as the phone draws it."""
    entry = sizes().get(name) or {}
    return tuple(entry.get(weight_name(weight)) or entry.get("regular") or ()) or None
