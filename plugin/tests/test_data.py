# SPDX-FileCopyrightText: 2026 Julien Malka
# SPDX-License-Identifier: MIT

import asyncio
import json
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "plugin"))

from dedala.files import Refused  # noqa: E402
from dedala.link import Link  # noqa: E402
from dedala.stores import Stores, records_of  # noqa: E402


def stores(tmp_path) -> Stores:
    return Stores(tmp_path / "dedala" / "stores")


def test_a_folder_store_reads_each_file_as_a_record(tmp_path):
    notes = tmp_path / "notes"
    (notes / "2026").mkdir(parents=True)
    (notes / "20261107--daily__daily.org").write_text("#+title: samedi 7 novembre\n#+filetags: :daily:journal:\n\n* Journal\n- [ ] Buy milk\n- See [[file:20260101T090000==phd--tosem-paper__paper_pdf.pdf]]\n")
    (notes / "2026" / "plan.md").write_text("---\ntitle: The plan\ntags: [work, nix]\n---\n\n- a\n")
    (notes / "20260101T090000==phd--tosem-paper__paper_pdf.pdf").write_bytes(b"%PDF")
    (notes / "scan.jpg").write_bytes(b"\xff" * 200)
    (notes / ".hidden.org").write_text("* no\n")
    found = stores(tmp_path)
    found.link("notes", str(notes))
    assert found.kind("notes") == "folder"
    records = found.held["notes"]
    assert [item["id"] for item in sorted(records, key=lambda item: item["id"])] == ["2026/plan.md", "20260101T090000==phd--tosem-paper__paper_pdf.pdf", "20261107--daily__daily.org", "scan.jpg"]
    paper = next(item for item in records if item["id"].endswith(".pdf"))
    assert paper["title"] == "tosem paper" and paper["tags"] == ["paper", "pdf"] and paper["signature"] == "phd" and paper["date"] == "2026-01-01T09:00:00"
    assert paper["file"] == str(notes / paper["id"]) and paper["size"] == 4 and "text" not in paper and paper["backlinks"] == ["20261107--daily__daily.org"]
    scan = next(item for item in records if item["id"] == "scan.jpg")
    assert scan["title"] == "scan" and scan["size"] == 200 and scan["file"] == str(notes / "scan.jpg")
    assert sorted(found.attachments("notes")) == [(paper["id"], notes / paper["id"]), ("scan.jpg", notes / "scan.jpg")]
    with pytest.raises(Refused, match="not a text file"):
        found.apply_edit("notes", paper["id"], {"toggle": "x"})
    daily = next(item for item in records if item["id"].startswith("20261107"))
    assert daily["title"] == "samedi 7 novembre" and daily["tags"] == ["daily", "journal"] and daily["name"] == "20261107--daily__daily.org"
    assert "lines" not in daily and "Buy milk" in daily["text"] and daily["updated"]
    plan = next(item for item in records if item["id"] == "2026/plan.md")
    assert plan["title"] == "The plan" and plan["tags"] == ["work", "nix"]
    op = found.op("notes")
    assert op["kind"] == "folder" and len(op["data"]) == 4
    assert [o.get("record", {}).get("id") for o in found.ops("notes")[1:]] == [item["id"] for item in records] and found.ops("notes")[0]["data"] == []


def test_a_folder_store_leaves_out_what_its_patterns_name(tmp_path):
    notes = tmp_path / "notes"
    for name in ("a.org", "npins/sources.json", "ci/deep/run.py", "shell.nix", "assets/talk.mp4", "assets/paper.pdf", "drafts/x/y.org"):
        (notes / name).parent.mkdir(parents=True, exist_ok=True)
        (notes / name).write_text("* x\n" if name.endswith(".org") else "x")
    found = stores(tmp_path)
    found.link("notes", str(notes))
    assert len(found.held["notes"]) == 7 and found.ignore("notes") == []
    found.set_ignore("notes", ["npins/", "ci/", "*.nix", "assets/*.mp4", "**/x/*"])
    assert sorted(item["id"] for item in found.held["notes"]) == ["a.org", "assets/paper.pdf"]
    assert found.ignored["notes"] == 5 and found.links["notes"]["ignore"] == ["npins/", "ci/", "*.nix", "assets/*.mp4", "**/x/*"]
    assert json.loads((tmp_path / "dedala" / "ignore.json").read_text()) == {"notes": ["npins/", "ci/", "*.nix", "assets/*.mp4", "**/x/*"]}
    again = stores(tmp_path)
    again.link("notes", str(notes))
    assert sorted(item["id"] for item in again.held["notes"]) == ["a.org", "assets/paper.pdf"]
    again.set_ignore("notes", None)
    assert len(again.held["notes"]) == 7 and "ignore" not in again.links["notes"]


