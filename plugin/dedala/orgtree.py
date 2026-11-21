# SPDX-FileCopyrightText: 2026 Julien Malka
# SPDX-License-Identifier: MIT

"""Org and Markdown read into the org-element tree (native/, the Rust library
the phone links too, here in the plugin's WebAssembly module): the same tree the app's `org()` and `markdown()` give
a screen, here for the twin to evaluate them and for edits to land on an
item's exact place in the file."""

from functools import lru_cache
from pathlib import Path

from . import native


def available() -> bool:
    return native.available()


@lru_cache(maxsize=256)
def parse(text: str, format: str = "") -> dict:
    """The tree of a text; `format` is "org" or "markdown", told from the
    text when empty."""
    return native.org_parse(text, format) or {"type": "org-data", "children": []}


def select(tree: dict, kind: str) -> list[dict]:
    """The nodes of one type anywhere in the tree, in document order."""
    found: list[dict] = []

    def walk(node: dict) -> None:
        if node.get("type") == kind:
            found.append(node)
        for child in node.get("children") or []:
            walk(child)
        for child in node.get("objects") or []:
            walk(child)

    walk(tree)
    return found


def format_of(path) -> str:
    return {".org": "org", ".md": "markdown", ".markdown": "markdown"}.get(Path(str(path)).suffix.lower(), "")
