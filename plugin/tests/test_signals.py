# SPDX-FileCopyrightText: 2026 Julien Malka
# SPDX-License-Identifier: MIT

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "plugin"))

from dedala.activities import Activities, shown, too_large  # noqa: E402
from dedala.checks import notify_problem  # noqa: E402
from dedala.stores import Stores  # noqa: E402


class FakeLink:
    """Records what the relay would be asked for an activity."""

    def __init__(self):
        self.state = {"channels": {}}
        self.pushed = []

    async def start_activity(self, activity, design, data, alert):
        self.state["channels"][activity] = f"ch-{activity}"
        self.pushed.append(("start", activity, data, alert))
        return {"ok": True}

    async def update_activity(self, activity, data, end, alert):
        self.pushed.append(("end" if end else "update", activity, data, alert))
        if end:
            self.state["channels"].pop(activity, None)
        return {"ok": True}


def bound(tmp_path):
    stores = Stores(tmp_path / "stores")
    link = FakeLink()
    return Activities(link.state, lambda: None, stores), stores, link


def test_an_activity_follows_its_store_and_the_store_ends_it(tmp_path):
    activities, stores, link = bound(tmp_path)
    stores.put("flight", {"gate": "F32", "status": "On time"})
    assert activities.problem("flight", {}) is None
    assert activities.problem("nowhere", {}).startswith("There is no store nowhere")
    asyncio.run(activities.start(link, "tp1235", "flight", {"views": {}}, {"title": "TP 1235", "body": "Check-in open"}))
    assert link.pushed == [("start", "tp1235", {"gate": "F32", "status": "On time"}, {"title": "TP 1235", "body": "Check-in open"})]
    asyncio.run(activities.sync(link))
    assert len(link.pushed) == 1
    stores.path("flight").write_text(json.dumps({"gate": "F40", "status": "Boarding", "alert": {"title": "Gate change", "body": "F40"}}))
    stores.scan()
    asyncio.run(activities.sync(link))
    assert link.pushed[-1] == ("update", "tp1235", {"gate": "F40", "status": "Boarding"}, {"title": "Gate change", "body": "F40"})
    stores.path("flight").write_text(json.dumps({"gate": "F40", "status": "Last call", "alert": {"title": "Gate change", "body": "F40"}}))
    stores.scan()
    asyncio.run(activities.sync(link))
    assert link.pushed[-1] == ("update", "tp1235", {"gate": "F40", "status": "Last call"}, None)
    asyncio.run(activities.sync(link))
    assert len(link.pushed) == 3
    stores.path("flight").write_text(json.dumps({"gate": "F40", "status": "Landed", "ended": True}))
    stores.scan()
    asyncio.run(activities.sync(link))
    assert link.pushed[-1][0] == "end" and activities.bound == {} and link.state["channels"] == {}
    assert activities.problem("flight", {}).endswith("would end at once")


def test_a_store_that_is_gone_or_too_large_for_a_push(tmp_path):
    activities, stores, link = bound(tmp_path)
    stores.put("deploy", {"step": 1})
    asyncio.run(activities.start(link, "deploy", "deploy", {"views": {}}, None))
    stores.put("deploy", None)
    asyncio.run(activities.sync(link))
    assert link.pushed[-1][0] == "end" and activities.bound == {}
    import os
    assert too_large({"log": os.urandom(4000).hex()}) is not None and too_large({"gate": "F32"}) is None
    assert shown({"gate": "F32", "ended": False, "alert": {}}) == {"gate": "F32"} and shown([1, 2]) == {"value": [1, 2]}
    (tmp_path / "notes.org").write_text("* x\n")
    stores.link("notes", str(tmp_path / "notes.org"))
    assert "text store" in activities.problem("notes", {})
    assert asyncio.run(activities.end(link, "nothing"))["error"] == "No activity nothing is running"


