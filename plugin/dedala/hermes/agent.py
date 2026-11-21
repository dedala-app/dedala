# SPDX-FileCopyrightText: 2026 Julien Malka
# SPDX-License-Identifier: MIT

"""Hermes as the agent the app's server serves (`agents.Agent`): its messages
through the platform adapter, its cron as the jobs, its vision model as the eye,
its subagents as background runs. Hermes runs cron jobs in the gateway, under a
task id `cron:<job>:<execution>`: the plugin's hooks see their tool calls and
stream like a conversation's."""

import logging
import threading
from datetime import datetime
from typing import Optional

from ..agents import Agent, Unavailable
from ..handlers import BUSY
from . import internals, vocabulary

logger = logging.getLogger(__name__)

# The plugin's context, once Hermes registered it: what seeds a topic's session with its brief.
context = None

KEPT_DELEGATIONS = 10
DELEGATION_STATUS = {"running": "running", "stalling": "running", "finalizing": "running", "completed": "ok"}
NO_CRON = "Hermes cron is not available here"


def run_of(task_id: str) -> tuple[str, str] | None:
    parts = (task_id or "").split(":")
    return (parts[1], parts[2]) if len(parts) == 3 and parts[0] == "cron" else None


def watching(job: dict) -> bool:
    """A job with a change detector (a monitor_script or monitor_url) checks often and runs
    the agent only when what it watches changed: it was updated then, and checked at its last tick."""
    return bool(job.get("monitor_script") or job.get("monitor_url"))


def last_update(job: dict) -> str | None:
    """When the job last ran the agent."""
    if watching(job) and (changed := (job.get("monitor_state") or {}).get("last_changed_at")):
        return changed
    return job.get("last_run_at")


def _job(job: dict, identifier: str | None = None) -> dict:
    identifier = job.get("id") or identifier
    found = {"id": identifier, "name": job.get("name") or identifier, "schedule": job.get("schedule_display") or "",
             "next": job.get("next_run_at"), "last": last_update(job), "status": job.get("last_status"),
             "silent": job.get("deliver") == "local"}
    if watching(job):
        found.update(watching=True, checked=job.get("last_run_at"))
    if job.get("last_error"):
        found["error"] = str(job["last_error"])[:200]
    if job.get("state") == "completed":
        found["done"] = True
    if job.get("state") == "paused" or not job.get("enabled", True):
        found["paused"] = True
    return found


def _status(execution: dict) -> str:
    if execution.get("status") in ("claimed", "running"):
        return "running"
    return "failed" if execution.get("status") == "failed" or execution.get("error") else "ok"


def _run(execution: dict) -> dict:
    run = {"id": execution["id"], "job": execution["job_id"], "started": execution.get("started_at") or execution.get("claimed_at"),
           "finished": execution.get("finished_at"), "status": _status(execution)}
    if execution.get("error"):
        run["error"] = str(execution["error"])[:200]
    return run


def _iso(stamp) -> str | None:
    return datetime.fromtimestamp(stamp).astimezone().isoformat(timespec="seconds") if stamp else None


def _goal(text: str) -> str:
    line = " ".join((text or "").split())
    return line if len(line) <= 90 else line[:89].rsplit(" ", 1)[0] + "…"


def _fire(execute, job_id: str) -> None:
    result = execute(job_id) or {}
    if not result.get("claimed") or result.get("error"):
        logger.warning("[app] job %s did not run: %s", job_id, result.get("error") or "not claimed")


