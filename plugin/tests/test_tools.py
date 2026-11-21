# SPDX-FileCopyrightText: 2026 Julien Malka
# SPDX-License-Identifier: MIT

import asyncio
import json
import types
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "plugin"))

from dedala.schemas import structured as _structured  # noqa: E402

SCHEMA = {"parameters": {"properties": {"id": {"type": "string"}, "components": {"type": "object"}, "people": {"type": "array"}}}}


async def echo(args, **_):
    return json.dumps(args)


def test_objects_sent_as_strings_are_read():
    call = _structured(echo, SCHEMA)
    answer = json.loads(asyncio.run(call({"id": "sc", "components": '{"SCPrs": {"body": {"Text": "Hi"}}}', "people": '["Marta"]'})))
    assert answer == {"id": "sc", "components": {"SCPrs": {"body": {"Text": "Hi"}}}, "people": ["Marta"]}


def test_a_string_that_does_not_parse_says_where():
    call = _structured(echo, SCHEMA)
    answer = json.loads(asyncio.run(call({"id": "sc", "components": '{"SCPrs": {"body": {"Text": "Hi"}}}}'})))
    assert "a } or ] too many closes it early" in answer["error"]
    assert '"Hi"}}}⟨HERE⟩}' in answer["error"]


def test_the_widgets_a_view_draws_include_nested_components():
    from dedala.analysis import used as _used

    components = {"SCWidget": {"body": {"Card": ["$content"]}}, "SCPrs": {"body": {"SCWidget": {"content": {"PRRow": {}}}}},
                  "PRRow": {"body": {"Text": "x"}}, "Unused": {"body": {"Text": "y"}}}
    view = {"VStack": [{"SCPrs": {"prs": "$sc.prs"}}]}
    assert sorted(_used(view, components, {})) == ["PRRow", "SCPrs", "SCWidget"]


def test_arguments_can_come_from_a_file(tmp_path):
    written = tmp_path / "card.json"
    written.write_text(json.dumps({"id": "theo", "components": {"Mail": {"body": {"Text": "Hi"}}}}))
    answer = json.loads(asyncio.run(_structured(echo, SCHEMA)({"from_file": str(written), "id": "theo-mail"})))
    assert answer == {"id": "theo-mail", "components": {"Mail": {"body": {"Text": "Hi"}}}}


def test_a_patch_that_drops_fields_from_a_list_says_so():
    from dedala.analysis import lists_replaced as _lists_replaced

    before = {"flows": [{"id": "pr", "name": "PR review", "summary": "Long"}], "meta": {"tags": [{"id": "a", "label": "A"}]}}
    assert _lists_replaced(before, {"flows": [{"id": "pr", "summary": "Short"}]}) == [
        "The patch replaced flows whole: its items no longer have name. A list is replaced, not merged: send the full list"]
    assert _lists_replaced(before, {"meta": {"tags": [{"id": "a"}]}})[0].startswith("The patch replaced meta.tags whole")
    assert _lists_replaced(before, {"flows": [{"id": "pr", "name": "PR", "summary": "Short"}]}) == []
    assert _lists_replaced(before, {"flows": []}) == []


def test_the_cron_tool_is_not_deferred_even_by_the_merged_defaults(monkeypatch):
    import dataclasses
    import types

    from dedala.hermes.internals import surface_directly as _surface_directly

    @dataclasses.dataclass(frozen=True)
    class ToolSearchConfig:
        defer_tools: frozenset

        @property
        def effective_defer_tools(self):
            return self.defer_tools

    tool_search = types.ModuleType("tools.tool_search")
    tool_search._DIRECT_SURFACE_TOOLSETS = frozenset({"desktop_ui"})
    tool_search.ToolSearchConfig = ToolSearchConfig
    tools = types.ModuleType("tools")
    tools.tool_search = tool_search
    monkeypatch.setitem(sys.modules, "tools", tools)
    monkeypatch.setitem(sys.modules, "tools.tool_search", tool_search)
    _surface_directly()
    _surface_directly()
    assert ToolSearchConfig(frozenset({"cronjob_manage", "image_generate"})).effective_defer_tools == {"image_generate"}
    assert "app" in tool_search._DIRECT_SURFACE_TOOLSETS


