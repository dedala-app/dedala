# SPDX-FileCopyrightText: 2026 Julien Malka
# SPDX-License-Identifier: MIT

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "plugin"))

from dedala.checks import remarks  # noqa: E402
from dedala.grammar import check_ops, idle, problems  # noqa: E402

EXAMPLES = sorted((ROOT / "docs" / "dedala-ui" / "examples").rglob("*.json"))


def test_every_example_is_sound():
    assert EXAMPLES
    for path in EXAMPLES:
        example = json.loads(path.read_text())
        ops = example if isinstance(example, list) else [example]
        assert check_ops(ops, set()) == [], path.name


def test_children_as_an_object_are_refused_with_the_way_to_write_them():
    card = {"VStack": {"spacing": 10, "children": [{"Text": "6 / 23"}]}}
    found = problems(card)
    assert len(found) == 1
    assert "takes its children as a list" in found[0]
    assert '{"VStack": [ … ], "spacing": 10}' in found[0]


def test_unknown_views_and_modifiers_are_named():
    found = problems({"Card": [{"Txt": "Hi"}, {"Text": "Hi", "colour": "red"}, {"spacing": 4}]})
    assert any("unknown view 'Txt'" in problem for problem in found)
    assert any("unknown modifier or argument 'colour'" in problem for problem in found)
    assert any("needs one capitalised view key" in problem for problem in found)


def test_an_argument_a_view_does_not_take_is_noted_once_and_not_refused():
    card = {"Card": [{"Card": [{"Text": "Hi", "id": "greeting", "font": "headline"}], "alignment": "center", "spacing": 8},
                     {"ProgressView": 0.4, "style": "linear", "minWidth": 80},
                     {"Flight": {"number": "AF12", "style": "big"}, "alignment": "leading"}], "alignment": "center"}
    assert problems(card, {"Flight"}) == []
    found = idle(card)
    assert len(found) == 2
    assert found[0].startswith("alignment does nothing on Card: it is an argument of ") and "VStack" in found[0]
    assert found[1].startswith("style does nothing on ProgressView")


def test_no_example_carries_an_argument_that_does_nothing():
    for path in EXAMPLES:
        example = json.loads(path.read_text())
        assert idle(example) == [], path.name


def test_a_name_that_is_also_a_live_value_is_noted():
    found = remarks({"Text": "$pages"}, {"pages": [], "total": 3}, {"today": 1}, {"tip": "tip"})
    assert len(found) == 2 and "data key pages" in found[0] and "state today" in found[1]
    assert "store is named today" in remarks({"Text": "x"}, {}, store="today")[0]
    assert remarks({"VStack": [], "spacing": 4}, {"people": []}, {}, None, "trip") == []


def test_defined_components_are_views():
    ops = [{"op": "define", "components": {"Match": {"props": {}, "body": {"Text": "$home"}}}},
           {"op": "say", "card": {"view": {"Match": {"home": "OL"}}}}]
    assert check_ops(ops, set()) == []
    assert check_ops(ops[1:], set()) != []
    assert check_ops(ops[1:], {"Match"}) == []


def test_props_beside_the_components_are_refused_with_where_they_go():
    ops = [{"op": "define", "components": {"SCElection": {"body": {"Text": "Hi"}}, "props": {"election": {}}}}]
    found = check_ops(ops, set())
    assert len(found) == 1
    assert "move it inside SCElection" in found[0]


def test_a_component_defined_as_null_is_deleted():
    ops = [{"op": "define", "components": {"Badge": None}}]
    assert check_ops(ops, {"Badge"}) == []
    assert check_ops(ops + [{"op": "say", "card": {"view": {"Badge": {}}}}], {"Badge"}) != []


def test_the_grammar_is_the_app_s_own_tables_written_out():
    grammar = json.loads((ROOT / "plugin" / "dedala" / "grammar.json").read_text())
    assert set(grammar["takes"]) == set(grammar["views"]) | {"ForEach", "If"}
    taken = {name for names in grammar["takes"].values() for name in names}
    assert taken <= set(grammar["arguments"]) and set(grammar["containers"]) <= set(grammar["views"])
    assert {"send", "edit", "set", "run"} <= set(grammar["actions"])