def test_a_folder_store_notices_files_saved_added_and_gone_one_by_one(tmp_path):
    notes = tmp_path / "notes"
    notes.mkdir()
    (notes / "a.org").write_text("* A\n")
    found = stores(tmp_path)
    found.link("notes", str(notes))
    found.taken("notes")
    assert found.scan() == []
    (notes / "a.org").write_text("* A\n- more\n")
    (notes / "b.md").write_text("# B\n")
    assert found.scan() == ["notes"] and found.taken("notes") == ({"a.org", "b.md"}, set())
    (notes / "a.org").unlink()
    assert found.scan() == ["notes"] and found.taken("notes") == (set(), {"a.org"})
    assert found.record_op("notes", "a.org") == {"op": "store", "id": "notes", "kind": "folder", "drop": "a.org"}
    assert found.record_op("notes", "b.md")["record"]["title"] == "B"


def test_a_folder_store_edits_make_add_and_delete_files(tmp_path):
    notes = tmp_path / "notes"
    notes.mkdir()
    (notes / "a.org").write_text("* A\n- [ ] one\n")
    found = stores(tmp_path)
    found.link("notes", str(notes))
    assert found.apply_edit("notes", "a.org", {"toggle": "one"}) is None
    assert (notes / "a.org").read_text() == "* A\n- [X] one\n"
    assert found.apply_edit("notes", None, {"add": "2026/new.org", "text": "#+title: New"}) == "2026/new.org"
    assert (notes / "2026" / "new.org").read_text() == "#+title: New\n"
    with pytest.raises(Refused):
        found.apply_edit("notes", None, {"add": "../out.org"})
    with pytest.raises(Refused):
        found.apply_edit("notes", None, {"toggle": "one"})
    assert found.apply_edit("notes", "a.org", {"delete": True}) is None
    assert not (notes / "a.org").exists()
    with pytest.raises(Refused):
        found.change("notes", {"store": "notes", "patch": {"x": 1}})


def test_records_are_patched_added_and_removed_in_the_file(tmp_path):
    found = stores(tmp_path)
    found.put("people", [{"id": "theo", "name": "Théo", "role": "PhD"}])
    found.change("people", {"store": "people", "id": "theo", "patch": {"role": "Postdoc", "org": {"name": "Botanic Garden"}}})
    found.change("people", {"store": "people", "add": {"id": "ana", "name": "Ana"}})
    assert [item["id"] for item in found.held["people"]] == ["theo", "ana"]
    assert found.held["people"][0] == {"id": "theo", "name": "Théo", "role": "Postdoc", "org": {"name": "Botanic Garden"}}
    found.change("people", {"store": "people", "remove": "theo"})
    assert json.loads(found.path("people").read_text()) == [{"id": "ana", "name": "Ana"}]
    with pytest.raises(Refused):
        found.change("people", {"store": "people", "add": {"name": "no id"}})
    found.put("trip", {"days": 2})
    found.change("trip", {"store": "trip", "patch": {"packed": True}})
    assert found.held["trip"] == {"days": 2, "packed": True}
    with pytest.raises(Refused):
        found.change("trip", {"store": "trip", "id": "x", "patch": {}})
    assert records_of([{"id": "a"}, {"id": "b"}]) and records_of([]) == [] and records_of({"a": 1}) is None and records_of([{"x": 1}]) is None


def test_a_declaration_rides_on_the_store_op_and_the_attachments_are_the_records_files(tmp_path):
    found = stores(tmp_path)
    lease = tmp_path / "lease.pdf"
    lease.write_bytes(b"%PDF-1.4")
    found.put("documents", [{"id": "lease", "title": "Lease", "file": str(lease)}, {"id": "memo", "title": "Memo"}])
    found.declare("documents", {"name": "Documents", "symbol": "doc", "screen": "Document", "title": "$title", "nonsense": 1})
    op = found.op("documents")
    assert op["declare"] == {"name": "Documents", "symbol": "doc", "screen": "Document", "title": "$title"} and "kind" not in op
    assert found.attachments("documents") == [("lease", lease)]
    found.declare("documents", None)
    assert "declare" not in found.op("documents")
    found.put("documents", None)
    assert "documents" not in found.held and not found.path("documents").exists()


