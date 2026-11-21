# SPDX-FileCopyrightText: 2026 Julien Malka
# SPDX-License-Identifier: MIT

import asyncio
import json
from pathlib import Path

import aiohttp
import pytest

from support import Phone, held_for_the_agent, online, paired, until

from dedala import seal
from dedala.link import Link, pair


async def test_pairing_sends_the_agent_s_name_in_its_profile_store(relay, tmp_path):
    link, phone = await paired(relay, tmp_path)
    assert {"op": "store", "id": "profile", "data": {"name": "Jacques"}} in await phone.ops()
    await link.stop()


async def test_what_the_agent_built_is_sent_again_in_order(relay, tmp_path):
    link, phone = await paired(relay, tmp_path)
    await link.send([
        {"op": "page", "id": "ol", "title": "OL", "view": {"Text": "Lyon"}},
        {"op": "store", "id": "ol", "data": {"score": "2-1"}},
        {"op": "store", "id": "people", "data": [{"id": "marta", "name": "Marta"}], "declare": {"name": "People", "title": "$name"}},
        {"op": "say", "text": "not an artifact"},
    ])
    await link.replay()
    replayed = (await phone.ops())[-5:]
    assert [op["op"] for op in replayed] == ["store", "store", "store", "page", "history"]
    assert replayed[2]["declare"] == {"name": "People", "title": "$name"} and replayed[2]["data"][0]["name"] == "Marta"
    assert [message["text"] for message in replayed[4]["messages"]] == ["not an artifact"]
    await link.stop()


async def test_the_app_coming_online_is_brought_in_sync(relay, tmp_path):
    link, phone = await paired(relay, tmp_path)
    online = asyncio.get_running_loop().create_future()

    async def sync():
        online.set_result(True)

    link.on_online = sync
    async with aiohttp.ClientSession(headers={"Authorization": f"Bearer {phone.token}"}) as http:
        async with http.ws_connect(f"{relay[0]}/ws"):
            assert await asyncio.wait_for(online, 2)
    await link.stop()


async def test_events_reach_the_agent_and_captures_are_fetched(relay, tmp_path):
    link, phone = await paired(relay, tmp_path)
    seen = []

    async def heard(event):
        seen.append(event)

    link.on_event = heard
    image = b"\xff\xd8 a jpeg"
    async with aiohttp.ClientSession(headers={"Authorization": f"Bearer {phone.token}"}) as http:
        async with http.post(f"{relay[0]}/blobs", json=seal.seal_bytes(phone.keys[1], 0, image)) as response:
            blob = (await response.json())["blob"]
    await phone.send([{"kind": "message", "conversation": "main", "text": "Hi"}, {"kind": "flag", "card": "plumber", "capture": {"blob": blob}}])
    for _ in range(100):
        if len(seen) == 2:
            break
        await asyncio.sleep(0.05)
    assert seen[0]["text"] == "Hi"
    assert Path(seen[1]["capture"]).read_bytes() == image
    await link.stop()


async def test_sending_without_a_phone_says_how_to_pair(relay, tmp_path):
    url, token = relay
    link = Link(tmp_path, url, token)
    with pytest.raises(RuntimeError, match="hermes dedala pair"):
        await link.send([{"op": "say", "text": "Hello"}])


async def test_attachments_are_described_then_fetched_in_parts_on_the_phones_request(relay, tmp_path, monkeypatch):
    from dedala import link as module

    monkeypatch.setattr(module, "PART_BYTES", 3 * module.BLOB_CHUNK)
    link, phone = await paired(relay, tmp_path / "home")
    pdf = tmp_path / "lease.pdf"
    pdf.write_bytes(b"%PDF-1.7 " + bytes(range(256)) * 16000)
    await link.send([{"op": "store", "id": "documents", "data": [{"id": "lease", "title": "Lease", "file": str(pdf)},
                                                                 {"id": "gone", "title": "Gone", "file": str(tmp_path / "gone.pdf")}]}])
    described = await link.unsent_attachments()
    assert [(op["store"], op["id"]) for op in described] == [("documents", "lease"), ("documents", "gone")]
    assert described[0]["size"] == pdf.stat().st_size and described[0]["version"] and "blobs" not in described[0]
    assert described[1]["missing"] is True
    assert await link.unsent_attachments() == [] and await link.send_parts() == []
    assert link.fetch("documents", "nothing") == "No file to fetch: the record nothing of documents names none"
    assert link.fetch("documents", "lease") is None and link.fetch("documents", "lease") is None
    assert link.state["fetching"] == [{"store": "documents", "id": "lease", "path": str(pdf), "size": pdf.stat().st_size, "next": 1, "of": 2}]
    body = b""
    for part in (1, 2):
        ops = await link.send_parts()
        assert len(ops) == 1 and ops[0]["part"] == part and ops[0]["of"] == 2 and ops[0]["name"] == "lease.pdf"
        async with aiohttp.ClientSession(headers={"Authorization": f"Bearer {phone.token}"}) as http:
            for blob in ops[0]["blobs"]:
                async with http.get(f"{relay[0]}/blobs/{blob}") as response:
                    body += seal.unseal_bytes(phone.keys[0], await response.json())
                async with http.delete(f"{relay[0]}/blobs/{blob}"):
                    pass
    assert body == pdf.read_bytes() and link.state["fetching"] == [] and await link.send_parts() == []
    pdf.write_bytes(b"%PDF-1.7 changed")
    assert [op["size"] for op in await link.unsent_attachments()] == [16]
    await link.replay()
    assert [op["id"] for op in await link.unsent_attachments()] == ["lease", "gone"]
    await link.stop()


