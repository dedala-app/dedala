# SPDX-FileCopyrightText: 2026 Julien Malka
# SPDX-License-Identifier: MIT

import sys
import threading
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "plugin"))

from dedala import maintenance  # noqa: E402
from dedala.hermes.agent import HermesAgent  # noqa: E402
from dedala.link import _valid_components  # noqa: E402

JOBS = {"sc": {"schedule_display": "every 6h", "last_run_at": "2026-10-25T12:00:00+02:00", "next_run_at": "2026-10-25T18:00:00+02:00",
               "last_status": "ok", "last_error": None, "state": "scheduled", "enabled": True}}
TRIGGERED = []
HERMES = HermesAgent()


def fake_cron(monkeypatch):
    jobs = types.ModuleType("cron.jobs")
    jobs.get_job = JOBS.get
    jobs.update_job = lambda job, fields: None
    jobs.trigger_job = lambda job: TRIGGERED.append(job) or JOBS.get(job)
    monkeypatch.setitem(sys.modules, "cron", types.ModuleType("cron"))
    monkeypatch.setitem(sys.modules, "cron.jobs", jobs)


def test_a_page_upkeep_reads_its_job(monkeypatch):
    fake_cron(monkeypatch)
    assert maintenance.state(HERMES, "sc") == {"job": "sc", "schedule": "every 6h", "last": "2026-10-25T12:00:00+02:00",
                                       "next": "2026-10-25T18:00:00+02:00", "status": "ok"}
    assert maintenance.state(HERMES, "gone") == {"job": "gone", "missing": True}
    assert maintenance.state(HERMES, None) is None


def test_refreshing_runs_the_job_or_says_why_not(monkeypatch):
    fake_cron(monkeypatch)
    monkeypatch.setitem(sys.modules, "tools.cronjob_tools", None)
    assert HERMES.run_job("sc") is None
    assert TRIGGERED == ["sc"]
    assert HERMES.run_job("gone") == "No cron job gone"


def test_refreshing_fires_the_job_at_once_where_hermes_can(monkeypatch):
    fake_cron(monkeypatch)
    fired = threading.Event()
    tools = types.ModuleType("tools.cronjob_tools")
    tools.execute_job_for_event = lambda job: fired.set() or {"claimed": True, "success": True, "error": None}
    monkeypatch.setitem(sys.modules, "tools.cronjob_tools", tools)
    assert HERMES.run_job("sc") is None
    assert fired.wait(2)
    assert HERMES.run_job("gone") == "No cron job gone"


WATCHED = {"schedule_display": "every 5m", "last_run_at": "2026-10-25T12:05:00+01:00", "next_run_at": "2026-10-25T12:10:00+01:00",
           "last_status": "ok", "state": "scheduled", "enabled": True, "monitor_script": "wm_jobs.py",
           "monitor_state": {"last_output_hash": "abc", "last_changed_at": "2026-10-25T09:00:00+01:00"}}


def test_a_change_detector_was_updated_when_it_last_changed_and_checked_at_its_tick(monkeypatch):
    fake_cron(monkeypatch)
    monkeypatch.setitem(JOBS, "wm", dict(WATCHED))
    assert maintenance.state(HERMES, "wm") == {"job": "wm", "schedule": "every 5m", "last": "2026-10-25T09:00:00+01:00",
                                       "next": "2026-10-25T12:10:00+01:00", "status": "ok", "watching": True,
                                       "checked": "2026-10-25T12:05:00+01:00"}


def test_components_the_app_refuses_are_not_kept():
    assert _valid_components({"SCReport": {"body": {"Text": "x"}}, "props": {"report": {}}, "Broken": {"view": {}}}) == \
        {"SCReport": {"body": {"Text": "x"}}}
