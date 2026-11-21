# SPDX-FileCopyrightText: 2026 Julien Malka
# SPDX-License-Identifier: MIT

"""The app is a directory. Everything the agent builds is a file under
dedala/, readable and writable by anything on this machine: pages,
components, scripts, commands, widgets, the button sets, the assets, the
profile, the Search declarations. The tools write these files; so may the
agent's editor, a program, or git. The plugin watches them as it watches the
stores, and what changes is checked and sent to the phone."""

import json
import logging
from pathlib import Path
from typing import Optional

from .files import write as write_text

logger = logging.getLogger(__name__)

# What each kind of thing is on disk: a folder of files, or one file.
FOLDERS = {"page": ("pages", ".json"), "components": ("components", ".json"), "scripts": ("scripts", ".js"),
           "command": ("commands", ".json"), "widget": ("widgets", ".json")}
SINGLE = {"buttons": "buttons.json", "assets": "assets.json", "profile": "profile.json", "search": "search.json",
          "tokens": "tokens.json", "triggers": "triggers.json"}
KINDS = (*FOLDERS, *SINGLE)


def _stamp(path: Path) -> Optional[tuple]:
    try:
        stat = path.stat()
    except OSError:
        return None
    return (stat.st_mtime_ns, stat.st_size)


class AppFiles:
    def __init__(self, home: Path):
        self.home = home
        self.loaded: dict = {kind: {} for kind in KINDS}
        self._stamps: dict[tuple[str, str], Optional[tuple]] = {}
        # Files that cannot be read as what they should be, each with why.
        self.unreadable: dict[str, str] = {}
        self.scan()

    # Where things are

    def folder(self, kind: str) -> Path:
        return self.home / FOLDERS[kind][0]

    def path(self, kind: str, name: Optional[str] = None) -> Path:
        if kind in SINGLE:
            return self.home / SINGLE[kind]
        folder, suffix = FOLDERS[kind]
        return self.home / folder / f"{name}{suffix}"

    @staticmethod
    def _name(kind: str, path: Path) -> str:
        return path.name[:-len(FOLDERS[kind][1])]

    # Reading

    def scan(self) -> list[tuple[str, Optional[str]]]:
        """Reads the files that changed since they were last read; what moved,
        as (kind, name), name None for a single file. A file gone is a thing
        removed."""
        moved: list[tuple[str, Optional[str]]] = []
        for kind, (folder, suffix) in FOLDERS.items():
            root = self.home / folder
            seen = set()
            for path in sorted(root.glob(f"*{suffix}")) if root.is_dir() else []:
                if path.name.startswith("."):
                    continue
                name = self._name(kind, path)
                seen.add(name)
                if self._read(kind, name, path):
                    moved.append((kind, name))
            for gone in set(self.loaded[kind]) - seen:
                del self.loaded[kind][gone]
                self._stamps.pop((kind, gone), None)
                self.unreadable.pop(f"{kind}/{gone}", None)
                moved.append((kind, gone))
        for kind, filename in SINGLE.items():
            path = self.home / filename
            stamp = _stamp(path)
            if stamp is None:
                if self.loaded.get(kind) or (kind, "") in self._stamps:
                    self.loaded[kind] = {}
                    self._stamps.pop((kind, ""), None)
                    moved.append((kind, None))
                continue
            if stamp == self._stamps.get((kind, "")):
                continue
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(value, dict):
                    raise ValueError("it is not a JSON object")
            except (OSError, ValueError) as error:
                self.unreadable[kind] = f"{path.name}: {error}"
                self._stamps[(kind, "")] = stamp
                continue
            self.unreadable.pop(kind, None)
            self._stamps[(kind, "")] = stamp
            if self.loaded.get(kind) != value:
                self.loaded[kind] = value
                moved.append((kind, None))
        return moved

    def _read(self, kind: str, name: str, path: Path) -> bool:
        stamp = _stamp(path)
        if stamp is None or stamp == self._stamps.get((kind, name)):
            return False
        key = f"{kind}/{name}"
        try:
            if kind == "scripts":
                value = path.read_text(encoding="utf-8")
            else:
                value = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(value, dict):
                    raise ValueError("it is not a JSON object")
        except (OSError, ValueError) as error:
            self.unreadable[key] = f"{path.name}: {error}"
            self._stamps[(kind, name)] = stamp
            return False
        self.unreadable.pop(key, None)
        self._stamps[(kind, name)] = stamp
        if name in self.loaded[kind] and self.loaded[kind][name] == value:
            return False
        self.loaded[kind][name] = value
        return True

    # Writing

    def write(self, kind: str, name: Optional[str], value) -> None:
        """Writes one thing's file whole; `None` deletes it. Remembered as read,
        so the watcher does not see the plugin's own writes."""
        path = self.path(kind, name)
        key = (kind, name if kind in FOLDERS else "")
        if value is None:
            path.unlink(missing_ok=True)
            if kind in FOLDERS:
                self.loaded[kind].pop(name, None)
            else:
                self.loaded[kind] = {}
            self._stamps.pop(key, None)
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        if kind == "scripts":
            write_text(path, value if value.endswith("\n") else value + "\n")
        else:
            write_text(path, json.dumps(value, indent=1, ensure_ascii=False) + "\n")
        if kind in FOLDERS:
            self.loaded[kind][name] = value
        else:
            self.loaded[kind] = value
        self._stamps[key] = _stamp(path)

    # As ops

    def op(self, kind: str, name: Optional[str]) -> Optional[dict]:
        """The op that puts one thing on the phone as the file now holds it;
        the op that removes it when the file is gone; None for things the
        phone does not hold one by one."""
        if kind == "page":
            value = self.loaded["page"].get(name)
            return {"op": "page", "id": name, **value} if value is not None else {"op": "page", "id": name, "remove": True}
        if kind == "widget":
            value = self.loaded["widget"].get(name)
            return {"op": "widget", "id": name, **value} if value is not None else {"op": "widget", "id": name, "remove": True}
        if kind == "components":
            return {"op": "define", "components": {name: self.loaded["components"].get(name)}}
        if kind == "scripts":
            return {"op": "define", "scripts": {name: self.loaded["scripts"].get(name)}}
        if kind == "buttons":
            return {"op": "buttons", "kinds": self.loaded["buttons"]} if self.loaded["buttons"] else None
        if kind == "assets":
            return {"op": "assets", "assets": self.loaded["assets"]} if self.loaded["assets"] else None
        if kind == "profile":
            return {"op": "profile", **self.loaded["profile"]}
        return None

    def replay(self, name: str) -> list[dict]:
        """Everything, in the order a new phone takes it."""
        ops = [{"op": "profile", "name": name, **self.loaded["profile"]}]
        if self.loaded["assets"]:
            ops.append({"op": "assets", "assets": self.loaded["assets"]})
        if self.loaded["components"] or self.loaded["scripts"]:
            ops.append({"op": "define", "components": self.loaded["components"], "scripts": self.loaded["scripts"]})
        return ops

    def after_stores(self) -> list[dict]:
        ops = [{"op": "page", "id": page_id, **page} for page_id, page in self.loaded["page"].items()]
        if self.loaded["buttons"]:
            ops.append({"op": "buttons", "kinds": self.loaded["buttons"]})
        ops += [{"op": "widget", "id": widget_id, **widget} for widget_id, widget in self.loaded["widget"].items()]
        return ops