def test_a_file_of_data_instead_of_arguments_is_refused(tmp_path):
    written = tmp_path / "patch.json"
    written.write_text(json.dumps({"updated": "2026-10-25T06:58:15+01:00", "status": {"label": "Idle"}}))
    schema = {"name": "app_page", "parameters": {"properties": {"id": {"type": "string"}, "patch": {"type": "object"}}}}
    answer = json.loads(asyncio.run(_structured(echo, schema)({"from_file": str(written), "id": "wm-jobs", "patch": {}})))
    assert answer["error"].startswith("app_page does not take status, updated: from_file holds the call's whole arguments")
    answer = json.loads(asyncio.run(_structured(echo, schema)({"id": "wm-jobs", "reason": "refresh"})))
    assert answer["error"] == "app_page does not take reason; it takes id, patch"


def test_a_component_still_drawn_cannot_be_deleted():
    from dedala.analysis import still_drawn as _still_drawn

    artifacts = {"components": {"Face": {"body": {"Text": "x"}}, "DayHeader": {"body": {"Text": "y"}},
                                "DayHead": {"body": {"Face": {}}}},
                 "page": {"sunday-outing": {"view": {"VStack": [{"DayHeader": {}}]}}}}
    assert _still_drawn([{"op": "define", "components": {"DayHeader": None}}], artifacts) == \
        ["DayHeader cannot be deleted: page sunday-outing draws it"]
    assert _still_drawn([{"op": "define", "components": {"Face": None}}], artifacts) == \
        ["Face cannot be deleted: component DayHead draws it"]
    assert _still_drawn([{"op": "define", "components": {"Face": None, "DayHead": None}}], artifacts) == []
    assert _still_drawn([{"op": "define", "components": {"DayHeader": None}},
                         {"op": "page", "id": "sunday-outing", "view": {"Text": "z"}}], artifacts) == []


def test_a_view_reads_other_stores_by_name_and_inside_expressions():
    from dedala.analysis import store_reads as _store_reads

    view = {"VStack": [{"Text": "$note.echo_at"}, {"If": "${note.echo != ''}", "then": {"Text": "${count(wm_jobs.recent)} runs"}},
                       {"Text": "gquetel.fr and $p.text"}]}
    assert _store_reads(view, {}, {"note", "wm_jobs", "gquetel"}) == {"note": {"echo_at", "echo"}, "wm_jobs": {"recent"}}


def test_changing_a_store_says_which_other_pages_it_breaks():
    from dedala.analysis import sharing as _sharing

    artifacts = {"page": {"day": {"view": {"Text": "Note saved ${note.echo_at}"}},
                          "note": {"view": {"Text": "$note.echo"}}}, "components": {}}
    assert _sharing("note", {"echo": "", "echo_at": ""}, artifacts, "note") == (["day"], [])
    readers, broken = _sharing("note", {"echo": ""}, artifacts, "note")
    assert readers == ["day"]
    assert broken == ["Page day reads $note.echo_at, which the new data does not have: fix its view or keep that key"]


def test_a_view_reading_a_field_another_store_lacks_is_told():
    from dedala.analysis import store_gaps as _store_gaps

    stores = {"note": {"echo": ""}, "day": {"hero": {}}}
    assert _store_gaps({"note": {"echo", "echo_at"}, "day": {"hero"}}, stores) == [
        "The view reads $note.echo_at, which the store note does not have: they show empty"]
    assert _store_gaps({"note": {"echo_at"}}, stores, own="note") == []


def test_topics_are_kept_with_their_outcome(monkeypatch, tmp_path):
    import dedala
    from dedala.link import Link

    link = Link(tmp_path, "https://relay.invalid", "token")

    async def sent(ops):
        return {"errors": []}

    monkeypatch.setattr(dedala.session, "link", lambda: link)
    monkeypatch.setattr(link, "send_and_check", sent)
    monkeypatch.setattr(dedala.session, "on_gateway", lambda work: work)
    asyncio.run(dedala.records.topic({"id": "backups", "title": "Paris backups failing"}))
    assert json.loads(asyncio.run(dedala.records.topic({"id": "nothing"})))["error"].startswith("There is no topic")
    closed = json.loads(asyncio.run(dedala.records.topic({"id": "backups", "closed": True, "outcome": "He does not care"})))
    assert closed["outcome"] == "He does not care" and closed["closed"]
    listed = json.loads(asyncio.run(dedala.records.topic({})))["topics"]
    assert [(topic["id"], topic["title"], topic["outcome"]) for topic in listed] == [("backups", "Paris backups failing", "He does not care")]
    reopened = json.loads(asyncio.run(dedala.records.topic({"id": "backups", "closed": False})))
    assert reopened["closed"] is None


