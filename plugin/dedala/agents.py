# SPDX-FileCopyrightText: 2026 Julien Malka
# SPDX-License-Identifier: MIT

"""The agent the app's server serves, as far as the server can tell. Everything
the server asks of an agent goes through `Agent`; what an agent tells the
server (what it said, the calls it makes, the tools it runs) it tells
`server.Server`. Nothing else in the plugin knows which agent this is: the
one for Hermes is `hermes/`.

An agent that can only talk takes messages and nothing more: each other
method says here what the app shows without it."""

from typing import Optional


class Unavailable(RuntimeError):
    """The agent has no such part (no scheduler, no eye): said in its own words."""


class Agent:
    async def deliver(self, conversation: str, text: str, media: Optional[str | list[str]] = None, message_id: Optional[str] = None) -> None:
        """A message in a conversation, as the user's: his words, or what the app tells the agent
        in his place (`[app: …]`), with the pictures that go with it. Each conversation is a
        session of its own."""
        raise NotImplementedError

    async def stop(self, conversation: str) -> None:
        """He stopped what the agent was doing there."""
        raise NotImplementedError

    async def reset(self, conversation: str) -> None:
        """The conversation starts again from nothing."""
        raise NotImplementedError

    def seed(self, conversation: str, brief: str) -> bool:
        """Puts a brief in a conversation's session without a turn; False where the agent cannot."""
        return False

    def conversation(self) -> Optional[str]:
        """The conversation of the tool call under way; None outside the app's conversations."""
        return None

    # Its own tools, in words

    def describe(self, tool: str, args: dict) -> Optional[tuple[str, str]]:
        """(line, SF Symbol) for a call of one of the agent's own tools once made ("Read notes.org"),
        None for its bookkeeping."""
        return f"Used {tool}", "wrench.and.screwdriver"

    def preparing(self, tool: str) -> Optional[str]:
        """What the agent is doing while the model writes a call of one of its own tools."""
        return None

    # Its jobs: what it does on its own, on a schedule or when asked. Without them the
    # app's Activity is empty and no page, store, source or command has a job behind it.

    def jobs(self, every: bool = False) -> Optional[list[dict]]:
        """The jobs, those switched off too with `every`: `{id, name, schedule, next, last,
        status, silent}` with `watching` and `checked` for one that wakes the agent only when
        what it watches changed, `error`, `paused`, `done`. None where there is no scheduler."""
        return None

    def job(self, job: str) -> Optional[dict]:
        """One job as `jobs` gives it, None when there is none by that id."""
        return None

    def runs(self, limit: int) -> Optional[list[dict]]:
        """The last runs of jobs, newest first: `{id, job, started, finished, status}` with
        `status` running, ok or failed, and `error`. None where there is no scheduler."""
        return None

    def run_job(self, job: str) -> Optional[str]:
        """Runs a job now without waiting for it; why not when it cannot."""
        return "This agent has no jobs"

    def run_job_with(self, job: str, prompt: str) -> Optional[str]:
        """Runs a job now and waits for it, `prompt` added to this run only: None when it ended
        well, `handlers.BUSY` when it is already running, else why it did not run or how it failed."""
        return "This agent has no jobs"

    def pause_job(self, job: str) -> Optional[str]:
        return "This agent has no jobs"

    def resume_job(self, job: str) -> Optional[str]:
        return "This agent has no jobs"

    def create_job(self, prompt: str, schedule: str, name: str) -> str:
        """A job that reports to no one, for the server's own use; its id. `Unavailable` where
        there is no scheduler."""
        raise Unavailable("This agent has no jobs")

    def update_job(self, job: str, prompt: str) -> None:
        return None

    def remove_job(self, job: str) -> None:
        return None

    def job_result(self, job: str, since: float) -> Optional[str]:
        """What the job's last run since then answered, when the agent keeps it."""
        return None

    def delegated(self) -> list[dict]:
        """The work handed to subagents in the background, as runs (`{id, job: "delegation",
        name, started, finished, status, steps, tokens, background, doing, error}`)."""
        return []

    # Its eye

    async def see(self, picture: str, question: str) -> str:
        """What the agent's vision model answers about a picture. `Unavailable` without one:
        cards and pages leave without a review."""
        raise Unavailable("This agent has no vision model")