def test_a_notification_needs_a_line_and_an_open_that_exists():
    artifacts = {"page": {"day": {}}, "components": {"Person": {}}}
    topics = {"lease": {}}
    assert notify_problem({"title": "", "body": " "}, artifacts, topics) == "a notification needs a title or a body"
    assert notify_problem({"title": "Deployed"}, artifacts, topics) is None
    assert notify_problem({"title": "Deployed", "open": {"page": "day"}}, artifacts, topics) is None
    assert notify_problem({"title": "Deployed", "open": {"show": "Person", "with": {"id": "theo"}}}, artifacts, topics) is None
    assert notify_problem({"title": "Deployed", "open": {"conversation": "lease"}}, artifacts, topics) is None
    assert "page gone" in notify_problem({"title": "x", "open": {"page": "gone"}}, artifacts, topics)
    assert "not defined" in notify_problem({"title": "x", "open": {"show": "Ghost"}}, artifacts, topics)
    assert "neither main nor a topic" in notify_problem({"title": "x", "open": {"conversation": "other"}}, artifacts, topics)
    assert notify_problem({"title": "x", "open": "day"}, artifacts, topics).startswith("open is")


def test_the_listener_rings_the_phone_for_a_signed_program(tmp_path):
    import aiohttp

    from dedala.inbox import serve
    from test_inbox import SECRET, Adapter, signature
    from dedala.inbox import Inbox

    class Ringing(Adapter):
        def __init__(self, inbox):
            super().__init__(inbox)
            self.rung = []

        async def notify(self, op):
            if not op.get("title"):
                return "a notification needs a title or a body"
            self.rung.append(op)
            return None

    async def scenario():
        adapter = Ringing(Inbox(tmp_path))
        runner = await serve(adapter, 0, SECRET, "127.0.0.1")
        port = runner.addresses[0][1]
        base = f"http://127.0.0.1:{port}"
        async with aiohttp.ClientSession() as http:
            body = json.dumps({"title": "Deployed", "body": "jacques is up", "open": {"page": "wm-jobs"}}).encode()
            async with http.post(f"{base}/notify", data=body, headers=signature(body)) as answer:
                assert answer.status == 200 and (await answer.json())["status"] == "sent"
            async with http.post(f"{base}/notify", data=body, headers={"X-Webhook-Timestamp": "1", "X-Webhook-Signature-V2": "x"}) as answer:
                assert answer.status == 401
            empty = json.dumps({"body": ""}).encode()
            async with http.post(f"{base}/notify", data=empty, headers=signature(empty)) as answer:
                assert answer.status == 400 and "needs a title" in (await answer.json())["error"]
        await runner.cleanup()
        return adapter.rung

    assert asyncio.run(scenario()) == [{"title": "Deployed", "body": "jacques is up", "open": {"page": "wm-jobs"}}]


def test_app_ops_rings_through_the_adapter_and_sends_the_rest(monkeypatch, tmp_path):
    import types

    import dedala
    import dedala.maintenance  # noqa: F401
    from support import fake_hermes

    fake_hermes()
    import dedala.server  # noqa: F401
    from test_tools import tools

    link, _, sent = tools(monkeypatch, tmp_path)
    link.state["artifacts"]["page"] = {"day": {"op": "page", "id": "day"}}
    rung = []

    async def notify(op):
        rung.append(op)
        return None

    monkeypatch.setattr(dedala.server, "current", types.SimpleNamespace(notify=notify, agent=dedala.agents.Agent()))
    answer = json.loads(asyncio.run(dedala.pages.ops({"ops": [{"op": "notify", "title": "Bill paid", "open": {"page": "day"}}, {"op": "say", "text": "Done"}]})))
    assert answer["sent"] == 2 and answer["rung"] == 1 and rung == [{"op": "notify", "title": "Bill paid", "open": {"page": "day"}}]
    assert [op["op"] for op in sent[-1]] == ["say"]
    refused = json.loads(asyncio.run(dedala.pages.ops({"ops": [{"op": "notify", "title": "x", "open": {"page": "gone"}}]})))
    assert refused["sent"] is False and "page gone" in refused["error"] and len(rung) == 1
    alone = json.loads(asyncio.run(dedala.pages.ops({"ops": [{"op": "notify", "body": "Ping"}]})))
    assert alone == {"sent": 1, "rung": 1}


