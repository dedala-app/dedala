# SPDX-FileCopyrightText: 2026 Julien Malka
# SPDX-License-Identifier: MIT

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "plugin"))

from dedala.files import Refused, edit, items, merge, read  # noqa: E402
from dedala.stores import Stores  # noqa: E402

DAILY = """#+title:      dimanche 25 octobre 2026
#+filetags:   :daily:

* Journal
- J'ai travaillé toute la journée sur mon appli.
  Et un peu sur Jacques.
- J'ai pris RDV chez le médecin.

* Later
"""


def test_a_file_reads_as_its_text_and_its_items_come_from_the_tree(tmp_path):
    note = tmp_path / "daily.org"
    note.write_text(DAILY)
    data = read(note)
    assert data["exists"] and data["name"] == "daily.org" and data["text"] == DAILY and "lines" not in data
    assert [item["text"] for item in items(DAILY, "org")] == ["J'ai travaillé toute la journée sur mon appli. Et un peu sur Jacques.",
                                                              "J'ai pris RDV chez le médecin."]
    assert read(tmp_path / "missing.org")["exists"] is False


def test_an_org_heading_is_not_a_list_item():
    assert [item["text"] for item in items("* Journal\n- a\n  * b\n", "org")] == ["a", "b"]


def test_appended_lines_go_after_the_last_line_and_its_continuation():
    text = edit(DAILY, {"append": ["Une ligne de plus.", "Et une autre."]}, "org")
    assert "- J'ai pris RDV chez le médecin.\n- Une ligne de plus.\n- Et une autre.\n\n* Later" in text
    continued = edit(DAILY.replace("- J'ai pris RDV chez le médecin.\n", ""), {"append": "Fin."}, "org")
    assert "  Et un peu sur Jacques.\n- Fin.\n" in continued


def test_appending_to_a_file_without_a_list_starts_one():
    assert edit("#+title: x\n", {"append": "Premier."}, "org") == "#+title: x\n\n- Premier.\n"
    assert edit("", {"append": "First."}, "markdown") == "- First.\n"


def test_lines_are_changed_removed_and_ticked_by_their_text():
    groceries = "# Groceries\n\n- [ ] Milk\n- [x] Bread\n- Eggs\n"
    assert "- [ ] Oat milk\n" in edit(groceries, {"change": "Milk", "to": "Oat milk"}, "markdown")
    assert "Bread" not in edit(groceries, {"remove": "Bread"}, "markdown")
    assert "- [x] Milk\n" in edit(groceries, {"toggle": "Milk"}, "markdown")
    assert "- [ ] Bread\n" in edit(groceries, {"toggle": "Bread"}, "markdown")
    assert "- [x] Eggs\n" in edit(groceries, {"toggle": "Eggs", "done": True}, "markdown")
    assert "- [X] Fait\n" in edit("- Fait\n", {"toggle": "Fait"}, "org")
    wrapped = "* Habits\n- [ ] A long task\n  that wraps\n- [X] Short\n"
    assert edit(wrapped, {"toggle": "A long task that wraps"}, "org").startswith("* Habits\n- [X] A long task\n  that wraps\n")
    assert edit(wrapped, {"remove": "A long task that wraps"}, "org") == "* Habits\n- [X] Short\n"
    assert edit(wrapped, {"change": "A long task that wraps", "to": "A short task"}, "org") == "* Habits\n- [ ] A short task\n- [X] Short\n"


def test_a_line_that_is_gone_refuses_the_edit():
    with pytest.raises(Refused, match="no longer in the file"):
        edit("- Milk\n", {"toggle": "Bread"}, "markdown")


def test_a_list_with_boxes_gets_new_lines_with_boxes():
    assert edit("- [ ] Milk\n", {"append": "Bread"}, "markdown") == "- [ ] Milk\n- [ ] Bread\n"


def test_the_whole_text_merges_with_what_changed_meanwhile():
    base = "one\ntwo\nthree\nfour\nfive\n"
    here = base.replace("one", "ONE")
    phone = base.replace("five", "FIVE")
    assert merge(here, base, phone) == "ONE\ntwo\nthree\nfour\nFIVE\n"
    with pytest.raises(Refused, match="same places"):
        merge(base.replace("three", "3"), base, base.replace("three", "trois"))


def stores(tmp_path) -> Stores:
    return Stores(tmp_path / "dedala" / "stores")


def test_an_edit_to_a_missing_file_is_refused_and_a_made_file_is_edited(tmp_path):
    found = stores(tmp_path)
    (tmp_path / "notes").mkdir()
    found.link("note", str(tmp_path / "notes" / "today.org"))
    assert found.kind("note") == "text" and found.held["note"]["exists"] is False
    with pytest.raises(Refused):
        found.apply_edit("note", None, {"append": "Bonjour."})
    (tmp_path / "notes" / "today.org").write_text("#+title: today\n")
    found.apply_edit("note", None, {"append": "Bonjour."})
    assert (tmp_path / "notes" / "today.org").read_text() == "#+title: today\n\n- Bonjour.\n"
    assert found.scan() == ["note"] and found.held["note"]["text"].endswith("- Bonjour.\n")


def test_a_save_from_an_editor_is_noticed_once(tmp_path):
    note = tmp_path / "note.md"
    note.write_text("- a\n")
    found = stores(tmp_path)
    found.link("note", str(note))
    assert found.scan() == []
    note.write_text("- a\n- b\n")
    assert found.scan() == ["note"] and found.op("note")["kind"] == "text" and found.held["note"]["text"] == "- a\n- b\n"
    assert found.scan() == []


def test_a_refused_text_is_kept_aside(tmp_path):
    note = tmp_path / "note.md"
    note.write_text("one\ntwo\n")
    found = stores(tmp_path)
    found.link("note", str(note))
    with pytest.raises(Refused):
        found.apply_edit("note", None, {"text": "uno\ntwo\n", "base": "ONE?\ntwo\n"})
    assert (list((tmp_path / "dedala" / "conflicts").glob("note-*.md"))[0]).read_text() == "uno\ntwo\n"
    assert note.read_text() == "one\ntwo\n"


def test_a_save_between_reading_and_writing_is_not_overwritten(tmp_path, monkeypatch):
    from dedala import stores as module

    path = tmp_path / "note.md"
    path.write_text("- a\n")
    found = stores(tmp_path)
    found.link("note", str(path))
    edit, saved = module.edit, []

    def edit_while_he_saves(text, change, kind):
        if not saved:
            saved.append(True)
            path.write_text("- a\n- from his editor\n")
        return edit(text, change, kind)

    monkeypatch.setattr(module, "edit", edit_while_he_saves)
    found.apply_edit("note", None, {"append": "b"})
    assert path.read_text() == "- a\n- from his editor\n- b\n"