def tools(monkeypatch, tmp_path):
    """The tools over a link that keeps what it is asked to send, the phone closed."""
    import dedala
    import dedala.maintenance  # noqa: F401
    from dedala.bank import Cards
    from dedala.link import PHONE_CLOSED, Link

    link = Link(tmp_path, "https://relay.invalid", "token")
    cards = Cards(tmp_path)
    sent = []

    async def send_and_check(ops):
        sent.append(ops)
        return {"errors": [], "phone": PHONE_CLOSED}

    async def no_look(*_, **__):
        return None

    monkeypatch.setattr(dedala.session, "link", lambda: link)
    monkeypatch.setattr(dedala.session, "said_cards", lambda: cards)
    monkeypatch.setattr(dedala.session, "on_gateway", lambda work: work)
    monkeypatch.setattr(link, "send_and_check", send_and_check)
    monkeypatch.setattr(dedala.checks, "all_stores", lambda: {})
    monkeypatch.setattr(dedala.checks, "look", no_look)
    monkeypatch.setattr(dedala.maintenance, "state", lambda agent, job: {"missing": True} if job == "gone" else {"id": job})
    return link, cards, sent


def test_app_ops_sends_its_own_ops_and_names_the_tool_for_the_others(monkeypatch, tmp_path):
    import dedala

    _, _, sent = tools(monkeypatch, tmp_path)
    refused = json.loads(asyncio.run(dedala.pages.ops({"ops": [
        {"op": "store", "id": "trip", "patch": {"days": 3}}, {"op": "page", "id": "trip", "view": {"Text": "x"}},
        {"op": "say", "text": "Here", "card": {"view": {"Text": "x"}}}, {"op": "presence", "state": "typing"}]})))
    assert refused["sent"] is False and sent == []
    assert len(refused["problems"]) == 4
    assert "store goes through app_data" in refused["problems"][0] and "page goes through app_page" in refused["problems"][1]
    assert "app_card" in refused["problems"][2] and "'presence'" in refused["problems"][3]
    answer = json.loads(asyncio.run(dedala.pages.ops({"ops": [{"op": "define", "components": {"Tile": {"body": {"Text": "x"}}}}, {"op": "say", "text": "Done"}]})))
    assert answer["sent"] == 2 and answer["errors"] == [] and answer["phone"].startswith("The phone is closed")
    assert [op["op"] for op in sent[0]] == ["define", "say"] and sent[0][1]["conversation"] == "main"


def test_a_patch_to_a_card_that_is_not_there_is_refused_with_the_last_ones(monkeypatch, tmp_path):
    import dedala

    _, cards, _ = tools(monkeypatch, tmp_path)
    cards.said({"op": "say", "id": "score", "text": "OL lead", "card": {"view": {"Text": "$score"}, "data": {"score": "1-0"}}})
    cards.said({"op": "say", "id": "gate", "text": "Gate B12", "card": {"view": {"Text": "$gate"}, "data": {"gate": "B12"}}})
    answer = json.loads(asyncio.run(dedala.cards.patch({"id": "scores", "data": {"score": "2-0"}})))
    assert answer["sent"] is False and "no card scores" in answer["error"]
    assert answer["recent_cards"] == [{"id": "gate", "text": "Gate B12"}, {"id": "score", "text": "OL lead"}]
    assert cards.get("score")["data"] == {"score": "1-0"}


def test_a_page_has_no_data_and_its_settings_are_sent_alone(monkeypatch, tmp_path):
    import dedala
    import dedala.maintenance  # noqa: F401

    link, _, sent = tools(monkeypatch, tmp_path)

    async def send(ops, **_):
        sent.append(link._record(ops))

    monkeypatch.setattr(link, "send", send)
    link._record([{"op": "page", "id": "trip", "title": "Trip", "symbol": "airplane", "view": {"Text": "$trip.days"}, "maintained_by": "refresh"}])
    link.stores.put("trip", {"days": 2})
    link._mirror(["trip"])
    refused = json.loads(asyncio.run(dedala.pages.page({"id": "trip", "patch": {"days": 3}})))
    assert refused["sent"] is False and "no data of its own" in refused["error"] and sent == []
    both = json.loads(asyncio.run(dedala.pages.page({"id": "trip", "handled_by": "on-edit", "focus": True})))
    page = sent[-1][0]
    assert page["handled_by"] == "on-edit" and page["maintained_by"] == "refresh" and page["focus"] is True and "store" not in page
    assert page["view"] == {"Text": "$trip.days"} and page["title"] == "Trip" and page["symbol"] == "airplane"
    assert both["page_updated"] == ["focus", "handled_by"] and both["maintained_by"] == {"id": "refresh"} and both["file"].endswith("pages/trip.json")
    missing = json.loads(asyncio.run(dedala.pages.page({"id": "trip", "maintained_by": "gone"})))
    assert "No cron job gone" in missing["error"] and len(sent) == 1


