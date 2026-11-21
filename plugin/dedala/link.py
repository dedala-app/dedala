# SPDX-FileCopyrightText: 2026 Julien Malka
# SPDX-License-Identifier: MIT

"""The agent's end of the relay (docs/relay.md), with nothing of Hermes in it so
it can be tested on its own: keys, numbered sealed ops out, events in, Live
Activity channels, and the record of what the agent built and what was said
so a newly paired phone gets it back."""

import asyncio
import base64
import contextlib
import fcntl
import itertools
import json
import logging
import os
import secrets
import time
from pathlib import Path
from typing import Awaitable, Callable, Optional

import aiohttp
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

from . import seal
from .grammar import removed
from .files import Refused
from .folder import AppFiles
from .journal import Journal
from .state import read, safe, write
from .stores import Stores, fingerprint

logger = logging.getLogger(__name__)

# The relay takes 512KB per sealed message: the box is base64 of these bytes.
MESSAGE_BUDGET = 380 * 1024
# APNs takes 4KB per notification, the sealed message inside it included.
NOTIFICATION_BUDGET = 3600
STORED_WAIT = 5
MISSING_KEPT = 200
BLOB_CHUNK = 1024 * 1024
# A file goes to the phone in parts of this many bytes, each fetched and freed
# before the next: the relay holds 50MB for a phone, never the whole file.
PART_BYTES = 16 * BLOB_CHUNK
# A blob of ours the phone has not fetched after this long was left behind by
# a failed upload: taken back when the relay is full.
ORPHAN_AGE = 300
CHECK_WAIT = 3
PHONE_CLOSED = ("The phone is closed, so these are not checked yet: it applies them when it opens, and what it cannot "
                "apply comes back to you as a message")
PHONE_SILENT = (f"The phone did not answer in {CHECK_WAIT} seconds, so these are not checked: what it cannot apply comes "
                "back to you as a message")
ARTIFACT_OPS = ("profile", "define", "page", "store", "assets", "buttons", "widget")


class Refusal(RuntimeError):
    """The relay will not carry a message."""


def _merged(base: dict, patch: dict) -> dict:
    """A store patch as the app applies it: objects merge, null removes, the rest replaces."""
    merged = dict(base)
    for key, value in patch.items():
        if value is None:
            merged.pop(key, None)
        elif isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merged(merged[key], value)
        else:
            merged[key] = value
    return merged


def _valid_components(components) -> dict:
    """Only definitions the app accepts: one it refuses would make it refuse the
    whole set when they are sent again to a newly paired phone."""
    if not isinstance(components, dict):
        return {}
    return {name: body for name, body in components.items()
            if name[:1].isupper() and isinstance(body, dict) and "body" in body}


