# SPDX-FileCopyrightText: 2026 Julien Malka
# SPDX-License-Identifier: MIT

import asyncio
import json

import pytest

from support import Phone, fake_hermes, online, until

from dedala.link import pair


@pytest.fixture
async def app(relay, tmp_path, monkeypatch):
    fake_hermes()
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))
    from gateway.config import PlatformConfig
    from dedala.hermes.adapter import AppAdapter

    url, token = relay
    adapter = AppAdapter(PlatformConfig(extra={"relay": url, "token": token, "name": "Jacques"}))
    assert await adapter.connect()
    phone = Phone(url)
    codes = asyncio.Queue()
    pairing = asyncio.create_task(pair(adapter.server.link.home, url, token, "Jacques", codes.put_nowait))
    await phone.claim(await codes.get())
    await pairing
    await until(lambda: adapter.server.link.identity.paired and adapter.server.link.state["seq_out"] >= 1)
    yield adapter, phone
    await adapter.disconnect()


def said(adapter) -> list[str]:
    return [event.text for event in adapter.heard]


async def acks(phone, count: int) -> list[dict]:
    found = []
    for _ in range(100):
        found = [op for op in await phone.ops() if op["op"] == "acked"]
        if len(found) >= count:
            break
        await asyncio.sleep(0.05)
    assert len(found) == count
    return found


async def test_between_two_steps_he_is_not_said_to_think(app):
    adapter, _ = app
    seen = []

    async def presence(chat, state):
        seen.append(state)

    adapter.server._presence = presence
    await adapter.send_typing("main")
    adapter.server.note_stream(40, None)
    await adapter.send_typing("main")
    assert "doing" not in seen[-1] and seen[-1]["tokens"] == 10
    adapter.server.note_stream(40, "Writing code", "chevron.left.forwardslash.chevron.right")
    adapter.server.note_stream(40, None)
    await adapter.send_typing("main")
    assert (seen[-1]["doing"], seen[-1]["symbol"]) == ("Writing code", "chevron.left.forwardslash.chevron.right")
    adapter.stepped("main")
    adapter.server.note_stream(40, None)
    await adapter.send_typing("main")
    assert "doing" not in seen[-1] and seen[-1]["tokens"] == 40
    adapter.server._turns.clear()


async def test_steps_are_said_in_the_present_while_the_turn_runs_and_in_the_past_with_its_message(app):
    adapter, _ = app
    seen = []

    async def presence(chat, state):
        seen.append(state)

    adapter.server._presence = presence
    adapter.server.link.add_step("main", {"text": "Read www.kth.se", "symbol": "globe"})
    adapter.server.link.add_step("main", {"text": "Used hindsight_recall", "symbol": "wrench.and.screwdriver", "failed": True})
    await adapter.send_typing("main")
    assert seen[-1]["steps"] == [{"text": "Reading www.kth.se", "symbol": "globe"},
                                 {"text": "Using hindsight_recall", "symbol": "wrench.and.screwdriver", "failed": True}]
    assert adapter.server.link._with_steps({"op": "say", "conversation": "main"})["steps"][0]["text"] == "Read www.kth.se"
    adapter.server._turns.clear()


async def test_a_tool_at_work_keeps_the_name_made_from_its_arguments(app):
    adapter, _ = app
    seen = []

    async def presence(chat, state):
        seen.append(state)

    adapter.server._presence = presence
    for first in (True, False):
        await adapter.send_typing("main")
        if first:
            adapter.server.starting("main", "call", "Running notmuch search", "terminal")
        adapter.set_status_text("main", "is running notmuch search --format=text --output=m…")
        if not first:
            adapter.server.starting("main", "call", "Running notmuch search", "terminal")
        await adapter.send_typing("main")
        assert (seen[-1]["doing"], seen[-1]["symbol"]) == ("Running notmuch search", "terminal")
        adapter.stepped("main", "call")
        await adapter.send_typing("main")
        assert "doing" not in seen[-1]
        adapter.set_status_text("main", "is reading /var/lib/hermes/notes")
        await adapter.send_typing("main")
        assert seen[-1]["doing"] == "Reading /var/lib/hermes/notes"
        adapter.set_status_text("main", None)
    adapter.server._turns.clear()


