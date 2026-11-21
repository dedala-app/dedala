# SPDX-FileCopyrightText: 2026 Julien Malka
# SPDX-License-Identifier: MIT

import json

from support import paired

from dedala import journal as module
from dedala.journal import Journal, fold


def lines(*ops):
    return [{"at": f"2026-11-11T10:00:{index:02d}+00:00", **op} for index, op in enumerate(ops)]


def test_a_message_said_again_stays_in_place_until_he_writes_after_it():
    conversations, _ = fold(lines(
        {"op": "say", "id": "a", "text": "Looking", "steps": [{"text": "Read mail", "symbol": "envelope"}]},
        {"op": "say", "id": "a", "text": "Found it"},
        {"op": "say", "id": "b", "text": "Anything else?"},
    ))
    assert [(message["id"], message["text"]) for message in conversations["main"]] == [("a", "Found it"), ("b", "Anything else?")]
    assert conversations["main"][0]["steps"] == [{"text": "Read mail", "symbol": "envelope"}]
    conversations, _ = fold(lines(
        {"op": "say", "id": "a", "text": "Looking"},
        {"op": "say", "id": "y", "from": "you", "text": "And?"},
        {"op": "say", "id": "a", "text": "Found it"},
    ))
    assert [message["id"] for message in conversations["main"]] == ["y", "a"]


def test_patches_receipts_and_what_he_did_fold_into_the_card():
    conversations, _ = fold(lines(
        {"op": "say", "id": "bill", "text": "Pay?", "card": {"view": {"Text": "$amount"}, "data": {"amount": 40, "due": "Fri"}}},
        {"op": "patch", "id": "bill", "data": {"amount": 42, "due": None}, "state": {"open": True}},
        {"op": "receipt", "message": "bill", "text": "Paid"},
        {"op": "answered", "message": "bill"},
        {"op": "loved", "message": "bill"},
    ))
    bill = conversations["main"][0]
    assert bill["card"]["data"] == {"amount": 42} and bill["card"]["state"] == {"open": True}
    assert bill["receipt"] == "Paid" and bill["answered"] == "2026-11-11T10:00:03+00:00" and bill["loved"] is True


def test_a_patch_that_says_again_after_he_wrote_moves_to_the_end():
    conversations, _ = fold(lines(
        {"op": "say", "id": "c", "text": "Draft", "card": {"view": {"Text": "x"}}},
        {"op": "say", "id": "y", "from": "you", "text": "ok"},
        {"op": "patch", "id": "c", "say": "Sent"},
    ))
    assert [message["id"] for message in conversations["main"]] == ["y", "c"]
    assert conversations["main"][1]["text"] == "Sent" and conversations["main"][1]["at"] == "2026-11-11T10:00:02+00:00"


def test_topics_keep_when_they_started_and_closed():
    _, topics = fold(lines(
        {"op": "topic", "id": "move", "title": "Moving", "symbol": "box"},
        {"op": "topic", "id": "move", "closed": True, "outcome": "Done"},
    ))
    assert topics["move"] == {"id": "move", "title": "Moving", "symbol": "box", "started": "2026-11-11T10:00:00+00:00",
                              "closed": "2026-11-11T10:00:01+00:00", "outcome": "Done"}


def test_the_history_comes_in_ops_that_fit_and_names_topics_kept_before_it(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "HISTORY_BUDGET", 400)
    kept = Journal(tmp_path / "conversations.jsonl")
    for index in range(6):
        kept.sent({"op": "say", "conversation": "main", "text": f"message {index} " + "x" * 100})
    kept.yours("main", "thanks", "phone-id", None)
    ops = kept.history({"old": {"title": "Old topic", "opened": "2026-11-01T09:00:00+0100", "closed": None, "outcome": None}})
    assert len(ops) > 1 and all(op["op"] == "history" for op in ops)
    assert ops[0]["topics"] == [{"id": "old", "title": "Old topic", "started": "2026-11-01T09:00:00+01:00"}]
    messages = [message for op in ops for message in op["messages"]]
    assert [message["text"][:9] for message in messages[:6]] == [f"message {index}" for index in range(6)]
    assert messages[-1] == {"conversation": "main", "id": "phone-id", "from": "you", "text": "thanks", "at": messages[-1]["at"]}


def test_a_long_journal_is_folded_on_disk(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "SLACK", 10)
    path = tmp_path / "conversations.jsonl"
    kept = Journal(path)
    for index in range(30):
        kept.sent({"op": "say", "id": "progress", "text": f"{index}%"})
    before = kept.history({})
    Journal(path)
    assert len(path.read_text().splitlines()) == 1
    assert Journal(path).history({}) == before


async def test_a_phone_paired_again_gets_the_conversation_and_the_arrangement(relay, tmp_path):
    link, phone = await paired(relay, tmp_path)
    await link.send([{"op": "say", "text": "Hello"}])
    link.journal.yours("main", "Hi", "y1", None)
    link.arranged({"kind": "arrangement", "pinned": ["today"], "tabNames": {"today": "Now"}, "pages": ["today", "budget"], "extra": 1})
    assert json.loads((tmp_path / "phone.json").read_text()) == {"pinned": ["today"], "tabNames": {"today": "Now"}, "pages": ["today", "budget"]}
    await link.replay()
    replayed = (await phone.ops())[2:]
    assert replayed[0] == {"op": "arrangement", "pinned": ["today"], "tabNames": {"today": "Now"}, "pages": ["today", "budget"]}
    assert [(message.get("from"), message["text"]) for message in replayed[-1]["messages"]] == [(None, "Hello"), ("you", "Hi")]
    await link.stop()


async def test_the_name_he_gives_the_agent_is_kept_and_its_changes_told(relay, tmp_path):
    link, phone = await paired(relay, tmp_path)
    assert link.arranged({"kind": "arrangement", "pinned": []}) is None
    assert link.arranged({"kind": "arrangement", "pinned": [], "name": "Jo"}) == (None, "Jo")
    assert link.arranged({"kind": "arrangement", "pinned": ["today"], "name": "Jo"}) is None
    assert link.arrangement() == [{"op": "arrangement", "pinned": ["today"], "name": "Jo"}]
    assert link.arranged({"kind": "arrangement", "pinned": ["today"]}) == ("Jo", None)
    await link.stop()


async def test_what_a_phone_paired_again_draws_is_not_the_agent_s_to_fix(relay, tmp_path):
    link, phone = await paired(relay, tmp_path)
    await link.send([{"op": "say", "id": "bill", "text": "Pay?", "card": {"view": {"Text": "x"}}}])
    await link.replay()
    assert link.redrawn({"kind": "rendered", "card": "bill"})
    assert not link.redrawn({"kind": "rendered", "card": "bill"})
    await link.replay()
    await link.send([{"op": "say", "id": "bill", "text": "Pay now?", "card": {"view": {"Text": "y"}}}])
    assert not link.redrawn({"kind": "rendered", "card": "bill"})
    await link.stop()