def test_buttons_are_declared_once_and_a_notification_names_them():
    from dedala.checks import buttons_problem, notify_buttons_problem

    assert buttons_problem({"kinds": {"bill": [{"id": "paid", "title": "Mark paid"}, {"id": "later", "title": "Snooze", "destructive": False}]}}) is None
    assert buttons_problem({"kinds": {}}).startswith("buttons is")
    assert "one to four" in buttons_problem({"kinds": {"x": []}})
    assert "needs an id" in buttons_problem({"kinds": {"x": [{"title": "t"}]}})
    assert "share an id" in buttons_problem({"kinds": {"x": [{"id": "a", "title": "t"}, {"id": "a", "title": "u"}]}})
    assert buttons_problem({"kinds": {"gone": None}}) is None
    artifacts = {"buttons": {"bill": [{"id": "paid", "title": "Mark paid"}]}, "command": {"pay": {}}, "components": {"Bill": {}}, "page": {"bills": {}}}
    assert notify_buttons_problem({"title": "x"}, artifacts) is None
    assert notify_buttons_problem({"kind": "bill", "actions": {"paid": {"command": "pay", "args": {"id": 1}}}}, artifacts) is None
    assert notify_buttons_problem({"kind": "bill", "actions": {"paid": {"edit": {"store": "bills", "id": "1", "paid": True}}}}, artifacts) is None
    assert "no buttons op declared" in notify_buttons_problem({"kind": "other", "actions": {}}, artifacts)
    assert "does not have" in notify_buttons_problem({"kind": "bill", "actions": {"later": {}}}, artifacts)
    assert "not bound" in notify_buttons_problem({"kind": "bill", "actions": {"paid": {"command": "ghost"}}}, artifacts)
    assert "not defined" in notify_buttons_problem({"kind": "bill", "actions": {"paid": {"show": "Ghost"}}}, artifacts)
    assert "maps each" in notify_buttons_problem({"kind": "bill"}, artifacts)


def test_buttons_and_widgets_are_kept_and_sent_again(tmp_path):
    from dedala.link import Link

    link = Link(tmp_path / "dedala", "https://relay.invalid", "token")
    link._record([{"op": "buttons", "kinds": {"bill": [{"id": "paid", "title": "Mark paid"}], "pr": [{"id": "review", "title": "Review"}]}},
                  {"op": "widget", "id": "glance", "store": "day", "component": "Glance", "families": ["small"]}])
    link._record([{"op": "buttons", "kinds": {"pr": None}}, {"op": "widget", "id": "other", "store": "day", "component": "Glance", "families": ["large"]},
                  {"op": "widget", "id": "other", "remove": True}])
    assert link.state["artifacts"]["buttons"] == {"bill": [{"id": "paid", "title": "Mark paid"}]}
    assert list(link.state["artifacts"]["widget"]) == ["glance"]


def test_the_listener_writes_a_store_for_a_signed_program(tmp_path):
    import aiohttp

    from dedala.inbox import Inbox, serve
    from test_inbox import SECRET, Adapter, signature

    class Writing(Adapter):
        def __init__(self, inbox):
            super().__init__(inbox)
            self.written = []

        async def write_store(self, name, body):
            if name == "notes":
                return "the store notes is a folder store: write its file"
            self.written.append((name, body))
            return None

    async def scenario():
        adapter = Writing(Inbox(tmp_path))
        runner = await serve(adapter, 0, SECRET, "127.0.0.1")
        base = f"http://127.0.0.1:{runner.addresses[0][1]}"
        async with aiohttp.ClientSession() as http:
            body = json.dumps({"data": {"gate": "F32"}}).encode()
            async with http.post(f"{base}/store/flight", data=body, headers=signature(body)) as answer:
                assert (await answer.json()) == {"status": "written", "store": "flight"}
            async with http.post(f"{base}/store/notes", data=body, headers=signature(body)) as answer:
                assert answer.status == 400 and "folder store" in (await answer.json())["error"]
            async with http.post(f"{base}/store/flight", data=body, headers={"X-Webhook-Timestamp": "1", "X-Webhook-Signature-V2": "x"}) as answer:
                assert answer.status == 401
        await runner.cleanup()
        return adapter.written

    assert asyncio.run(scenario()) == [("flight", {"data": {"gate": "F32"}})]


