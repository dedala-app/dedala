# SPDX-FileCopyrightText: 2026 Julien Malka
# SPDX-License-Identifier: MIT

import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "plugin"))

from dedala.background import Runs, act, running, snapshot  # noqa: E402
from dedala.hermes.agent import HermesAgent, run_of  # noqa: E402

HERMES = HermesAgent()

JOBS = [{"id": "sc", "name": "SC page refresh", "schedule_display": "every day at 9am", "next_run_at": "2026-10-26T09:00:00+01:00",
         "last_run_at": "2026-10-25T02:23:10+02:00", "last_status": "ok", "last_error": None, "state": "scheduled",
         "enabled": True, "deliver": "local"},
        {"id": "brief", "name": "morning-brief", "schedule_display": "45 7 * * *", "next_run_at": None, "last_run_at": None,
         "last_status": "error", "last_error": "interrupted", "state": "paused", "enabled": False, "deliver": "origin"},
        {"id": "match", "name": "OM vs Le Havre result", "schedule_display": "once at 2026-10-25 19:25", "next_run_at": None,
         "last_run_at": "2026-10-25T18:26:55+01:00", "last_status": "ok", "state": "completed", "enabled": False,
         "deliver": "origin"}]
EXECUTIONS = [{"id": "e2", "job_id": "sc", "status": "running", "claimed_at": "2026-10-25T02:30:26+02:00",
               "started_at": "2026-10-25T02:30:27+02:00", "finished_at": None, "error": None},
              {"id": "e1", "job_id": "sc", "status": "completed", "claimed_at": "2026-10-25T02:20:34+02:00",
               "started_at": "2026-10-25T02:20:35+02:00", "finished_at": "2026-10-25T02:23:10+02:00", "error": None}]
DONE = []


def fake_cron(monkeypatch):
    jobs = types.ModuleType("cron.jobs")
    jobs.list_jobs = lambda include_disabled=False: [dict(job) for job in JOBS]
    jobs.get_job = lambda job: next((dict(found) for found in JOBS if found["id"] == job), None)
    jobs.trigger_job = lambda job: DONE.append(("run", job)) or job == "sc"
    jobs.pause_job = lambda job, reason=None: DONE.append(("pause", job)) or job == "sc"
    jobs.resume_job = lambda job: DONE.append(("resume", job)) or job == "sc"
    jobs.update_job = lambda job, fields: None
    executions = types.ModuleType("cron.executions")
    executions.list_executions = lambda limit=50: EXECUTIONS[:limit]
    monkeypatch.setitem(sys.modules, "cron", types.ModuleType("cron"))
    monkeypatch.setitem(sys.modules, "cron.jobs", jobs)
    monkeypatch.setitem(sys.modules, "cron.executions", executions)


def test_cron_task_ids_name_their_job_and_run():
    assert run_of("cron:sc:e2") == ("sc", "e2")
    assert run_of("app:main") is None
    assert run_of("") is None


def test_a_run_keeps_its_steps_and_tokens(tmp_path):
    runs = Runs(tmp_path)
    runs.stream("s1", 400, "Thinking", [("sc", "e2")])
    runs.step("sc", "e2", "s1", {"text": "Read a page", "symbol": "globe"})
    runs.step("sc", "e2", "s1", {"text": "Read a page", "symbol": "globe"})
    runs.stream("s1", 40, "Writing", [("sc", "e2"), ("brief", "e3")])
    runs.stream("other", 40, "Writing", [("sc", "e2"), ("brief", "e3")])
    assert runs.of("e2") == {"steps": [{"text": "Read a page", "symbol": "globe"}], "tokens": 110, "doing": "Writing"}


def test_jobs_and_runs_are_shown_with_what_the_hooks_saw(monkeypatch, tmp_path):
    fake_cron(monkeypatch)
    runs = Runs(tmp_path)
    runs.step("sc", "e2", "s1", {"text": "Read a page", "symbol": "globe"})
    runs.step("gone", "e0", "s0", {"text": "Old", "symbol": "globe"})
    found = snapshot(HERMES, runs, {"sc-recap": {"maintained_by": "sc"}, "other": {}})
    assert found["jobs"] == [
        {"id": "sc", "name": "SC page refresh", "schedule": "every day at 9am", "next": "2026-10-26T09:00:00+01:00",
         "last": "2026-10-25T02:23:10+02:00", "status": "ok", "silent": True, "page": "sc-recap"},
        {"id": "brief", "name": "morning-brief", "schedule": "45 7 * * *", "next": None, "last": None, "status": "error",
         "silent": False, "error": "interrupted", "paused": True},
        {"id": "match", "name": "OM vs Le Havre result", "schedule": "once at 2026-10-25 19:25", "next": None,
         "last": "2026-10-25T18:26:55+01:00", "status": "ok", "silent": False, "done": True}]
    assert found["runs"] == [
        {"id": "e2", "job": "sc", "name": "SC page refresh", "started": "2026-10-25T02:30:27+02:00", "finished": None,
         "status": "running", "steps": [{"text": "Read a page", "symbol": "globe"}], "tokens": 0, "doing": None},
        {"id": "e1", "job": "sc", "name": "SC page refresh", "started": "2026-10-25T02:20:35+02:00",
         "finished": "2026-10-25T02:23:10+02:00", "status": "ok", "steps": [], "tokens": 0}]
    assert Runs(tmp_path).of("e2")["steps"] == [{"text": "Read a page", "symbol": "globe"}]
    assert Runs(tmp_path).of("e0")["steps"] == []
    assert running(HERMES) == [("sc", "e2")]