def test_a_linked_json_file_is_a_store_read_from_its_path(tmp_path):
    config = tmp_path / "config.json"
    config.write_text('{"theme": "dark"}')
    found = stores(tmp_path)
    found.link("config", str(config))
    assert found.kind("config") is None and found.held["config"] == {"theme": "dark"}
    found.change("config", {"store": "config", "patch": {"theme": "light"}})
    assert json.loads(config.read_text()) == {"theme": "light"}
    found.unlink("config")
    assert "config" not in found.held and config.exists()


def link(tmp_path) -> Link:
    return Link(tmp_path / "dedala", "https://relay.invalid", "token")


def test_the_link_sends_a_folder_store_whole_once_then_record_by_record(tmp_path):
    notes = tmp_path / "notes"
    notes.mkdir()
    (notes / "a.org").write_text("* A\n")
    kept = link(tmp_path)
    kept.unsent_stores()
    kept.stores.link("notes", str(notes))
    kept.stores_written()
    first = kept.unsent_stores()
    assert [op["op"] for op in first] == ["store", "store"] and first[0]["kind"] == "folder" and first[0]["data"] == []
    assert first[1]["record"]["id"] == "a.org"
    assert kept.unsent_stores() == []
    (notes / "b.org").write_text("* B\n")
    (notes / "a.org").write_text("* A\n- changed\n")
    kept.stores_written()
    ops = kept.unsent_stores()
    assert sorted(op["record"]["id"] for op in ops) == ["a.org", "b.org"]
    (notes / "b.org").write_text("* B\nSee [[file:a.org]].\n")
    kept.stores_written()
    ops = kept.unsent_stores()
    assert sorted(op["record"]["id"] for op in ops) == ["a.org", "b.org"] and ops[0]["record"]["backlinks"] == ["b.org"]
    (notes / "a.org").unlink()
    kept.stores_written()
    assert kept.unsent_stores() == [{"op": "store", "id": "notes", "kind": "folder", "drop": "a.org"},
                                    {"op": "store", "id": "notes", "kind": "folder", "record": kept.stores.held["notes"][0]}]
    assert kept.unsent_stores() == []


def test_his_record_edits_are_made_to_the_file_and_a_refused_one_is_logged_with_why(tmp_path):
    kept = link(tmp_path)
    kept._record([{"op": "page", "id": "people", "title": "People", "view": {"Text": "x"}, "handled_by": "people-handler"},
                  {"op": "store", "id": "people", "data": [{"id": "theo", "name": "Théo"}]}])
    jobs = kept.edited({"at": "2026-11-07T10:00:00Z", "changes": [
        {"store": "people", "id": "theo", "patch": {"role": "PhD"}, "from": "people"},
        {"store": "people", "add": {"id": "ana", "name": "Ana"}, "from": "people"},
        {"store": "people", "remove": "nobody", "from": "people"},
        {"store": "trip", "patch": {"days": 3}, "from": "quiet"},
        {"store": "people", "add": {"name": "no id"}, "from": "people"},
    ]})
    assert jobs == ["people-handler"]
    assert kept.stores.held["people"] == [{"id": "theo", "name": "Théo", "role": "PhD"}, {"id": "ana", "name": "Ana"}]
    assert kept.stores.held["trip"] == {"days": 3}
    logged = kept.changes()[-1]["changes"]
    assert logged[-1]["refused"] == "A record added needs an id" and "refused" not in logged[0]
    assert kept.state["artifacts"]["store"]["people"]["data"][1]["name"] == "Ana"


