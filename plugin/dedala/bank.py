# SPDX-FileCopyrightText: 2026 Julien Malka
# SPDX-License-Identifier: MIT

"""The cards the agent drew, as they last stood, and the bank of the ones he
loved: what the agent starts from next time it draws something of the kind."""

import json
import re
import shutil
import threading
from datetime import datetime, timezone
from pathlib import Path

from .state import write

KEPT = 200


class Cards:
    """The latest text, view and data of each card said, kept on disk so a card
    can still be put in the bank after a restart."""

    def __init__(self, home: Path):
        self.path = home / "cards.json"
        self.lock = threading.RLock()
        try:
            self.cards: dict[str, dict] = json.loads(self.path.read_text())
        except (OSError, ValueError):
            self.cards = {}

    def said(self, op: dict) -> None:
        card = op.get("card") or {}
        with self.lock:
            self.cards.pop(op["id"], None)
            self.cards[op["id"]] = {"conversation": op.get("conversation", "main"), "text": op.get("text", ""),
                                    "view": card.get("view"), "data": card.get("data") or {}, "state": card.get("state") or {},
                                    **{key: card[key] for key in ("script", "derive") if card.get(key)}}
            self._save()

    def recent(self, count: int) -> list[tuple[str, dict]]:
        """The cards said last, the latest first."""
        with self.lock:
            return list(reversed(list(self.cards.items())))[:count]

    def patched(self, op: dict) -> None:
        with self.lock:
            if (card := self.cards.get(op["id"])) is None:
                return
            for key, value in (op.get("data") or {}).items():
                if value is None:
                    card["data"].pop(key, None)
                else:
                    card["data"][key] = value
            for key in ("view", "script", "derive"):
                if op.get(key) is not None:
                    card[key] = op[key]
            if op.get("state") is not None:
                card["state"] = {**(card.get("state") or {}), **op["state"]}
            if op.get("say") is not None:
                card["text"] = op["say"]
            self._save()

    def loved(self, card: str, spec: dict) -> None:
        """A card he loved, as the app sent it: known from then on even if drawn before a restart."""
        with self.lock:
            self.cards[card] = {"conversation": spec.get("conversation", "main"), "text": spec.get("text", ""),
                                "view": spec.get("view"), "data": spec.get("data") or {}, "state": spec.get("state") or {},
                                **({"capture": spec["capture"]} if spec.get("capture") else {})}
            self._save()

    def captured(self, card: str, capture: str) -> None:
        with self.lock:
            if card in self.cards:
                self.cards[card]["capture"] = capture
                self._save()

    def get(self, card: str) -> dict | None:
        return self.cards.get(card)

    def _save(self) -> None:
        while len(self.cards) > KEPT:
            self.cards.pop(next(iter(self.cards)))
        write(self.path, self.cards)


def bank(home: Path) -> Path:
    """The cards he loved, in the plugin's folder: the skills are read-only."""
    return home / "bank"


def _name(card: str) -> str:
    return re.sub(r"[^\w-]+", "-", card).strip("-") or "card"


def annotate(home: Path, card: str, note: str) -> Path | None:
    """Adds his reasons to a card already in the bank."""
    path = bank(home) / f"{_name(card)}.json"
    try:
        entry = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    entry["note"] = note
    path.write_text(json.dumps(entry, ensure_ascii=False, indent=1))
    return path


def keep(home: Path, card: str, spec: dict, note: str, by: str) -> Path:
    """Puts a card in the bank, its capture beside it; keeping it again replaces it."""
    folder = bank(home)
    folder.mkdir(parents=True, exist_ok=True)
    name = _name(card)
    entry = {"card": card, "kept": datetime.now(timezone.utc).isoformat(timespec="seconds"), "by": by, "note": note,
             "text": spec.get("text", ""), "view": spec.get("view"), "data": spec.get("data") or {}, "state": spec.get("state") or {}}
    capture = spec.get("capture")
    if isinstance(capture, str) and Path(capture).is_file():
        shutil.copyfile(capture, folder / f"{name}.jpg")
        entry["capture"] = f"{name}.jpg"
    path = folder / f"{name}.json"
    path.write_text(json.dumps(entry, ensure_ascii=False, indent=1))
    return path