async def test_a_full_relay_makes_a_part_wait_and_a_changed_file_is_told_missing(relay, tmp_path, monkeypatch):
    from dedala import link as module
    from hermes_relay import store as relay_store

    monkeypatch.setattr(module, "PART_BYTES", 2 * module.BLOB_CHUNK)
    monkeypatch.setattr(relay_store, "BLOBS_LIMIT", module.BLOB_CHUNK + 10)
    link, phone = await paired(relay, tmp_path / "home")
    pdf = tmp_path / "big.pdf"
    pdf.write_bytes(b"x" * (3 * module.BLOB_CHUNK))
    await link.send([{"op": "store", "id": "documents", "data": [{"id": "big", "title": "Big", "file": str(pdf)}]}])
    await link.unsent_attachments()
    assert link.fetch("documents", "big") is None
    assert await link.send_parts() == [] and link.state["fetching"][0]["next"] == 1
    orphan = await link._upload(b"left behind" * 40_000)
    monkeypatch.setattr(relay_store, "BLOBS_LIMIT", 3 * module.BLOB_CHUNK)
    monkeypatch.setattr(module, "ORPHAN_AGE", 0)
    first = await link.send_parts()
    async with aiohttp.ClientSession(headers={"Authorization": f"Bearer {phone.token}"}) as http:
        assert (await http.get(f"{relay[0]}/blobs/{orphan}")).status == 404
    assert first[0]["part"] == 1 and len(first[0]["blobs"]) == 2
    pdf.write_bytes(b"y" * 10)
    told = await link.send_parts()
    assert told == [{"op": "attachment", "store": "documents", "id": "big", "name": "big.pdf", "size": 3 * module.BLOB_CHUNK, "missing": True}]
    assert link.state["fetching"] == []
    await link.stop()


async def test_a_file_asset_reaches_the_phone_privately_once_until_it_changes(relay, tmp_path):
    link, phone = await paired(relay, tmp_path / "home")
    take = tmp_path / "take-1.jpg"
    take.write_bytes(b"\xff\xd8" + bytes(range(256)) * 5000)
    await link.send([{"op": "assets", "assets": {"take-1": str(take), "ol": "https://example.com/ol.png"}}])
    await link.send([{"op": "assets", "assets": {"take-1": str(take)}}])
    first, again = [op["assets"] for op in await phone.ops() if op["op"] == "assets"]
    assert first["ol"] == "https://example.com/ol.png" and len(first["take-1"]["blobs"]) == 2
    assert again == {}
    body = b""
    async with aiohttp.ClientSession(headers={"Authorization": f"Bearer {phone.token}"}) as http:
        for blob in first["take-1"]["blobs"]:
            async with http.get(f"{relay[0]}/blobs/{blob}") as response:
                body += seal.unseal_bytes(phone.keys[0], await response.json())
    assert body == take.read_bytes()
    await link.replay()
    assert "blobs" in [op for op in await phone.ops() if op["op"] == "assets"][-1]["assets"]["take-1"]
    assert link.state["artifacts"]["assets"]["take-1"] == str(take)
    await link.stop()


