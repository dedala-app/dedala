# SPDX-FileCopyrightText: 2026 Julien Malka
# SPDX-License-Identifier: MIT

"""Every store is a file here, the truth of what its pages show: a JSON file
under stores/ that the plugin owns, or a path the agent linked, a JSON file,
a text file read as lines, or a folder of text files read as records. The
plugin writes a store when the agent or the phone changes it, and watches
it: what anything else writes (an editor, a script, a job with no model, a
flow, a command) reaches the phone like the agent's own change. A file that
stops being JSON changes nothing: the store keeps what it last held, and why
is kept for the agent. A declaration makes a store's records findable on the
phone; a record's `file` is an attachment the phone keeps, and so is the
profile's `picture` (profile.py)."""

import fnmatch
import json
import os
import re
from datetime import datetime, timezone
import time
import urllib.parse
from pathlib import Path
from typing import Optional

from . import profile
from .files import Refused, digest, edit, form, read, write

TEXT_SUFFIXES = {".org", ".md", ".markdown", ".txt", ".text"}
# A record's text beyond this is cut: a message to the phone is at most 512KB.
TEXT_KEPT = 300_000
DECLARATION = ("name", "symbol", "screen", "title", "subtitle", "words")
# An edit is made to the file as it was read: saved here meanwhile, it is read again.
SAVED_MEANWHILE_TRIES = 5
KEYWORD_ORG = re.compile(r"^#\+(\w+):\s*(.+?)\s*$", re.IGNORECASE | re.MULTILINE)
PROPERTY_ID = re.compile(r"^\s*:ID:\s*(\S+)\s*$", re.IGNORECASE | re.MULTILINE)
HEADING = re.compile(r"^(?:\*+|#+)\s+(.+?)\s*$", re.MULTILINE)
FRONT_LINE = re.compile(r"^(\w+):\s*(.+?)\s*$", re.MULTILINE)
# A Denote file name starts with its identifier: 20260401T225935==public--slug__tag.org.
DENOTE_ID = re.compile(r"^(\d{8}T\d{6})")
DENOTE_NAME = re.compile(r"^(?:(?P<id>\d{8}T\d{6}))?(?:==(?P<signature>[^-_.]+))?(?:--(?P<title>[^_.]+))?(?:__(?P<tags>[^.]+))?")
DATE = re.compile(r"(\d{4}-\d{2}-\d{2})(?:[ T][^\d]*(\d{2}:\d{2}(?::\d{2})?))?")
# A link to another file: [[denote:ID]], [[id:UUID]], [[file:path]]; Markdown [text](file.md) and [[wikilinks]].
LINK_ORG = re.compile(r"\[\[(denote|id|file):([^\]\[]+?)(?:::[^\]]*)?\](?:\[[^\]]*\])?\]")
LINK_MD = re.compile(r"\]\(((?!https?:|mailto:)[^)\s]+\.[A-Za-z0-9]{1,8})\)|\[\[([^\]\[|]+)(?:\|[^\]]*)?\]\]")


def fingerprint(data) -> str:
    return digest(json.dumps(data, sort_keys=True, ensure_ascii=False))


def record(root: Path, path: Path) -> dict:
    """A file of a folder store as the phone shows it, its links still as
    written: `targets`, resolved to record ids once the folder is read."""
    data = read(path)
    text = data["text"]
    kind = form(path)
    front = _front(text, kind)
    identifier = front.get("identifier") or front.get("id")
    if not identifier and (match := DENOTE_ID.match(path.name)):
        identifier = match.group(1)
    found = {"id": path.relative_to(root).as_posix(), "name": path.name, "path": str(path), "title": front.get("title") or _heading(text[:4000]) or path.stem,
             "tags": front.get("tags", []), "text": text, "updated": data["updated"],
             "targets": _targets(text, kind)}
    if identifier:
        found["identifier"] = identifier
    if date := _date(front.get("date"), identifier):
        found["date"] = date
    if front.get("signature"):
        found["signature"] = front["signature"]
    if len(text) > TEXT_KEPT:
        found.update(text=text[:TEXT_KEPT], truncated=True)
    return found