async def test_calls_run_at_once_each_leave_their_step_and_the_one_still_running_is_shown(app):
    adapter, _ = app
    seen = []

    async def presence(chat, state):
        seen.append(state)

    adapter.server._presence = presence
    await adapter.send_typing("main")
    adapter.server.starting("main", "a", "Searching the web for nodecode.ai", "globe")
    adapter.set_status_text("main", "is searching the web for nodecode.ai")
    adapter.server.starting("main", "b", "Reading nodecode.ai", "globe")
    adapter.set_status_text("main", "is reading nodecode.ai")
    await adapter.send_typing("main")
    assert seen[-1]["doing"] == "Searching the web for nodecode.ai" and seen[-1]["steps"] == []
    adapter.stepped("main", "a", {"text": "Searched the web for nodecode.ai", "symbol": "globe"})
    await adapter.send_typing("main")
    assert seen[-1]["doing"] == "Reading nodecode.ai" and [step["text"] for step in seen[-1]["steps"]] == ["Searching the web for nodecode.ai"]
    adapter.stepped("main", "b", {"text": "Read nodecode.ai", "symbol": "globe"})
    adapter.server.starting("main", "c", "Reading nodecode.ai", "globe")
    adapter.stepped("main", "c", {"text": "Read nodecode.ai", "symbol": "globe"})
    await adapter.send_typing("main")
    assert "doing" not in seen[-1] and len(seen[-1]["steps"]) == 3
    adapter.server.starting("main", "lost", "Running a command", "terminal")
    adapter.server.note_stream(40, "Writing code", "chevron.left.forwardslash.chevron.right")
    await adapter.send_typing("main")
    assert seen[-1]["doing"] == "Writing code"
    adapter.server.link.steps.pop("main", None)
    adapter.server._turns.clear()


async def test_a_new_phone_starts_a_new_session(app):
    adapter, _ = app
    await until(lambda: "/new" in said(adapter))


async def test_a_phone_paired_again_keeps_the_session_and_gets_its_conversation(app, relay):
    adapter, _ = app
    await until(lambda: "/new" in said(adapter))
    adapter.server.link.journal.yours("main", "Hello", "y1", None)
    url, token = relay
    phone = Phone(url)
    codes = asyncio.Queue()
    pairing = asyncio.create_task(pair(adapter.server.link.home, url, token, "Jacques", codes.put_nowait))
    await phone.claim(await codes.get())
    await pairing
    found = []

    async def history():
        found[:] = [op for op in await phone.ops() if op["op"] == "history"]
        return found

    for _ in range(100):
        if await history():
            break
        await asyncio.sleep(0.05)
    assert found[0]["messages"][0]["text"] == "Hello"
    await asyncio.sleep(0.3)
    assert said(adapter).count("/new") == 1


async def test_what_he_writes_is_his_message_in_its_conversation(app):
    adapter, phone = app
    await phone.send([{"kind": "message", "conversation": "lease", "text": "Two months is fine"}])
    await until(lambda: any(text.startswith("Two months is fine") for text in said(adapter)))
    heard = next(event for event in adapter.heard if event.text.startswith("Two months"))
    assert heard.source["chat_id"] == "lease" and heard.source["user_id"] == "app"
    history = adapter.server.link.journal.history({})
    assert any(message["conversation"] == "lease" and message["from"] == "you" for op in history for message in op["messages"])


async def test_a_tap_that_did_nothing_is_told_where_it_happened(app):
    adapter, phone = app
    adapter.server.cards.said({"op": "say", "id": "split", "conversation": "lease", "text": "", "card": {"view": {"Text": "x"}}})
    await phone.send([{"kind": "failed", "card": "split", "tapped": "Ask them", "problem": "Script: the handler ask threw"},
                      {"kind": "failed", "page": "today", "problem": "There is no item 'gone'"}])
    await until(lambda: sum("nothing happened" in text for text in said(adapter)) == 2)
    on_card = next(event for event in adapter.heard if "card split" in event.text)
    assert on_card.source["chat_id"] == "lease"
    assert 'tapped "Ask them" on card split' in on_card.text and "the handler ask threw" in on_card.text and "app_patch" in on_card.text
    on_page = next(event for event in adapter.heard if "page today" in event.text)
    assert on_page.source["chat_id"] == "main" and "used page today" in on_page.text and "app_page" in on_page.text