async def test_steps_go_with_the_next_message_once(relay, tmp_path):
    link, phone = await paired(relay, tmp_path)
    search = {"text": "Searched files for tosem", "symbol": "magnifyingglass"}
    read = {"text": "Read tosem.org", "symbol": "doc.text"}
    link.add_step("main", search)
    link.add_step("main", search)
    link.add_step("main", read)
    assert link.steps["main"] == [search, search, read]
    await link.send([{"op": "say", "conversation": "main", "text": "Here it is"},
                     {"op": "say", "conversation": "main", "text": "Anything else?"}])
    first, second = [op for op in await phone.ops() if op["op"] == "say"][-2:]
    assert first["steps"] == [search, read]
    assert "steps" not in second
    await link.stop()


async def test_a_send_returns_what_the_app_found_or_says_it_did_not_look(relay, tmp_path):
    link, phone = await paired(relay, tmp_path)
    page = [{"op": "page", "id": "sc", "title": "SC", "view": {"Text": "Hi"}}]
    closed = await link.send_and_check(page)
    assert closed["errors"] == [] and closed["phone"].startswith("The phone is closed")
    http, socket = await online(relay, link, phone)

    async def app_side(errors):
        while True:
            frame = await socket.receive_json()
            if "message" not in frame:
                continue
            ops = seal.unseal(phone.keys[0], frame["message"])
            if check := next((op for op in ops if op.get("op") == "check"), None):
                if errors is not None:
                    await phone.send([{"kind": "checked", "id": check["id"], "errors": errors}], socket)
                return check["id"]

    answering = asyncio.create_task(app_side(["op 0: Component names are capitalised: props"]))
    assert await link.send_and_check(page) == {"errors": ["op 0: Component names are capitalised: props"]}
    await answering
    answering = asyncio.create_task(app_side([]))
    assert await link.send_and_check(page) == {"errors": []}
    await answering
    answering = asyncio.create_task(app_side(None))
    silent = await link.send_and_check(page, timeout=0.2)
    assert silent["errors"] == [] and silent["phone"].startswith("The phone did not answer")
    heard = []

    async def on_event(event):
        heard.append(event)

    link.on_event = on_event
    await phone.send([{"kind": "checked", "id": await answering, "errors": ["op 0: late"]}], socket)
    for _ in range(50):
        if heard:
            break
        await asyncio.sleep(0.05)
    assert heard[-1]["kind"] == "errors" and heard[-1]["errors"] == ["op 0: late"]
    await socket.close()
    await http.close()
    await link.stop()


async def heard(link, count):
    seen = []

    async def hear(event):
        if event.get("fails"):
            raise ValueError("this one cannot be handled")
        seen.append(event)

    link.on_event = hear
    return seen


async def test_an_event_that_fails_does_not_stop_the_ones_after_it(relay, tmp_path):
    link, phone = await paired(relay, tmp_path)
    seen = await heard(link, 2)
    await phone.send([{"kind": "message", "text": "before"}, {"kind": "message", "fails": True}, {"kind": "message", "text": "after"}])
    await phone.send([{"kind": "message", "text": "next message"}])
    await until(lambda: len(seen) == 3)
    assert [event["text"] for event in seen] == ["before", "after", "next message"]
    assert link.state["last_in"] == 2
    await asyncio.sleep(0.1)
    assert await held_for_the_agent(relay) == []
    await link.stop()


async def test_a_message_that_arrives_late_is_still_heard_once(relay, tmp_path):
    link, phone = await paired(relay, tmp_path)
    seen = await heard(link, 2)
    phone.seq = 1
    await phone.send([{"kind": "message", "text": "numbered second, arrived first"}])
    phone.seq = 0
    await phone.send([{"kind": "message", "text": "numbered first, arrived second"}])
    await until(lambda: len(seen) == 2)
    phone.seq = 0
    await phone.send([{"kind": "message", "text": "numbered first, arrived second"}])
    await asyncio.sleep(0.3)
    assert len(seen) == 2
    await link.stop()


async def test_a_late_message_is_heard_after_a_restart_too(relay, tmp_path):
    url, token = relay
    link, phone = await paired(relay, tmp_path)
    seen = await heard(link, 1)
    phone.seq = 2
    await phone.send([{"kind": "message", "text": "third"}])
    await until(lambda: len(seen) == 1)
    await link.stop()
    link = Link(tmp_path, url, token, "Jacques")
    seen = await heard(link, 2)
    await link.start()
    for number, text in ((0, "first, late"), (2, "third again"), (1, "second, late"), (0, "first again")):
        phone.seq = number
        await phone.send([{"kind": "message", "text": text}])
    await until(lambda: len(seen) == 2)
    await asyncio.sleep(0.3)
    assert [event["text"] for event in seen] == ["first, late", "second, late"]
    assert link.state["missing"] == []
    await link.stop()


