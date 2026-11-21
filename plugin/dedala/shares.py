# SPDX-FileCopyrightText: 2026 Julien Malka
# SPDX-License-Identifier: MIT

"""What he shares from another app on his phone, through the share sheet: a
link (with the page's text as Safari showed it), photos, files or text, and a
note saying what he wants done with it. Each share is kept under
`shared/<id>/` before the agent hears of it, so a share sent twice (the app
sends again what was not acknowledged) is handled once."""

import json
import re
from pathlib import Path
from typing import Awaitable, Callable, Optional

INLINE_CHARS = 4000


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_. -]", "_", name).strip(" .")[:80] or "file"


async def keep(root: Path, event: dict, fetch: Callable[[str], Awaitable[Optional[bytes]]]) -> Optional[dict]:
    """The share as kept on disk, its blobs fetched into files; None when it
    is kept already."""
    identifier = re.sub(r"[^A-Za-z0-9_-]", "_", str(event.get("id") or ""))[:80]
    if not identifier:
        return None
    folder = root / identifier
    manifest = folder / "share.json"
    if manifest.exists():
        return None
    folder.mkdir(parents=True, exist_ok=True)

    async def joined(blobs) -> Optional[bytes]:
        parts = [await fetch(blob) for blob in blobs or []]
        return None if not parts or any(part is None for part in parts) else b"".join(parts)

    items = []
    for index, shared in enumerate(event.get("items") or []):
        kind = shared.get("type")
        item = {key: value for key, value in shared.items() if key not in ("blobs", "page")}
        if kind == "link" and shared.get("page"):
            page = await joined(shared["page"])
            if page is None:
                item["missing"] = "the page's text"
            else:
                (folder / f"{index}-page.txt").write_bytes(page)
                item["page"] = str(folder / f"{index}-page.txt")
        elif kind in ("image", "file") or shared.get("blobs"):
            body = await joined(shared.get("blobs"))
            name = f"{index}-{_safe(shared.get('name') or ('photo.jpg' if kind == 'image' else 'text.txt'))}"
            if body is None:
                item["missing"] = "its content"
            else:
                (folder / name).write_bytes(body)
                item["path"] = str(folder / name)
                item["size"] = len(body)
        items.append(item)
    kept = {"id": identifier, "conversation": event.get("conversation") or "main", "text": str(event.get("text") or "").strip(),
            "at": event.get("at"), "folder": str(folder), "items": items}
    manifest.write_text(json.dumps(kept, ensure_ascii=False, indent=1))
    return kept


def images(kept: dict) -> list[str]:
    return [item["path"] for item in kept["items"] if item.get("type") == "image" and item.get("path")]


def shown(kept: dict) -> list[dict]:
    """The items as his message shows them in the app."""
    found = []
    for item in kept["items"]:
        shown = {key: item[key] for key in ("type", "url", "title", "name", "size", "item") if item.get(key) is not None}
        if item.get("type") == "text":
            text = item.get("text") or (Path(item["path"]).read_text(errors="replace") if item.get("path") else "")
            shown["text"] = text[:280]
        found.append(shown)
    return found


def told(kept: dict) -> str:
    """What the agent reads: his note, then what came with it."""
    lines = []
    for item in kept["items"]:
        kind = item.get("type")
        missing = f" ({item['missing']} did not arrive)" if item.get("missing") else ""
        if kind == "link":
            line = f"- a link: {item.get('title') or ''} {item.get('url')}".replace("  ", " ")
            if item.get("page"):
                line += f"; the page's text as he saw it is in {item['page']}"
            if item.get("selection"):
                line += f"; he had selected: \"{item['selection']}\""
        elif kind == "image":
            line = f"- a photo, attached and kept at {item.get('path')}"
        elif kind == "file":
            line = f"- a file, {item.get('name')} ({item.get('mime')}), kept at {item.get('path')}"
        elif item.get("text") and len(item["text"]) <= INLINE_CHARS:
            line = f"- some text: \"{item['text']}\""
        else:
            line = f"- some text, kept at {item.get('path') or 'nowhere'}"
        lines.append(line + missing)
    return (f"{kept['text']}\n\n[app: he shared this from another app on his phone, with the note above:\n"
            + "\n".join(lines) + f"\nAll of it is kept in {kept['folder']}]")