def test_he_can_run_pause_and_resume_a_job(monkeypatch):
    fake_cron(monkeypatch)
    monkeypatch.setitem(sys.modules, "tools.cronjob_tools", None)
    assert act(HERMES, "sc", "run") is None
    assert act(HERMES, "sc", "pause") is None
    assert act(HERMES, "sc", "resume") is None
    assert act(HERMES, "gone", "run") == "No cron job gone"
    assert act(HERMES, "sc", "delete") == "Unknown action delete"
    assert DONE[:3] == [("run", "sc"), ("pause", "sc"), ("resume", "sc")]


def test_a_change_detector_shows_only_the_ticks_that_woke_the_agent(monkeypatch, tmp_path):
    fake_cron(monkeypatch)
    watched = {"id": "wm", "name": "wm-jobs maintainer", "schedule_display": "every 5m", "next_run_at": "2026-10-25T12:10:00+01:00",
               "last_run_at": "2026-10-25T12:05:00+01:00", "last_status": "ok", "state": "scheduled", "enabled": True,
               "deliver": "local", "monitor_script": "wm_jobs.py",
               "monitor_state": {"last_output_hash": "abc", "last_changed_at": "2026-10-25T09:00:00+01:00"}}
    ticks = [{"id": f"t{n}", "job_id": "wm", "status": status, "claimed_at": f"2026-10-25T12:0{n}:00+01:00",
              "started_at": f"2026-10-25T12:0{n}:00+01:00", "finished_at": None, "error": error}
             for n, status, error in [(5, "completed", None), (4, "running", None), (3, "failed", "wm_jobs.py exited 1"), (2, "completed", None)]]
    monkeypatch.setattr(sys.modules[__name__], "JOBS", [watched])
    monkeypatch.setattr(sys.modules[__name__], "EXECUTIONS", ticks)
    runs = Runs(tmp_path)
    runs.step("wm", "t2", "s2", {"text": "Read Windmill", "symbol": "gearshape"})
    found = snapshot(HERMES, runs, {"wm-jobs": {"maintained_by": "wm"}})
    assert found["jobs"][0]["last"] == "2026-10-25T09:00:00+01:00"
    assert found["jobs"][0]["watching"] is True and found["jobs"][0]["checked"] == "2026-10-25T12:05:00+01:00"
    assert [run["id"] for run in found["runs"]] == ["t3", "t2"]


def test_background_delegations_show_as_runs(monkeypatch, tmp_path):
    fake_cron(monkeypatch)
    module = types.ModuleType("tools.async_delegation")
    module.list_async_delegations = lambda: [
        {"delegation_id": "deleg_a", "goal": "Research the public activity of Grégor Quétel", "status": "running",
         "dispatched_at": 1792938076.0, "completed_at": None,
         "children_activity": [{"api_calls": 12, "current_tool": "web_extract", "seconds_since_activity": 2.0}]},
        {"delegation_id": "deleg_b", "goal": "Say OK", "status": "completed", "dispatched_at": 1792938017.0,
         "completed_at": 1792938026.0},
        {"delegation_id": "deleg_c", "goal": "Check the build", "status": "interrupted", "dispatched_at": 1792937000.0,
         "completed_at": 1792937100.0},
    ]
    monkeypatch.setitem(sys.modules, "tools", types.ModuleType("tools"))
    monkeypatch.setitem(sys.modules, "tools.async_delegation", module)
    found = {run["id"]: run for run in snapshot(HERMES, Runs(tmp_path), {})["runs"]}
    assert found["deleg_a"]["status"] == "running" and found["deleg_a"]["doing"] == "Using web_extract · 12 model calls"
    assert found["deleg_a"]["name"] == "Research the public activity of Grégor Quétel" and found["deleg_a"]["background"]
    assert found["deleg_b"]["status"] == "ok" and found["deleg_b"]["finished"]
    assert found["deleg_c"]["status"] == "failed" and found["deleg_c"]["error"] == "interrupted"


def test_a_job_that_runs_on_arrival_says_so_instead_of_its_schedule(monkeypatch, tmp_path):
    fake_cron(monkeypatch)
    JOBS.append({"id": "mail", "name": "inbox/mail", "schedule_display": "0 4 1 1 *", "next_run_at": "2027-01-01T04:00:00+01:00",
                 "last_run_at": None, "last_status": None, "state": "scheduled", "enabled": True, "deliver": "local"})
    try:
        found = {job["id"]: job for job in snapshot(HERMES, Runs(tmp_path), {}, {"wm": "sc"})["jobs"]}
    finally:
        JOBS.pop()
    assert (found["mail"]["schedule"], found["mail"]["next"]) == ("When something arrives", None)
    assert (found["sc"]["schedule"], found["sc"]["next"]) == ("When wm changes", None)