async def test_a_message_the_relay_refuses_is_an_error_not_a_silence(relay, tmp_path):
    link, phone = await paired(relay, tmp_path)
    await until(lambda: link._socket is not None)
    with pytest.raises(RuntimeError, match="512KB"):
        await link.send([{"op": "store", "id": "big", "data": {"text": "x" * 600_000}}])
    await link.send([{"op": "say", "text": "still working"}])
    assert (await phone.ops())[-1]["text"] == "still working"
    await link.stop()


async def test_batches_fit_the_relay_once_sealed():
    ops = [{"op": "say", "text": "é" * 100_000} for _ in range(6)]
    batches = Link._batches(ops)
    assert sum(len(batch) for batch in batches) == 6
    key = b"k" * 32
    assert all(len(json.dumps(seal.seal(key, 1, batch))) <= 512 * 1024 for batch in batches)


async def test_a_phone_paired_while_the_gateway_was_away_starts_from_nothing(relay, tmp_path):
    url, token = relay
    link, phone = await paired(relay, tmp_path)
    await link.send([{"op": "page", "id": "ol", "title": "OL", "view": {"Text": "Lyon"}}])
    await link.stop()
    second = Phone(url)
    codes = asyncio.Queue()
    pairing = asyncio.create_task(pair(tmp_path, url, token, "Jacques", codes.put_nowait))
    await second.claim(await codes.get())
    await pairing
    link = Link(tmp_path, url, token, "Jacques")
    assert link.state["seq_out"] > 1
    await link.start()
    await until(lambda: link.state.get("pairing") == link.identity.data["pairing"] and link.state["seq_out"] == 1)
    assert [op["op"] for op in await second.ops()] == ["store", "page"]
    await link.stop()


def test_state_that_cannot_be_read_stops_the_plugin(tmp_path):
    (tmp_path / "link.json").write_text('{"seq_out": 41, "last_')
    with pytest.raises(RuntimeError, match="link.json"):
        Link(tmp_path, "http://relay", "token", "Jacques")
    (tmp_path / "link.json").unlink()
    (tmp_path / "identity.json").write_text("")
    with pytest.raises(RuntimeError, match="identity.json"):
        Link(tmp_path, "http://relay", "token", "Jacques")


def test_what_the_agent_builds_is_files_and_the_numbering_is_kept_apart(tmp_path):
    (tmp_path / "link.json").write_text(json.dumps({"seq_out": 41, "last_in": 7, "channels": {}}))
    (tmp_path / "pages").mkdir()
    (tmp_path / "pages" / "ol.json").write_text(json.dumps({"title": "OL", "view": {"Text": "Lyon"}}))
    link = Link(tmp_path, "http://relay", "token", "Jacques")
    assert link.state["seq_out"] == 41 and link.state["artifacts"]["page"]["ol"]["title"] == "OL"
    assert "artifacts" not in json.loads((tmp_path / "link.json").read_text())
    link._record([{"op": "store", "id": "ol", "data": {"score": "2-1"}},
                  {"op": "page", "id": "day", "title": "Day", "view": {"Text": "x"}, "store": "day", "focus": True},
                  {"op": "define", "components": {"Tile": {"body": {"Text": "t"}}}, "scripts": {"m": "return {}"}},
                  {"op": "buttons", "kinds": {"bill": [{"id": "paid", "title": "Paid"}]}},
                  {"op": "widget", "id": "glance", "store": "day", "component": "Tile", "families": ["small"]},
                  {"op": "assets", "assets": {"logo": "https://x/logo.png"}}])
    assert json.loads((tmp_path / "pages" / "day.json").read_text()) == {"title": "Day", "view": {"Text": "x"}}
    assert json.loads((tmp_path / "components" / "Tile.json").read_text()) == {"body": {"Text": "t"}}
    assert (tmp_path / "scripts" / "m.js").read_text() == "return {}\n"
    assert json.loads((tmp_path / "buttons.json").read_text()) == {"bill": [{"id": "paid", "title": "Paid"}]}
    assert json.loads((tmp_path / "widgets" / "glance.json").read_text()) == {"store": "day", "component": "Tile", "families": ["small"]}
    assert json.loads((tmp_path / "assets.json").read_text()) == {"logo": "https://x/logo.png"}
    again = Link(tmp_path, "http://relay", "token", "Jacques")
    assert again.state["seq_out"] == 41 and again.state["artifacts"]["store"]["ol"]["data"] == {"score": "2-1"}
    assert sorted(again.state["artifacts"]["page"]) == ["day", "ol"] and again.state["artifacts"]["widget"]["glance"]["component"] == "Tile"
    link._record([{"op": "page", "id": "day", "remove": True}, {"op": "define", "components": {"Tile": None}}, {"op": "widget", "id": "glance", "remove": True}])
    assert not (tmp_path / "pages" / "day.json").exists() and not (tmp_path / "components" / "Tile.json").exists() and not (tmp_path / "widgets" / "glance.json").exists()


