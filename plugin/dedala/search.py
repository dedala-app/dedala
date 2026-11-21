# SPDX-FileCopyrightText: 2026 Julien Malka
# SPDX-License-Identifier: MIT

"""What the agent can find on the phone from here: his pages by what they
show, and the records of the stores he declared by their declared fields.
The phone's Search knows more (messages, topics); this knows what he built."""

import unicodedata

from .stores import records_of

SPOKEN = {"Text", "Label", "Button", "Section", "DisclosureGroup", "TextField"}
LIMIT = 30


def plain(text) -> str:
    """Letters alone, no accents nor case, so velodrome finds Vélodrome."""
    return "".join(c for c in unicodedata.normalize("NFKD", str(text)) if not unicodedata.combining(c)).casefold()


def strings(value) -> list[str]:
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, list):
        return [s for item in value for s in strings(item)]
    if isinstance(value, dict):
        return [s for key in sorted(value) for s in strings(value[key])]
    return []


def spoken(view, components: dict, seen: frozenset = frozenset()) -> list[str]:
    """The words a view shows as written in it, through its components."""
    if isinstance(view, str):
        return [] if "$" in view or not view else [view]
    if isinstance(view, list):
        return [s for child in view for s in spoken(child, components, seen)]
    if not isinstance(view, dict):
        return []
    found = []
    for key, value in view.items():
        if key in SPOKEN:
            found += spoken(value[0] if key == "Label" and isinstance(value, list) and value else value, components, seen)
        elif key[:1].isupper() and key not in seen and key in components:
            found += spoken(components[key].get("body"), components, seen | {key})
            found += spoken(value, components, seen)
        elif isinstance(value, (dict, list)):
            found += spoken(value, components, seen)
    return found


def field(record: dict, expression) -> str:
    """A declared title, subtitle or word as the phone reads it off a record:
    `$name`, `${name}`, or a plain string."""
    if not isinstance(expression, str):
        return ""
    text = expression.strip()
    if text.startswith("${") and text.endswith("}"):
        text = "$" + text[2:-1]
    if text.startswith("$"):
        value = record
        for part in text[1:].split("."):
            value = value.get(part) if isinstance(value, dict) else None
        return " ".join(strings(value)) if value is not None else ""
    return text


def entries(artifacts: dict, stores) -> list[dict]:
    """Everything searchable in what the agent built: {in, id, title, texts},
    pages and the records of the declared stores."""
    found = []
    components = artifacts.get("components", {})
    held = stores.held
    for page_id, page in artifacts.get("page", {}).items():
        store = held.get(page.get("store") or page_id.replace("-", "_"))
        found.append({"in": "page", "id": page_id, "title": page.get("title") or page_id,
                      "texts": spoken(page.get("view"), components) + strings(store)})
    for name, declaration in stores.declared.items():
        for item in records_of(held.get(name)) or []:
            texts = [field(item, declaration.get("subtitle"))] + [field(item, word)[:200_000] for word in declaration.get("words") or []]
            found.append({"in": name, "id": item["id"], "title": field(item, declaration.get("title")) or item.get("title") or item["id"], "texts": texts})
    return found


def search(found: list[dict], query: str, within: list[str] | None = None, limit: int = LIMIT) -> list[dict]:
    """The entries holding every word of the query, with where the first was found."""
    words = [plain(word) for word in query.split()]
    if not words:
        return []
    results = []
    for entry in found:
        if within and entry["in"] not in within:
            continue
        fields = [entry["title"]] + [text for text in entry["texts"] if text]
        plains = [plain(field) for field in fields]
        if not all(any(word in field for field in plains) for word in words):
            continue
        where = next((field for field, flat in zip(fields, plains) if words[0] in flat), entry["title"])
        where = " ".join(where.split())
        if len(where) > 160:
            at = plain(where).find(words[0])
            start = max(0, at - 60)
            where = ("…" if start else "") + where[start:start + 160] + "…"
        results.append({"in": entry["in"], "id": entry["id"], "title": entry["title"], "found_in": where})
    return results[:limit]
