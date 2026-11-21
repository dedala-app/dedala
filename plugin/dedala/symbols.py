# SPDX-FileCopyrightText: 2026 Julien Malka
# SPDX-License-Identifier: MIT

"""The SF Symbols the twin lays out, measured on the phone: Apple's symbol data
cannot ship here, so the phone measures each name the twin meets at the point
sizes it needs, and the numbers are kept in twin/symbols.json until iOS changes,
with a picture of each in twin/glyphs/ for the twin's drawings. A symbol met for
the first time is laid out from an estimate; the phone's report on what it drew
catches what that misses."""

import base64
import json
import logging
import re
import time
from pathlib import Path

from . import twin
from .state import read, write

logger = logging.getLogger(__name__)

WEIGHTS = ("ultraLight", "thin", "light", "regular", "medium", "semibold", "bold", "heavy", "black")
SCALES = ("small", "medium", "large")
ASKED_AGAIN = 600
PER_OP = 10
NAME = re.compile(r"[a-z0-9]+(\.[a-z0-9]+)*")
SKILLS = Path(__file__).resolve().parent / "skills"


class Symbols:
    """symbols.json: {os, symbols: {name: {sizes: {"17.0": [[width, height,
    baseline, aspect] per weight and scale]}} | null}}, null for a name iOS
    does not know."""

    def __init__(self, home: Path):
        self.path = home / "twin" / "symbols.json"
        self.glyphs = home / "twin" / "glyphs"
        self.home = home
        self.data = {"os": None, "symbols": {}, **read(self.path)}
        self.asked: dict[tuple[str, float], float] = {}
        self.installed = False

    def _measured(self, change) -> bool:
        """`change` applied to the twin's measured symbols, filled from the file
        the first time; False when the twin cannot load here."""
        def apply(target):
            if not self.installed:
                target.sizes.clear()
                target.wanted.clear()
                for name, entry in self.data["symbols"].items():
                    _install(target, name, entry)
                self.installed = True
            return change(target)

        try:
            return twin.measured(apply)
        except Exception as error:
            logger.warning("[app] the twin's symbols could not be set: %s", error)
            return False

    def received(self, event: dict) -> None:
        """What the phone measured, kept and handed to the twin."""
        if event.get("os") and event["os"] != self.data["os"]:
            self._reset(event["os"])
        measured = {name: entry for name, entry in (event.get("symbols") or {}).items() if NAME.fullmatch(name)}
        self._pictures(measured)
        for name, entry in measured.items():
            if entry is None:
                self.data["symbols"][name] = None
                continue
            kept = self.data["symbols"].get(name) or {"sizes": {}}
            kept["sizes"].update(entry.get("sizes") or {})
            self.data["symbols"][name] = kept
        write(self.path, self.data)
        self._measured(lambda target: [_install(target, name, entry) for name, entry in measured.items()])

    def _pictures(self, measured: dict) -> None:
        """Each symbol's pictures as twin/glyphs.py reads them: <name>-<weight>.png
        and their sizes in sizes.json."""
        sizes = read(self.glyphs / "sizes.json")
        for name, entry in measured.items():
            for weight, picture in ((entry or {}).pop("images", None) or {}).items():
                if weight not in ("regular", "semibold", "bold") or not isinstance(picture, dict):
                    continue
                try:
                    png = base64.b64decode(picture["png"])
                except (KeyError, TypeError, ValueError):
                    continue
                self.glyphs.mkdir(parents=True, exist_ok=True)
                (self.glyphs / f"{name}-{weight}.png").write_bytes(png)
                sizes.setdefault(name, {})[weight] = picture.get("size")
        if sizes:
            write(self.glyphs / "sizes.json", sizes)

    def _reset(self, os: str) -> None:
        self.data = {"os": os, "symbols": {name: None if entry is None else {"sizes": {}} for name, entry in self.data["symbols"].items()}}
        self.installed = False
        self.asked.clear()
        write(self.path, self.data)

    def display(self, display: dict, artifacts: dict) -> list[dict]:
        """What to measure when the phone says how it draws: the names known and
        the ones the skills, the card bank and his pages use, at the text size's
        point sizes they lack, all of them again on a new iOS. Nothing for an
        app too old to measure."""
        if not display.get("os"):
            return []
        if display["os"] != self.data["os"]:
            self._reset(display["os"])
        try:
            sizes = twin.text_sizes(display.get("textSize"))
        except Exception:
            return []
        names = set(self.data["symbols"]) | starter(self.home, artifacts)
        return self._ops({name: sizes for name in names})

    def wanted(self) -> list[dict]:
        """What the twin met unmeasured since the last call."""
        if not self.data["os"]:
            return []
        def take(target):
            met = set(target.wanted)
            target.wanted.clear()
            return met

        wanted: dict[str, set[float]] = {}
        for name, size in self._measured(take) or ():
            wanted.setdefault(name, set()).add(size)
        return self._ops(wanted)

    def _ops(self, wanted: dict[str, set[float]]) -> list[dict]:
        now = time.time()
        asking: dict[str, list[float]] = {}
        for name, sizes in sorted(wanted.items()):
            if not NAME.fullmatch(name) or (name in self.data["symbols"] and self.data["symbols"][name] is None):
                continue
            have = set((self.data["symbols"].get(name) or {}).get("sizes", {}))
            missing = sorted(size for size in sizes if str(float(size)) not in have and now - self.asked.get((name, size), 0) > ASKED_AGAIN)
            if missing:
                asking[name] = missing
                for size in missing:
                    self.asked[(name, size)] = now
        names = list(asking)
        return [{"op": "measure", "symbols": {name: asking[name] for name in names[at:at + PER_OP]}} for at in range(0, len(names), PER_OP)]


def _install(target, name: str, entry: dict | None) -> None:
    if not entry:
        return
    for size, rows in (entry.get("sizes") or {}).items():
        for index, values in enumerate(rows):
            if values:
                target.add(name, float(size), WEIGHTS[index // len(SCALES)], SCALES[index % len(SCALES)], values)


def starter(home: Path, artifacts: dict) -> set[str]:
    """The symbol names the skills' examples, the card bank and his pages and
    components use."""
    found: set[str] = set()
    for folder in (SKILLS, home / "bank"):
        for path in folder.rglob("*.json") if folder.is_dir() else ():
            try:
                named(json.loads(path.read_text()), found)
            except (OSError, ValueError):
                continue
    named(artifacts, found)
    return {name for name in found if NAME.fullmatch(name)}


def named(value, found: set[str]) -> None:
    if isinstance(value, dict):
        for key, inner in value.items():
            if key in ("Image", "symbol") and isinstance(inner, str):
                found.add(inner)
            elif key == "Label" and isinstance(inner, list) and len(inner) > 1 and isinstance(inner[1], str):
                found.add(inner[1])
            named(inner, found)
    elif isinstance(value, list):
        for inner in value:
            named(inner, found)
