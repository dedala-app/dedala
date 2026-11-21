# SPDX-FileCopyrightText: 2026 Julien Malka
# SPDX-License-Identifier: MIT

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "plugin"))

from dedala import handlers as module  # noqa: E402
from dedala.handlers import BUSY, Arrivals, Edits, Handlers  # noqa: E402
from dedala.inbox import Inbox  # noqa: E402
from dedala.link import Link  # noqa: E402

JOBS = {"grain": "job-grain"}


async def idle(handlers: Handlers) -> None:
    for _ in range(200):
        await asyncio.sleep(0.01)
        if not handlers._settling and not handlers._running:
            return
    raise AssertionError("the handler never finished")


async def test_what_a_job_read_is_read_only_when_its_run_ends_well(tmp_path):
    inbox = Inbox(tmp_path)
    inbox.arrive("grain", {"text": "Stand-up notes"}, "rec-1")
    outcomes, seen = [None, "the run failed: boom"], []

    def run(job, prompt):
        seen.append([item["id"] for item in inbox.take("grain")])
        return outcomes.pop()

    handlers = Handlers(run)
    handlers.trigger("job-grain", Arrivals(inbox, "job-grain", lambda: JOBS), 0)
    await idle(handlers)
    assert seen == [["rec-1"]]
    assert [item["id"] for item in inbox.unread("grain")] == ["rec-1"]
    inbox.arrive("grain", {"text": "Retro notes"}, "rec-2")
    handlers.trigger("job-grain", Arrivals(inbox, "job-grain", lambda: JOBS), 0)
    await idle(handlers)
    assert seen == [["rec-1"], ["rec-1", "rec-2"]]
    assert inbox.unread("grain") == [] and inbox.take("grain") == []


async def test_what_arrives_during_a_run_gets_a_run_of_its_own(tmp_path, monkeypatch):
    inbox = Inbox(tmp_path)
    inbox.arrive("grain", {"text": "First"}, "rec-1")
    seen = []
    monkeypatch.setattr("dedala.inbox.now", iter(f"2026-11-06T10:00:0{second}+00:00" for second in range(9)).__next__)

    def run(job, prompt):
        seen.append([item["id"] for item in inbox.take("grain")])
        if len(seen) == 1:
            inbox.arrive("grain", {"text": "Came while it ran"}, "rec-2")
        return None

    handlers = Handlers(run)
    handlers.trigger("job-grain", Arrivals(inbox, "job-grain", lambda: JOBS), 0)
    await idle(handlers)
    assert seen == [["rec-1"], ["rec-2"]]


async def test_a_job_that_is_busy_is_asked_again(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "BUSY_WAIT", 0)
    inbox = Inbox(tmp_path)
    inbox.arrive("grain", {"text": "Notes"}, "rec-1")
    answers = [None, BUSY, BUSY]

    def run(job, prompt):
        inbox.take("grain")
        return answers.pop()

    handlers = Handlers(run)
    handlers.trigger("job-grain", Arrivals(inbox, "job-grain", lambda: JOBS), 0)
    await idle(handlers)
    assert answers == [] and inbox.unread("grain") == []


def test_a_run_cut_by_a_restart_leaves_nothing_taken(tmp_path):
    inbox = Inbox(tmp_path)
    inbox.arrive("grain", {"text": "Notes"}, "rec-1")
    inbox.give(["grain"])
    assert [item["id"] for item in inbox.take("grain")] == ["rec-1"]
    assert inbox.unread("grain") == []
    assert [item["id"] for item in Inbox(tmp_path).unread("grain")] == ["rec-1"]


def test_reading_outside_a_handler_s_run_marks_read_at_once(tmp_path):
    inbox = Inbox(tmp_path)
    inbox.arrive("mail", {"text": "Hello"}, "m-1")
    assert [item["id"] for item in inbox.take("mail")] == ["m-1"]
    assert Inbox(tmp_path).unread("mail") == []


async def test_his_changes_are_handled_until_none_is_left_and_given_again_after_a_failure(tmp_path):
    link = Link(tmp_path, "http://relay", "token", "Jacques")

    def changed(what):
        link.log_edits({"at": "2026-11-06T10:00:00Z", "changes": [{"store": "tasks", "patch": {"done": what}, "from": "today"}]})

    changed("before the job was linked")
    changed("first")
    link.follow_changes("tasks-handler")
    prompts, outcomes = [], ["the run failed: boom"]

    def run(job, prompt):
        prompts.append(prompt)
        after = int(prompt.split('"after": ')[1].split("}")[0])
        read = [entry["changes"][0]["patch"]["done"] for entry in link.changes(after=after)]
        if len(prompts) == 2:
            changed("made while it ran")
        return outcomes.pop() if outcomes else read and None

    handlers = Handlers(run)
    handlers.trigger("tasks-handler", Edits(link, "tasks-handler"), 0)
    await idle(handlers)
    assert link.unhandled_changes("tasks-handler") == (1, 2)
    handlers.trigger("tasks-handler", Edits(link, "tasks-handler"), 0)
    await idle(handlers)
    assert ['"after": 1' in prompt for prompt in prompts] == [True, True, False] and '"after": 2' in prompts[2]
    assert link.unhandled_changes("tasks-handler") == (3, 3)
    assert json.loads((tmp_path / "link.json").read_text())["changes_handled"] == {"tasks-handler": 3}


def test_changes_are_numbered_and_read_after_a_number(tmp_path):
    link = Link(tmp_path, "http://relay", "token", "Jacques")
    for index in range(60):
        link.log_edits({"at": f"2026-11-06T10:00:{index:02d}Z", "changes": []})
    assert [entry["n"] for entry in link.changes(after=57)] == [58, 59, 60]
    assert len(link.changes(after=0)) == 60 and len(link.changes()) == 50 and link.changes()[0]["n"] == 11
    assert [entry["n"] for entry in link.changes(since="2026-11-06T10:00:57Z")] == [59, 60]