def test_the_tool_writes_links_declares_reads_and_hands_a_record(monkeypatch, tmp_path):
    import dedala

    kept = link(tmp_path)
    sent = []

    async def send_and_check(ops):
        sent.append(kept._record(ops))
        return {"errors": [], "phone": "closed"}

    async def nothing(*_, **__):
        return []

    monkeypatch.setattr(dedala.session, "link", lambda: kept)
    monkeypatch.setattr(dedala.session, "on_gateway", lambda work: work)
    monkeypatch.setattr(kept, "send_and_check", send_and_check)
    monkeypatch.setattr(kept, "unsent_attachments", nothing)
    kept.state["artifacts"]["components"] = {"Person": {"props": ["id"], "title": "$id", "body": {"Text": "x"}}}
    call = lambda args: json.loads(asyncio.run(dedala.data.data(args)))  # noqa: E731
    assert [store["id"] for store in call({})["stores"]] == ["profile"]
    assert "There is no store people" in call({"id": "people"})["error"]
    written = call({"id": "people", "data": [{"id": "theo", "name": "Théo"}], "name": "People", "symbol": "person", "screen": "Person", "title": "$name"})
    assert written["store"]["records"] == 1 and written["store"]["declared"]["screen"] == "Person"
    assert sent[-1][0]["declare"] == {"name": "People", "symbol": "person", "screen": "Person", "title": "$name"} and sent[-1][0]["data"][0]["id"] == "theo"
    assert "not defined" in call({"id": "people", "screen": "Ghost"})["error"]
    shown = call({"id": "people"})["store"]
    assert shown["kind"] == "json" and shown["declared"]["name"] == "People" and shown["file"].endswith("people.json")
    handed = call({"id": "people", "record": "theo", "say": "Here is Théo"})
    assert handed["handed"] == "theo" and sent[-1][-1] == {"op": "say", "conversation": "main", "text": "Here is Théo", "record": {"store": "people", "id": "theo"}}
    assert "no record nobody" in call({"id": "people", "record": "nobody", "say": "x"})["error"]
    assert "did you mean people" in call({"id": "peple", "patch": {"x": 1}})["error"] and "peple" not in kept.stores.held
    note = tmp_path / "daily.org"
    note.write_text("#+title: today\n")
    linked = call({"id": "daily", "path": str(note)})
    assert linked["store"]["kind"] == "text" and linked["store"]["exists"] is True and sent[-1][0]["kind"] == "text"
    assert "text store" in call({"id": "daily", "data": {"x": 1}})["error"]
    notes = tmp_path / "notes"
    notes.mkdir()
    (notes / "a.org").write_text("#+title: A\n")
    folder = call({"id": "notes", "path": str(notes), "name": "Notes", "title": "$title", "words": ["$text"]})
    assert folder["store"]["kind"] == "folder" and folder["store"]["files"] == [{"id": "a.org", "title": "A", "tags": [], "updated": folder["store"]["files"][0]["updated"]}]
    listed = call({})["stores"]
    assert sorted(store["id"] for store in listed) == ["daily", "notes", "people", "profile"]
    assert call({"id": "notes", "remove": True})["note"].startswith("The file stays") and notes.exists() and "notes" not in kept.stores.held
    assert call({"id": "people", "remove": True})["removed"] == "people" and not kept.stores.path("people").exists()
    assert sent[-1] == [{"op": "store", "id": "people", "data": None}]


def test_search_finds_records_by_their_declared_fields(tmp_path):
    from dedala.search import entries, search

    kept = link(tmp_path)
    kept.stores.put("people", [{"id": "theo", "name": "Théo Lefèvre", "role": "Botany", "contact": {"email": "theo@garden.example"}}])
    kept.stores.declare("people", {"name": "People", "title": "$name", "subtitle": "$role", "words": ["$contact.email"]})
    kept.stores.put("secret", [{"id": "x", "name": "Hidden"}])
    kept._record([{"op": "page", "id": "trip", "title": "Trip", "view": {"Text": "Lisbon"}}])
    found = entries(kept.state["artifacts"], kept.stores)
    assert [(entry["in"], entry["id"]) for entry in found] == [("page", "trip"), ("people", "theo")]
    assert search(found, "lefèvre")[0]["title"] == "Théo Lefèvre"
    assert search(found, "garden.example")[0]["found_in"] == "theo@garden.example"
    assert search(found, "hidden") == [] and search(found, "lisbon", ["people"]) == []


async def test_a_file_written_by_hand_reaches_the_phone_checked(app, relay):
    adapter, phone = app
    from support import online, until

    http, socket = await online(relay, adapter.server.link, phone)
    home = adapter.server.link.home
    (home / "components").mkdir(exist_ok=True)
    (home / "components" / "Tile.json").write_text(json.dumps({"props": ["t"], "body": {"Text": "$t"}}))
    (home / "pages").mkdir(exist_ok=True)
    (home / "pages" / "hand.json").write_text(json.dumps({"title": "By hand", "view": {"Tile": {"t": "hi"}}}))
    await adapter.server.sync_app()
    ops = await phone.ops()
    assert any(op["op"] == "define" and "Tile" in op["components"] for op in ops)
    assert any(op["op"] == "page" and op["id"] == "hand" and op["title"] == "By hand" for op in ops)
    assert adapter.server.link.state["artifacts"]["page"]["hand"]["title"] == "By hand"
    (home / "pages" / "hand.json").write_text(json.dumps({"title": "Broken", "view": {"Text": "x", "fnt": "title"}}))
    await adapter.server.sync_app()
    await until(lambda: any("pages/hand.json changed and would not draw" in event.text for event in adapter.heard))
    assert not any(op["op"] == "page" and op.get("title") == "Broken" for op in await phone.ops())
    (home / "pages" / "hand.json").write_text("{not json")
    await adapter.server.sync_app()
    await until(lambda: any("the app file hand.json" in event.text for event in adapter.heard))
    (home / "pages" / "hand.json").unlink()
    await adapter.server.sync_app()
    assert any(op["op"] == "page" and op["id"] == "hand" and op.get("remove") for op in await phone.ops())
    assert "hand" not in adapter.server.link.state["artifacts"]["page"]
    (home / "search.json").write_text(json.dumps({"people": {"name": "People", "title": "$name"}}))
    adapter.server.link.stores.put("people", [{"id": "a", "name": "A"}])
    adapter.server.link._mirror(["people"])
    await adapter.server.sync_app()
    declared = [op for op in await phone.ops() if op["op"] == "store" and op["id"] == "people" and op.get("declare")]
    assert declared and declared[-1]["declare"] == {"name": "People", "title": "$name"}
    await socket.close()
    await http.close()


