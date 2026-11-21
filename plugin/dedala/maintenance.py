# SPDX-FileCopyrightText: 2026 Julien Malka
# SPDX-License-Identifier: MIT

"""Pages kept up to date by a job of the agent's: the agent creates the job and
links it to the page; the plugin only reads the job's state for the app and
runs it when he asks ("Refresh now"). A job with a change detector checks often
and runs the agent only when what it watches changed: it was updated then, and
checked at its last tick."""

from .agents import Agent


def state(agent: Agent, job_id: str | None) -> dict | None:
    """What the app shows about a page's upkeep: when it last ran and how, when next."""
    if not job_id:
        return None
    job = agent.job(job_id)
    if not job:
        return {"job": job_id, "missing": True}
    found = {"job": job_id, "schedule": job["schedule"], "last": job["last"], "next": job["next"], "status": job["status"]}
    found.update({key: job[key] for key in ("watching", "checked", "error", "paused") if key in job})
    return found