def asset(root: Path, path: Path) -> dict:
    """A file of a folder store that is not text: what its Denote name says of
    it, and the file itself as the record's attachment, fetched by the phone
    when shown."""
    stat = path.stat()
    named = DENOTE_NAME.match(path.name)
    title = (named.group("title") or "").replace("-", " ").strip() if named else ""
    found = {"id": path.relative_to(root).as_posix(), "name": path.name, "path": str(path), "title": title or path.stem,
             "tags": [tag for tag in (named.group("tags") or "").split("_") if tag] if named else [],
             "updated": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(timespec="seconds"), "size": stat.st_size, "targets": []}
    identifier = named.group("id") if named else None
    if identifier:
        found["identifier"] = identifier
    if date := _date(None, identifier):
        found["date"] = date
    if named and named.group("signature"):
        found["signature"] = named.group("signature")
    found["file"] = str(path)
    return found


def _front(text: str, kind: str) -> dict:
    """What the file says of itself: Org keywords, or Markdown front matter."""
    head = text[:4000]
    found: dict = {}
    if kind == "org":
        for key, value in KEYWORD_ORG.findall(head):
            found.setdefault(key.lower(), value)
        if "tags" not in found and "filetags" in found:
            found["tags"] = [tag for tag in found["filetags"].replace(":", " ").split() if tag]
        if match := PROPERTY_ID.search(head):
            found.setdefault("id", match.group(1))
        return found
    if head.startswith("---"):
        parts = head.split("---", 2)
        if len(parts) >= 3:
            for key, value in FRONT_LINE.findall(parts[1]):
                found.setdefault(key.lower(), value.strip().strip("\"'"))
            if "tags" in found:
                found["tags"] = [tag.strip().strip("\"'") for tag in found["tags"].strip("[]").split(",") if tag.strip()]
    return found


def _date(written: Optional[str], identifier: Optional[str]) -> Optional[str]:
    """`[2026-04-01 mer. 22:59]` reads 2026-04-01T22:59; a Denote identifier is a date too."""
    if written and (match := DATE.search(written)):
        return match.group(1) + (f"T{match.group(2)}" if match.group(2) else "")
    if identifier and (match := re.match(r"^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})$", identifier)):
        year, month, day, hour, minute, second = match.groups()
        return f"{year}-{month}-{day}T{hour}:{minute}:{second}"
    return None


def _targets(text: str, kind: str) -> list[tuple[str, str]]:
    """The other files this one links to, each as (scheme, target) as written."""
    if kind == "org":
        return [(scheme.lower(), target.strip()) for scheme, target in LINK_ORG.findall(text)]
    return [("file", path) if path else ("wiki", name.strip()) for path, name in LINK_MD.findall(text)]


def resolve_links(records: dict[str, dict]) -> dict[str, dict]:
    """The records of a folder with their `links`, the ids of the records
    they point to, and `backlinks`, the ids of the records that point to
    them; `targets` gone."""
    by_identifier = {item["identifier"]: item["id"] for item in records.values() if item.get("identifier")}
    by_stem = {Path(item["id"]).stem: item["id"] for item in records.values()}
    by_title = {item["title"].lower(): item["id"] for item in records.values() if item.get("title")}
    resolved: dict[str, dict] = {}
    for identifier, item in records.items():
        links: list[str] = []
        for scheme, target in item.get("targets", []):
            found = None
            if scheme in ("denote", "id"):
                found = by_identifier.get(target)
            elif scheme == "file":
                relative = os.path.normpath((Path(identifier).parent / target.split("::")[0]).as_posix())
                found = relative if relative in records and not relative.startswith("..") else by_stem.get(Path(target).stem)
            else:
                found = by_stem.get(target) or by_title.get(target.lower())
            if found and found != identifier and found not in links:
                links.append(found)
        resolved[identifier] = {key: value for key, value in item.items() if key != "targets"}
        resolved[identifier]["links"] = links
    for item in resolved.values():
        item["backlinks"] = []
    for identifier, item in resolved.items():
        for target in item["links"]:
            resolved[target]["backlinks"].append(identifier)
    return resolved


