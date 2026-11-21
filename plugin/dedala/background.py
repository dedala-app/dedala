# SPDX-FileCopyrightText: 2026 Julien Malka
# SPDX-License-Identifier: MIT

"""What the agent does in the background: his jobs, the runs under way with
the steps they take and the tokens they write, and the runs before, for the
app's Activity. The agent tells the steps and the stream of a run as it does
a conversation's."""

import json
import logging
import threading
import time
from pathlib import Path

from .agents import Agent
from .state import write

logger = logging.getLogger(__name__)

KEPT_RUNS = 20
SCANNED_RUNS = 300
KEPT_STEPS = 60
# The steps of a run under way are written this often, so a restart keeps them.
KEEP_EVERY = 30


class Runs:
    """The steps and tokens of each run, as the hooks see them (from the agent's
    threads), kept for the last runs across restarts."""

    def __init__(self, home: Path):
        self.path = home / "runs.json"
        self.lock = threading.Lock()
        self.sessions: dict[str, str] = {}
        self._changed = False
        self._kept_at = 0.0
        try:
            self.runs: dict[str, dict] = json.loads(self.path.read_text())
        except (OSError, ValueError):
            self.runs = {}

    def _run(self, execution: str, job: str) -> dict:
        return self.runs.setdefault(execution, {"job": job, "steps": [], "tokens": 0, "doing": None})

    def step(self, job: str, execution: str, session: str, step: dict) -> None:
        with self.lock:
            run = self._run(execution, job)
            if session:
                self.sessions[session] = execution
            if not run["steps"] or run["steps"][-1] != step:
                run["steps"] = (run["steps"] + [step])[-KEPT_STEPS:]
            run["doing"] = None
            self._changed = True

    def stream(self, session: str, characters: int, writing: str, running: list[tuple[str, str]]) -> None:
        """A run's session is known from its first tool call; before it, the only
        run under way is the one writing."""
        with self.lock:
            execution = self.sessions.get(session)
            if execution is None and len(running) == 1:
                job, execution = running[0]
                self._run(execution, job)
                if session:
                    self.sessions[session] = execution
            if execution in self.runs:
                self.runs[execution]["tokens"] += max(1, round(characters / 4))
                self.runs[execution]["doing"] = writing
                self._changed = True

    def of(self, execution: str) -> dict:
        with self.lock:
            run = self.runs.get(execution) or {}
            return {"steps": list(run.get("steps", [])), "tokens": run.get("tokens", 0), "doing": run.get("doing")}

    def keep(self, executions: list[str]) -> None:
        """Only the runs still shown are kept, on disk for the next start."""
        with self.lock:
            kept = {execution: self.runs[execution] for execution in executions if execution in self.runs}
            now = time.monotonic()
            if kept.keys() == self.runs.keys() and not (self._changed and now - self._kept_at >= KEEP_EVERY):
                return
            self.runs = kept
            self.sessions = {session: execution for session, execution in self.sessions.items() if execution in kept}
            self._changed, self._kept_at = False, now
            try:
                write(self.path, kept)
            except OSError as error:
                logger.debug("[app] runs not kept: %s", error)


def quiet(run: dict) -> bool:
    """A change detector's tick that found nothing new: the agent did not run."""
    return run["status"] != "failed" and not run["steps"] and not run["tokens"]


def snapshot(agent: Agent, runs: Runs, pages: dict, stores_handled: dict[str, str] | None = None) -> dict:
    """Every job and the last runs, with the steps of those the agent told; the
    ticks of change detectors that woke no agent are left out. A job that runs
    when something arrives says so instead of the schedule it is given."""
    from .inbox import handlers

    known = agent.jobs(every=True)
    if known is None or agent.runs(1) is None:
        return {"jobs": [], "runs": []}
    maintains = {op.get("maintained_by"): page for page, op in pages.items() if op.get("maintained_by")}
    arrivals = {job: "When something arrives" for job in handlers(known).values()}
    arrivals.update({job: f"When {store} changes" for store, job in (stores_handled or {}).items()})
    jobs = []
    names = {}
    watched = set()
    for job in known:
        names[job["id"]] = job["name"]
        found = {key: value for key, value in job.items() if key not in ("done", "paused")}
        if job.get("watching"):
            watched.add(job["id"])
        if job.get("done"):
            found["done"] = True
        elif job.get("paused"):
            found["paused"] = True
        if job["id"] in maintains:
            found["page"] = maintains[job["id"]]
        if job["id"] in arrivals:
            found.update(schedule=arrivals[job["id"]], next=None)
        jobs.append(found)
    shown = []
    for told in agent.runs(SCANNED_RUNS if watched else KEPT_RUNS):
        run = {**told, "name": names.get(told["job"], told["job"]), **runs.of(told["id"])}
        if run["status"] != "running":
            run.pop("doing")
        if run["job"] in watched and quiet(run):
            continue
        shown.append(run)
        if len(shown) == KEPT_RUNS:
            break
    runs.keep([run["id"] for run in shown])
    shown = sorted(shown + agent.delegated(), key=lambda run: run.get("started") or "", reverse=True)
    return {"jobs": jobs, "runs": shown}


def running(agent: Agent) -> list[tuple[str, str]]:
    return [(run["job"], run["id"]) for run in agent.runs(10) or [] if run["status"] == "running"]


def act(agent: Agent, job_id: str, action: str) -> str | None:
    """What he can do to a job from the app: run it now, pause it, resume it."""
    do = {"run": agent.run_job, "pause": agent.pause_job, "resume": agent.resume_job}.get(action)
    return do(job_id) if do else f"Unknown action {action}"

