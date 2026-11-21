# SPDX-FileCopyrightText: 2026 Julien Malka
# SPDX-License-Identifier: MIT

import asyncio
import json
import sys
import types
from pathlib import Path

import pytest

from support import fake_hermes, online, until

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "plugin"))

from dedala.commands import Audit, Commands  # noqa: E402
from dedala.hermes.agent import HermesAgent  # noqa: E402
from dedala.stores import Stores  # noqa: E402


def script(folder: Path, name: str, body: str) -> None:
    path = folder / name
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(0o755)


def commands(tmp_path: Path) -> Commands:
    home = tmp_path / "hermes" / "dedala"
    home.mkdir(parents=True)
    (tmp_path / "hermes" / "scripts").mkdir()
    artifacts: dict = {}
    return Commands(home, artifacts, lambda name, record: None, Stores(home / "stores"), agent=HermesAgent())


def test_a_script_gets_its_args_on_stdin_and_its_stdout_is_the_result(tmp_path):
    found = commands(tmp_path)
    script(found.scripts, "review.sh", 'read args; echo "{\\"pr\\": $(echo $args | sed "s/[^0-9]//g"), \\"verdict\\": \\"ok\\"}"\n'
                                       'echo "{\\"items\\": [1]}" > "$APP_STORES/reviews.json"\n')
    record = found.define("pr_review", {"script": "review.sh", "description": "Review a PR"})
    entry = found.run(record, {"pr": 312}, "prs", "c1", lambda job, prompt: None)
    assert entry["status"] == "done" and entry["result"] == {"pr": 312, "verdict": "ok"} and entry["exit"] == 0
    assert entry["wrote"] == ["reviews"] and entry["id"] == "c1" and entry["from"] == "prs"
    assert found.records["pr_review"]["runs"] == 1 and found.records["pr_review"]["unaudited_since"] == entry["at"]
    assert found.live() == {"pr_review": {"status": "done", "result": {"pr": 312, "verdict": "ok"}, "error": None, "at": entry["at"],
                                          "duration": entry["duration"], "args": {"pr": 312}}}
    assert found.told(None) == [f'pr_review({{"pr": 312}}) done in {entry["duration"]}s, wrote reviews']


def test_a_failing_script_gives_the_last_line_of_stderr_and_wakes_the_supervisor(tmp_path):
    found = commands(tmp_path)
    script(found.scripts, "deploy.sh", 'echo "building" >&2\necho "no such host: jacques" >&2\nexit 3\n')
    record = found.define("deploy", {"script": "deploy.sh", "description": "Deploy", "supervised_by": "job-1"})
    entry = found.run(record, None, "ops", "c2", lambda job, prompt: None)
    assert entry["status"] == "failed" and entry["exit"] == 3 and entry["error"] == "no such host: jacques"
    assert entry["stderr"] == "building\nno such host: jacques"
    assert found.signal(record, entry) == "a run failed" and record["failed"] == 1 and record["audits"] == 0
    audit = Audit(found, "deploy", "a run failed")
    prompt = audit.claim()
    assert prompt.startswith("[app: why you were woken: a run failed.") and '"error": "no such host: jacques"' in prompt
    assert audit.claim() is None
    audit.settle(True)
    assert record["audited"] == 1 and record["audits"] == 1 and "unaudited_since" not in record


def test_a_script_that_runs_out_of_time_or_is_missing_fails_with_why(tmp_path):
    found = commands(tmp_path)
    script(found.scripts, "slow.sh", "sleep 5\n")
    record = found.define("slow", {"script": "slow.sh", "description": "Slow", "timeout": 1})
    entry = found.run(record, {}, "p", "c3", lambda job, prompt: None)
    assert entry["status"] == "failed" and entry["error"] == "Ran out of time after 1s"
    assert found.problem({"script": "nothere.sh"}).startswith("There is no script")
    assert found.problem({"script": "../etc/passwd"}).startswith("script is a file under")
    assert found.problem({"script": "slow.sh", "job": "j"}).startswith("A command is bound to one thing")
    (found.scripts / "plain.sh").write_text("echo hi\n")
    assert found.problem({"script": "plain.sh"}).endswith("chmod +x it")
    assert found.problem({"flow": "f/pr/review"}).startswith("No Windmill here")


