# SPDX-FileCopyrightText: 2026 Julien Malka
# SPDX-License-Identifier: MIT

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "plugin"))

from dedala.bank import Cards, keep  # noqa: E402


def test_a_card_is_kept_as_it_last_stood(tmp_path):
    home = tmp_path / "dedala"
    cards = Cards(home)
    cards.said({"id": "theo", "conversation": "main", "text": "Théo wrote", "card": {"view": {"Text": "$subject"}, "data": {"subject": "v1", "draft": True}}})
    cards.patched({"id": "theo", "data": {"subject": "Futur & Ruptures", "draft": None}})
    capture = tmp_path / "theo.jpg"
    capture.write_bytes(b"jpeg")
    cards.captured("theo", str(capture))
    path = keep(home, "theo", Cards(home).get("theo"), "the original first, summary on tap", "said")
    entry = json.loads(path.read_text())
    assert path == tmp_path / "dedala" / "bank" / "theo.json"
    assert entry["data"] == {"subject": "Futur & Ruptures"}
    assert entry["note"] == "the original first, summary on tap"
    assert (path.parent / entry["capture"]).read_bytes() == b"jpeg"


def test_a_note_reaches_a_card_already_in_the_bank(tmp_path):
    from dedala.bank import annotate

    home = tmp_path / "dedala"
    keep(home, "theo", {"text": "Théo", "view": {"Text": "Hi"}}, "", "loved in the app")
    path = annotate(home, "theo", "original first")
    assert json.loads(path.read_text())["note"] == "original first"
    assert annotate(home, "unknown", "x") is None


def test_the_plugin_brings_its_skills_named_and_described():
    from dedala.hermes.plugin import skills

    found = {name: (path, description) for name, path, description in skills()}
    assert sorted(found) == ["building-pages", "drawing-cards", "living-in-the-app"]
    assert all(path.is_file() and description for path, description in found.values())
    assert (found["drawing-cards"][0].parent / "references" / "dedala-ui.md").is_file()
