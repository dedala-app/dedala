# SPDX-FileCopyrightText: 2026 Julien Malka
# SPDX-License-Identifier: MIT

import json
from datetime import datetime, timezone

import pytest

from support import until

from dedala import transition
from dedala.agents import Agent
from dedala.bank import Cards
from dedala.link import Link
from dedala.server import Server
from dedala.transition import Drawing, Preparation

MOMENT = datetime(2026, 11, 23, 17, 0, tzinfo=timezone.utc)
PHONE = {"utcOffset": 3600}
LIVE = {"waiting": [], "running": {"turns": [], "runs": []}, "today": {"answered": [], "runs": [], "messages": 0}, "pages": [], "commands": {}}
TASKS = [{"id": "t1", "title": "Call the plumber", "due": "2026-11-23T21:00:00+01:00", "done": False},
         {"id": "t2", "title": "Renew the lease", "due": "2026-11-25T09:30:00+01:00", "done": True}]
TASK_ROW = {"props": {"task": None}, "body": {"HStack": [
    {"Image": "${task.done ? 'checkmark.circle.fill' : 'circle'}"},
    {"Text": "$task.title", "bold": "${!task.done}"},
    {"Spacer": {}},
    {"If": "task.done", "then": {"Text": "${date(task.due, 'dayMonth')}", "color": "secondary"}, "else": {"Text": "${until(task.due)}"}},
], "spacing": 8}}
PAGE = {"title": "Tasks", "symbol": "checklist", "state": {"filter": "all"},
        "script": "function left({stores}) { return stores.tasks.filter(t => !t.done).length }", "derive": {"left": "left"},
        "view": {"VStack": [
            {"Text": "${count(tasks)} tasks, ${left} left", "font": "headline"},
            {"Picker": "Show", "bind": "$filter", "options": ["all", "open"], "style": "segmented"},
            {"ForEach": "$tasks", "as": "task", "content": {"TaskRow": {"task": "$task"}}, "padding": 4},
            {"If": "left == 0", "then": "All done", "else": {"Text": "Still ${left} to do", "hidden": "filter == 'open'"}},
        ], "spacing": 12}}
DRAWN = {"VStack": [
    {"Text": "2 tasks, 1 left", "font": "headline"},
    {"Picker": "Show", "value": "all", "options": ["all", "open"], "style": "segmented"},
    {"Group": [{"HStack": [{"Image": "circle"}, {"Text": "Call the plumber", "bold": True}, {"Spacer": {}}, {"Text": "in 3 h"}], "spacing": 8}],
     "padding": 4},
    {"Group": [{"HStack": [{"Image": "checkmark.circle.fill"}, {"Text": "Renew the lease", "bold": False}, {"Spacer": {}},
                           {"Text": "25 Nov", "color": "secondary"}], "spacing": 8}], "padding": 4},
    {"Text": "Still 1 to do"},
], "spacing": 12}
BROKEN = {"view": {"Text": "$total"}, "script": "function total() { throw new Error('no total') }", "derive": {"total": "total"}}


def drawing(stores=None, components=None) -> Drawing:
    return Drawing(stores or {}, LIVE, components or {}, {}, MOMENT, PHONE)


def home(tmp_path) -> Preparation:
    link = Link(tmp_path, "http://relay.invalid", "token", "Jacques")
    link.state["display"] = PHONE
    return Preparation(link, Cards(tmp_path))


def read(preparation: Preparation, name: str):
    text = (preparation.folder / name).read_text()
    return [json.loads(line) for line in text.splitlines()] if name.endswith(".jsonl") else json.loads(text)


def test_a_page_is_the_literal_tree_it_draws():
    assert drawing({"tasks": TASKS}, {"TaskRow": TASK_ROW}).of(PAGE) == {"view": DRAWN, "state": {"filter": "all"}}


def test_a_tap_that_asks_the_phone_lasts_and_one_on_state_or_script_disables_its_button():
    flight = {"number": "AF1234", "gate": "K42", "url": "https://example.org/af1234"}
    card = {"data": {"flight": flight}, "state": {"open": False}, "script": "function ask({data}) { return {send: {about: data.flight.number}} }",
            "view": {"Card": [
                {"Button": "Check in", "action": {"send": {"checkin": "$flight.number", "gate": "${flight.gate}"}, "say": "Check in ${flight.number}"}},
                {"Button": "Details", "action": {"set": {"open": True}}},
                {"Button": "Ask", "action": {"run": "ask"}},
                {"Button": "Open", "action": [{"open": "$flight.url"}, {"toggle": "open"}], "style": "bordered"},
                {"Toggle": "Window seat", "bind": "$open", "onChange": {"edit": {"store": "trip", "window": "$value"}}},
                {"Text": "$flight.gate", "onTap": {"copy": "$flight.gate"}, "actions": [
                    {"title": "Copy ${flight.gate}", "symbol": "doc.on.doc", "copy": "$flight.gate"},
                    {"title": "More", "show": "Flight", "with": {"number": "$flight.number"}}]},
            ]}}
    assert drawing().of(card)["view"] == {"Card": [
        {"Button": "Check in", "action": {"send": {"checkin": "AF1234", "gate": "K42"}, "say": "Check in AF1234"}},
        {"Button": "Details", "disabled": True},
        {"Button": "Ask", "disabled": True},
        {"Button": "Open", "action": {"open": "https://example.org/af1234"}, "style": "bordered"},
        {"Toggle": "Window seat", "value": False},
        {"Text": "K42", "onTap": {"copy": "K42"}, "actions": [{"title": "Copy K42", "symbol": "doc.on.doc", "copy": "K42"}]},
    ]}