def test_a_live_activity_design_is_checked_where_the_phone_reads_it():
    design = {"views": {"lock": {"Score": {"home": "$home"}}, "lockCompact": {"Text": "$home"}},
              "components": {"Score": {"props": {"home": ""}, "body": {"HStack": ["$home"]}}}, "tint": "#FF9F0A"}
    assert check_ops([{"op": "activity", "design": design}], set()) == []
    assert check_ops([{"op": "activity", "id": "ol", **design}], set()) == []
    broken = {"views": {"lock": {"VStack": {"children": []}}, "minimal": {"Sparkle": {}}}}
    found = check_ops([{"op": "activity", "design": broken}], set())
    assert any("design.views.lock" in problem and "VStack" in problem for problem in found)
    assert any("design.views.minimal" in problem and "Sparkle" in problem for problem in found)
    flat = check_ops([{"op": "activity", "design": {"lock": {"Text": "2-1"}, "lockCompact": {"Text": "2-1"}}}], set())
    assert len(flat) == 1 and "go inside views" in flat[0]
    assert check_ops([{"op": "activity", "id": "ol", "data": {"home": 2}}], set()) == []


def test_a_show_names_a_component_the_batch_knows():
    row = {"Text": "$it.number", "onTap": {"show": "Invoice", "with": {"id": "$it.id"}}}
    page = {"op": "page", "id": "invoices", "view": {"ForEach": "$invoices.items", "as": "it", "content": row}}
    found = check_ops([page], set())
    assert len(found) == 1 and "no component 'Invoice'" in found[0]
    define = {"op": "define", "components": {"Invoice": {"props": ["id"], "title": "Invoice", "body": {"Text": "$id"}}}}
    assert check_ops([define, page], set()) == []
    assert check_ops([page], {"Invoice"}) == []
    assert check_ops([{"op": "page", "id": "p", "view": {"Button": "Go", "action": {"show": "$it.screen"}}}], set()) == []


def test_a_toolbar_takes_up_to_three_buttons_or_menus_with_a_symbol():
    info = {"Button": "Info", "symbol": "info.circle", "action": {"show": "NoteInfo", "with": {"id": "$id"}, "as": "sheet"}}
    sound = [{"op": "define", "components": {"NoteInfo": {"props": ["id"], "body": {"Text": "$id"}},
                                              "NoteScreen": {"props": ["id"], "body": {"Text": "$id"}, "toolbar": [info]}}},
             {"op": "page", "id": "notes", "title": "Notes", "view": {"Text": "x"}, "toolbar": [info, {"Menu": "More", "symbol": "ellipsis.circle", "items": [{"title": "A", "copy": "a"}]}]}]
    assert check_ops(sound, set()) == []
    found = check_ops([{"op": "page", "id": "notes", "title": "Notes", "view": {"Text": "x"},
                        "toolbar": [{"Text": "no"}, {"Button": "Info", "action": {"copy": "x"}}, {"Button": "A", "symbol": "a.circle", "style": "bordered", "action": {"copy": "x"}},
                                    {"Button": "B", "symbol": "b.circle", "action": {"show": "Missing"}}]}], set())
    assert any("toolbar[0]: the bar takes only a Button or a Menu" in problem for problem in found)
    assert any("toolbar[1]: a bar button needs a symbol" in problem for problem in found)
    assert any("toolbar[2]: the bar styles its own buttons" in problem for problem in found)
    assert any("at most 3 items" in problem for problem in found)
    assert any("toolbar[3]" in problem and "Missing" in problem for problem in found)
    assert check_ops([{"op": "define", "components": {"S": {"body": {"Text": "x"}, "toolbar": {"Button": "x"}}}}], set()) == [
        "ops[0] define components.S.toolbar: a list of up to 3 Buttons or Menus with a symbol, drawn in the bar"]


def test_an_action_the_phone_does_not_know_and_a_page_that_is_not_there_are_refused():
    view = {"VStack": [{"Button": "Done", "action": {"dismiss": True}}, {"Text": "Go", "onTap": [{"page": "budjet"}]},
                       {"Button": "Ok", "action": {"page": "budget", "haptic": "light"}}]}
    found = check_ops([{"op": "page", "id": "home", "view": view}], set(), set(), {"budget"})
    assert any("dismiss is not an action" in problem for problem in found)
    assert any("no page 'budjet'" in problem for problem in found)
    assert not any("'budget'" in problem for problem in found)


def test_names_a_view_reads_from_nowhere_are_noted():
    from dedala.analysis import unresolved

    view = {"VStack": [{"Text": "$data.gate"}, {"Text": "$gate"}, {"TextField": "x", "bind": "$draft"}, {"Text": "$draft"},
                       {"Text": "${field == 'a' ? 1 : 2}"}, {"Text": "$ghost"}]}
    found = unresolved(view, {"gate"}, card=True, script="function open() { return {state: {field: 'a'}} }")
    assert len(found) == 2 and "$data. is for widgets" in found[0] and "$ghost" in found[1]