async def test_an_edit_to_a_linked_file_is_made_once_and_acknowledged(app, tmp_path):
    adapter, phone = app
    note = tmp_path / "note.md"
    note.write_text("- [ ] milk\n")
    adapter.server.link.stores.link("daily", str(note))
    edit = {"kind": "file", "id": "e1", "store": "daily", "edit": {"append": "eggs"}, "from": "note", "at": "2026-11-06T10:00:00Z"}
    await phone.send([edit])
    acked = (await acks(phone, 1))[0]
    assert acked["ids"] == ["e1"] and "failed" not in acked
    assert note.read_text() == "- [ ] milk\n- [ ] eggs\n"
    answer = acked["answers"]["e1"]
    assert answer[-1]["op"] == "store" and answer[-1]["kind"] == "text" and answer[-1]["data"]["text"] == "- [ ] milk\n- [ ] eggs\n"
    await phone.send([edit])
    again = (await acks(phone, 2))[1]
    assert again["ids"] == ["e1"] and again["answers"] == acked["answers"]
    assert note.read_text() == "- [ ] milk\n- [ ] eggs\n"
    assert [entry["changes"][0]["edit"] for entry in adapter.server.link.changes()] == [{"append": "eggs"}]


async def test_an_edit_the_file_cannot_take_is_refused_the_same_way_each_time(app, tmp_path):
    adapter, phone = app
    note = tmp_path / "note.md"
    note.write_text("- [ ] milk\n")
    adapter.server.link.stores.link("daily", str(note))
    edit = {"kind": "file", "id": "e2", "store": "daily", "edit": {"toggle": "bread"}}
    await phone.send([edit])
    refused = {"e2": "“bread” is no longer in the file"}
    first = (await acks(phone, 1))[0]
    assert first["ids"] == ["e2"] and first["failed"] == refused and first["answers"]["e2"][0]["id"] == "daily"
    await phone.send([edit])
    assert (await acks(phone, 2))[1] == first
    assert note.read_text() == "- [ ] milk\n"


async def test_a_file_that_cannot_be_read_fails_its_edit_and_nothing_else(app, tmp_path):
    adapter, phone = app
    good, bad = tmp_path / "good.md", tmp_path / "bad.md"
    good.write_text("- one\n")
    bad.write_text("- two\n")
    adapter.server.link.stores.link("good", str(good))
    adapter.server.link.stores.link("bad", str(bad))
    bad.write_bytes(b"\xff\xfe not text")
    await phone.send([{"kind": "file", "id": "e3", "store": "bad", "edit": {"append": "three"}}])
    failed = (await acks(phone, 1))[0]["failed"]["e3"]
    assert failed.startswith("Could not write the file")
    assert any("his edit to the store bad" in text for text in said(adapter))
    await phone.send([{"kind": "file", "id": "e4", "store": "good", "edit": {"append": "four"}}])
    fine = (await acks(phone, 2))[1]
    assert fine["ids"] == ["e4"] and "failed" not in fine and fine["answers"]["e4"][-1]["id"] == "good"
    http, socket = await online(None, adapter.server.link, phone)
    for _ in range(100):
        ops = await phone.ops()
        if ops[-1] == {"op": "synced"}:
            break
        await asyncio.sleep(0.05)
    assert ops[-1] == {"op": "synced"}
    assert not any(op["op"] == "store" and op["id"] == "bad" for op in ops)
    await socket.close()
    await http.close()


async def test_his_edits_on_the_phone_are_applied_once(app):
    adapter, phone = app
    adapter.server.link._record([{"op": "store", "id": "groceries", "data": {"list": ["milk"]}}])
    edits = {"kind": "edits", "id": "b1", "at": "2026-11-06T10:00:00Z",
             "changes": [{"store": "groceries", "patch": {"list": ["milk", "eggs"]}, "from": "shopping"}]}
    await phone.send([edits])
    await acks(phone, 1)
    await phone.send([edits])
    await acks(phone, 2)
    assert adapter.server.link.state["artifacts"]["store"]["groceries"]["data"] == {"list": ["milk", "eggs"]}
    assert len(adapter.server.link.changes()) == 1


async def stores_sent(phone, name: str) -> list:
    return [op.get("data") for op in await phone.ops() if op["op"] == "store" and op["id"] == name]


async def test_his_edit_to_a_store_is_written_to_its_file_and_comes_back_before_the_ack(app):
    adapter, phone = app
    adapter.server.link._record([{"op": "store", "id": "groceries", "data": {"list": ["milk"], "shop": "Biocoop"}}])
    adapter.server.link.stores.path("groceries").write_text('{"list": ["milk"], "shop": "Naturalia"}')
    await phone.send([{"kind": "edits", "id": "e1", "at": "2026-11-06T10:00:00Z",
                       "changes": [{"store": "groceries", "patch": {"list": ["milk", "eggs"]}, "from": "shopping"}]}])
    acked = (await acks(phone, 1))[0]
    assert json.loads(adapter.server.link.stores.path("groceries").read_text()) == {"list": ["milk", "eggs"], "shop": "Naturalia"}
    assert [op["op"] for op in acked["answers"]["e1"]] == ["store"] and acked["answers"]["e1"][0]["data"] == {"list": ["milk", "eggs"], "shop": "Naturalia"}