def test_an_action_handed_to_a_component_is_worked_out_where_it_is_written():
    chip = {"props": {"label": "", "onPick": None}, "body": {"Button": "$label", "action": "$onPick"}}
    view = {"ForEach": "$people", "as": "who", "content": {"Chip": {"label": "$who", "onPick": {"send": {"picked": "$who"}}}}}
    assert drawing(components={"Chip": chip}).of({"view": view, "data": {"people": ["Alex", "Manon"]}})["view"] == {"Group": [
        {"Button": "Alex", "action": {"send": {"picked": "Alex"}}}, {"Button": "Manon", "action": {"send": {"picked": "Manon"}}}]}


def test_a_dollar_that_is_no_expression_comes_out_as_written():
    card = {"data": {"amount": 3, "note": "costs $x, at most"}, "view": [{"Text": "Lunch: $12, or 5 $"}, "$ ${amount} and US$", {"Text": "$note"}]}
    assert drawing().of(card)["view"] == [{"Text": "Lunch: $12, or 5 $"}, "$ 3 and US$", {"Text": "costs $x, at most"}]


def test_a_list_holds_its_rows_and_a_hidden_node_is_gone():
    view = {"VStack": [{"List": "$notes", "as": "note", "content": [{"Text": "$note.title"}, {"Text": "$note.at", "visible": "note.at"}]},
                       {"Text": "None", "visible": "count(notes) == 0"}]}
    notes = [{"title": "Plumber", "at": "Monday"}, {"title": "Lease"}]
    assert drawing({"notes": notes}).of({"view": view})["view"] == {"VStack": [{"List": [
        {"VStack": [{"Text": "Plumber"}, {"Text": "Monday"}], "alignment": "leading", "spacing": 0}, {"Text": "Lease"}]}]}


def test_views_inside_arguments_are_drawn_and_what_folds_or_binds_shows_where_it_stood():
    view = {"VStack": [
        {"DisclosureGroup": "Done", "expanded": "$open[group.id]", "content": {"ForEach": "$group.items", "content": "$item"}},
        {"Toggle": "Keep", "bind": "$keep[group.id]"},
        {"Menu": {"Image": "${group.symbol}"}, "items": [{"title": "Open", "page": "$group.id"}, {"title": "Hide", "toggle": "hidden"}]},
        {"Color": "blue", "overlay": {"If": "count(group.items) > 1", "then": {"Text": "${count(group.items)}"}}, "disabled": "!keep.a"},
    ], "state": {"open": {"a": True}, "keep": {"a": False}}}
    group = {"id": "a", "symbol": "tray", "items": ["Milk", "Eggs"]}
    assert drawing().of({"view": view, "data": {"group": group}})["view"] == {"VStack": [
        {"DisclosureGroup": "Done", "expanded": True, "content": ["Milk", "Eggs"]},
        {"Toggle": "Keep", "value": False},
        {"Menu": {"Image": "tray"}, "items": [{"title": "Open", "page": "a"}]},
        {"Color": "blue", "overlay": {"Text": "2"}, "disabled": True},
    ]}