class Identity:
    """Who the agent is to the relay and which device it is paired with.
    Written by pairing (`hermes dedala pair`), read by the gateway."""

    def __init__(self, home: Path):
        self.path = home / "identity.json"
        self.data = read(self.path)
        if "agent_private" not in self.data:
            raw = X25519PrivateKey.generate().private_bytes(
                serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
            self.data["agent_private"] = base64.b64encode(raw).decode()
            self.save()

    def reload(self) -> None:
        self.data = read(self.path) or self.data

    def save(self) -> None:
        write(self.path, self.data)

    @property
    def private(self) -> X25519PrivateKey:
        return X25519PrivateKey.from_private_bytes(base64.b64decode(self.data["agent_private"]))

    @property
    def public(self) -> str:
        return seal.public(self.private)

    @property
    def paired(self) -> bool:
        return bool(self.data.get("pairing") and self.data.get("device_key"))

    def keys(self) -> tuple[bytes, bytes]:
        return seal.keys(self.private, self.data["device_key"], self.data["pairing"])

    def expect(self, pairing: str, proof: str) -> None:
        self.data["pending"] = {"pairing": pairing, "proof": proof}
        self.save()

    def complete(self, pairing: str, device: dict) -> bool:
        """Accepts the device the relay says claimed the code, if it carries the proof."""
        pending = self.data.get("pending") or {}
        if pending.get("pairing") != pairing:
            return False
        if not secrets.compare_digest(device.get("mac", ""), seal.proof_mac(pending["proof"], device.get("key", ""))):
            logger.error("[app] pairing %s: the device key does not carry the proof, refused", pairing)
            return False
        self.data.update(pairing=pairing, device_key=device["key"], device_name=device.get("name", "iPhone"))
        self.data.pop("pending", None)
        self.save()
        return True


class Link:
    """The relay connection the gateway keeps open."""

    def __init__(self, home: Path, relay: str, token: str, name: str = "Assistant"):
        self.home = home
        self.relay = relay.rstrip("/")
        self.token = token
        self.name = name
        self.identity = Identity(home)
        self.state_path = home / "link.json"
        self.state = {"seq_out": 0, "last_in": 0, "channels": {}, **read(self.state_path)}
        self.state.pop("artifacts", None)
        self.app = AppFiles(home)
        self.state["artifacts"] = self.app.loaded
        self.app.loaded["store"] = {}
        self.stores = Stores(home / "stores", self.app)
        self._mirror(list(self.stores.held))
        self.journal = Journal(home / "conversations.jsonl")
        self.replayed: set[tuple[str, str]] = set()
        self._lock = None
        self.app_online = False
        self.on_event: Callable[[dict], Awaitable[None]] | None = None
        self.on_paired: Callable[[], Awaitable[None]] | None = None
        self.on_online: Callable[[], Awaitable[None]] | None = None
        self._syncing: asyncio.Task | None = None
        self.steps: dict[str, list[dict]] = {}
        self._checks: dict[str, asyncio.Future] = {}
        self._missing: set[int] = set(self.state.get("missing", []))
        self._inbox: asyncio.Queue = asyncio.Queue()
        self._stored: dict[int, asyncio.Future] = {}
        self._sending = asyncio.Lock()
        self._socket: aiohttp.ClientWebSocketResponse | None = None
        self._session: aiohttp.ClientSession | None = None
        self._task: asyncio.Task | None = None
        self._worker: asyncio.Task | None = None

    # Lifecycle

    async def start(self) -> None:
        """Connects to the relay; one process at a time per home, since two links
        would number their messages from the same counters and the app drops
        what it has already seen."""
        self._lock = open(self.home / ".link.lock", "w")
        try:
            fcntl.flock(self._lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self._lock.close()
            raise RuntimeError("Another process already talks to the app from this home (the gateway): "
                               "send to the app through the app tools, never through a Link of your own")
        self._session = aiohttp.ClientSession(self.relay, headers={"Authorization": f"Bearer {self.token}"})
        self._worker = asyncio.create_task(self._work())
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        for task in (self._task, self._worker):
            if task:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
        if self._session:
            await self._session.close()
        if self._lock:
            self._lock.close()
            self._lock = None

    async def _run(self) -> None:
        """Reads the relay's frames. Nothing here waits on the agent: what takes
        time is queued for `_work`, so the relay's answers to what is being sent
        are always heard."""
        delay = 1
        while True:
            try:
                async with self._session.ws_connect("/ws", heartbeat=30) as socket:
                    self._socket = socket
                    delay = 1
                    logger.info("[app] connected to the relay")
                    self._inbox.put_nowait(("connected", None))
                    async for frame in socket:
                        if frame.type == aiohttp.WSMsgType.TEXT:
                            self._frame(json.loads(frame.data))
            except asyncio.CancelledError:
                raise
            except Exception as error:
                logger.warning("[app] relay connection lost: %s", error)
            self._socket = None
            self.app_online = False
            for stored in self._stored.values():
                if not stored.done():
                    stored.set_exception(ConnectionError("the relay connection was lost"))
            await asyncio.sleep(delay)
            delay = min(delay * 2, 60)

    def _frame(self, frame: dict) -> None:
        if "message" in frame:
            self._inbox.put_nowait(("message", frame["message"]))
        elif "paired" in frame:
            self._inbox.put_nowait(("paired", frame["paired"]))
        elif "app" in frame:
            self.app_online = frame["app"] == "online"
            if self.app_online and self.on_online:
                self._syncing = asyncio.create_task(self.on_online())
        elif "stored" in frame:
            if (stored := self._stored.get(frame["stored"])) and not stored.done():
                stored.set_result(None)
        elif "error" in frame:
            if (stored := self._stored.get(frame.get("seq"))) and not stored.done():
                stored.set_exception(Refusal(f"The relay refused the message: {frame['error']}"))
            else:
                logger.warning("[app] relay: %s", frame["error"])

    async def _work(self) -> None:
        """Handles what the relay delivered, in order, one thing at a time."""
        while True:
            kind, value = await self._inbox.get()
            try:
                if kind == "message":
                    await self._incoming(value)
                elif kind == "paired":
                    await self._paired(value)
                else:
                    await self._connected()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("[app] could not handle what the relay delivered (%s)", kind)

    async def _connected(self) -> None:
        """A phone paired while the gateway was away gets what a live pairing gets."""
        self.identity.reload()
        if not self.identity.paired:
            return
        if "pairing" not in self.state:
            self.state["pairing"] = self.identity.data["pairing"]
            self._save()
        elif self.state["pairing"] != self.identity.data["pairing"]:
            await self._begin(self.identity.data["pairing"])

    async def _paired(self, paired: dict) -> None:
        for _ in range(30):
            self.identity.reload()
            if self.identity.data.get("pairing") == paired["pairing"] or self.identity.complete(paired["pairing"], paired["device"]):
                break
            await asyncio.sleep(0.5)
        if self.identity.data.get("pairing") != paired["pairing"]:
            logger.error("[app] a device claimed %s but no pairing here expects it", paired["pairing"])
            return
        if self.state.get("pairing") != paired["pairing"]:
            await self._begin(paired["pairing"])

    async def _begin(self, pairing: str) -> None:
        """A newly paired phone starts from nothing: the numbering restarts and
        it is sent what the agent built."""
        self.state.update(pairing=pairing, seq_out=0, last_in=0, missing=[], channels={}, assets_sent={})
        self._missing.clear()
        self._save()
        logger.info("[app] paired with %s", self.identity.data.get("device_name"))
        await self.replay()
        if self.on_paired:
            await self.on_paired()

    async def _incoming(self, message: dict) -> None:
        seq = message["seq"]
        if not self.identity.paired or (seq <= self.state["last_in"] and seq not in self._missing):
            await self._ack(seq)
            return
        _, to_agent = self.identity.keys()
        try:
            events = seal.unseal(to_agent, message)
        except Exception:
            logger.error("[app] a message from the app could not be opened")
            return
        for event in events if isinstance(events, list) else [events]:
            try:
                await self._fetch_capture(event)
                self._settle(event)
                if self.on_event:
                    await self.on_event(event)
            except asyncio.CancelledError:
                raise
            except Exception:
                kind = event.get("kind") if isinstance(event, dict) else type(event).__name__
                logger.exception("[app] the %s event in message %s could not be handled; skipped", kind, seq)
        self._heard(seq)
        await self._ack(seq)

    def _heard(self, seq: int) -> None:
        """The phone numbers its messages one by one, and one can overtake
        another (the app and its extensions each send): the numbers skipped so
        far are remembered, so a late message is still heard, and only once."""
        last = self.state["last_in"]
        if seq > last:
            if seq - last <= MISSING_KEPT:
                self._missing.update(range(last + 1, seq))
            self.state["last_in"] = seq
        self._missing.discard(seq)
        self.state["missing"] = sorted(self._missing)[-MISSING_KEPT:]
        self._missing = set(self.state["missing"])
        self._save()

    async def _ack(self, seq: int) -> None:
        if self._socket is not None and not self._socket.closed:
            with contextlib.suppress(ConnectionError, aiohttp.ClientError):
                await self._socket.send_json({"ack": seq})

    def _settle(self, event: dict) -> None:
        """Hands what the app found in a batch it was asked to check to the
        call waiting for it. An answer nobody waits for any more (the phone
        opened later) becomes an `errors` event, so what it found is not lost."""
        if event.get("kind") != "checked":
            return
        waiter = self._checks.pop(event.get("id"), None)
        if waiter is not None and not waiter.done():
            waiter.set_result(event.get("errors") or [])
        else:
            event["kind"] = "errors"

    async def _fetch_capture(self, event: dict) -> None:
        capture = event.get("capture")
        if not isinstance(capture, dict) or "blob" not in capture:
            return
        if (image := await self.blob(capture["blob"])) is None:
            return
        folder = self.home / "captures"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{safe(event.get('card', 'card'))}-{int(time.time())}.jpg"
        path.write_bytes(image)
        event["capture"] = str(path)

    async def blob(self, blob: str) -> Optional[bytes]:
        """A blob the app left on the relay, opened and deleted there; None when
        it is gone."""
        _, to_agent = self.identity.keys()
        async with self._session.get(f"/blobs/{blob}") as response:
            if response.status != 200:
                return None
            body = seal.unseal_bytes(to_agent, await response.json())
        async with self._session.delete(f"/blobs/{blob}"):
            pass
        return body

    # Sending

    def add_step(self, conversation: str, step: dict) -> None:
        self.steps.setdefault(conversation, []).append(step)

    def _with_steps(self, op: dict) -> dict:
        """What the agent did since its last message goes with the next one it says, a step
        taken several times in a row said once."""
        if op.get("op") != "say" or not (steps := self.steps.pop(op.get("conversation") or "main", None)):
            return op
        return {**op, "steps": [step for step, _ in itertools.groupby(steps)]}

    async def send(self, ops: list[dict], notify: bool = False, record: bool = True, collapse: str | None = None, ring: bool = False) -> None:
        """Seals ops for the app; also notifies the phone when it is closed and
        `notify` asks, replacing the notification with the same `collapse` key;
        `ring` notifies even when the app is open, a line of the agent's own."""
        if not self.identity.paired:
            raise RuntimeError("No phone is paired: run `hermes dedala pair` on the machine where Hermes runs")
        sent_before = {name: value for name, value in self.state.get("stores_sent", {}).items()}
        touched = {op.get("id") for op in ops if op.get("op") == "store" and op.get("id")}
        if record:
            ops = self._record(ops)
            self.replayed -= {key for op in ops for key in _drawn(op)}
        ops = [self.journal.sent(self._with_steps(await self._carry(op))) for op in ops]
        for batch in self._batches(ops):
            async with self._sending:
                to_app, _ = self.identity.keys()
                self.state["seq_out"] += 1
                message = seal.seal(to_app, self.state["seq_out"], batch)
                self._save()
                try:
                    await self._transmit(message)
                except Exception:
                    for name in touched:
                        if name in sent_before:
                            self.state["stores_sent"][name] = sent_before[name]
                        else:
                            self.state.get("stores_sent", {}).pop(name, None)
                    self._save()
                    raise
            if notify and (ring or not self.app_online):
                fits = len(json.dumps(message)) <= NOTIFICATION_BUDGET
                body = {**({"box": message} if fits else {}), **({"collapse": collapse} if collapse else {}), **({"ring": True} if ring else {})}
                async with self._session.post("/push/notify", json=body) as response:
                    if response.status != 200:
                        logger.warning("[app] notification refused: %s", await response.text())

    async def _transmit(self, message: dict) -> None:
        """Returns once the relay holds the message, in the order it was
        numbered; raises when the relay will not take it."""
        socket = self._socket
        if socket is not None and not socket.closed:
            stored = self._stored[message["seq"]] = asyncio.get_running_loop().create_future()
            try:
                await socket.send_json({"send": message})
                await asyncio.wait_for(stored, STORED_WAIT)
                return
            except (asyncio.TimeoutError, ConnectionError, aiohttp.ClientError):
                pass
            finally:
                self._stored.pop(message["seq"], None)
        async with self._session.post("/mailbox", json=message) as response:
            if response.status != 200:
                raise Refusal(f"The relay refused the message: {await response.text()}")

    async def _carry(self, op: dict) -> dict:
        """An asset that is a file here goes as sealed blobs the app fetches and deletes."""
        if op.get("op") == "assets":
            return {**op, "assets": await self._carry_assets(op.get("assets") or {})}
        return op

    async def _carry_assets(self, assets: dict) -> dict:
        """An asset is a URL the phone downloads, or a file on this machine sent
        as sealed blobs: private, and sent again only once it changed."""
        sent = self.state.setdefault("assets_sent", {})
        carried = {}
        for name, source in assets.items():
            if not isinstance(source, str) or source.startswith(("http://", "https://")):
                carried[name] = source
                continue
            path = Path(source).expanduser()
            try:
                stat = path.stat()
                version = f"{stat.st_mtime_ns}-{stat.st_size}"
                if sent.get(name) == version:
                    continue
                body = path.read_bytes()
            except OSError:
                logger.warning("[app] the asset %s names %s, which is gone; not sent", name, source)
                continue
            carried[name] = {"blobs": [await self._upload(body[start:start + BLOB_CHUNK]) for start in range(0, max(len(body), 1), BLOB_CHUNK)],
                             "size": len(body)}
            sent[name] = version
        return carried

    async def _upload(self, chunk: bytes) -> str:
        to_app, _ = self.identity.keys()
        async with self._session.post("/blobs", json=seal.seal_bytes(to_app, 0, chunk)) as response:
            answer = await response.json()
            if response.status != 201:
                raise RuntimeError(f"The relay refused a file: {answer.get('error') or answer}")
            return answer["blob"]

    @staticmethod
    def _batches(ops: list[dict]) -> list[list[dict]]:
        batches, current, size = [], [], 0
        for op in ops:
            length = len(json.dumps(op, separators=(",", ":"), ensure_ascii=False).encode()) + 1
            if current and size + length > MESSAGE_BUDGET:
                batches.append(current)
                current, size = [], 0
            current.append(op)
            size += length
        return batches + ([current] if current else [])

    async def ring(self, ops: list[dict], collapse: str) -> None:
        """A notification only, never in the mailbox: the app already has these
        ops, the phone shows them once more, replacing what `collapse` names."""
        to_app, _ = self.identity.keys()
        async with self._session.post("/push/notify", json={"box": seal.seal(to_app, 0, ops), "collapse": collapse}) as response:
            if response.status != 200:
                logger.warning("[app] notification refused: %s", await response.text())

    async def send_and_check(self, ops: list[dict], timeout: float = CHECK_WAIT) -> dict:
        """Sends ops and returns {"errors": what the app could not apply}, as
        the app answered. When it did not check them, `phone` says why: closed,
        or silent for `timeout` seconds."""
        if not self.app_online:
            await self.send(ops)
            return {"errors": [], "phone": PHONE_CLOSED}
        check = os.urandom(4).hex()
        waiter = self._checks[check] = asyncio.get_running_loop().create_future()
        try:
            await self.send([*ops, {"op": "check", "id": check}])
            return {"errors": await asyncio.wait_for(waiter, timeout)}
        except asyncio.TimeoutError:
            return {"errors": [], "phone": PHONE_SILENT}
        finally:
            self._checks.pop(check, None)

    # Artifacts: what the agent built, sent again to a newly paired phone

    def _record(self, ops: list[dict]) -> list[dict]:
        """Writes what the ops build to the app's files (folder.py), and
        returns them as they go to the phone: a store patch goes as the whole
        store its file now holds, so the phone has what the file has whatever
        it had before."""
        leaving = []
        for op in ops:
            kind = op.get("op")
            if kind == "store" and not op.get("id"):
                leaving.append(op)
                continue
            if kind == "store":
                if "declare" in op:
                    self.stores.declare(op["id"], op["declare"])
                if "patch" in op or "data" in op:
                    current = self.stores.read(op["id"])
                    self.store(op["id"], _merged(current if isinstance(current, dict) else {}, op["patch"]) if "patch" in op else op.get("data"))
                else:
                    self._stores_sent([op["id"]])
                leaving += self.stores.ops(op["id"]) if op["id"] in self.stores.held else [{"op": "store", "id": op["id"], "data": None}]
                continue
            leaving.append(op)
            self.write_artifact(op)
        return leaving

    def write_artifact(self, op: dict) -> None:
        """One op's effect on the app's files."""
        kind = op.get("op")
        app = self.app
        if kind == "define":
            for name, body in _valid_components(op.get("components")).items():
                app.write("components", name, body)
            for name in removed([op]):
                app.write("components", name, None)
            for name, source in (op.get("scripts") or {}).items():
                app.write("scripts", name, source if isinstance(source, str) else None)
            self.state["defined_sent"] = fingerprint({"components": app.loaded["components"], "scripts": app.loaded["scripts"]})
            self._save()
        elif kind == "page":
            if op.get("remove"):
                app.write("page", op.get("id"), None)
            else:
                app.write("page", op["id"], {key: value for key, value in op.items() if key not in ("op", "id", "store", "data", "focus")})
        elif kind == "widget":
            app.write("widget", op["id"], None if op.get("remove") else {key: value for key, value in op.items() if key not in ("op", "id")})
        elif kind == "buttons":
            kinds = dict(app.loaded["buttons"])
            for name, buttons in (op.get("kinds") or {}).items():
                if buttons is None:
                    kinds.pop(name, None)
                else:
                    kinds[name] = buttons
            app.write("buttons", None, kinds)
        elif kind == "profile":
            app.write("profile", None, {**app.loaded["profile"], **{key: value for key, value in op.items() if key != "op"}})
        elif kind == "assets":
            app.write("assets", None, {**app.loaded["assets"], **(op.get("assets") or {})})

    # Stores: each a file (stores.py), mirrored in artifacts["store"] in the
    # shape of the op that sends it, which is how the tools read them.

    def store(self, name: str, data) -> None:
        """Gives a JSON store its data, written to its file; `None` removes it.
        The phone is taken to have it: whoever calls sends it."""
        self.stores.put(name, data)
        self._mirror([name])
        self._stores_sent([name])

    def _mirror(self, names) -> None:
        mirrored = self.app.loaded.setdefault("store", {})
        for name in names:
            if name in self.stores.held:
                mirrored[name] = self.stores.op(name)
            else:
                mirrored.pop(name, None)

    def _stores_sent(self, names) -> None:
        sent = self.state.setdefault("stores_sent", {})
        for name in names:
            if name not in self.stores.held:
                sent.pop(name, None)
            elif self.stores.kind(name) == "folder":
                sent[name] = {item["id"]: fingerprint(item) for item in self.stores.held[name]}
                self.stores.taken(name)
            else:
                sent[name] = fingerprint(self.stores.held[name])
        self._save()

    def stores_written(self) -> None:
        """Takes in what was written to the store files from outside."""
        self._mirror(self.stores.scan())

    def unsent_stores(self) -> list[dict]:
        """The ops that bring the phone's stores to what the files hold,
        remembered as sent: a folder store goes record by record once it
        has been sent whole."""
        sent = self.state.get("stores_sent", {})
        ops = []
        settled = []
        for name, data in self.stores.held.items():
            if self.stores.kind(name) == "folder" and isinstance(sent.get(name), dict):
                before = sent[name]
                current = {item["id"]: fingerprint(item) for item in data}
                for identifier in sorted(set(current) | set(before)):
                    if current.get(identifier) != before.get(identifier):
                        ops.append(self.stores.record_op(name, identifier))
                if ops:
                    settled.append(name)
            elif self.stores.kind(name) == "folder" or sent.get(name) != fingerprint(data):
                ops += self.stores.ops(name)
                settled.append(name)
        gone = [name for name in sent if name not in self.stores.held]
        ops += [{"op": "store", "id": name, "data": None} for name in gone]
        if settled or gone:
            self._stores_sent(settled + gone)
        return ops

    def unsent_define(self) -> list[dict]:
        """The components and scripts as they stand, when the phone does not
        have them: changed by hand here, or migrated."""
        defined = {"components": self.app.loaded["components"], "scripts": self.app.loaded["scripts"]}
        print_ = fingerprint(defined)
        if self.state.get("defined_sent") == print_:
            return []
        self.state["defined_sent"] = print_
        self._save()
        return [{"op": "define", **defined}] if defined["components"] or defined["scripts"] else []

    async def wake(self) -> None:
        """A silent push: the app, closed, fetches its mailbox and redraws its widgets."""
        async with self._session.post("/push/notify", json={"silent": True, "collapse": "wake"}) as response:
            if response.status != 200:
                logger.debug("[app] wake not sent: %s", await response.text())

    async def unsent_attachments(self) -> list[dict]:
        """The files the records name, described to the phone when they appear
        or change: name, size and version, nothing uploaded. The phone asks
        for the file itself when it shows it (`fetch`), and gets it in parts."""
        sent = self.state.setdefault("attachments_sent", {})
        ops = []
        live = set()
        for name in list(self.stores.held):
            for identifier, path in self.stores.attachments(name):
                key = f"{name}/{identifier}"
                live.add(key)
                op = {"op": "attachment", "store": name, "id": identifier, "name": path.name}
                try:
                    stat = path.stat()
                    version = f"{stat.st_mtime_ns}-{stat.st_size}"
                    op.update(size=stat.st_size, version=version)
                except OSError:
                    version = "missing"
                    op["missing"] = True
                if sent.get(key) == version:
                    continue
                ops.append(op)
                sent[key] = version
        for key in [key for key in sent if key not in live]:
            del sent[key]
        if ops or len(live) != len(sent):
            self._save()
        return ops

    def fetch(self, store: str, identifier: str) -> str | None:
        """The phone asks for a record's file: queued to go in parts while the
        phone is open; the reason when there is no such file."""
        path = next((path for found, path in self.stores.attachments(store) if found == identifier), None)
        if path is None:
            return f"No file to fetch: the record {identifier} of {store} names none"
        try:
            size = path.stat().st_size
        except OSError:
            return f"The file of {identifier} is missing on this machine"
        fetching = self.state.setdefault("fetching", [])
        if not any(item["store"] == store and item["id"] == identifier for item in fetching):
            fetching.append({"store": store, "id": identifier, "path": str(path), "size": size, "next": 1,
                             "of": max(1, -(-size // PART_BYTES))})
            self._save()
        return None

    async def send_parts(self) -> list[dict]:
        """The next part of the file the phone is waiting for: its blobs
        uploaded and the op that names them, one part a turn so the phone
        frees the relay between parts. A refusal (the relay full) waits for
        the next turn; a file that changed or went is told as missing."""
        fetching = self.state.get("fetching") or []
        if not fetching:
            return []
        item = fetching[0]
        path = Path(item["path"])
        op = {"op": "attachment", "store": item["store"], "id": item["id"], "name": path.name, "size": item["size"]}
        try:
            with path.open("rb") as file:
                file.seek((item["next"] - 1) * PART_BYTES)
                body = file.read(PART_BYTES)
            if path.stat().st_size != item["size"]:
                raise OSError("changed")
        except OSError:
            fetching.pop(0)
            self._save()
            return [{**op, "missing": True}]
        blobs = []
        try:
            for start in range(0, max(len(body), 1), BLOB_CHUNK):
                blobs.append(await self._upload(body[start:start + BLOB_CHUNK]))
        except RuntimeError as refusal:
            for blob in blobs:
                async with self._session.delete(f"/blobs/{blob}"):
                    pass
            async with self._session.delete("/blobs", params={"older": str(ORPHAN_AGE)}) as response:
                cleared = (await response.json()).get("cleared", 0) if response.status == 200 else 0
            if cleared:
                logger.warning("[app] the relay refused part %d/%d of %s (%s); took back %d blob(s) left behind, trying again",
                               item["next"], item["of"], path.name, refusal, cleared)
                return await self.send_parts()
            if item.get("told") != item["next"]:
                item["told"] = item["next"]
                self._save()
                logger.warning("[app] part %d/%d of %s waits for the phone to free the relay: %s", item["next"], item["of"], path.name, refusal)
            return []
        op.update(part=item["next"], of=item["of"], blobs=blobs)
        if item["next"] >= item["of"]:
            fetching.pop(0)
        else:
            item["next"] += 1
        self._save()
        return [op]

    def edited(self, event: dict) -> list[str]:
        """What he changed on the phone, once it settled: each store's file
        takes the change, so a replay or a resend keeps it; the changes are
        logged for app_events; the jobs that handle the pages touched are
        returned, to run now. A change a store cannot take is logged with
        why, and the store goes back as it stands."""
        artifacts = self.state["artifacts"]
        at = event.get("at")
        jobs: list[str] = []
        changes = []
        for change in event.get("changes") or []:
            source = change.get("from") or ""
            name = change.get("store")
            if not name:
                continue
            try:
                self.stores.change(name, change)
                self._mirror([name])
                self._stores_sent([name])
            except Refused as refusal:
                logger.warning("[app] his change to the store %s was not made: %s", name, refusal)
                change = {**change, "refused": str(refusal)}
            changes.append(change)
            job = (artifacts.get("page", {}).get(source) or {}).get("handled_by")
            if job and job not in jobs:
                jobs.append(job)
        self.log_edits({"at": at, "changes": changes})
        return jobs

    def log_edits(self, entry: dict) -> None:
        """What he changed, kept for app_events."""
        try:
            with (self.home / "edits.jsonl").open("a") as log:
                log.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError as error:
            logger.warning("[app] could not log his edits: %s", error)

    def handled(self, identifier: str | None) -> bool:
        """Whether an event the phone keeps sending until acknowledged was handled already."""
        return bool(identifier) and identifier in self.state.get("acked", [])

    def handle(self, identifier: str | None, refusal: str | None = None, answer: list[dict] | None = None) -> None:
        """Remembers such an event as handled, with why it was refused and
        what answered it: sent again, it gets the same answer and is not made
        twice."""
        if not identifier:
            return
        handled = self.state.setdefault("acked", [])
        if identifier not in handled:
            handled.append(identifier)
        del handled[:-500]
        refusals = self.state.setdefault("refused", {})
        answers = self.state.setdefault("answers", {})
        if refusal:
            refusals[identifier] = refusal
        if answer:
            answers[identifier] = answer
        for kept in (refusals, answers):
            for gone in set(kept) - set(handled):
                del kept[gone]
        self._save()

    def refusal(self, identifier: str | None) -> str | None:
        return self.state.get("refused", {}).get(identifier)

    def answer(self, identifier: str | None) -> list[dict]:
        return self.state.get("answers", {}).get(identifier) or []

    def changes(self, since: str | None = None, limit: int | None = None, after: int | None = None) -> list[dict]:
        """His edits, oldest first, each with its number `n`: after
        `since` (ISO) if given, the latest `limit` (50 unless said); or after
        the change numbered `after`, all of them unless a limit is given."""
        found = []
        for number, line in enumerate(self._change_lines(), 1):
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if (since and (entry.get("at") or "") <= since) or (after is not None and number <= after):
                continue
            found.append({"n": number, **entry})
        if after is not None:
            return found[:limit] if limit else found
        return found[-(limit or 50):]

    def _change_lines(self) -> list[str]:
        try:
            return (self.home / "edits.jsonl").read_text().splitlines()
        except OSError:
            return []

    def follow_changes(self, job: str) -> None:
        """A job starts handling his changes with the one just logged: what he
        changed before it was linked is not its to handle."""
        handled = self.state.setdefault("changes_handled", {})
        if job not in handled:
            handled[job] = max(len(self._change_lines()) - 1, 0)
            self._save()

    def unhandled_changes(self, job: str) -> tuple[int, int]:
        """The number of the last change a job handled, and of the last one logged."""
        count = len(self._change_lines())
        return min(self.state.get("changes_handled", {}).get(job, count), count), count

    def handled_changes(self, job: str, upto: int) -> None:
        self.state.setdefault("changes_handled", {})[job] = upto
        self._save()

    def arranged(self, event: dict) -> Optional[tuple[Optional[str], Optional[str]]]:
        """How he arranged the app on the phone, kept for the next phone; the
        name he gives the agent there, before and after, when it changed."""
        before = (self.arrangement() or [{}])[0].get("name")
        write(self.home / "phone.json", {key: event[key] for key in ("pinned", "tabNames", "pageStates", "pages", "look", "name") if key in event})
        after = event.get("name")
        return (before, after) if before != after else None

    def arrangement(self) -> list[dict]:
        try:
            kept = json.loads((self.home / "phone.json").read_text())
        except (OSError, ValueError):
            return []
        return [{"op": "arrangement", **kept}] if isinstance(kept, dict) and kept else []

    async def replay(self) -> None:
        """Everything a newly paired phone is sent: how he arranged the app
        first, so the pages coming in take their places, what the agent built,
        then the conversations."""
        self.state["assets_sent"] = {}
        ops = self.arrangement() + self.app.replay(self.name)
        ops += [op for name in self.stores.held for op in self.stores.ops(name)] + self.app.after_stores()
        ops += self.journal.history(self.state.get("topics", {}))
        self._stores_sent(list(self.stores.held))
        self.state["attachments_sent"] = {}
        self.state["defined_sent"] = fingerprint({"components": self.app.loaded["components"], "scripts": self.app.loaded["scripts"]})
        self.replayed = {key for op in ops for key in _drawn(op)}
        await self.send(ops, record=False)

    def redrawn(self, event: dict) -> bool:
        """Whether the phone reports on a card or page it was given back at
        pairing, not one the agent just sent: its problems are old, not his turn's."""
        key = ("card", event["card"]) if event.get("card") else ("page", event.get("page"))
        if key in self.replayed:
            self.replayed.discard(key)
            return True
        return False

    # Live Activities

    async def start_activity(self, activity: str, design: dict, data: dict, alert: dict | None) -> dict:
        to_app, _ = self.identity.keys()
        if previous := self.state.get("channels", {}).get(activity):
            async with self._session.delete(f"/channels/{previous}"):
                pass
        async with self._session.post("/channels") as response:
            answer = await response.json()
            if response.status != 201:
                return {"error": answer.get("error") or answer}
        channel = answer["channel"]
        self.state.setdefault("channels", {})[activity] = channel
        self._save()
        body = {"id": activity, "design": seal.seal_design(to_app, design), "data": seal.seal_state(to_app, data), "channel": channel}
        if alert:
            body["alert"] = alert
        async with self._session.post("/push/activity/start", json=body) as response:
            return await response.json()

    async def update_activity(self, activity: str, data: dict, end: bool, alert: dict | None) -> dict:
        channel = self.state.get("channels", {}).get(activity)
        if channel is None:
            return {"error": f"No running activity {activity}; start it first"}
        to_app, _ = self.identity.keys()
        body = {"channel": channel, "data": seal.seal_state(to_app, data), "event": "end" if end else "update"}
        if alert:
            body["alert"] = alert
        async with self._session.post("/push/activity/broadcast", json=body) as response:
            answer = await response.json()
        if end:
            async with self._session.delete(f"/channels/{channel}"):
                pass
            self.state["channels"].pop(activity, None)
            self._save()
        return answer

    def _save(self) -> None:
        """Keeps the numbering and the runtime state; what the agent built
        lives in the app's files (folder.py)."""
        write(self.state_path, {key: value for key, value in self.state.items() if key != "artifacts"})



async def pair(home: Path, relay: str, token: str, name: str, show: Callable[[str], None], timeout: float = 600) -> dict:
    """Opens a pairing and waits for the phone: what `hermes dedala pair` runs."""
    identity = Identity(home)
    claim, proof = secrets.token_urlsafe(18), secrets.token_urlsafe(18)
    async with aiohttp.ClientSession(relay.rstrip("/"), headers={"Authorization": f"Bearer {token}"}) as http:
        async with http.post("/pairings", json={"claim_hash": seal.claim_hash(claim)}) as response:
            if response.status != 201:
                raise RuntimeError(f"The relay refused to open a pairing: {await response.text()}")
            pairing = (await response.json())["pairing"]
        identity.expect(pairing, proof)
        show(json.dumps({"v": 1, "relay": relay.rstrip("/"), "pairing": pairing, "claim": claim, "proof": proof,
                         "agent_key": identity.public, "name": name}, separators=(",", ":")))
        deadline = time.time() + timeout
        while time.time() < deadline:
            async with http.get(f"/pairings/{pairing}") as response:
                status = await response.json()
            if status.get("status") == "paired":
                identity.reload()
                if identity.data.get("pairing") == pairing or identity.complete(pairing, status["device"]):
                    return {"device": identity.data.get("device_name", "iPhone")}
                raise RuntimeError("The device that claimed the code does not carry its proof; refused")
            if status.get("status") == "expired":
                break
            await asyncio.sleep(2)
    raise RuntimeError("The pairing code expired; run the command again")


def _drawn(op: dict) -> list[tuple[str, str]]:
    """The cards and pages an op makes the phone draw, as a rendered event names them."""
    if op.get("op") == "say" and op.get("card") and op.get("id"):
        return [("card", op["id"])]
    if op.get("op") == "page" and op.get("id") and not op.get("remove"):
        return [("page", op["id"])]
    if op.get("op") == "history":
        return [("card", message["id"]) for message in op.get("messages") or [] if message.get("card") and message.get("id")]
    return []
