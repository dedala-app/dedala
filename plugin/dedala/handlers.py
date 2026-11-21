# SPDX-FileCopyrightText: 2026 Julien Malka
# SPDX-License-Identifier: MIT

"""The jobs that handle what happens without him writing: what he changed on
the phone, what arrived from outside. One rule for both: the job runs once
things settle, again for what came while it ran, and what it was given only
counts as handled when its run ends well. A run that fails, or that a restart
cuts, is given the same again."""

import asyncio
import logging
from typing import Callable, Optional, Protocol

logger = logging.getLogger(__name__)

# A handler job already running: its run is asked for again later, for an hour.
BUSY = "busy"
BUSY_TRIES = 60
BUSY_WAIT = 60


class Pending(Protocol):
    """What waits for a job."""

    def claim(self) -> Optional[str]:
        """Gives the job what waits now: the prompt for its run, or None when nothing waits."""

    def settle(self, handled: bool) -> None:
        """The run ended: what it was given is handled, or waits again."""


class Handlers:
    def __init__(self, run: Callable[[str, str], Optional[str]]):
        """`run(job, prompt)` runs a job and waits for it: None when it ended
        well, BUSY when it is already running, else why it did not."""
        self.run = run
        self._settling: dict[str, asyncio.Task] = {}
        self._running: set[str] = set()

    def trigger(self, job: str, pending: Pending, settle: float) -> None:
        """Something happened for this job. Only a job still waiting for things
        to settle is put off by it; one already running picks it up when it ends."""
        if task := self._settling.get(job):
            task.cancel()
        self._settling[job] = asyncio.create_task(self._handle(job, pending, settle))

    def stop(self) -> None:
        for task in self._settling.values():
            task.cancel()

    async def _handle(self, job: str, pending: Pending, settle: float) -> None:
        await asyncio.sleep(settle)
        if self._settling.get(job) is asyncio.current_task():
            self._settling.pop(job)
        if job in self._running:
            return
        self._running.add(job)
        try:
            while (prompt := await asyncio.to_thread(pending.claim)) is not None:
                error: Optional[str] = BUSY
                for _ in range(BUSY_TRIES):
                    error = await asyncio.to_thread(self.run, job, prompt)
                    if error != BUSY:
                        break
                    await asyncio.sleep(BUSY_WAIT)
                await asyncio.to_thread(pending.settle, error is None)
                if error:
                    logger.warning("[app] the handler %s did not handle what it was given, which waits for its next run: %s", job, error)
                    return
        finally:
            self._running.discard(job)


class Arrivals:
    """What arrived from outside for the job that handles its source."""

    def __init__(self, inbox, job: str, handlers: Callable[[], dict]):
        self.inbox = inbox
        self.job = job
        self.handlers = handlers
        self.after: Optional[str] = None
        self.token: Optional[str] = None

    def claim(self) -> Optional[str]:
        from .inbox import handled_by, now

        waiting = {item["source"] for item in self.inbox.unread(None, self.after)}
        sources = handled_by(self.handlers(), self.job, waiting)
        if not sources:
            return None
        self.after = now()
        self.token = self.inbox.give(sources)
        return f"New in the inbox from {', '.join(sources)}: read each with app_events and its source."

    def settle(self, handled: bool) -> None:
        if self.token:
            self.inbox.settle(self.token, handled)


class Edits:
    """What he changed on the phone for the job that handles it."""

    def __init__(self, link, job: str):
        self.link = link
        self.job = job
        self.upto = 0

    def claim(self) -> Optional[str]:
        after, self.upto = self.link.unhandled_changes(self.job)
        if self.upto <= after:
            return None
        return (f"He changed things on the phone: read them with app_events {{\"after\": {after}}} and act on them. "
                "Write to him only if something needs him.")

    def settle(self, handled: bool) -> None:
        if handled:
            self.link.handled_changes(self.job, self.upto)


class StoreChanged:
    """A store whose file was written from outside, for the job that handles it."""

    def __init__(self, link, store: str, job: str):
        self.link = link
        self.store = store
        self.job = job
        self._seen = None

    def claim(self) -> Optional[str]:
        from .stores import fingerprint

        current = fingerprint(self.link.stores.held.get(self.store))
        handled = self.link.state.setdefault("stores_handled", {}).get(self.job)
        if current == handled or current == self._seen:
            return None
        self._seen = current
        return (f"The store {self.store} was written on disk, by a program or by hand: read it with app_data {{\"id\": \"{self.store}\"}} "
                "and act on what changed. Write to him only if something needs him.")

    def settle(self, handled: bool) -> None:
        if handled and self._seen is not None:
            self.link.state.setdefault("stores_handled", {})[self.job] = self._seen
            self.link._save()
