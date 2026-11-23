# SPDX-FileCopyrightText: 2026 Julien Malka
# SPDX-License-Identifier: MIT

"""The app's server: everything the phone and the agent's tools talk to, whichever
agent it is. It holds the link to the phone and what the agent built there, turns
what you write, tap, share or change into messages for the agent or into work done
at once with no model, and shows the agent's turn as it happens.

The agent is an `agents.Agent`: the server asks it to hear a message, to run a
job, to look at a picture. What the agent says and does it tells the server:
`said` and `interim`, then the turn as it goes, `working`, `status`, `starting`,
`stepped`, `note_stream`, `rested`, and a job's run through `runs`.

`settings`: `inbox_port` and `inbox_secret` (where what arrives from outside is
posted, see inbox.py; no inbox without them), `inbox_host` (default every
address), `windmill_url` and `windmill_workspace` (for commands bound to a flow)."""

import asyncio
import json
import logging
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional

from .agents import Agent
from .background import Runs, quiet
from .bank import Cards, keep
from .activities import Activities
from .commands import Audit, Commands
from .files import Refused
from .stores import fingerprint
from .symbols import Symbols
from .fonts import Fonts
from . import profile, twin
from .handlers import Arrivals, Edits, Handlers, StoreChanged
from .inbox import TP7_PREFACE, Inbox, handlers, serve
from .link import Link
from .notices import notice
from .transition import EVERY, Preparation

logger = logging.getLogger(__name__)

DEFAULT_RELAY = "https://relay.dedala.app"

current: Optional["Server"] = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# How long arrivals from outside must stop before their handler runs: a burst
# of mail is one run. His edits already settled on the phone before they came.
SETTLE = 20
EDITS_SETTLE = 2
REST = 2.5


# Added to each message you write, where the agent reads it as it answers: a
# rule in the system prompt was not enough to make it draw instead of describe,
# nor to stop it retelling the card in text afterwards.
NUDGE = ("[app: if your answer has a shape - a score, a result, a place, a time, a choice, things to compare - "
         "draw it with app_card instead of writing it. The card is your answer: after it, at most one short line "
         "that adds something (a question, a next step); never retell it, and never tell him what you fixed. If he "
         "asks for a document or a note, hand him the document itself: a record with its file, given with app_data "
         "{id, record, say}]")


def _undrawn(undrawn: dict[str, list[str]]) -> str:
    """What the agent is told when he places a widget at a size it does not draw."""
    placed = "; ".join(f"{name} at {', '.join(sizes)}" for name, sizes in undrawn.items())
    return (f"[app: he placed widgets at sizes they do not draw: {placed}. Until they do, the widget shows that you are "
            "making it fit. Add those sizes to the widget's families with app_widget, the component varying its look with "
            "If on $family. Say it in one short line at most.]")


def _conversation_of(card: Optional[str]) -> str:
    spec = current.cards.get(card or "") if current else None
    return spec["conversation"] if spec else "main"