def test_the_history_holds_a_patched_card_as_it_stands(tmp_path):
    preparation = home(tmp_path)
    bill = {"op": "say", "id": "bill", "conversation": "main", "text": "Pay?", "components": {"Bill": {"body": "x"}},
            "card": {"view": {"Text": "${amount} € due ${due}"}, "data": {"amount": 40, "due": "Friday"}}}
    patch = {"op": "patch", "id": "bill", "data": {"amount": 42}, "say": "Pay now?"}
    preparation.cards.said(bill)
    preparation.cards.patched(patch)
    journal = preparation.link.journal
    journal.add({"op": "topic", "id": "trip", "title": "Trip", "at": "2026-11-20T10:00:00+00:00"})
    journal.add({**bill, "at": "2026-11-20T10:01:00+00:00"})
    journal.add({**patch, "at": "2026-11-20T10:02:00+00:00"})
    journal.yours("main", "Paid", "y1", "2026-11-20T10:03:00+00:00")
    preparation.write(preparation.gather())
    frozen = {"view": {"Text": "42 € due Friday"}, "state": {}}
    assert read(preparation, "conversations.jsonl") == [
        {"op": "topic", "id": "trip", "title": "Trip", "at": "2026-11-20T10:00:00+00:00"},
        {"op": "say", "conversation": "main", "id": "bill", "text": "Pay now?", "card": frozen, "at": "2026-11-20T10:01:00+00:00"},
        {"op": "say", "conversation": "main", "id": "y1", "from": "you", "text": "Paid", "at": "2026-11-20T10:03:00+00:00"}]
    assert read(preparation, "cards.json") == {"bill": {"conversation": "main", "text": "Pay now?", **frozen}}


def test_what_cannot_be_drawn_does_not_stop_the_rest(tmp_path):
    preparation = home(tmp_path)
    link = preparation.link
    link.store("tasks", TASKS)
    link.app.write("components", "TaskRow", TASK_ROW)
    link.app.write("scripts", "money", "function twice(x) { return x * 2 }\nreturn {twice}")
    link.app.write("page", "broken", BROKEN)
    link.app.write("page", "tasks", PAGE)
    said = {"op": "say", "id": "sum", "conversation": "main", "text": "The total", "card": BROKEN}
    preparation.cards.said(said)
    link.journal.add({**said, "at": "2026-11-20T10:00:00+00:00"})
    prepared = preparation.write(preparation.gather())
    assert prepared == read(preparation, "prepared.json") and prepared["failed"] == {"cards": 1, "pages": ["broken"]}
    assert prepared["offset"] == 3600 and datetime.fromisoformat(prepared["at"]).timestamp() == prepared["now"]
    assert read(preparation, "pages/broken/page.json") == BROKEN
    assert "no total" in read(preparation, "pages/broken/expected.json")["error"]
    assert read(preparation, "pages/tasks/page.json") == PAGE
    expected = read(preparation, "pages/tasks/expected.json")
    assert expected["state"] == {"filter": "all"} and expected["view"]["VStack"][0] == {"Text": "2 tasks, 1 left", "font": "headline"}
    assert read(preparation, "components/TaskRow.json") == TASK_ROW
    assert (preparation.folder / "scripts" / "money.js").read_text() == "function twice(x) { return x * 2 }\nreturn {twice}\n"
    assert read(preparation, "cards.json") == {"sum": {"conversation": "main", "text": "The total"}}
    assert read(preparation, "conversations.jsonl") == [
        {"op": "say", "conversation": "main", "id": "sum", "text": "The total", "at": "2026-11-20T10:00:00+00:00"}]


def test_an_input_of_a_frozen_card_is_bound_to_what_it_showed(tmp_path):
    card = {"data": {"seats": [{"id": "12A", "window": True}, {"id": "12C", "window": False}]}, "state": {"note": "By the wing", "nights": 2},
            "view": {"VStack": [
                {"ForEach": "$seats", "as": "seat", "content": {"Toggle": "$seat.id", "bind": "$seat.window",
                                                                "onChange": {"edit": {"store": "trip", "id": "$seat.id", "window": "$value"}}}},
                {"TextField": "Note", "bind": "$note"},
                {"Stepper": "Nights", "bind": "$nights", "in": [1, 9]}]}}
    tree = [{"Toggle": "12A", "bind": "$f1"}, {"Toggle": "12C", "bind": "$f2"}, {"TextField": "Note", "bind": "$f3"},
            {"Stepper": "Nights", "bind": "$f4", "in": [1, 9]}]
    frozen = {"view": {"VStack": tree}, "state": {"f1": True, "f2": False, "f3": "By the wing", "f4": 2}}
    assert drawing().frozen(card) == frozen
    assert drawing().of(card)["view"]["VStack"][0] == {"Toggle": "12A", "value": True}
    preparation = home(tmp_path)
    said = {"op": "say", "id": "seats", "conversation": "main", "text": "Your seats", "card": card}
    preparation.cards.said(said)
    preparation.link.journal.add({**said, "at": "2026-11-20T10:00:00+00:00"})
    preparation.link.app.write("page", "seats", {"view": {"Toggle": "Window", "bind": "$window"}, "state": {"window": True}})
    preparation.write(preparation.gather())
    assert read(preparation, "cards.json") == {"seats": {"conversation": "main", "text": "Your seats", **frozen}}
    assert read(preparation, "conversations.jsonl")[0]["card"] == frozen
    assert read(preparation, "pages/seats/expected.json") == {"view": {"Toggle": "Window", "value": True}, "state": {"window": True}}