@pytest.fixture
async def app(relay, tmp_path, monkeypatch):
    from support import Phone, fake_hermes, until

    fake_hermes()
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))
    from gateway.config import PlatformConfig
    from dedala.hermes.adapter import AppAdapter
    from dedala.link import pair

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


async def test_a_store_the_relay_refused_is_not_remembered_as_sent(tmp_path):
    from dedala.link import Link, Refusal

    link = Link(tmp_path / "dedala", "https://relay.invalid", "token")
    link.identity.data.update(pairing="p", device_key="k")
    monkey = {"calls": 0}

    async def refuse(message):
        monkey["calls"] += 1
        raise Refusal("A message is at most 512KB")

    link._transmit = refuse
    link.identity.keys = lambda: (b"\0" * 32, b"\0" * 32)
    try:
        await link.send([{"op": "store", "id": "notes", "data": {"big": "x"}}])
    except Refusal:
        pass
    assert monkey["calls"] == 1 and "notes" not in link.state.get("stores_sent", {})
    assert link.stores.held["notes"] == {"big": "x"}
    assert [op["id"] for op in link.unsent_stores()] == ["profile", "notes"]


def test_a_folder_store_reads_front_matter_and_links_between_its_files(tmp_path):
    notes = tmp_path / "notes"
    notes.mkdir()
    (notes / "20260401T225935==public--report__sc.org").write_text(
        "#+title:      Report\n#+date:       [2026-04-01 mer. 22:59]\n#+filetags:   :sc:\n#+identifier: 20260401T225935\n#+signature:  public\n\n"
        "About the [[denote:20251109T181549][Committee]] and [[denote:20251109T181549]] again, [[file:plan.md][the plan]], [[https://x.org][x]], [[denote:00000000T000000][gone]].\n")
    (notes / "20251109T181549--committee__sc.org").write_text("#+title: Committee\n\n* Members\n")
    (notes / "plan.md").write_text("---\ntitle: The plan\ndate: 2026-02-03\n---\n\nSee [the report](20260401T225935==public--report__sc.org) and [[Committee]].\n")
    found = stores(tmp_path)
    found.link("notes", str(notes))
    records = {item["id"]: item for item in found.held["notes"]}
    report = records["20260401T225935==public--report__sc.org"]
    assert report["identifier"] == "20260401T225935" and report["date"] == "2026-04-01T22:59" and report["signature"] == "public"
    assert report["links"] == ["20251109T181549--committee__sc.org", "plan.md"] and report["backlinks"] == ["plan.md"]
    assert "targets" not in report
    committee = records["20251109T181549--committee__sc.org"]
    assert committee["identifier"] == "20251109T181549" and committee["date"] == "2025-11-09T18:15:49"
    assert committee["links"] == [] and sorted(committee["backlinks"]) == ["20260401T225935==public--report__sc.org", "plan.md"]
    plan = records["plan.md"]
    assert plan["date"] == "2026-02-03" and "identifier" not in plan
    assert plan["links"] == ["20260401T225935==public--report__sc.org", "20251109T181549--committee__sc.org"]
    found.taken("notes")
    (notes / "plan.md").write_text("---\ntitle: The plan\n---\n\nNothing linked.\n")
    assert found.scan() == ["notes"]
    moved, dropped = found.taken("notes")
    assert moved == {"plan.md", "20260401T225935==public--report__sc.org", "20251109T181549--committee__sc.org"} and dropped == set()
    assert {item["id"]: item["backlinks"] for item in found.held["notes"]}["20260401T225935==public--report__sc.org"] == []