async def test_store_patches_are_recorded_merged(relay, tmp_path):
    link, phone = await paired(relay, tmp_path)
    await link.send([{"op": "store", "id": "sc", "data": {"election": {"seats": 4, "open": True}, "prs": [1]}}])
    await link.send([{"op": "store", "id": "sc", "patch": {"election": {"open": False}, "prs": None}}])
    assert link.state["artifacts"]["store"]["sc"]["data"] == {"election": {"seats": 4, "open": False}}
    await link.stop()


def test_a_deleted_component_is_no_longer_kept_to_send_again(tmp_path):
    from dedala.link import Link

    link = Link(tmp_path, "http://relay", "token", "Jacques")
    link._record([{"op": "define", "components": {"Face": {"body": {"Text": "x"}}, "DayHead": {"body": {"Text": "y"}}}}])
    link._record([{"op": "define", "components": {"Face": None}}])
    assert list(link.state["artifacts"]["components"]) == ["DayHead"]


def test_his_edits_patch_the_copies_and_name_the_jobs_that_handle_them(tmp_path):
    from dedala.link import Link

    link = Link(tmp_path, "http://relay", "token", "Jacques")
    link._record([{"op": "store", "id": "tasks", "data": [{"id": "water", "title": "Water the plants", "done": False, "room": "kitchen"}]},
                  {"op": "page", "id": "tasks", "title": "Tasks", "view": {"Text": "x"}, "handled_by": "tasks-handler"},
                  {"op": "page", "id": "today", "title": "Today", "view": {"Text": "x"}, "handled_by": "today-handler"},
                  {"op": "page", "id": "quiet", "title": "Quiet", "view": {"Text": "y"}},
                  {"op": "store", "id": "groceries", "data": {"list": ["milk", "eggs"], "shop": "Biocoop"}}])
    jobs = link.edited({"at": "2026-10-26T09:00:00Z", "changes": [
        {"store": "tasks", "id": "water", "patch": {"done": True, "subtitle": "Done"}, "from": "tasks"},
        {"store": "groceries", "patch": {"list": ["eggs", "milk"]}, "from": "today"},
    ]})
    assert jobs == ["tasks-handler", "today-handler"]
    water = link.state["artifacts"]["store"]["tasks"]["data"][0]
    assert water == {"id": "water", "title": "Water the plants", "done": True, "room": "kitchen", "subtitle": "Done"}
    assert link.state["artifacts"]["store"]["groceries"]["data"] == {"list": ["eggs", "milk"], "shop": "Biocoop"}
    assert link.edited({"at": "2026-10-26T09:05:00Z", "changes": [{"store": "groceries", "patch": {"replace": ["bread"]}, "from": "quiet"}]}) == []
    assert link.state["artifacts"]["store"]["groceries"]["data"] == ["bread"]
    assert [entry["at"] for entry in link.changes()] == ["2026-10-26T09:00:00Z", "2026-10-26T09:05:00Z"]
    assert [entry["at"] for entry in link.changes(since="2026-10-26T09:00:00Z")] == ["2026-10-26T09:05:00Z"]
    assert link.changes(limit=1)[0]["changes"][0]["store"] == "groceries"


def test_a_name_from_outside_stays_inside_its_folder():
    from dedala.state import safe

    assert [safe(name) for name in ("lease", "Lease v4.pdf", "..", ".", "../../etc", "a/b", "")] == [
        "lease", "Lease-v4.pdf", "item", "item", "..-..-etc", "a-b", "item"]
    assert all("/" not in safe(name) and safe(name) not in ("..", ".") for name in ("../x", "/abs", "a/../b"))



async def test_a_second_link_on_the_same_home_is_refused(relay, tmp_path):
    url, token = relay
    first = Link(tmp_path, url, token, "Jacques")
    await first.start()
    second = Link(tmp_path, url, token, "Jacques")
    with pytest.raises(RuntimeError, match="through the app tools"):
        await second.start()
    await first.stop()
    await second.start()
    await second.stop()