def test_the_sample_waits_longer_after_each_clean_audit_and_drift_wakes_at_once(tmp_path):
    found = commands(tmp_path)
    script(found.scripts, "ok.sh", "echo done\n")
    record = found.define("ok", {"script": "ok.sh", "description": "Ok"})
    run = lambda: found.run(record, {}, "p", None, lambda job, prompt: None)  # noqa: E731
    assert found.signal(record, run()) == "a sample: 1 runs since you last looked"
    found.audited(record, True)
    assert found.signal(record, run()) is None
    assert found.signal(record, run()) == "a sample: 2 runs since you last looked"
    found.audited(record, True)
    for _ in range(3):
        assert found.signal(record, run()) is None
    assert found.signal(record, run()) == "a sample: 4 runs since you last looked"
    record["sample"] = 1
    assert found.signal(record, run()) == "a sample: 1 runs since you last looked"
    found.audited(record, True)
    from dedala.commands import _drift

    assert _drift({"status": "done", "duration": 30.0, "wrote": ["x"]}, [{"status": "done", "duration": 2.0, "wrote": ["x"]}] * 3) \
        == "a run unlike the others: it took 30.0s where the others take about 2.0s"
    assert _drift({"status": "done", "duration": 2.0, "wrote": []}, [{"status": "done", "duration": 2.0, "wrote": ["x"]}] * 3) \
        == "a run unlike the others: it wrote no store where the others do"
    assert _drift({"status": "done", "duration": 2.0, "wrote": []}, [{"status": "done", "duration": 2.0, "wrote": []}] * 3) is None
    assert _drift({"status": "done", "duration": 2.0}, [{"status": "done", "duration": 2.0}] * 2) is None


def test_a_job_bound_command_runs_the_job_with_the_args_and_reads_its_output(tmp_path, monkeypatch):
    found = commands(tmp_path)
    record = found.define("triage", {"job": "job-9", "description": "Triage the inbox"})
    output = tmp_path / "out"
    jobs = types.ModuleType("cron.jobs")
    jobs.get_cron_output_dir = lambda: output
    monkeypatch.setitem(sys.modules, "cron", types.ModuleType("cron"))
    monkeypatch.setitem(sys.modules, "cron.jobs", jobs)
    given = []

    def run_job(job, prompt):
        given.append((job, prompt))
        (output / "job-9").mkdir(parents=True)
        (output / "job-9" / "now.md").write_text("Three mails filed.\n")
        return None

    entry = found.run(record, {"folder": "inbox"}, "mail", "c4", run_job)
    assert given == [("job-9", '[app: he ran the command triage with {"folder": "inbox"}. Do what its contract says: Triage the inbox]')]
    assert entry["status"] == "done" and entry["result"] == "Three mails filed."
    assert found.run(record, {}, "mail", "c5", lambda job, prompt: "busy")["error"] == "The job is already running"


def test_rebinding_keeps_the_description_and_starts_the_sample_over(tmp_path):
    found = commands(tmp_path)
    script(found.scripts, "a.sh", "echo a\n")
    record = found.define("x", {"job": "j", "description": "X"})
    record["audits"] = 3
    found.define("x", {"script": "a.sh"})
    assert found.records["x"]["script"] == "a.sh" and "job" not in found.records["x"]
    assert found.records["x"]["description"] == "X" and found.records["x"]["audits"] == 0
    assert found.binding(found.records["x"]) == "script a.sh"
    assert found.remove("x")["id"] == "x" and found.remove("x") is None


@pytest.fixture
async def app(relay, tmp_path, monkeypatch):
    fake_hermes()
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))
    from support import Phone

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
    (tmp_path / "hermes" / "scripts").mkdir(parents=True, exist_ok=True)
    yield adapter, phone
    await adapter.disconnect()


async def ops_of(phone, kinds: tuple, count: int) -> list[dict]:
    found = []
    for _ in range(100):
        found = [op for op in await phone.ops() if op["op"] in kinds]
        if len(found) >= count:
            return found
        await asyncio.sleep(0.05)
    raise AssertionError(f"waited for {count} of {kinds}, got {found}")


async def test_a_command_tapped_on_the_phone_runs_here_and_comes_back_with_its_stores(app, relay):
    adapter, phone = app
    http, socket = await online(relay, adapter.server.link, phone)
    script(adapter.server.commands.scripts, "count.sh", 'echo "$(cat)" >> "$APP_STORES/../taps.log"\necho "{\\"n\\": 1}" > "$APP_STORES/taps.json"\necho ok\n')
    adapter.server.commands.define("count", {"script": "count.sh", "description": "Count taps", "supervised_by": "sup-1"})
    woken = []
    adapter.server.handlers.trigger = lambda job, pending, settle: woken.append((job, pending.why))
    tap = {"kind": "command", "id": "k1", "name": "count", "args": {"page": 1}, "from": "today", "at": "2026-11-07T10:00:00Z"}
    await phone.send([tap])
    acked = (await ops_of(phone, ("acked",), 1))[0]
    store, command = acked["answers"]["k1"]
    assert store["id"] == "taps" and store["data"] == {"n": 1}
    assert command["name"] == "count" and command["status"] == "done" and command["result"] == "ok" and command["args"] == {"page": 1}
    assert acked["ids"] == ["k1"] and "failed" not in acked
    assert woken == [("sup-1", "a sample: 1 runs since you last looked")]
    await phone.send([tap])
    again = (await ops_of(phone, ("acked",), 2))[1]
    assert again["answers"]["k1"][1]["status"] == "done" and again["ids"] == ["k1"]
    assert (adapter.server.commands.home / "taps.log").read_text().count("page") == 1
    await socket.close()
    await http.close()