async def test_what_a_program_writes_to_a_store_file_reaches_the_phone_when_it_is_open(app, relay):
    adapter, phone = app
    adapter.server.link._record([{"op": "store", "id": "jobs", "data": {"running": 0}}])
    adapter.server.link.stores.path("jobs").write_text('{"running": 2}')
    await adapter.server.sync_stores()
    assert adapter.server.link.state["artifacts"]["store"]["jobs"]["data"] == {"running": 2}
    assert await stores_sent(phone, "jobs") == []
    http, socket = await online(relay, adapter.server.link, phone)
    await until(lambda: adapter.server.link.state["stores_sent"].get("jobs") is not None and not adapter.server.link.unsent_stores())
    assert (await stores_sent(phone, "jobs"))[-1] == {"running": 2}
    adapter.server.link.stores.path("jobs").write_text('{"running": 3')
    await adapter.server.sync_stores()
    await adapter.server.sync_stores()
    told = [text for text in said(adapter) if "cannot be read" in text]
    assert len(told) == 1 and "jobs.json" in told[0] and "keeps what it last held" in told[0]
    assert adapter.server.link.state["artifacts"]["store"]["jobs"]["data"] == {"running": 2}
    await socket.close()
    await http.close()


async def test_an_inbox_source_is_a_name_never_a_path(app):
    adapter, _ = app
    adapter.server.inbox.arrive("tp7", {"text": "Buy oat milk"}, "take-9")
    assert adapter.server.inbox.take("..") == []
    assert adapter.server.inbox.take("../dedala") == []
    assert [item["id"] for item in adapter.server.inbox.take("tp7")] == ["take-9"]


def test_registering_gives_hermes_the_platform_the_tools_and_the_hooks():
    fake_hermes()
    import dedala

    class Context:
        def __init__(self):
            self.platforms, self.tools, self.hooks, self.commands, self.skills = [], {}, [], [], []

        def register_platform(self, **platform):
            self.platforms.append(platform)

        def register_tool(self, name, schema, handler, **_):
            self.tools[name] = (schema, handler)

        def register_hook(self, name, hook):
            self.hooks.append(name)

        def register_cli_command(self, name, **_):
            self.commands.append(name)

        def register_skill(self, name, path, description=""):
            self.skills.append(name)

    context = Context()
    dedala.register(context)
    assert [platform["name"] for platform in context.platforms] == ["app"]
    assert len(context.tools) == 12 and all(name.startswith("app_") for name in context.tools)
    assert all("from_file" in schema["parameters"]["properties"] and schema["parameters"]["required"] == [] for schema, _ in context.tools.values())
    assert context.hooks == ["pre_tool_call", "post_tool_call", "on_stream_delta"] and context.commands == ["dedala"]
    assert context.skills == ["building-pages", "drawing-cards", "living-in-the-app"]
    assert dedala.hermes.agent.context is context
    unknown = asyncio.run(context.tools["app_card"][1]({"view": {"Text": "Hi"}, "colour": "red"}))
    assert "does not take colour" in unknown


async def test_a_turn_told_over_after_the_next_began_keeps_showing(app, monkeypatch):
    from dedala import server as module

    adapter, _ = app
    monkeypatch.setattr(module, "REST", 0.2)
    seen = []

    async def presence(chat, state, again=False):
        seen.append(state)

    adapter.server._presence = presence
    await adapter.send_typing("main")
    await adapter.stop_typing("main")
    await adapter.send_typing("main")
    await asyncio.sleep(0.4)
    assert seen and all(state.get("typing") for state in seen)
    await adapter.stop_typing("main")
    await asyncio.sleep(0.4)
    assert seen[-1] == {}


async def test_a_phone_coming_back_mid_turn_is_shown_the_turn_at_once(app):
    adapter, phone = app
    server = adapter.server
    server.link.app_online = False
    await adapter.send_typing("main")
    http, socket = await online(None, server.link, phone)
    try:
        await until(lambda: server._presence_sent.get("main", {}).get("typing"))
        assert any(op["op"] == "presence" and op.get("typing") for op in await phone.ops())
    finally:
        await socket.close()
        await http.close()
        await adapter.stop_typing("main")