def test_the_widget_tool_binds_a_component_to_a_store(monkeypatch, tmp_path):
    import dedala
    import dedala.maintenance  # noqa: F401
    from test_tools import tools

    link, _, sent = tools(monkeypatch, tmp_path)
    link.state["artifacts"]["components"] = {"Glance": {"props": [], "body": {"Text": "$data.weather"}}}
    link.stores.put("day", {"weather": "Rain"})
    link._mirror(["day"])
    call = lambda args: json.loads(asyncio.run(dedala.data.widget(args)))  # noqa: E731
    assert call({})["widgets"] == []
    assert "needs store" in call({"id": "glance"})["error"]
    assert "not defined" in call({"id": "glance", "store": "day", "component": "Ghost"})["error"]
    assert "no store" in call({"id": "glance", "store": "nope", "component": "Glance"})["error"].lower()
    made = call({"id": "glance", "store": "day", "component": "Glance", "families": ["small", "medium"]})
    assert made["widget"] == {"id": "glance", "store": "day", "component": "Glance", "families": ["small", "medium"]}
    assert sent[-1] == [{"op": "widget", "id": "glance", "store": "day", "component": "Glance", "families": ["small", "medium"]}]
    assert "among" in call({"id": "glance", "store": "day", "component": "Glance", "families": ["huge"]})["error"]
    link._record(sent[-1])
    assert call({"id": "glance", "remove": True})["removed"] == "glance"
    locked = call({"id": "locked", "store": "day", "component": "Glance", "families": ["medium", "rectangular"]})
    assert locked["widget"]["families"] == ["medium", "rectangular"] and "Home Screen or Lock Screen" in locked["then"]
    assert call({"id": "plain", "store": "day", "component": "Glance"})["widget"]["families"] == ["small", "medium", "large"]
    link._record(sent[-1])
    link.state["placed"] = {"plain": ["small", "inline"]}
    assert {widget["id"]: widget["placed"] for widget in call({})["widgets"]}["plain"] == ["small", "inline"]
    assert "inline" in call({"id": "plain", "families": ["small"]})["undrawn"]


async def test_a_photo_in_an_edit_lands_as_an_attachment(tmp_path, monkeypatch):
    from support import fake_hermes

    fake_hermes()
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))
    from gateway.config import PlatformConfig
    from dedala.hermes.adapter import AppAdapter

    adapter = AppAdapter(PlatformConfig(extra={"relay": "https://relay.invalid", "token": "t", "name": "Jacques"}))
    blobs = {"b1": b"\xff\xd8JPEG", "b2": b"\xff\xd9"}

    async def blob(name):
        return blobs.get(name)

    monkeypatch.setattr(adapter.server.link, "blob", blob)
    adapter.server.link.stores.put("receipts", [])
    event = {"changes": [{"store": "receipts", "add": {"id": "r1", "amount": 12, "file": {"blobs": ["b1", "b2"], "name": "photo.jpg", "size": 6, "type": "image/jpeg"}}, "from": "receipts"},
                         {"store": "receipts", "id": "r0", "patch": {"file": {"blobs": ["gone"], "name": "x.jpg"}}, "from": "receipts"}]}
    await adapter.server._fetch_photos(event)
    kept = tmp_path / "hermes" / "dedala" / "attachments" / "receipts" / "r1" / "photo.jpg"
    assert kept.read_bytes() == b"\xff\xd8JPEG\xff\xd9"
    assert event["changes"][0]["add"]["file"] == str(kept) and event["changes"][1]["patch"]["file"] is None