class HermesAgent(Agent):
    def __init__(self, adapter=None):
        """`adapter` is the platform adapter, which hears for Hermes; without it (the tests of
        its cron) the agent has its jobs and its eye, and no ear."""
        self.adapter = adapter

    async def deliver(self, conversation: str, text: str, media: Optional[str | list[str]] = None, message_id: Optional[str] = None) -> None:
        await self.adapter.hear(conversation, text, media, message_id)

    async def stop(self, conversation: str) -> None:
        await self.deliver(conversation, "/stop")

    async def reset(self, conversation: str) -> None:
        await self.deliver(conversation, "/new")

    def seed(self, conversation: str, brief: str) -> bool:
        if context is None:
            return False
        origin = self.adapter.source_for(conversation).to_dict() if self.adapter else None
        return bool(context.inject_message(brief, role="user", origin=origin))

    def conversation(self) -> Optional[str]:
        if internals.session("HERMES_SESSION_PLATFORM") == "app":
            return internals.session("HERMES_SESSION_CHAT_ID") or "main"
        return None

    def describe(self, tool: str, args: dict) -> Optional[tuple[str, str]]:
        return vocabulary.describe(tool, args)

    def preparing(self, tool: str) -> Optional[str]:
        return vocabulary.preparing(tool)

    def jobs(self, every: bool = False) -> Optional[list[dict]]:
        cron = internals.cron()
        if cron is None:
            return None
        return [_job(job) for job in (cron.list_jobs(include_disabled=True) if every else cron.list_jobs())]

    def job(self, job: str) -> Optional[dict]:
        cron = internals.cron()
        found = cron.get_job(job) if cron is not None else None
        return _job(found, job) if found else None

    def runs(self, limit: int) -> Optional[list[dict]]:
        found = internals.executions(limit)
        return None if found is None else [_run(execution) for execution in found]

    def run_job(self, job: str) -> Optional[str]:
        """In a thread of its own, the way Hermes's webhooks fire one; at the cron ticker's next
        tick where that is missing. A change detector checks now, and runs the agent only if
        what it watches changed."""
        jobs = internals.cron()
        if jobs is None:
            return NO_CRON
        if not jobs.get_job(job):
            return f"No cron job {job}"
        execute = internals.execute_now()
        if execute is None:
            try:
                return None if jobs.trigger_job(job) else f"No cron job {job}"
            except ValueError as error:
                return str(error)
        threading.Thread(target=_fire, args=(execute, job), name=f"app-run-{job}", daemon=True).start()
        return None

    def run_job_with(self, job: str, prompt: str) -> Optional[str]:
        execute = internals.execute_now()
        if execute is None:
            jobs = internals.cron()
            if jobs is None:
                return NO_CRON
            return None if jobs.trigger_job(job, prompt) else f"No cron job {job}"
        result = execute(job, extra_prompt=prompt) or {}
        error = str(result.get("error") or "")
        if result.get("claimed"):
            return None if result.get("success", True) and not error else f"the run failed: {error or 'no reason given'}"
        return error if "not found" in error else BUSY

    def pause_job(self, job: str) -> Optional[str]:
        return self._switch(job, lambda cron: cron.pause_job(job, "paused in the app"))

    def resume_job(self, job: str) -> Optional[str]:
        return self._switch(job, lambda cron: cron.resume_job(job))

    @staticmethod
    def _switch(job: str, do) -> Optional[str]:
        cron = internals.cron()
        if cron is None:
            return NO_CRON
        try:
            return None if do(cron) else f"No cron job {job}"
        except ValueError as error:
            return str(error)

    def create_job(self, prompt: str, schedule: str, name: str) -> str:
        jobs = internals.cron()
        if jobs is None or not hasattr(jobs, "create_job"):
            raise Unavailable(NO_CRON)
        return jobs.create_job(prompt=prompt, schedule=schedule, name=name, deliver="local")["id"]

    def update_job(self, job: str, prompt: str) -> None:
        jobs = internals.cron()
        if jobs is not None and hasattr(jobs, "update_job"):
            jobs.update_job(job, {"prompt": prompt})

    def remove_job(self, job: str) -> None:
        jobs = internals.cron()
        if jobs is not None and hasattr(jobs, "remove_job"):
            jobs.remove_job(job)

    def job_result(self, job: str, since: float) -> Optional[str]:
        jobs = internals.cron()
        if jobs is None or not hasattr(jobs, "get_cron_output_dir"):
            return None
        folder = jobs.get_cron_output_dir() / job
        outputs = sorted((path for path in folder.glob("*.md") if path.stat().st_mtime >= since - 1), key=lambda path: path.stat().st_mtime)
        return outputs[-1].read_text(errors="replace").strip() if outputs else None

    def delegated(self) -> list[dict]:
        """What each set out to do, what its subagent does now, how it ended."""
        found = []
        for record in sorted(internals.delegations(), key=lambda record: record.get("dispatched_at") or 0, reverse=True)[:KEPT_DELEGATIONS]:
            status = DELEGATION_STATUS.get(record.get("status"), "failed")
            goals = record.get("goals") or [record.get("goal")]
            run = {"id": record.get("delegation_id"), "job": "delegation", "name": _goal(goals[0] or "Background task"),
                   "started": _iso(record.get("dispatched_at")), "finished": _iso(record.get("completed_at")),
                   "status": status, "steps": [], "tokens": 0, "background": True}
            if len(goals) > 1:
                run["name"] = f"{run['name']} (+{len(goals) - 1})"
            if status == "running":
                children = [child for child in record.get("children_activity") or [] if child]
                tool = next((child.get("current_tool") for child in children if child.get("current_tool")), None)
                calls = sum(child.get("api_calls") or 0 for child in children)
                run["doing"] = f"Using {tool}" if tool else "Thinking"
                if calls:
                    run["doing"] += f" · {calls} model calls"
            elif status == "failed":
                run["error"] = str(record.get("error") or record.get("status") or "failed")[:200]
            found.append(run)
        return found

    async def see(self, picture: str, question: str) -> str:
        return await internals.see(picture, question)
