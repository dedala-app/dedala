# SPDX-FileCopyrightText: 2026 Julien Malka
# SPDX-License-Identifier: MIT

"""Text files the phone works on directly (stores.py, text and folder stores):
read as their text, and changed by the phone's edits with no model in
between: an item of a list appended, changed, removed or ticked where the
org-element tree (orgtree.py) puts it, or the whole text, merged with what
changed here meanwhile."""

import hashlib
import os
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from . import orgtree

EDITS = ("append", "change", "remove", "toggle", "text")
# An edit is made to the file as it was read: saved here meanwhile, it is read again.
SAVED_MEANWHILE_TRIES = 5


class Refused(Exception):
    """An edit the file can no longer take: the line it names is gone, or both
    sides changed the same part of the text."""


def form(path: Path) -> str:
    return {".org": "org", ".md": "markdown", ".markdown": "markdown"}.get(path.suffix.lower(), "text")


def items(text: str, kind: str) -> list[dict]:
    """The list items of a text as the tree reads them, nested ones included."""
    return orgtree.select(orgtree.parse(text, "markdown" if kind == "markdown" else "org"), "item")


def digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def read(path: Path) -> dict:
    """The file as the phone shows it."""
    try:
        text = path.read_text(encoding="utf-8")
        updated = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(timespec="seconds")
        exists = True
    except FileNotFoundError:
        text, updated, exists = "", None, False
    return {"path": str(path), "name": path.name, "exists": exists, "text": text, "updated": updated}


def edit(text: str, change: dict, kind: str) -> str:
    """The text with one edit from the phone made to it, at the place the
    tree gives the item named (the phone makes the same edit to show it,
    Hermes/Files/TextEdits.swift)."""
    if "text" in change:
        return merge(text, change.get("base"), str(change["text"]))
    found = items(text, kind)
    data = bytearray(text.encode("utf-8"))
    if "append" in change:
        added = change["append"] if isinstance(change["append"], list) else [change["append"]]
        top = [item for item in found if not item.get("indent")]
        style = top[-1] if top else None
        bullet = style["bullet"] if style and not style["bullet"][:1].isdigit() else "-"
        ticked = change.get("done")
        boxed = ticked is not None or bool(style and style.get("checkbox") is not None)
        mark = ("X" if kind == "org" else "x") if ticked else " "
        new = [f"{bullet} {f'[{mark}] ' if boxed else ''}{str(line).strip()}" for line in added if str(line).strip()]
        if not new:
            raise Refused("Nothing to add")
        if style:
            at = min(style["end"], len(data))
            if at and data[at - 1 : at] != b"\n":
                data[at:at] = b"\n"
                at += 1
            data[at:at] = ("\n".join(new) + "\n").encode("utf-8")
            return data.decode("utf-8")
        body = text.rstrip("\n")
        return (f"{body}\n\n" if body else "") + "\n".join(new) + "\n"
    target = next((key for key in ("change", "remove", "toggle") if key in change), None)
    if target is None:
        raise Refused(f"An edit of a file is one of {', '.join(EDITS)}")
    line = str(change[target]).strip()
    item = next((item for item in found if item.get("text") == line), None)
    if item is None:
        raise Refused(f"“{line}” is no longer in the file")
    if target == "remove":
        end = item["end"]
        if end < len(data) and data[end : end + 1] == b"\n" and end and data[end - 1 : end] != b"\n":
            end += 1
        del data[item["begin"] : end]
    elif target == "change":
        replacement = str(change.get("to", "")).strip()
        if not replacement:
            raise Refused("A changed line needs its new text in to")
        data[item["contentBegin"] : item["contentEnd"]] = replacement.encode("utf-8")
    else:
        done = change.get("done")
        done = item.get("checkbox") != "on" if done is None else bool(done)
        mark = ("X" if kind == "org" else "x") if done else " "
        if "checkboxBegin" in item:
            data[item["checkboxBegin"] : item["checkboxEnd"]] = f"[{mark}]".encode("utf-8")
        else:
            at = item["contentBegin"]
            data[at:at] = f"[{mark}] ".encode("utf-8")
    return data.decode("utf-8")


def merge(current: str, base: str | None, mine: str) -> str:
    """The phone's whole text over a file that may have changed since the phone
    read it: both sides' changes kept, unless they touch the same lines."""
    if base is None or base == current or mine == current:
        return mine
    if base == mine:
        return current
    with tempfile.TemporaryDirectory() as folder:
        paths = {}
        for name, text in (("current", current), ("base", base), ("mine", mine)):
            paths[name] = Path(folder) / name
            paths[name].write_text(text, encoding="utf-8")
        result = subprocess.run(["git", "merge-file", "-p", str(paths["mine"]), str(paths["base"]), str(paths["current"])],
                                capture_output=True, text=True)
    if result.returncode != 0:
        raise Refused("The file changed here too, in the same places; your version was kept aside")
    return result.stdout


def write(path: Path, text: str) -> None:
    """Replaces the file in one step, keeping its permissions."""
    mode = path.stat().st_mode & 0o777 if path.exists() else 0o644
    handle, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as out:
            out.write(text)
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