def test_a_page_is_laid_out_and_never_reviewed(monkeypatch, tmp_path):
    import dedala

    link, _, _ = tools(monkeypatch, tmp_path)
    left = []

    async def send(ops, **_):
        left.append(ops)

    async def review(*_):
        raise AssertionError("a page is not reviewed")

    async def cut(*_, **__):
        return {"card": {}, "faults": ["Text 'Departure' is cut"], "notes": []}

    monkeypatch.setattr(link, "send", send)
    monkeypatch.setattr(dedala.checks, "review", review)
    sent = json.loads(asyncio.run(dedala.pages.page({"id": "trip", "title": "Trip", "view": {"Text": "Lisbon"}})))
    assert sent["sent"] is True and "review" not in sent and [op["op"] for op in left[0]] == ["page"]
    monkeypatch.setattr(dedala.checks, "look", cut)
    monkeypatch.setattr(dedala.checks, "hold", lambda key, conversation, send: dedala.checks.held_back.__setitem__(key, {}))
    held = json.loads(asyncio.run(dedala.pages.page({"id": "trip", "view": {"Text": "Departure"}})))
    dedala.checks.held_back.clear()
    assert held["sent"] is False and held["problems"] == ["Text 'Departure' is cut"] and len(left) == 1


def test_what_this_hermes_lacks_is_named_with_what_it_costs(monkeypatch):
    import types

    from dedala.hermes import internals as hermes

    for name, _, _ in hermes.USED:
        monkeypatch.setitem(sys.modules, name, None)
    assert len(hermes.missing()) == len(hermes.USED)
    assert hermes.session("HERMES_SESSION_PLATFORM") is None and hermes.cron() is None and hermes.executions(5) is None
    assert hermes.execute_now() is None and hermes.delegations() == []
    jobs = types.ModuleType("cron.jobs")
    jobs.list_jobs = jobs.get_job = jobs.trigger_job = jobs.pause_job = lambda *args: None
    jobs.create_job = jobs.update_job = jobs.remove_job = jobs.get_cron_output_dir = lambda *args: None
    monkeypatch.setitem(sys.modules, "cron", types.ModuleType("cron"))
    monkeypatch.setitem(sys.modules, "cron.jobs", jobs)
    gone = [line for line in hermes.missing() if line.startswith("cron.jobs")]
    assert gone == ["cron.jobs has no resume_job: Activity, page upkeep and handlers are off"]


def test_a_value_that_is_an_object_or_a_list_is_read_from_a_string_too():
    schema = {"parameters": {"properties": {"id": {"type": "string"}, "data": {"type": ["object", "array"]}}}}
    call = _structured(echo, schema)
    assert json.loads(asyncio.run(call({"id": "countdown", "data": '{"until": "2026-11-10T22:00:00+01:00"}'}))) == {
        "id": "countdown", "data": {"until": "2026-11-10T22:00:00+01:00"}}
    assert json.loads(asyncio.run(call({"id": "people", "data": '[{"id": "marta"}]'})))["data"] == [{"id": "marta"}]
    assert json.loads(asyncio.run(call({"id": "people", "data": [{"id": "marta"}]})))["data"] == [{"id": "marta"}]
    assert "data must be a JSON object or array" in json.loads(asyncio.run(call({"id": "x", "data": "Until 22:00"})))["error"]
    assert json.loads(asyncio.run(call({"id": "x", "data": "12"})))["error"] == "data must be a JSON object or array"


def test_every_structured_parameter_of_the_tools_says_its_shape():
    from dedala import schemas

    untyped = [(schema["name"], name) for _, schema in schemas.TOOLS
               for name, spec in schema["parameters"]["properties"].items() if spec.get("type") is None]
    assert untyped == []