def test_a_token_does_only_what_its_scope_says(tmp_path):
    import aiohttp

    from dedala.inbox import Inbox, allowed, serve
    from test_inbox import SECRET, Adapter, signature

    assert allowed(None, "store", "x") and allowed({"stores": ["*"]}, "store", "x") and not allowed({"stores": ["y"]}, "store", "x")
    assert allowed({"notify": True}, "notify", None) and not allowed({"stores": ["x"]}, "notify", None)
    assert allowed({"sources": ["tp7"]}, "source", "tp7") and not allowed({"sources": ["tp7"]}, "source", "grain")

    class Writing(Adapter):
        def __init__(self, inbox):
            super().__init__(inbox)
            self.written, self.rung = [], []

        async def write_store(self, name, body):
            self.written.append(name)
            return None

        async def notify(self, op):
            self.rung.append(op)
            return None

    tokens = {"k-flow": {"id": "pr-flow", "stores": ["pr_reviews"]}, "k-ring": {"id": "ringer", "notify": True, "sources": ["grain"]}}

    async def scenario():
        adapter = Writing(Inbox(tmp_path))
        runner = await serve(adapter, 0, SECRET, "127.0.0.1", lambda: tokens)
        base = f"http://127.0.0.1:{runner.addresses[0][1]}"
        body = json.dumps({"data": {"items": []}}).encode()
        async with aiohttp.ClientSession() as http:
            async with http.post(f"{base}/store/pr_reviews", data=body, headers={"Authorization": "Bearer k-flow"}) as answer:
                assert answer.status == 200
            async with http.post(f"{base}/store/day", data=body, headers={"Authorization": "Bearer k-flow"}) as answer:
                assert answer.status == 403 and "may not store day" in (await answer.json())["error"]
            async with http.post(f"{base}/store/day", data=body, headers={"Authorization": "Bearer nope"}) as answer:
                assert answer.status == 401
            ring = json.dumps({"title": "Done"}).encode()
            async with http.post(f"{base}/notify", data=ring, headers={"Authorization": "Bearer k-flow"}) as answer:
                assert answer.status == 403
            async with http.post(f"{base}/notify", data=ring, headers={"Authorization": "Bearer k-ring"}) as answer:
                assert answer.status == 200
            note = json.dumps({"text": "hello"}).encode()
            async with http.post(f"{base}/in/grain", data=note, headers={"Authorization": "Bearer k-ring", "X-Request-ID": "g1"}) as answer:
                assert answer.status == 202
            async with http.post(f"{base}/in/tp7", data=note, headers={"Authorization": "Bearer k-ring"}) as answer:
                assert answer.status == 403
            async with http.post(f"{base}/store/day", data=body, headers=signature(body)) as answer:
                assert answer.status == 200
        await runner.cleanup()
        return adapter.written, adapter.rung

    written, rung = asyncio.run(scenario())
    assert written == ["pr_reviews", "day"] and len(rung) == 1


def test_a_store_written_from_outside_wakes_its_handler(tmp_path):
    from dedala.handlers import StoreChanged
    from dedala.link import Link

    link = Link(tmp_path / "dedala", "https://relay.invalid", "token")
    link.stores.put("pr_reviews", {"items": [1]})
    pending = StoreChanged(link, "pr_reviews", "job-r")
    prompt = pending.claim()
    assert prompt and 'app_data {"id": "pr_reviews"}' in prompt and pending.claim() is None
    pending.settle(True)
    again = StoreChanged(link, "pr_reviews", "job-r")
    assert again.claim() is None
    link.stores.path("pr_reviews").write_text('{"items": [1, 2]}')
    link.stores.scan()
    assert StoreChanged(link, "pr_reviews", "job-r").claim() is not None


