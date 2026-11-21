# SPDX-FileCopyrightText: 2026 Julien Malka
# SPDX-License-Identifier: MIT

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "plugin"))

from dedala import scripts  # noqa: E402


LIVE = {**scripts.samples([]), "stores": {"documents": [{"id": "offer", "title": "Offer", "people": ["Marta"]}]}}
SPLIT = """
function shares({data, state}) {
  const who = data.people.filter(p => !state.left_out.includes(p))
  return who.map(p => ({name: p, owes: h.round(data.total / who.length, 2)}))
}
function ask(input) { return {send: {split: shares(input)}, say: 'Ask them'} }
function marta({stores}) { return stores.documents.filter(d => d.people.includes('Marta')).map(d => d.id) }
"""


def card(**extra):
    return {"view": {"Button": "Ask", "action": {"run": "ask"}}, "state": {"left_out": ["Théo"]},
            "script": SPLIT, "derive": {"shares": "shares", "docs": "marta"}, **extra}


def test_derived_values_and_handlers_are_computed_here():
    found = scripts.check(card(), {"total": 90, "people": ["Julien", "Manon", "Théo"]}, {}, {}, LIVE)
    assert found["derived"] == {"shares": [{"name": "Julien", "owes": 45}, {"name": "Manon", "owes": 45}], "docs": ["offer"]}
    assert found["handlers"]["ask"]["say"] == "Ask them"
    assert "errors" not in found


def test_a_script_that_breaks_on_the_data_is_refused():
    found = scripts.check(card(), {"total": 90}, {}, {}, LIVE)
    assert any("shares" in error and "filter" in error for error in found["errors"])


def test_a_handler_can_only_return_actions():
    found = scripts.check(card(script=SPLIT + "function ask() { return {delete: true} }"), {"total": 1, "people": []}, {}, {}, LIVE)
    assert any("delete, which a handler cannot do" in error for error in found["errors"])


def test_a_derived_value_cannot_hide_a_data_key():
    found = scripts.check(card(derive={"total": "shares"}), {"total": 90, "people": []}, {}, {}, LIVE)
    assert any("name of a data key" in error for error in found["errors"])


def test_an_endless_script_runs_out_of_time(monkeypatch):
    monkeypatch.setattr(scripts, "TIMEOUT", 1)
    found = scripts.check({"script": "function spin() { while (true) {} }", "derive": {"x": "spin"}}, {}, {}, {}, LIVE)
    assert found["errors"] == ["Script: the derived value x (spin) ran out of time"]


def test_modules_are_checked_and_shared():
    assert scripts.check_modules({"money": "function twice(x) { return x * 2 }\nreturn {twice}"}, {}) == []
    assert scripts.check_modules({"broken": "return nope.x"}, {})[0].startswith("The modules do not load")
    found = scripts.check({"script": "function go() { return money.twice(21) }", "derive": {"x": "go"}}, {},
                          {"money": "function twice(x) { return x * 2 }\nreturn {twice}"}, {}, LIVE)
    assert found["derived"] == {"x": 42}


def test_a_script_reads_other_stores_by_name():
    page = {"view": {"Text": "$written"}, "script": "function written({stores}) { return stores.daily.lines.length }",
            "derive": {"written": "written"}}
    found = scripts.check(page, {}, {}, {}, {**LIVE, "stores": {"daily": {"lines": [{"text": "Bonjour"}]}, "big": {"x": 1}}})
    assert found["derived"] == {"written": 1}


def test_a_script_gets_only_the_stores_it_names():
    page = {"view": {"Text": "$names"}, "script": "function names({stores}) { return Object.keys(stores).sort().join(' ') + ' ' + stores['other'].n }",
            "derive": {"names": "names"}}
    found = scripts.check(page, {}, {}, {}, {**LIVE, "stores": {"daily": {}, "other": {"n": 2}, "big": {}}})
    assert found["derived"] == {"names": "other 2"}


def test_what_a_script_prints_itself_is_not_taken_for_a_result():
    output = '\n'.join(['{"note": "from the script"}', '3', '"text"', '{"i": 1, "value": "2"}', '{"i": 0, "error": "boom"}', '{"i": 7, "value": "9"}'])
    assert scripts._parse(output, 3) == [{"error": "boom"}, {"value": 2}, None]
    assert scripts._parse('{"load": "x is not defined"}', 2) == [{"error": "the script does not load: x is not defined"}] * 2


def test_a_script_reads_a_note_through_the_org_helper():
    page = {"view": {"Text": "$open"}, "script": "function open({stores}) { return h.org(stores.daily.text, 'item').filter(i => i.checkbox == 'off').map(i => i.text) }\n"
            "function outline({stores}) { return h.org(stores.daily.text, 'headline').map(x => x.todoKeyword + ' ' + x.title) }",
            "derive": {"open": "open", "outline": "outline"}}
    text = "* TODO Habits\n- [X] Run\n- [ ] Read a long\n  book\n* DONE Done\n"
    found = scripts.check(page, {}, {}, {}, {**LIVE, "stores": {"daily": {"text": text}}})
    assert found["derived"] == {"open": ["Read a long book"], "outline": ["TODO Habits", "DONE Done"]}


def test_each_example_of_a_handler_keeps_its_result():
    found = scripts.check(card(examples=[{"run": "ask", "state": {"left_out": []}}, {"run": "ask", "state": {"left_out": ["Manon"]}}]),
                          {"total": 90, "people": ["Julien", "Manon"]}, {}, {}, LIVE)
    assert [len(result["send"]["split"]) for result in found["handlers"]["ask"]] == [2, 1]


def test_a_handler_the_view_runs_must_be_in_the_script():
    found = scripts.check(card(view={"Button": "Ask", "action": {"run": "aks"}}, examples=[{"run": "ask"}]),
                          {"total": 90, "people": ["Julien"]}, {}, {}, LIVE)
    assert any("aks" in error for error in found["errors"])


def test_button_verbs_returned_by_a_handler_are_named_as_such():
    found = scripts.check({"view": {"Button": "Go", "action": {"run": "go"}}, "script": "function go() { return {close: true} }"}, {}, {}, {}, LIVE)
    assert any("what a button's action does" in error for error in found["errors"])


def test_dates_formatted_by_locale_are_noted():
    found = scripts.check({"view": {"Text": "$when"}, "script": "function when({now}) { return new Date(now).toLocaleDateString() }",
                           "derive": {"when": "when"}}, {}, {}, {}, LIVE)
    assert "toLocale" in found["notes"][0]