def test_the_names_a_view_reads():
    from dedala.analysis import names_read

    view = {"VStack": [{"Text": "$label"}, {"Text": {"countdown": "$until"}},
                       {"Text": "Gate ${flight.gate} · ${format(price, 'currency:EUR')} · ${late ? 'Late' : shown}"},
                       {"ForEach": "$lines", "as": "l", "index": "n", "content": {"Text": "${n + 1}. $l.name ${item.x}"}},
                       {"Text": "Costs $14"}]}
    assert names_read(view) == {"label", "until", "flight", "price", "late", "shown", "lines"}


def test_an_object_given_both_in_the_file_and_the_call_is_refused(tmp_path):
    written = tmp_path / "patch.json"
    written.write_text(json.dumps({"id": "theo", "components": {"Mail": {"body": {"Text": "Hi"}}}}))
    answer = json.loads(asyncio.run(_structured(echo, SCHEMA)({"from_file": str(written), "components": {"Other": {"body": {"Text": "x"}}}})))
    assert "components came both in from_file and in the call" in answer["error"]


def test_a_prop_named_like_a_store_is_not_a_read_of_it():
    from dedala.analysis import store_reads

    components = {"Recent": {"props": ["work"], "body": {"Text": "$work.recent"}}}
    view = {"VStack": [{"Recent": {"work": "$sc"}}, {"Text": "$work.title"}]}
    assert store_reads(view, components, {"work", "sc"}) == {"work": {"title"}}


def test_a_brief_its_session_cannot_take_comes_with_the_topic_s_first_message(monkeypatch, tmp_path):
    import dedala
    from dedala.link import Link

    link = Link(tmp_path, "https://relay.invalid", "token")

    async def sent(ops):
        return {"errors": []}

    monkeypatch.setattr(dedala.session, "link", lambda: link)
    monkeypatch.setattr(link, "send_and_check", sent)
    monkeypatch.setattr(dedala.session, "on_gateway", lambda work: work)
    monkeypatch.setattr(dedala.session, "agent", lambda: types.SimpleNamespace(seed=lambda conversation, brief: False))
    answer = json.loads(asyncio.run(dedala.records.topic({"id": "move", "title": "Moving", "brief": "He moves on the 3rd"})))
    assert "brief_kept" in answer and link.state["briefs"] == {"move": "He moves on the 3rd"}
    heard = []

    async def deliver(conversation, text, media=None, message_id=None):
        heard.append((conversation, text))

    server = types.SimpleNamespace(link=link, agent=types.SimpleNamespace(deliver=deliver))
    from dedala.server import Server

    asyncio.run(Server._deliver(server, "move", "Any news?"))
    asyncio.run(Server._deliver(server, "move", "And now?"))
    assert heard[0][1].startswith("[app: the brief this topic was opened with: He moves on the 3rd]") and heard[1][1] == "And now?"


def test_the_screens_a_page_opens_are_found_with_a_sample_record():
    from dedala.pages import _sample, _screens

    components = {"Row": {"props": ["id"], "body": {"Button": "Open", "action": {"show": "Person", "with": {"id": "$id", "tab": "info"}}}},
                  "Person": {"props": ["id", "tab"], "title": "$name", "body": {"Text": "x"}},
                  "Plain": {"body": {"Text": "y"}}}
    view = {"VStack": [{"Row": {"id": "$p.id"}}, {"Button": "x", "action": {"show": "Plain"}}]}
    assert _screens(view, components) == {"Person": {"tab": "info"}}
    stores = {"notes": [{"id": "n1"}], "people": [{"id": "marta", "name": "Marta"}]}
    assert _sample("Person", {"tab": "info"}, components["Person"], stores, {"people": {"screen": "Person"}}) == {"tab": "info", "id": "marta"}


def test_a_screen_s_sample_is_the_first_of_the_list_it_finds_its_record_in():
    from dedala.pages import _sample

    screen = {"props": {"id": ""}, "title": "Mail", "body": {"Text": "${find(sofia.emails, 'id', $id).subject}"}}
    stores = {"notes": [{"id": "n1"}], "sofia": {"person": {}, "emails": [{"id": "m1", "subject": "Hi"}]}}
    assert _sample("Mail", {}, screen, stores, {}) == {"id": "m1"}