def _heading(head: str) -> Optional[str]:
    match = HEADING.search(head)
    return match.group(1) if match else None


def records_of(data) -> Optional[list]:
    """The records of a store's data, when it holds records."""
    if isinstance(data, list) and data and all(isinstance(item, dict) and isinstance(item.get("id"), str) for item in data):
        return data
    return [] if data == [] else None


class Stores:
    """The stores folder: `<id>.json` the plugin owns, and symlinks to his own
    files and folders (`daily.org -> /…/daily.org`, `notes -> /…/notes/`),
    which are the linked stores. The Search declarations are `search.json`
    beside it (folder.py)."""

    def __init__(self, folder: Path, app=None):
        self.folder = folder
        self.app = app
        # Each store's data as its file last gave it.
        self.held: dict[str, object] = {}
        # The files that cannot be read as a store, each with why.
        self.unreadable: dict[str, str] = {}
        self._stamps: dict[str, object] = {}
        # Of each folder store, its files as read, before their links are resolved.
        self._parsed: dict[str, dict[str, dict]] = {}
        # The linked stores: name -> the symlink in the folder.
        self._links: dict[str, Path] = {}
        self._search: dict = {}
        # Of a folder store, the patterns of the files it leaves out (ignore.json beside the folder).
        self.ignore_path = folder.parent / "ignore.json"
        self._ignore: dict[str, list[str]] = {}
        try:
            loaded = json.loads(self.ignore_path.read_text(encoding="utf-8"))
            self._ignore = {name: [str(pattern) for pattern in patterns] for name, patterns in loaded.items() if isinstance(patterns, list)}
        except (OSError, ValueError):
            pass
        # Of a folder store, how many files its patterns left out at the last scan.
        self.ignored: dict[str, int] = {}
        # Of a folder store, the records that moved and the ones gone since the last scan.
        self.moved_records: dict[str, set[str]] = {}
        self.dropped_records: dict[str, set[str]] = {}
        self.scan()

    # What a store is

    @property
    def links(self) -> dict:
        """The linked stores, each with the path it stands for, and the
        patterns a folder leaves out."""
        return {name: {"path": str(self._target(link)), **({"ignore": self._ignore[name]} if self._ignore.get(name) else {})}
                for name, link in self._links.items()}

    def ignore(self, name: str) -> list[str]:
        return list(self._ignore.get(name) or [])

    def set_ignore(self, name: str, patterns: Optional[list]) -> list[str]:
        """The patterns of the files a folder store leaves out, gitignore
        style, relative to the folder: `npins/` a folder anywhere, `*.nix`,
        `assets/*.mp4`. None clears them. The folder is read again."""
        cleaned = [str(pattern).strip() for pattern in (patterns or []) if str(pattern).strip()]
        if cleaned:
            self._ignore[name] = cleaned
        else:
            self._ignore.pop(name, None)
        write(self.ignore_path, json.dumps(self._ignore, indent=1, ensure_ascii=False) + "\n")
        self._parsed.pop(name, None)
        self._stamps.pop(name, None)
        if name in self._links:
            self._read(name, self.path(name))
        return cleaned

    @staticmethod
    def ignores(patterns: list[str], relative: str) -> bool:
        """Whether a file at `relative` (its path inside the folder) is left out."""
        parts = relative.split("/")
        for pattern in patterns:
            if pattern.endswith("/"):
                folder = pattern.rstrip("/")
                if any(fnmatch.fnmatch(part, folder) for part in parts[:-1]) or any(fnmatch.fnmatch("/".join(parts[:k]), folder) for k in range(1, len(parts))):
                    return True
            elif fnmatch.fnmatch(relative, pattern) or fnmatch.fnmatch(parts[-1], pattern) or any(fnmatch.fnmatch(part, pattern) for part in parts[:-1]):
                return True
        return False

    @property
    def declared(self) -> dict:
        return self.app.loaded["search"] if self.app is not None else self._search

    @staticmethod
    def _target(link: Path) -> Path:
        try:
            return Path(os.readlink(link)) if link.is_symlink() else link
        except OSError:
            return link

    def path(self, name: str) -> Path:
        if name in self._links:
            return self._target(self._links[name])
        quoted = urllib.parse.quote(name, safe="")
        return self.folder / f"{'%2E' + quoted[1:] if quoted.startswith('.') else quoted}.json"

    def kind(self, name: str) -> Optional[str]:
        """`text`, `folder`, or None for a JSON store."""
        link = self._links.get(name)
        if link is None:
            return None
        if link.suffix == "" or self._target(link).is_dir():
            return "folder"
        return None if link.suffix.lower() == ".json" else "text"

    def link(self, name: str, path: str) -> None:
        """Makes the store be that file or folder: a symlink in the folder."""
        resolved = Path(path).expanduser().resolve()
        suffix = "" if resolved.is_dir() else (resolved.suffix if resolved.suffix else ".txt")
        self.folder.mkdir(parents=True, exist_ok=True)
        if old := self._links.get(name):
            old.unlink(missing_ok=True)
        link = self.folder / f"{name}{suffix}"
        link.unlink(missing_ok=True)
        os.symlink(str(resolved), link)
        self.held.pop(name, None)
        self._stamps.pop(name, None)
        self._parsed.pop(name, None)
        self.scan()

    def unlink(self, name: str) -> None:
        if link := self._links.pop(name, None):
            link.unlink(missing_ok=True)
        self.held.pop(name, None)
        self._stamps.pop(name, None)
        self._parsed.pop(name, None)
        self.unreadable.pop(name, None)

    def declare(self, name: str, declaration: Optional[dict]) -> Optional[dict]:
        declared = dict(self.declared)
        if declaration is None:
            declared.pop(name, None)
        else:
            declared[name] = {key: declaration[key] for key in DECLARATION if declaration.get(key) is not None}
        if self.app is not None:
            self.app.write("search", None, declared)
        else:
            self._search = declared
        return declared.get(name)

    def op(self, name: str) -> dict:
        """The store whole, as the phone takes it."""
        op = {"op": "store", "id": name, "data": self.held.get(name)}
        if kind := self.kind(name):
            op["kind"] = kind
        if name in self.declared:
            op["declare"] = self.declared[name]
        return op

    def ops(self, name: str) -> list[dict]:
        """The store for the phone, in ops a message can carry: a folder store
        goes as an empty store followed by one op per record."""
        op = self.op(name)
        if self.kind(name) != "folder":
            return [op]
        records = op.get("data") or []
        return [{**op, "data": []}] + [{"op": "store", "id": name, "kind": "folder", "record": item} for item in records]

    def record_op(self, name: str, identifier: str) -> dict:
        found = next((item for item in self.held.get(name) or [] if item.get("id") == identifier), None)
        if found is None:
            return {"op": "store", "id": name, "kind": "folder", "drop": identifier}
        return {"op": "store", "id": name, "kind": "folder", "record": found}

    # Reading

    def scan(self) -> list[str]:
        """Reads the files that changed since they were last read; the stores
        whose data moved, the ones whose file is gone among them."""
        moved = []
        found = set()
        links: dict[str, Path] = {}
        for entry in sorted(self.folder.iterdir()) if self.folder.is_dir() else []:
            if entry.name.startswith("."):
                continue
            if entry.is_symlink():
                links[entry.name[:-len(entry.suffix)] if entry.suffix else entry.name] = entry
            elif entry.suffix == ".json" and entry.is_file():
                name = urllib.parse.unquote(entry.name[:-5])
                found.add(name)
                if self._read(name, entry):
                    moved.append(name)
        for name in set(self._links) - set(links):
            self._stamps.pop(name, None)
        self._links = links
        for name in links:
            found.add(name)
            if self._read(name, self.path(name)):
                moved.append(name)
        for name in set(self.held) - found:
            del self.held[name]
            self._stamps.pop(name, None)
            self._parsed.pop(name, None)
            moved.append(name)
        for name in set(self.unreadable) - found:
            del self.unreadable[name]
        return moved

    def read(self, name: str):
        """A store's data as its file stands now, read again if it was written
        since; what it last held when the file cannot be read."""
        self._read(name, self.path(name))
        return self.held.get(name)

    def _read(self, name: str, path: Path) -> bool:
        kind = self.kind(name)
        if kind == "folder":
            return self._read_folder(name, path)
        stamp = self._stamp(path)
        if kind == "text":
            if stamp == self._stamps.get(name) and name in self.held:
                return False
            try:
                data = read(path)
            except (OSError, ValueError) as error:
                self.unreadable[name] = f"it cannot be read as text ({error})"
                self._stamps[name] = stamp
                return False
            self.unreadable.pop(name, None)
            self._stamps[name] = stamp
            if self.held.get(name) == data:
                return False
            self.held[name] = data
            return True
        if stamp is None or stamp == self._stamps.get(name):
            return False
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            self.unreadable[name] = f"it is not JSON ({error})"
        else:
            if data is not None:
                self.unreadable.pop(name, None)
                self._stamps[name] = stamp
                if name in self.held and self.held[name] == data:
                    return False
                self.held[name] = data
                return True
            self.unreadable[name] = "it holds null: delete the file to remove the store"
        self._stamps[name] = stamp
        return False

    def _read_folder(self, name: str, root: Path) -> bool:
        stamps: dict = self._stamps.get(name) if isinstance(self._stamps.get(name), dict) else {}
        parsed: dict[str, dict] = self._parsed.setdefault(name, {})
        before = {item["id"]: item for item in self.held.get(name) or []}
        seen = set()
        patterns = self._ignore.get(name) or []
        left_out = 0
        for path in sorted(root.rglob("*")) if root.is_dir() else []:
            if not path.is_file() or any(part.startswith(".") for part in path.relative_to(root).parts):
                continue
            identifier = path.relative_to(root).as_posix()
            if patterns and self.ignores(patterns, identifier):
                left_out += 1
                continue
            seen.add(identifier)
            stamp = self._stamp(path)
            if stamp == stamps.get(identifier) and identifier in parsed:
                continue
            try:
                parsed[identifier] = record(root, path) if path.suffix.lower() in TEXT_SUFFIXES else asset(root, path)
            except (OSError, ValueError):
                continue
            stamps[identifier] = stamp
        for gone in set(parsed) - seen:
            del parsed[gone]
            stamps.pop(gone, None)
        self.ignored[name] = left_out
        current = resolve_links(parsed)
        moved = {identifier for identifier, item in current.items() if before.get(identifier) != item}
        dropped = set(before) - set(current)
        self._stamps[name] = stamps
        first = name not in self.held
        self.held[name] = sorted(current.values(), key=lambda item: item.get("updated") or "", reverse=True)
        if moved or dropped:
            self.moved_records.setdefault(name, set()).update(moved)
            self.dropped_records.setdefault(name, set()).update(dropped)
        return first or bool(moved or dropped)

    def taken(self, name: str) -> tuple[set[str], set[str]]:
        """The folder records that moved and the ones gone since last asked."""
        return self.moved_records.pop(name, set()), self.dropped_records.pop(name, set())

    # Writing

    def put(self, name: str, data) -> None:
        """Replaces a JSON store's file in one step; `None` deletes it."""
        if self.kind(name) is not None:
            raise Refused(f"The store {name} is a {self.kind(name)}: its edits are line edits")
        path = self.path(name)
        self.unreadable.pop(name, None)
        if data is None:
            if name in self._links:
                self.unlink(name)
            else:
                path.unlink(missing_ok=True)
            self.held.pop(name, None)
            self._stamps.pop(name, None)
            if name in self.declared:
                self.declare(name, None)
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        write(path, json.dumps(data, indent=1, ensure_ascii=False) + "\n")
        self.held[name] = data
        self._stamps[name] = self._stamp(path)

    def change(self, name: str, change: dict) -> None:
        """One of his edits to a JSON store, made to its file as it stands:
        a patch to the value, a patch to one record, a record added or removed."""
        from .link import _merged

        data = self.read(name)
        if "add" in change:
            records = records_of(data) if data is not None else []
            if records is None:
                raise Refused(f"The store {name} holds no records to add to")
            added = dict(change["add"]) if isinstance(change["add"], dict) else {}
            if not isinstance(added.get("id"), str) or not added["id"]:
                raise Refused("A record added needs an id")
            self.put(name, [item for item in records if item.get("id") != added["id"]] + [added])
        elif "remove" in change:
            records = records_of(data)
            if records is None:
                raise Refused(f"The store {name} holds no records to remove from")
            self.put(name, [item for item in records if item.get("id") != change["remove"]])
        elif change.get("id") is not None:
            records = records_of(data)
            if records is None:
                raise Refused(f"The store {name} holds no records to patch")
            patch = change.get("patch") if isinstance(change.get("patch"), dict) else {}
            self.put(name, [_merged(item, patch) if item.get("id") == change["id"] else item for item in records])
        else:
            patch = change.get("patch") if isinstance(change.get("patch"), dict) else {}
            fields = {key: value for key, value in patch.items() if key != "replace"}
            base = patch["replace"] if "replace" in patch else data
            base = {} if base is None else base
            self.put(name, _merged(base, fields) if fields and isinstance(base, dict) else base)

    def apply_edit(self, name: str, identifier: Optional[str], change: dict) -> Optional[str]:
        """One line edit from the phone, made to a text store's file or to a
        file of a folder store; the record's id when a file was made."""
        kind = self.kind(name)
        if kind is None:
            raise Refused(f"The store {name} is not a text file: its edits are patches")
        if kind == "folder":
            root = self.path(name)
            if "add" in change:
                added = str(change["add"]).strip().lstrip("/")
                if not added or ".." in Path(added).parts:
                    raise Refused("A new file needs a name inside the folder")
                path = root / added
                if path.exists():
                    raise Refused(f"{added} already exists")
                path.parent.mkdir(parents=True, exist_ok=True)
                text = str(change.get("text") or "")
                write(path, text if text.endswith("\n") or not text else text + "\n")
                return path.relative_to(root).as_posix()
            if not identifier or ".." in Path(identifier).parts:
                raise Refused("An edit to a folder store names the file by its id")
            path = root / identifier
            if change.get("delete"):
                if not path.is_file():
                    raise Refused(f"{identifier} is not in the folder")
                path.unlink()
                return None
            if path.suffix.lower() not in TEXT_SUFFIXES:
                raise Refused(f"{identifier} is not a text file: it can be deleted, not edited")
        else:
            path = self.path(name)
        for _ in range(SAVED_MEANWHILE_TRIES):
            stamp = self._stamp(path)
            if stamp is not None:
                text = path.read_text(encoding="utf-8")
            else:
                raise Refused(f"{path.name} does not exist: make the file first")
            try:
                new = edit(text, change, form(path))
            except Refused:
                if "text" in change:
                    self._keep_aside(name, identifier, str(change["text"]), path.suffix)
                raise
            if new == text:
                return None
            if self._stamp(path) == stamp:
                write(path, new)
                return None
        raise Refused(f"{path.name} keeps being saved here; try again")

    def _keep_aside(self, name: str, identifier: Optional[str], text: str, suffix: str) -> Path:
        folder = self.folder.parent / "conflicts"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{name}{'-' + identifier.replace('/', '_') if identifier else ''}-{time.strftime('%Y%m%dT%H%M%S')}{suffix}"
        path.write_text(text, encoding="utf-8")
        return path

    # Attachments

    def attachments(self, name: str) -> list[tuple[str, Path]]:
        """The files the records of a store name, by record, and the profile's picture."""
        found = []
        for item in records_of(self.held.get(name)) or []:
            if isinstance(item.get("file"), str) and item["file"]:
                found.append((item["id"], Path(item["file"]).expanduser()))
        held = self.held.get(name)
        if name == profile.STORE and isinstance(held, dict) and isinstance(held.get("picture"), str) and held["picture"]:
            found.append(("picture", Path(held["picture"]).expanduser()))
        return found

    @staticmethod
    def _stamp(path: Path) -> tuple | None:
        try:
            stat = path.stat()
        except OSError:
            return None
        return (stat.st_mtime_ns, stat.st_size)