def test_the_token_tool_makes_scoped_keys_in_a_file(monkeypatch, tmp_path):
    import dedala
    from dedala.link import Link

    link = Link(tmp_path / "dedala", "https://relay.invalid", "token")
    monkeypatch.setattr(dedala.session, "link", lambda: link)
    monkeypatch.setattr(dedala.session, "on_gateway", lambda work: work)
    call = lambda args: json.loads(asyncio.run(dedala.data.token(args)))  # noqa: E731
    assert call({})["tokens"] == []
    assert "needs a scope" in call({"id": "x"})["error"]
    made = call({"id": "pr-flow", "stores": ["pr_reviews"], "notify": True})
    assert made["scope"] == {"id": "pr-flow", "stores": ["pr_reviews"], "notify": True} and len(made["token"]) > 20
    kept = json.loads((tmp_path / "dedala" / "tokens.json").read_text())
    assert kept[made["token"]]["id"] == "pr-flow" and link.app.loaded["tokens"] == kept
    again = call({"id": "pr-flow", "stores": ["*"]})
    assert again["token"] != made["token"] and len(json.loads((tmp_path / "dedala" / "tokens.json").read_text())) == 1
    assert call({})["tokens"] == [{"id": "pr-flow", "stores": ["*"]}]
    assert call({"id": "pr-flow", "remove": True}) == {"removed": "pr-flow"} and call({})["tokens"] == []


COUNTDOWN = {"views": {"lock": {"VStack": [{"Text": "$label"}, {"Text": {"countdown": "$until"}}, {"Text": "$when"}]},
                       "minimal": {"Image": "hourglass"}}}


def test_an_activity_over_a_store_that_is_not_an_object_is_refused(tmp_path):
    activities, stores, _ = bound(tmp_path)
    stores.put("countdown", '{"until": "2026-11-10T22:00:00+01:00", "label": "Until 22:00", "when": "Tuesday 10 November"}')
    problem = activities.problem("countdown", COUNTDOWN)
    assert problem.startswith("The store countdown holds a string, not an object: the design reads $label, $until, $when")
    stores.put("scores", [3, 1])
    assert activities.problem("scores", {"views": {"lock": {"Text": "${value[0]} – ${value[1]}"}}}) is None


def test_an_activity_says_what_its_store_does_not_have(tmp_path):
    activities, stores, _ = bound(tmp_path)
    stores.put("countdown", {"until": "2026-11-10T22:00:00+01:00", "label": "Until 22:00"})
    assert activities.problem("countdown", COUNTDOWN) is None
    assert activities.remarks("countdown", COUNTDOWN) == [
        "The design reads $when, which the store countdown does not have: they show empty until it does"]
    stores.put("countdown", {"until": "2026-11-10T22:00:00+01:00", "label": "Until 22:00", "when": "Tuesday 10 November"})
    assert activities.remarks("countdown", COUNTDOWN) == []


def test_running_activities_start_again_on_a_new_phone_from_where_their_stores_are(tmp_path):
    activities, stores, link = bound(tmp_path)
    stores.put("flight", {"gate": "F32"})
    stores.put("deploy", {"step": 1})
    asyncio.run(activities.start(link, "tp1235", "flight", {"views": {"lock": {"Text": "$gate"}}}, None))
    asyncio.run(activities.start(link, "deploy", "deploy", {"views": {}}, None))
    activities.bound["old"] = {"store": "flight", "sent": ""}
    stores.put("flight", {"gate": "F40"})
    stores.put("deploy", {"step": 2, "ended": True})
    link.pushed.clear()
    asyncio.run(activities.restart(link))
    assert link.pushed == [("start", "tp1235", {"gate": "F40"}, None)]
    assert set(activities.bound) == {"tp1235"}


def test_an_activity_started_again_ends_the_one_running_first(tmp_path):
    activities, stores, link = bound(tmp_path)
    stores.put("flight", {"gate": "F32"})
    asyncio.run(activities.start(link, "tp1235", "flight", {"views": {"lock": {"Text": "$gate"}}}, None))
    asyncio.run(activities.start(link, "tp1235", "flight", {"views": {"lock": {"Text": "Gate $gate"}}}, None))
    assert [(kind, activity) for kind, activity, *_ in link.pushed] == [("start", "tp1235"), ("end", "tp1235"), ("start", "tp1235")]