async def test_a_command_nobody_bound_fails_on_the_phone_and_tells_the_agent(app):
    adapter, phone = app
    await phone.send([{"kind": "command", "id": "k2", "name": "ghost", "args": None, "from": "today", "at": "2026-11-07T10:00:00Z"}])
    acked = (await ops_of(phone, ("acked",), 1))[0]
    command = acked["answers"]["k2"][0]
    assert command["status"] == "failed" and command["error"] == "No command named ghost"
    assert acked["failed"] == {"k2": "No command named ghost"}
    await until(lambda: any("no command by that name" in event.text for event in adapter.heard))


async def test_his_message_carries_the_commands_he_ran_since_the_last_one(app):
    adapter, phone = app
    script(adapter.server.commands.scripts, "ok.sh", "echo fine\n")
    adapter.server.commands.define("ok", {"script": "ok.sh", "description": "Ok"})
    await phone.send([{"kind": "command", "id": "k3", "name": "ok", "args": {"a": 1}, "from": "p", "at": "2026-11-07T10:00:00Z"}])
    await ops_of(phone, ("acked",), 1)
    await phone.send([{"kind": "message", "conversation": "main", "text": "Was that right?"}])
    await until(lambda: any(event.text.startswith("Was that right?") for event in adapter.heard))
    heard = next(event.text for event in adapter.heard if event.text.startswith("Was that right?"))
    assert "[app: commands he ran since your last message: ok({\"a\": 1}) done in" in heard
    await phone.send([{"kind": "message", "conversation": "main", "text": "And now?"}])
    await until(lambda: any(event.text.startswith("And now?") for event in adapter.heard))
    assert "commands he ran" not in next(event.text for event in adapter.heard if event.text.startswith("And now?"))


def test_the_tool_binds_with_a_contract_and_makes_the_supervisor(monkeypatch, tmp_path):
    import dedala
    from dedala.link import Link

    fake_hermes()
    home = tmp_path / "hermes" / "dedala"
    link = Link(home, "https://relay.invalid", "token")
    (tmp_path / "hermes" / "scripts").mkdir(parents=True)
    found = Commands(home, link.state["artifacts"], lambda name, record: None, link.stores, agent=HermesAgent())
    adapter = types.SimpleNamespace(commands=found, agent=found.agent)
    monkeypatch.setattr(dedala.session, "link", lambda: link)
    monkeypatch.setattr(dedala.session, "on_gateway", lambda work: work)
    monkeypatch.setattr(dedala.server, "current", adapter)
    made = []
    jobs = types.ModuleType("cron.jobs")
    jobs.create_job = lambda **fields: made.append(fields) or {"id": f"sup-{len(made)}"}
    jobs.update_job = lambda job, updates: made.append((job, updates))
    jobs.remove_job = lambda job: made.append(("removed", job))
    jobs.get_job = lambda job: {"id": job} if job == "job-7" else None
    monkeypatch.setitem(sys.modules, "cron", types.ModuleType("cron"))
    monkeypatch.setitem(sys.modules, "cron.jobs", jobs)
    script(tmp_path / "hermes" / "scripts", "r.sh", "echo 1\n")

    call = lambda args: json.loads(asyncio.run(dedala.commands.tool(args)))  # noqa: E731
    assert call({})["commands"] == []
    assert "There is no command pr_review" in call({"id": "pr_review"})["error"]
    assert "needs a description" in call({"id": "pr_review", "script": "r.sh"})["error"]
    bound = call({"id": "pr_review", "script": "r.sh", "description": "Review PR n and write the verdict into pr_reviews"})
    assert bound["command"]["supervised_by"] == "sup-1" and bound["command"]["binding"] == "script r.sh"
    assert bound["use"] == {"command": "pr_review", "args": "{…}"} and bound["live"].startswith("$commands.pr_review:")
    assert made[0]["name"] == "command/pr_review" and made[0]["deliver"] == "local" and made[0]["schedule"] == "0 4 31 2 *"
    assert "Review PR n and write the verdict" in made[0]["prompt"] and "bound to script r.sh" in made[0]["prompt"]
    assert link.state["artifacts"]["command"]["pr_review"]["description"].startswith("Review PR n")
    rebound = call({"id": "pr_review", "job": "job-7"})
    assert rebound["command"]["binding"] == "job job-7" and made[1][0] == "sup-1" and "bound to job job-7" in made[1][1]["prompt"]
    assert "No cron job job-8" in call({"id": "other", "job": "job-8", "description": "x"})["error"]
    shown = call({"id": "pr_review"})
    assert shown["command"]["binding"] == "job job-7" and shown["runs"] == []
    assert call({"id": "pr_review", "remove": True}) == {"removed": "pr_review"} and made[-1] == ("removed", "sup-1")
    assert call({})["commands"] == []


def test_a_view_naming_a_command_nobody_bound_is_refused():
    from dedala.grammar import shown

    view = {"VStack": [{"Button": "Review", "action": {"command": "pr_review", "args": {"pr": 1}}}, {"Button": "Run", "action": {"command": "$it.cmd"}}]}
    assert shown(view, set(), set()) == ["command: no command 'pr_review' is bound; app_command binds it to a script, a flow or a job first"]
    assert shown(view, set(), {"pr_review"}) == [] and shown(view, set()) == []