class Server:
    def __init__(self, home: Path, agent: Agent, name: str, token: str, relay: Optional[str] = None, settings: Optional[dict] = None):
        """`home` is where it keeps its state, `name` the agent's in the app, `token` the one
        the relay gave the agent for an invite."""
        settings = settings or {}
        self.agent = agent
        self.link = Link(home, relay or DEFAULT_RELAY, token, name)
        self.cards = Cards(home)
        twin.configure(home)
        self.symbols = Symbols(home)
        self.fonts = Fonts(home)
        self.commands = Commands(home, self.link.app.loaded, lambda name, record: self.link.app.write("command", name, record), self.link.stores,
                                 {"url": settings.get("windmill_url"), "workspace": settings.get("windmill_workspace")}, agent)
        self.activities = Activities(self.link.state, self.link._save, self.link.stores)
        self._overdue_told: Dict[str, float] = {}
        self._widget_stores: Dict[str, str] = {}
        self._woken = 0.0
        self._declared_sent: set = set(self.link.app.loaded["search"])
        self._unreadable: Dict[str, str] = {}
        self.link.on_event = self._event
        self.link.on_paired = self._paired
        self.link.on_online = self._app_online
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self._presence_sent: Dict[str, dict] = {}
        self._presence_at: Dict[str, float] = {}
        self._presence_now: Dict[str, dict] = {}
        self._resting: Dict[str, asyncio.Task] = {}
        self._turns: Dict[str, dict] = {}
        self._stepping = threading.Lock()
        self._upkeep_sent: Dict[str, dict] = {}
        self._refreshing: Dict[str, tuple] = {}
        self.runs = Runs(home)
        self._activity_sent: Optional[dict] = None
        self.running: list = []
        self._watching: Optional[asyncio.Task] = None
        self._last_chat = "main"
        self.inbox = Inbox(home)
        self._inbox_config = (settings.get("inbox_port"), str(settings.get("inbox_secret") or ""), settings.get("inbox_host") or None)
        self._inbox_server = None
        self.handlers = Handlers(self._run_handler)
        self.transition = Preparation(self.link, self.cards, self.commands)
        self._preparing: Optional[asyncio.Task] = None
        global current
        current = self

    async def start(self) -> None:
        self.loop = asyncio.get_running_loop()
        await self.link.start()
        self._watching = asyncio.create_task(self._watch_background())
        self._preparing = asyncio.create_task(self._keep_prepared())
        port, secret, host = self._inbox_config
        if port and secret:
            self._inbox_server = await serve(self, int(port), secret, host, lambda: self.link.app.loaded["tokens"])
        elif port:
            logger.error("[app] inbox_port without inbox_secret: no inbox")
        logger.info("[app] linked to %s, %s", self.link.relay, "paired" if self.link.identity.paired else "not paired yet")

    async def stop(self) -> None:
        """The agent is going: no turn will finish, so none is left showing as under way."""
        for chat in list(self._turns):
            self._turns.pop(chat, None)
            await self._presence(chat, {})
        if self._watching:
            self._watching.cancel()
        if self._preparing:
            self._preparing.cancel()
            await self.transition.prepare()
        self.handlers.stop()
        if self._inbox_server:
            await self._inbox_server.cleanup()
        await self.link.stop()

    def arrival_jobs(self) -> dict:
        """The jobs that handle arrivals, by source."""
        return handlers(self.agent.jobs() or [])

    async def said(self, conversation: str, text: str, aside: bool = False, meanwhile: bool = False) -> None:
        """What the agent says in a conversation. `aside` is not the agent talking but what
        runs it speaking for itself (a command's reply, a warning), drawn as an event;
        `meanwhile` is said while the turn goes on, which it leaves showing."""
        await self.link.send([{"op": "say", "conversation": conversation, **({"notice": notice(text)} if aside else {"text": text})}], notify=True)
        if not meanwhile:
            self._presence_sent.pop(conversation, None)

    def interim(self, conversation: str, line: str) -> None:
        """What the agent says between two steps ("Found it, filing it") is not a message:
        it becomes what it is doing."""
        self._turn(conversation)["said"] = line.splitlines()[0][:80] if line else None

    def _turn(self, chat_id: Optional[str]) -> dict:
        return self._turns.setdefault(str(chat_id or "main"),
                                      {"since": datetime.now(timezone.utc).isoformat(timespec="milliseconds"), "tokens": 0, "writing": None, "writing_symbol": None, "calls": {}, "status_symbol": None, "said": None})

    def status(self, conversation: str, symbol: Optional[str]) -> None:
        """The agent names the tool it runs in its own words, shown for a call `starting`
        gave no name (`working` is handed the words): this is its symbol. Called from the
        agent's threads."""
        if turn := self._turns.get(conversation):
            turn["writing"] = None
            turn["status_symbol"] = symbol

    def starting(self, chat_id: Optional[str], call: str, line: str, symbol: str) -> None:
        """A tool call about to run, named from its whole arguments: of those running at once the
        first begun is shown. Called from its worker thread."""
        if turn := self._turns.get(str(chat_id or "main")):
            with self._stepping:
                turn["calls"][call] = (line, symbol)

    def note_stream(self, characters: int, writing: Optional[str], symbol: Optional[str] = None) -> None:
        """What the model streams (reply, reasoning, a tool call's arguments), counted
        in tokens for the chat at work, with the symbol of the tool whose call it
        writes. Reasoning is counted and not named: between two steps the app
        keeps showing the last one. A call or a reply it writes means the calls before
        are over, whether or not their end was told. Called from the agent's threads."""
        if turn := self._turns.get(self._last_chat):
            turn["tokens"] += max(1, round(characters / 4))
            if writing:
                with self._stepping:
                    turn["calls"].clear()
                    turn["writing"] = writing
                    turn["writing_symbol"] = symbol

    def stepped(self, chat_id: Optional[str], call: str = "", step: Optional[dict] = None) -> None:
        """A tool call ended: what was said of it while it was written or run is over, and the step
        it leaves joins the others in the same moment, so that no view of the turn shows it twice
        or not at all. Called from its worker thread."""
        chat = str(chat_id or "main")
        with self._stepping:
            if turn := self._turns.get(chat):
                turn["calls"].pop(call, None)
                turn["writing"] = turn["said"] = None
            if step:
                self.link.add_step(chat, step)

    async def working(self, chat_id: str, status: Optional[Callable[[], Optional[str]]] = None) -> None:
        """The live view of a turn, refreshed by the agent every couple of seconds:
        the steps so far, said in the present while it lasts, what the agent is doing
        now if it has a name (a call it writes, a tool it runs, its reply), the tokens
        it wrote. `status` answers what the agent itself says it is doing, read with
        the rest so that a step is never shown both done and under way."""
        from .steps import present

        chat = str(chat_id or "main")
        self._last_chat = chat
        if resting := self._resting.pop(chat, None):
            resting.cancel()
        turn = self._turn(chat)
        with self._stepping:
            steps = [{**step, "text": present(step["text"])} for step in self.link.steps.get(chat, [])]
            said = (next(iter(turn["calls"].values()), (None, None)), (status() if status else None, turn["status_symbol"]),
                    (turn["writing"], turn["writing_symbol"]), (turn["said"], None))
        state = {"typing": True, "since": turn["since"], "tokens": turn["tokens"], "steps": steps}
        for doing, symbol in said:
            if doing:
                state["doing"] = doing[:80]
                if symbol:
                    state["symbol"] = symbol
                break
        await self._presence(chat, state)

    async def rested(self, chat_id: str) -> None:
        """The turn is over, unless another starts within REST seconds: Hermes can
        tell a turn's end after the one queued behind it has begun."""
        from .checks import release_held

        chat = str(chat_id or "main")
        self._turns.pop(chat, None)
        if resting := self._resting.pop(chat, None):
            resting.cancel()
        self._resting[chat] = asyncio.create_task(self._rest(chat))
        try:
            await release_held(chat)
        except Exception as error:
            logger.warning("[app] could not send the cards held back: %s", error)

    async def _rest(self, chat: str) -> None:
        await asyncio.sleep(REST)
        if self._resting.get(chat) is asyncio.current_task():
            del self._resting[chat]
        await self._presence(chat, {})

    async def _presence(self, chat_id: str, state: dict, again: bool = False) -> None:
        """What changes, and the same again every 10 seconds of a turn so the app
        knows it is still under way: it lets a silent one go after 30. Only what
        reached the app counts as sent; `again` sends it whatever was sent before."""
        chat = chat_id or "main"
        now = time.monotonic()
        if bool(state) != bool(self._presence_now.get(chat)):
            logger.info("[app] %s: %s", chat, "working" if state else "idle")
        self._presence_now[chat] = state
        if not again and self._presence_sent.get(chat, {}) == state and (not state or now - self._presence_at.get(chat, 0) < 10):
            return
        if not (self.link.app_online and self.link.identity.paired):
            return
        try:
            await self.link.send([{"op": "presence", "conversation": chat, **state}])
        except Exception as error:
            logger.debug("[app] presence not sent: %s", error)
            return
        self._presence_sent[chat] = state
        self._presence_at[chat] = now

    async def _watch_background(self) -> None:
        from .background import running

        while True:
            try:
                self.running = await asyncio.to_thread(running, self.agent)
                await self.sync_activity()
                await self.sync_upkeep()
                await self.sync_stores()
                await self.sync_app()
                await self.activities.sync(self.link)
                self._supervise_overdue()
            except Exception as error:
                logger.warning("[app] background work not synced: %r", error)
            await asyncio.sleep(2)

    async def _keep_prepared(self) -> None:
        """What the next contract needs of this one (transition.py), written
        at the start and again every ten minutes when what it reads changed."""
        await self.transition.prepare()
        while True:
            await asyncio.sleep(EVERY)
            await self.transition.prepare(changed=True)

    async def _app_online(self) -> None:
        """The app has what waited for it: everything it shows is sent again, then
        that it is in sync."""
        if not self.link.identity.paired:
            return
        try:
            self._upkeep_sent.clear()
            self._activity_sent = None
            await self.sync_upkeep()
            await self.sync_activity()
            self.link.stores_written()
            await self.link.send(self.link.unsent_define() + self.link.unsent_stores() + await self.link.unsent_attachments() + await self.link.send_parts() + [{"op": "synced"}], record=False)
            for chat, state in list(self._presence_now.items()):
                if state:
                    await self._presence(chat, state, again=True)
        except Exception as error:
            logger.warning("[app] the app could not be brought in sync: %s", error)

    async def sync_activity(self) -> None:
        """His jobs and their runs, sent to the app when they change: every couple
        of seconds while one runs, as it takes steps and writes."""
        from .background import snapshot

        if not (self.link.app_online and self.link.identity.paired):
            self._activity_sent = None
            return
        found = await asyncio.to_thread(snapshot, self.agent, self.runs, self.link.state.get("artifacts", {}).get("page", {}),
                                        self.link.app.loaded["triggers"].get("store") or {})
        if found != self._activity_sent:
            self._activity_sent = found
            await self.link.send([{"op": "background", **found}])

    async def sync_upkeep(self) -> None:
        """How each maintained page is kept up to date, sent to the app when it
        changes, and all again each time the app comes back."""
        from .maintenance import state

        if not (self.link.app_online and self.link.identity.paired):
            self._upkeep_sent.clear()
            return
        running = {job for job, _ in self.running}
        working = {job for job, execution in self.running if not quiet({"status": "running", **self.runs.of(execution)})}
        for page_id, op in list(self.link.state.get("artifacts", {}).get("page", {}).items()):
            job = op.get("maintained_by")
            if not job and page_id not in self._upkeep_sent:
                continue
            current = await asyncio.to_thread(state, self.agent, job) or {}
            if page_id in self._refreshing:
                before, since = self._refreshing[page_id]
                if (self._done(current) != before and job not in running) or time.time() - since > 900:
                    self._refreshing.pop(page_id)
                else:
                    current["refreshing"] = True
            if job in (working if current.get("watching") else running):
                current["refreshing"] = True
            if self._upkeep_sent.get(page_id) != current:
                self._upkeep_sent[page_id] = current
                await self.link.send([{"op": "upkeep", "page": page_id, **({"state": current} if current else {})}])

    @staticmethod
    def _done(upkeep: dict):
        """What changes once a refresh is over: a change detector's check, or a run."""
        return upkeep.get("checked") if upkeep.get("watching") else upkeep.get("last")

    async def _refresh(self, page_id: str) -> None:
        """He asked for a page to be brought up to date: its job runs at the next tick."""
        from .maintenance import state

        job = (self.link.state.get("artifacts", {}).get("page", {}).get(page_id) or {}).get("maintained_by")
        if not job:
            logger.info("[app] refresh asked for %s, which no job maintains", page_id)
            return
        before = self._done(await asyncio.to_thread(state, self.agent, job) or {})
        if error := await asyncio.to_thread(self.agent.run_job, job):
            logger.warning("[app] could not run %s for %s: %s", job, page_id, error)
        else:
            self._refreshing[page_id] = (before, time.time())
        self._upkeep_sent.pop(page_id, None)
        await self.sync_upkeep()

    async def _durable(self, event: dict, handle) -> None:
        """One guarantee for every event the phone sends until acknowledged:
        made once, answered in the ack with what settles it (the store as it
        stands, a command's outcome) or refused with why, and sent again
        answered the same way, never made twice."""
        identifier = event.get("id")
        if self.link.handled(identifier):
            answer, refusal = self.link.answer(identifier), self.link.refusal(identifier)
        else:
            self.link.handle(identifier)
            try:
                answer, refusal = await handle(event)
            except Exception as error:
                logger.warning("[app] the %s event %s broke: %r", event.get("kind"), identifier, error)
                answer, refusal = [], f"{type(error).__name__}: {error}"
            self.link.handle(identifier, refusal, answer)
        if not identifier:
            return
        acked = {"op": "acked", "ids": [identifier]}
        if refusal:
            acked["failed"] = {identifier: refusal}
        if answer:
            acked["answers"] = {identifier: answer}
        await self.link.send([acked], record=False)

    async def _edited(self, event: dict) -> tuple[List[dict], Optional[str]]:
        """He changed things on the phone: the files follow, each store he
        changed goes back as its file now holds it, and the jobs handling the
        pages touched run, in sessions of their own, until they have handled
        every change. A photo he took travels as blobs and lands as an
        attachment. No conversation hears of it unless a job says so, but for
        the agent's name and face (profile.py)."""
        await self._fetch_photos(event)
        before = self.link.stores.held.get(profile.STORE)
        jobs = self.link.edited(event)
        if any(change.get("store") == profile.STORE for change in event.get("changes") or []):
            if said := profile.told(before, self.link.stores.held.get(profile.STORE)):
                await self._deliver("main", said)
        touched = dict.fromkeys(change["store"] for change in event.get("changes") or [] if change.get("store"))
        logger.info("[app] %d edits from the phone; handled by %s", len(event.get("changes") or []), jobs or "no job")
        for job in jobs:
            self.link.follow_changes(job)
            self.handlers.trigger(job, Edits(self.link, job), EDITS_SETTLE)
        return [self.link.stores.op(name) for name in touched if name in self.link.stores.held], None

    def _run_handler(self, job: str, prompt: str) -> Optional[str]:
        return self.agent.run_job_with(job, prompt)

    async def _fetch_photos(self, event: dict) -> None:
        """A field of a change whose value is `{blobs, name, …}` is a file he
        picked on the phone: fetched, kept under attachments, and the field
        becomes that path."""
        from .state import safe

        for change in event.get("changes") or []:
            store = change.get("store")
            fields = change.get("add") if isinstance(change.get("add"), dict) else change.get("patch") if isinstance(change.get("patch"), dict) else None
            if not store or not fields:
                continue
            record = change.get("id") or (fields.get("id") if "add" in change else None) or "store"
            for key, value in list(fields.items()):
                if not (isinstance(value, dict) and isinstance(value.get("blobs"), list)):
                    continue
                parts = [await self.link.blob(blob) for blob in value["blobs"]]
                folder = self.link.home / "attachments" / safe(store) / safe(str(record))
                name = safe(str(value.get("name") or "file"))
                if any(part is None for part in parts):
                    logger.warning("[app] the file %s he sent for %s/%s is gone from the relay", name, store, record)
                    fields[key] = None
                    continue
                folder.mkdir(parents=True, exist_ok=True)
                path = folder / name
                path.write_bytes(b"".join(parts))
                fields[key] = str(path)

    async def write_store(self, name: str, body: dict) -> Optional[str]:
        """A program off this machine writes a store through the inbox: the
        reason when it cannot."""
        if not name or not isinstance(body, dict) or not any(key in body for key in ("data", "patch")):
            return "body is {\"data\": value} or {\"patch\": {…}}"
        if self.link.stores.kind(name) is not None:
            return f"the store {name} is a {self.link.stores.kind(name)} store: write its file"
        try:
            if "data" in body:
                self.link.store(name, body["data"])
            else:
                self.link.stores.change(name, {"store": name, "patch": body["patch"]})
                self.link._mirror([name])
                self.link._stores_sent([name])
        except Refused as refusal:
            return str(refusal)
        if self.link.identity.paired and self.link.app_online:
            await self.link.send([self.link.stores.op(name)] if name in self.link.stores.held else [{"op": "store", "id": name, "data": None}], record=False)
        return None

    async def _fetch(self, event: dict) -> tuple[List[dict], Optional[str]]:
        """The phone asks for a record's file: queued, its parts follow."""
        return [], self.link.fetch(event.get("store") or "", event.get("record") or "")

    async def _file_edit(self, event: dict) -> tuple[List[dict], Optional[str]]:
        """An edit he made on the phone to a text store, or to a file of a
        folder store: made to the file at once; the store as it now stands
        answers it. An edit the file can no longer take is refused with the
        reason; a file that cannot be written also tells the agent."""
        store, record, change = event.get("store") or "", event.get("record"), event.get("edit") or {}
        refusal, made = await self._edit_file(store, record, change, event)
        return self._store_back(store, record, made), refusal

    async def _edit_file(self, store: str, record: Optional[str], change: dict, event: dict) -> tuple[Optional[str], Optional[str]]:
        """Makes his edit to the file; the reason when it could not be made,
        and the id of a file made."""
        if store not in self.link.stores.links:
            return f"No text store is linked as {store}", None
        try:
            made = await asyncio.to_thread(self.link.stores.apply_edit, store, record, change)
        except Refused as refusal:
            return str(refusal), None
        except Exception as error:
            logger.warning("[app] his edit to %s could not be written: %r", store, error)
            await self._deliver("main", f"[app: his edit to the store {store} ({change}) could not be written: {error}. "
                                        "Find out why and fix it; tell him only if he must act]")
            return f"Could not write the file: {getattr(error, 'strerror', None) or error}", None
        self.link.log_edits({"at": event.get("at"), "changes": [{"store": store, **({"id": record} if record else {}), "edit": change,
                                                                "from": event.get("from") or ""}]})
        return None, made

    def _store_back(self, store: str, record: Optional[str], made: Optional[str]) -> List[dict]:
        """The store as it stands after an edit, for the phone: whole for a
        text store, the file's record for a folder store."""
        self.link.stores_written()
        if store not in self.link.stores.held:
            return []
        if self.link.stores.kind(store) == "folder":
            identifier = made or record
            if identifier is None:
                return []
            self.link._stores_sent([store])
            return [self.link.stores.record_op(store, identifier)]
        self.link._stores_sent([store])
        return [self.link.stores.op(store)]

    async def _command(self, event: dict) -> tuple[List[dict], Optional[str]]:
        """He tapped a command: it runs here, now, with no model; its outcome
        and the stores it wrote answer the tap."""
        name = event.get("name") or ""
        record = self.commands.get(name)
        if record is None:
            refusal = f"No command named {name}"
            await self._deliver("main", f"[app: he tapped the command {name!r} on {event.get('from') or 'a page'} and no command by that name "
                                        "is defined. Define it with app_command, or fix the page.]")
            return [{"op": "command", "name": name, "status": "failed", "error": refusal, "at": _now()}], refusal
        if self.commands.running(name):
            return [], "Already running"
        entry = await asyncio.to_thread(self.commands.run, record, event.get("args"), event.get("from") or "", event.get("id"), self._run_handler)
        self.link.stores_written()
        written = [self.link.stores.op(store) for store in entry.get("wrote") or [] if store in self.link.stores.held]
        self.link._stores_sent([store for store in entry.get("wrote") or [] if store in self.link.stores.held])
        self._supervise(record, self.commands.signal(record, entry))
        return written + [self.commands.op(entry)], entry.get("error") if entry.get("status") == "failed" else None

    def _supervise(self, record: dict, why: Optional[str]) -> None:
        """The command's supervisor looks at the runs since it last did, for this reason."""
        if not why:
            return
        job = record.get("supervised_by")
        if not job:
            logger.info("[app] the command %s has no supervisor to wake: %s", record["id"], why)
            return
        self.handlers.trigger(job, Audit(self.commands, record["id"], why), EDITS_SETTLE)

    def _supervise_overdue(self) -> None:
        for name, record in list(self.commands.records.items()):
            if self.commands.overdue(record) and time.time() - self._overdue_told.get(name, 0) > 3600:
                self._overdue_told[name] = time.time()
                self._supervise(record, "a day of runs you have not looked at")

    def _runs_told(self) -> str:
        """The commands he ran since his last message, for the agent's context."""
        told = self.commands.told(self.link.state.get("runs_told"))
        self.link.state["runs_told"] = _now()
        self.link._save()
        return f"\n\n[app: commands he ran since your last message: {'; '.join(told)}]" if told else ""

    async def arrived(self, source: str, payload: dict, identifier: Optional[str]) -> Optional[dict]:
        """Something arrived from outside: kept, then handled once its source
        settles by the job named after it, else by the main conversation."""
        item = await asyncio.to_thread(self.inbox.arrive, source, payload, identifier)
        if item is None:
            return None
        logger.info("[app] %s arrived from %s", item["id"], source)
        found = await asyncio.to_thread(self.arrival_jobs)
        job = found.get(source) or found.get("*")
        if job is None:
            title = f' "{item["title"]}"' if item.get("title") else ""
            await self._deliver("main", f"[app: something arrived from {source}{title}. Read it with app_events. "
                                        f"No job handles {source}: name one inbox/{source}, or inbox for every source, "
                                        "and it handles the next ones in a session of its own]")
            return item
        self.handlers.trigger(job, Arrivals(self.inbox, job, self.arrival_jobs), SETTLE)
        return item

    async def notify(self, op: dict) -> Optional[str]:
        """Rings the phone with a line of its own, from the agent or from a
        program through the inbox: the reason when it cannot."""
        from .checks import notify_buttons_problem, notify_problem

        artifacts = self.link.state.get("artifacts", {})
        if problem := notify_problem(op, artifacts, self.link.state.get("topics", {})) or notify_buttons_problem(op, artifacts):
            return problem
        try:
            await self.link.send([{"op": "notify", **{key: op[key] for key in ("title", "body", "open", "collapse", "kind", "actions") if op.get(key) is not None}}],
                                 notify=True, record=False, collapse=op.get("collapse"), ring=True)
        except Exception as error:
            return f"could not notify: {error}"
        return None

    async def forward(self, source: str, conversation: str) -> int:
        """What arrived from a source, put in a conversation as his own words,
        as if he had written it there: his voice notes."""
        from .checks import new_turn

        items = await asyncio.to_thread(self.inbox.take, source)
        for item in items:
            text = self.inbox.text(item).strip()
            if not text:
                continue
            preface = item.get("preface") or (TP7_PREFACE if source == "tp7" else "")
            new_turn()
            await self.link.send([{"op": "say", "conversation": conversation, "id": f"in-{source}-{item['id']}", "from": "you", "text": text}])
            await self._deliver(conversation, f"{preface}\n\n{text}\n\n{NUDGE}" if preface else f"{text}\n\n{NUDGE}")
        return len(items)

    async def sync_app(self) -> None:
        """What was written to the app's files from outside (an editor, a
        program, git) reaches the phone: checked as a tool call is, and told
        to the agent instead when it would not draw."""
        from .checks import check_file

        app = self.link.app
        moved = await asyncio.to_thread(app.scan)
        for key, why in list(app.unreadable.items()):
            if self._unreadable.get(f"app/{key}") != why:
                self._unreadable[f"app/{key}"] = why
                await self._deliver("main", f"[app: the app file {why}. The phone keeps what it had; fix the file.]")
        for key in [key for key in self._unreadable if key.startswith("app/") and key[4:] not in app.unreadable]:
            del self._unreadable[key]
        if not moved:
            return
        ops = []
        for kind, name in moved:
            if kind == "command":
                record = app.loaded["command"].get(name)
                if record is not None:
                    record.setdefault("id", name)
                    if record.get("supervised_by"):
                        from .commands import update_supervisor

                        await asyncio.to_thread(update_supervisor, self.agent, record["supervised_by"], self.commands.supervisor_prompt(record))
                continue
            if kind == "search":
                ops += [op for store in self.link.stores.held if store in app.loaded["search"] or store in self._declared_sent for op in self.link.stores.ops(store)]
                self._declared_sent = set(app.loaded["search"])
                continue
            op = app.op(kind, name)
            if op is None:
                continue
            if problems := check_file(op, app.loaded):
                where = str(app.path(kind, name).relative_to(app.home))
                await self._deliver("main", f"[app: {where} changed and would not draw on his phone, so it was not sent; the phone keeps the previous one. "
                                            f"Problems: {json.dumps(problems, ensure_ascii=False)}. Fix the file.]")
                continue
            ops.append(op)
        if ops and self.link.identity.paired:
            try:
                await self.link.send(ops, record=False)
            except Exception as error:
                logger.warning("[app] what changed in the app's files could not be sent: %s", error)
        if any(kind in ("components", "scripts") for kind, _ in moved):
            self.link.state.pop("defined_sent", None)

    async def sync_stores(self) -> None:
        """What was written to the store files here reaches the phone, when it
        is open; closed, it gets them as they stand when it comes back. A file
        that can no longer be read is told to the agent, once. A store with a
        handler job wakes it."""
        moved = self.link.stores.scan()
        self.link._mirror(moved)
        for name in moved:
            if job := (self.link.app.loaded["triggers"].get("store") or {}).get(name):
                self.handlers.trigger(job, StoreChanged(self.link, name, job), EDITS_SETTLE)
        unreadable = dict(self.link.stores.unreadable)
        for name, why in unreadable.items():
            if self._unreadable.get(name) != why:
                await self._deliver("main", f"[app: the store file {self.link.stores.path(name)} cannot be read: {why}. The store {name} keeps "
                                            "what it last held, and so do the pages that read it. Fix the file, or what writes it: "
                                            "a file is written whole, to a temporary file renamed over it.]")
        self._unreadable = unreadable
        if self.link.identity.paired and self.link.app_online:
            parts = []
            try:
                parts = await self.link.send_parts()
            except Exception as error:
                logger.warning("[app] a file's part could not go: %r", error)
            if ops := self.link.unsent_stores() + await self.link.unsent_attachments() + parts:
                await self.link.send(ops, record=False)
        await self._wake_widgets()

    # Widgets are redrawn by the app: closed, it is woken by a silent push when
    # a store a widget shows changed, at most this often.
    WAKE_EVERY = 300

    async def _wake_widgets(self) -> None:
        if not self.link.identity.paired or self.link.app_online:
            return
        watched = {widget["store"] for widget in self.link.state["artifacts"].get("widget", {}).values() if widget.get("store")}
        current = {name: fingerprint(self.link.stores.held[name]) for name in watched if name in self.link.stores.held}
        if current != {name: print_ for name, print_ in self._widget_stores.items() if name in current} or set(current) != set(self._widget_stores):
            changed = self._widget_stores and current != self._widget_stores
            self._widget_stores = current
            if changed and time.time() - self._woken > self.WAKE_EVERY:
                self._woken = time.time()
                try:
                    await self.link.wake()
                except Exception as error:
                    logger.debug("[app] could not wake the app for its widgets: %s", error)

    async def _job(self, job: str, action: str) -> None:
        """He ran, paused or resumed one of the agent's jobs from Activity."""
        from .background import act

        if error := await asyncio.to_thread(act, self.agent, job, action):
            logger.warning("[app] could not %s job %s: %s", action, job, error)
        await self.sync_activity()

    def _sent(self, event: dict) -> bool:
        """Whether the agent drew what the phone reports on: a card drawn by hand
        over USB is not his to fix."""
        if event.get("card"):
            return self.cards.get(event["card"]) is not None
        return event.get("page") in self.link.state.get("artifacts", {}).get("page", {})

    async def _deliver(self, conversation: str, text: str, media: Optional[str | List[str]] = None, message_id: Optional[str] = None) -> None:
        """Gives the agent something in a conversation; a topic's first message
        brings the brief its session could not be given when it opened."""
        if not text.startswith("/") and (brief := self.link.state.get("briefs", {}).pop(conversation, None)):
            self.link._save()
            text = f"[app: the brief this topic was opened with: {brief}]\n\n{text}"
        await self.agent.deliver(conversation, text, media, message_id)

    async def _share(self, event: dict) -> tuple[List[dict], Optional[str]]:
        """Something he shared from another app, with a note: kept, shown in
        the app as his message, then given to the agent as his."""
        from . import shares
        from .checks import new_turn

        kept = await shares.keep(self.link.home / "shared", event, self.link.blob)
        if kept is None:
            return [], "The share's files are gone from the relay"
        conversation = kept["conversation"]
        new_turn()
        self.link.steps.pop(conversation, None)
        said = {"op": "say", "conversation": conversation, "id": f"share-{kept['id']}", "from": "you",
                "text": kept["text"], "share": kept["id"], "shared": shares.shown(kept)}
        await self._deliver(conversation, f"{shares.told(kept)}\n\n{NUDGE}", media=shares.images(kept))
        return [said], None

    async def _event(self, event: dict) -> None:
        """Turns what the app sends into messages from you, in the conversation it came from."""
        kind = event.get("kind")
        conversation = event.get("conversation") or "main"
        if kind in ("message", "action", "flag"):
            from .checks import new_turn

            new_turn()
        if kind == "message":
            self.link.steps.pop(conversation, None)
            text = event.get("text", "")
            self.link.journal.yours(conversation, text, event.get("yours"), event.get("at"))
            await self._deliver(conversation, text if text.startswith("/") else f"{text}{self._runs_told()}\n\n{NUDGE}")
        elif kind == "share":
            await self._durable(event, self._share)
        elif kind == "action":
            payload = json.dumps(event.get("payload"), ensure_ascii=False)
            where = f"card {event['message']}" if event.get("message") else f"page {event.get('page')}"
            said = event.get("say")
            if said:
                self.link.journal.yours(conversation, said, event.get("yours"), event.get("at"))
            if event.get("message"):
                self.link.journal.add({"op": "answered", "message": event["message"], "at": event.get("at")})
            await self._deliver(conversation, f"{said}\n\n[app: tapped on {where}, payload {payload}]" if said else f"[app: tapped on {where}, payload {payload}]")
        elif kind == "flag":
            self.link.journal.yours(conversation, "This one looks off.", event.get("yours"), event.get("at"))
            report = {key: value for key, value in event.items() if key not in ("kind", "capture")}
            await self._deliver(conversation, f"This card looks off.\n\n[app: render report {json.dumps(report, ensure_ascii=False)}]", media=event.get("capture"))
        elif kind == "refresh":
            await self._refresh(event.get("page") or "")
        elif kind in ("edits", "file", "command", "fetch"):
            await self._durable(event, {"edits": self._edited, "file": self._file_edit, "command": self._command, "fetch": self._fetch}[kind])
        elif kind == "job":
            await self._job(event.get("job") or "", event.get("action") or "")
        elif kind == "loved":
            card = event.get("card") or ""
            self.link.journal.add({"op": "loved", "message": card})
            spec = {**(self.cards.get(card) or {}), **{key: event[key] for key in ("text", "view", "data") if key in event}}
            if isinstance(event.get("capture"), str):
                spec["capture"] = event["capture"]
            self.cards.loved(card, {**spec, "conversation": conversation})
            path = keep(self.link.home, card, spec, "", "loved in the app")
            await self._deliver(conversation, f"[app: he loved card {card}; it is in your card bank as {path.name}. If you "
                                              "know what he liked in it, add it with app_card {id, keep: true, note}. Answer in one "
                                              "short line at most.]")
        elif kind == "activity-report":
            report = {key: value for key, value in event.items() if key not in ("kind", "captures")}
            await self._deliver("main", f"[app: a Live Activity did not fit when the phone drew it: {json.dumps(report, ensure_ascii=False)}]")
        elif kind == "stop":
            await self.agent.stop(conversation)
        elif kind == "arrangement":
            self.link.arranged(event)
        elif kind == "widgets":
            if undrawn := self.link.placed(event.get("placed") or {}):
                await self._deliver("main", _undrawn(undrawn))
        elif kind == "display":
            self.link.state["display"] = {key: value for key, value in event.items() if key != "kind"}
            display = self.link.state["display"]
            await self._measure(self.fonts.display(display) + self.symbols.display(display, self.link.state.get("artifacts") or {}))
        elif kind == "symbols":
            self.symbols.received(event)
        elif kind == "fonts":
            await self.fonts.received(event, self.link.blob)
        elif kind == "rendered" and not event.get("awaited") and (event.get("issues") or event.get("diagnostics")) and self._sent(event):
            report = {key: value for key, value in event.items() if key not in ("kind", "capture", "awaited")}
            spec = self.cards.get(event["card"]) if event.get("card") else self.link.state.get("artifacts", {}).get("page", {}).get(event.get("page"))
            self._missed(spec, report)
            if self.link.redrawn(event):
                return
            what, fix = (f"card {event.get('card')}", "app_patch") if event.get("card") else (f"page {event.get('page')}", "app_page")
            what += " and found problems the check before sending missed"
            await self._deliver(_conversation_of(event.get("card")),
                                f"[app: the phone drew {what}: {json.dumps(report, ensure_ascii=False)}. Fix it with {fix} on that id.]",
                                media=event.get("capture") if isinstance(event.get("capture"), str) else None)
        elif kind == "failed":
            await self._failed(event)
        elif kind == "errors" and event.get("errors"):
            await self._deliver(conversation, f"[app: ops you sent failed when the phone applied them: "
                                              f"{json.dumps(event['errors'], ensure_ascii=False)}. Send them again, fixed.]")

    async def measure_wanted(self) -> None:
        """Asks the phone for the symbols the twin just met unmeasured."""
        await self._measure(self.symbols.wanted())

    async def _measure(self, ops: list[dict]) -> None:
        if not ops or not self.link.identity.paired:
            return
        try:
            await self.link.send(ops, record=False)
        except Exception as error:
            logger.warning("[app] could not ask the phone for the twin's fonts and symbols: %s", error)

    async def _failed(self, event: dict) -> None:
        """An action he ran that could not do what it says: he saw nothing
        happen, and the agent is told where and why, in the card's conversation."""
        if event.get("card"):
            where, fix = f"card {event['card']}", "app_patch on that id"
        else:
            where, fix = f"page {event.get('page')}", "app_page on that id"
        did = f"tapped \"{event['tapped']}\" on {where}" if event.get("tapped") else f"used {where}"
        await self._deliver(_conversation_of(event.get("card")),
                            f"[app: he {did} and nothing happened: {event.get('problem')}. Fix it with {fix}, then tell him "
                            "in one short line that it works now.]")

    def _missed(self, spec: dict | None, report: dict) -> None:
        """A card or page the twin passed and the phone found problems in: kept to correct the twin with."""
        line = {"spec": spec, "display": self.link.state.get("display"), "report": report}
        try:
            with open(self.link.home / "twin-misses.jsonl", "a") as out:
                out.write(json.dumps(line, ensure_ascii=False) + "\n")
        except OSError as error:
            logger.warning("[app] could not keep the twin's miss: %s", error)

    async def _paired(self) -> None:
        """A new phone: the app becomes home, and the main conversation starts a
        new session unless it has a history the phone was just given back. The
        Live Activities that were running start again on it."""
        if self.link.journal.empty:
            logger.info("[app] new phone paired; starting a new session in main")
            await self.agent.reset("main")
        else:
            logger.info("[app] phone paired again; the conversations are sent back and the session goes on")
        await self.activities.restart(self.link)
