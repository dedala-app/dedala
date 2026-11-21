# SPDX-FileCopyrightText: 2026 Julien Malka
# SPDX-License-Identifier: MIT

import asyncio
import hashlib
import hmac
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "plugin"))

from dedala.inbox import INLINE_CHARS, Inbox, handled_by, handlers, serve, signed  # noqa: E402

SECRET = "s3cret"


def signature(body: bytes, at: float | None = None) -> dict:
    timestamp = str(int(at or time.time()))
    digest = hmac.new(SECRET.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
    return {"X-Webhook-Timestamp": timestamp, "X-Webhook-Signature-V2": digest}


def test_an_arrival_is_kept_once_and_read_once(tmp_path):
    inbox = Inbox(tmp_path)
    assert inbox.arrive("grain", {"title": "Focus & Intensity", "text": "We agreed"}, "rec-1")["title"] == "Focus & Intensity"
    assert inbox.arrive("grain", {"text": "We agreed"}, "rec-1") is None
    inbox.arrive("tp7", {"text": "Buy oat milk"}, "take-9")
    assert [item["id"] for item in inbox.take("grain")] == ["rec-1"]
    assert inbox.take("grain") == []
    assert [item["id"] for item in inbox.take()] == ["take-9"]
    assert [item["id"] for item in inbox.take("grain", since="2000-01-01")] == ["rec-1"]


def test_a_long_text_stays_in_its_file(tmp_path):
    inbox = Inbox(tmp_path)
    transcript = "Julien: " + "word " * INLINE_CHARS
    inbox.arrive("grain", {"text": transcript}, "rec-2")
    item = inbox.take("grain")[0]
    assert "text" not in item and Path(item["file"]).read_text() == transcript.strip()
    assert Inbox.shown(item)["start"] == transcript[:600]
    assert Inbox.text(item) == transcript.strip()


def test_jobs_named_after_a_source_handle_it():
    jobs = [{"id": "a", "name": "inbox"}, {"id": "b", "name": "inbox/tp7"}, {"id": "c", "name": "inbox/Bad Name"},
            {"id": "d", "name": "morning-brief"}]
    assert handlers(jobs) == {"*": "a", "tp7": "b"}


def test_reading_every_source_leaves_those_with_a_job_of_their_own(tmp_path):
    inbox = Inbox(tmp_path)
    inbox.arrive("tp7", {"text": "Buy oat milk"}, "take-1")
    inbox.arrive("grain", {"text": "We agreed"}, "rec-1")
    assert [item["id"] for item in inbox.take(besides=frozenset({"tp7"}))] == ["rec-1"]
    assert [item["id"] for item in inbox.take("tp7")] == ["take-1"]


def test_the_job_named_inbox_handles_every_source_without_its_own():
    found = {"*": "a", "tp7": "b"}
    assert handled_by(found, "a", {"grain", "mail", "tp7"}) == ["grain", "mail"]
    assert handled_by(found, "b", {"grain", "tp7"}) == ["tp7"]
    assert handled_by({"tp7": "b"}, "a", {"grain"}) == []


def test_only_a_fresh_signature_of_the_body_is_accepted():
    body = b'{"text": "hi"}'
    headers = signature(body)
    assert signed(SECRET, headers["X-Webhook-Timestamp"], body, headers["X-Webhook-Signature-V2"])
    assert not signed(SECRET, headers["X-Webhook-Timestamp"], b'{"text": "other"}', headers["X-Webhook-Signature-V2"])
    stale = signature(body, time.time() - 3600)
    assert not signed(SECRET, stale["X-Webhook-Timestamp"], body, stale["X-Webhook-Signature-V2"])
    assert not signed(SECRET, "", body, "")


class Adapter:
    def __init__(self, inbox):
        self.inbox = inbox
        self.forwarded = []

    async def arrived(self, source, payload, identifier):
        return self.inbox.arrive(source, payload, identifier)

    async def forward(self, source, conversation):
        items = self.inbox.take(source)
        self.forwarded += [(conversation, item["text"]) for item in items]
        return len(items)


def test_the_listener_takes_signed_arrivals_and_forwards_from_this_machine(tmp_path):
    import aiohttp

    async def scenario():
        adapter = Adapter(Inbox(tmp_path))
        runner = await serve(adapter, 0, SECRET, "127.0.0.1")
        port = runner.addresses[0][1]
        base = f"http://127.0.0.1:{port}"
        async with aiohttp.ClientSession() as http:
            note = json.dumps({"text": "Buy oat milk"}).encode()
            async with http.post(f"{base}/note", data=note, headers={**signature(note), "X-Request-ID": "take-1"}) as answer:
                assert answer.status == 202
            async with http.post(f"{base}/note", data=note, headers={**signature(note), "X-Request-ID": "take-1"}) as answer:
                assert (await answer.json())["status"] == "duplicate"
            recording = json.dumps({"preface": "🎥 (meeting recording from Grain)", "text": "We agreed"}).encode()
            async with http.post(f"{base}/note", data=recording, headers={**signature(recording), "X-Request-ID": "grain:rec-7"}) as answer:
                assert answer.status == 202
            async with http.post(f"{base}/in/grain", data=note, headers={"X-Webhook-Timestamp": "1", "X-Webhook-Signature-V2": "x"}) as answer:
                assert answer.status == 401
            async with http.post(f"{base}/in/Not A Source", data=note, headers=signature(note)) as answer:
                assert answer.status == 400
            async with http.post(f"{base}/forward", json={"source": "tp7"}) as answer:
                assert (await answer.json())["forwarded"] == 1
        await runner.cleanup()
        assert [item["id"] for item in adapter.inbox.take("grain")] == ["rec-7"]
        return adapter.forwarded

    assert asyncio.run(scenario()) == [("main", "Buy oat milk")]