def test_the_stores_are_written_as_the_trees_were_drawn_over_them(tmp_path):
    preparation = home(tmp_path)
    link = preparation.link
    daily, notes = tmp_path / "daily.org", tmp_path / "notes"
    daily.write_text("- [ ] eggs\n")
    notes.mkdir()
    (notes / "plumber.md").write_text("# Plumber\n\nCalled on Monday.\n")
    link.stores.link("daily", str(daily))
    link.stores.link("notes", str(notes))
    link.store("tasks", TASKS)
    link.stores.declare("notes", {"name": "Notes", "title": "$title"})
    link.app.write("page", "home", {"view": {"VStack": [
        {"ForEach": "org(daily.text, 'item')", "as": "line", "content": "${line.text} (${daily.sync})"},
        {"ForEach": "$notes", "as": "note", "content": {"Text": "$note.title"}}]}})
    preparation.write(preparation.gather())
    assert sorted(path.name for path in (preparation.folder / "stores").iterdir()) == ["daily.json", "notes.json", "profile.json", "tasks.json"]
    text = read(preparation, "stores/daily.json")
    assert text == {**link.stores.held["daily"], "sync": "synced", "error": None}
    assert sorted(text) == ["error", "exists", "name", "path", "sync", "text", "updated"] and text["text"] == "- [ ] eggs\n"
    records = read(preparation, "stores/notes.json")
    assert records == [{**record, "sync": "synced", "error": None} for record in link.stores.held["notes"]]
    assert [(record["id"], record["title"], record["sync"]) for record in records] == [("plumber.md", "Plumber", "synced")]
    assert read(preparation, "stores/tasks.json") == TASKS
    assert read(preparation, "search.json") == {"notes": {"name": "Notes", "title": "$title"}}
    assert read(preparation, "pages/home/expected.json") == {"view": {"VStack": ["eggs (synced)", {"Text": "Plumber"}]}, "state": {}}


async def test_the_folder_is_replaced_whole_and_a_failure_leaves_the_one_before(tmp_path, monkeypatch):
    preparation = home(tmp_path)
    preparation.link.app.write("page", "tasks", {"view": "Nothing to do"})
    await preparation.prepare()
    first = read(preparation, "prepared.json")
    (preparation.folder / "stray.json").write_text("{}")
    preparation.link.app.write("page", "tasks", None)
    await preparation.prepare()
    assert sorted(path.name for path in preparation.folder.iterdir()) == ["cards.json", "conversations.jsonl", "prepared.json", "search.json", "stores"]
    kept = (preparation.folder / "prepared.json").read_text()

    def fails(lines):
        raise RuntimeError("the history cannot be folded")

    monkeypatch.setattr(transition, "fold", fails)
    await preparation.prepare()
    assert (preparation.folder / "prepared.json").read_text() == kept and json.loads(kept)["plugin"] == first["plugin"]
    assert [path.name for path in preparation.folder.parent.iterdir()] == ["2"]


def test_a_preparation_asked_on_a_change_waits_for_one(tmp_path):
    preparation = home(tmp_path)
    assert preparation.write(preparation.gather(), changed=True) is not None
    assert preparation.write(preparation.gather(), changed=True) is None
    preparation.link.store("tasks", TASKS)
    assert preparation.write(preparation.gather(), changed=True) is not None
    preparation.cards.said({"op": "say", "id": "hello", "text": "Hello", "card": {"view": "Hello"}})
    assert preparation.write(preparation.gather(), changed=True) is not None
    assert preparation.write(preparation.gather(), changed=True) is None
    assert preparation.write(preparation.gather()) is not None


@pytest.mark.parametrize("ahead, words", [(30, "now"), (12 * 60, "in 12 min"), (3 * 3600, "in 3 h"), (86400, "in 1 day"), (3 * 86400, "in 3 days")])
def test_until_is_worked_out_at_the_moment_of_the_preparation(ahead, words):
    date = datetime.fromtimestamp(MOMENT.timestamp() + ahead, timezone.utc).isoformat()
    assert drawing().of({"view": "${until(when)}, ${date(when, 'relative')}", "data": {"when": date}})["view"] == f"{words}, {words}"


async def test_the_gateway_prepares_when_it_starts_and_when_it_stops(relay, tmp_path):
    url, token = relay
    server = Server(tmp_path, Agent(), "Jacques", token, url)
    await server.start()
    prepared = server.transition.folder / "prepared.json"
    await until(prepared.exists)
    server.link.app.write("page", "tasks", {"view": "Nothing to do"})
    await server.stop()
    assert json.loads((server.transition.folder / "pages" / "tasks" / "expected.json").read_text()) == {"view": "Nothing to do", "state": {}}
