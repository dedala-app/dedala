# SPDX-FileCopyrightText: 2026 Julien Malka
# SPDX-License-Identifier: MIT

"""What a view reads and draws, found by reading it: the components it uses,
the fields of each store it reads, what a change of data would leave empty."""

import json
import re


def still_drawn(ops: list[dict], artifacts: dict) -> list[str]:
    """Components a batch deletes that a page or a component it keeps still draws."""
    from .grammar import removed

    gone = removed(ops)
    if not gone:
        return []
    components = artifacts.get("components", {})
    pages = {**artifacts.get("page", {}), **{op.get("id"): op for op in ops if op.get("op") == "page" and "view" in op}}
    drawers = [(f"page {page_id}", page.get("view")) for page_id, page in pages.items()]
    drawers += [(f"component {name}", body.get("body")) for name, body in components.items() if name not in gone]
    return [f"{name} cannot be deleted: {drawer} draws it" for drawer, view in drawers
            for name in sorted(gone & set(used(view, components, {})))]


def used(node, components: dict, found: dict) -> dict:
    """The components a view draws, with the ones they draw in turn."""
    if isinstance(node, list):
        for child in node:
            used(child, components, found)
    elif isinstance(node, dict):
        for key, value in node.items():
            if key in components and key not in found:
                found[key] = components[key]
                used(components[key].get("body"), components, found)
            used(value, components, found)
    return found


def names_read(view) -> set[str]:
    """The names a view reads from its data, as `$name` or inside `${…}`: the
    first step of each path, the ones a `ForEach` names left out."""
    text = json.dumps(view, ensure_ascii=False)
    found = set(re.findall(r"\$([A-Za-z_]\w*)", text))
    for source in re.findall(r"\$\{([^}]*)\}", text):
        found |= set(re.findall(r"(?<![\w.])([A-Za-z_]\w*)(?!\w*\s*\()", re.sub(r"'[^']*'", "", source)))
    named = set(re.findall(r'"(?:as|index)": "([A-Za-z_]\w*)"', text))
    return found - named - {"item", "true", "false", "null"}


def _set_by(node) -> set[str]:
    """The state a view makes as it runs: what its inputs bind, what its
    actions set or toggle."""
    found: set[str] = set()
    if isinstance(node, list):
        for child in node:
            found |= _set_by(child)
    elif isinstance(node, dict):
        if isinstance(bound := node.get("bind"), str) and (match := re.match(r"\$([A-Za-z_]\w*)", bound)):
            found.add(match.group(1))
        if isinstance(node.get("set"), dict):
            found |= {key for key in node["set"] if isinstance(key, str)}
        if isinstance(node.get("toggle"), str):
            found.add(node["toggle"].lstrip("$"))
        for value in node.values():
            found |= _set_by(value)
    return found


def unresolved(view, available: set[str], card: bool, script: str | None = None) -> list[str]:
    """The names a view reads that nothing gives it: they show empty. A name its
    script mentions may be state a handler returns, so it is let be."""
    from .grammar import LIVE

    found = []
    for name in sorted(names_read(view) - available - LIVE - _set_by(view)):
        if script and re.search(rf"\b{re.escape(name)}\b", script):
            continue
        if name == "data" and card:
            found.append("The view reads $data, which a card does not have: it reads its data's keys by name ($gate, not "
                         "$data.gate); $data. is for widgets and Live Activities")
        else:
            found.append(f"The view reads ${name}, which is no store, {'data key, ' if card else ''}state, derived value or "
                         "live value: it shows empty")
    return found


def store_reads(view, components: dict, stores) -> dict[str, set[str]]:
    """The fields of each store a view and its widgets read, as `$store.field` or
    inside `${…}`; inside a component, a prop of the same name hides the store."""
    found: dict[str, set[str]] = {}
    parts = [(view, set())] + [(body.get("body"), set(body.get("props") or ())) for body in used(view, components, {}).values()
                               if isinstance(body, dict)]
    for node, props in parts:
        text = json.dumps(node)
        sources = re.findall(r"\$\{([^}]*)\}", text) + re.findall(r"\$([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+)", text)
        for source in sources:
            for name, key in re.findall(r"(?<![\w.'\"])([A-Za-z_]\w*)\.([A-Za-z_]\w*)", source):
                if name in stores and name not in props:
                    found.setdefault(name, set()).add(key)
    return found


def store_gaps(reads: dict[str, set[str]], stores: dict, own: str | None = None) -> list[str]:
    """What a view reads from other stores that they do not have."""
    gaps = []
    for name, keys in sorted(reads.items()):
        held = stores.get(name)
        if name == own or not isinstance(held, dict) or not (missing := sorted(keys - set(held))):
            continue
        gaps.append(f"The view reads {', '.join(f'${name}.{key}' for key in missing)}, which the store {name} does not have: "
                    "they show empty")
    return gaps


def _readers(store: str, artifacts: dict, besides: str | None = None) -> dict[str, set[str]]:
    """The pages that read a store, but `besides`, with the fields each reads."""
    components = artifacts.get("components", {})
    return {page_id: keys for page_id, recorded in artifacts.get("page", {}).items()
            if page_id != besides and (keys := store_reads(recorded.get("view"), components, {store}).get(store))}


def sharing(store: str, data, artifacts: dict, besides: str | None = None) -> tuple[list[str], list[str]]:
    """The other pages reading a store about to hold `data`, and what of theirs it breaks."""
    readers = _readers(store, artifacts, besides)
    broken = [f"Page {page_id} reads {', '.join(f'${store}.{key}' for key in missing)}, which the new data does not have: "
              f"fix its view or keep {'those keys' if len(missing) > 1 else 'that key'}"
              for page_id, keys in sorted(readers.items())
              if isinstance(data, dict) and (missing := sorted(keys - set(data)))]
    return sorted(readers), broken


def shared(view, components: dict, artifacts: dict, page_id: str | None = None) -> dict[str, list[str]]:
    """Each store a view reads, with the other pages that read it."""
    stores = set(artifacts.get("store", {}))
    read = set(store_reads(view, components, stores))
    return {name: sorted(_readers(name, artifacts, page_id)) for name in sorted(read)}


def lists_replaced(before, patch, path: str = "") -> list[str]:
    """Lists in a patch replace the old ones whole: say so when items lost fields."""
    found: list[str] = []
    if not isinstance(before, dict) or not isinstance(patch, dict):
        return found
    for key, value in patch.items():
        old, where = before.get(key), f"{path}{key}"
        if isinstance(value, dict) and isinstance(old, dict):
            found += lists_replaced(old, value, f"{where}.")
        elif isinstance(value, list) and isinstance(old, list):
            had = {field for item in old if isinstance(item, dict) for field in item}
            has = {field for item in value if isinstance(item, dict) for field in item}
            if has and (lost := sorted(had - has)):
                found.append(f"The patch replaced {where} whole: its items no longer have {', '.join(lost)}. "
                             "A list is replaced, not merged: send the full list")
    return found
