# SPDX-FileCopyrightText: 2026 Julien Malka
# SPDX-License-Identifier: MIT

"""What arrives from outside for the agent to process: a voice note, a meeting
recording, a mail. Anything signed may post to `/in/<source>`; the plugin keeps
each arrival on disk before any model sees it, then runs the job that handles
its source once arrivals settle: the job named `inbox/<source>`, else the one
named `inbox`. Without either, the main conversation hears of it.

A job reads what arrived with app_events. A handler that needs no model is a
script job: `/forward`, reachable from this machine only, puts what arrived
from a source into a conversation as his own words (his voice notes).

Signed like Hermes's webhook V2 scheme: hex HMAC-SHA256 of `<timestamp>.<body>`
in `X-Webhook-Signature-V2`, the timestamp in `X-Webhook-Timestamp`, an id in
`X-Request-ID` or the body's `id`. `/note` is the TP-7 route's old address:
the source `tp7`, unless the request id names another as `<source>:<id>`
(Grain recordings post there as `grain:<id>`)."""

import hashlib
import hmac
import json
import logging
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

MAX_BODY_BYTES = 1024 * 1024
INLINE_CHARS = 4000
FRESH_SECONDS = 300
SOURCE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")
TP7_PREFACE = "🎙️ (voice note from my TP-7, transcribed automatically)"


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _safe(identifier: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", identifier)[:80]


def _keep(path: Path, item: dict) -> None:
    """Writes an arrival whole or not at all: a half-written one would never be read."""
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(item, ensure_ascii=False))
    temporary.replace(path)


def signed(secret: str, timestamp: str, body: bytes, signature: str) -> bool:
    try:
        fresh = abs(time.time() - float(timestamp)) <= FRESH_SECONDS
    except ValueError:
        return False
    expected = hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
    return fresh and hmac.compare_digest(expected, signature)


class Inbox:
    """Arrivals by source, one JSON file each under `inbox/<source>/`, with the
    text beside it when it is long."""

    def __init__(self, home: Path):
        self.root = home / "inbox"
        # The sources given to a handler job whose run is under way, by its token.
        self.given: dict[str, str] = {}
        self._settle(None, False)

    def arrive(self, source: str, payload: dict, identifier: str | None = None) -> dict | None:
        """Keeps an arrival; None when one with that id is already kept."""
        identifier = str(identifier or payload.get("id") or uuid.uuid4().hex)
        folder = self.root / source
        folder.mkdir(parents=True, exist_ok=True)
        if any(folder.glob(f"*--{_safe(identifier)}.json")):
            return None
        at = now()
        name = f"{at.replace(':', '').replace('-', '')}--{_safe(identifier)}"
        text = str(payload.get("text") or "").strip()
        item = {"id": identifier, "source": source, "at": at, "title": str(payload.get("title") or "").strip(),
                "preface": str(payload.get("preface") or "").strip(), "chars": len(text),
                **{key: value for key, value in payload.items() if key not in ("id", "text", "title", "preface")}}
        if len(text) > INLINE_CHARS:
            (folder / f"{name}.txt").write_text(text)
            item["file"] = str(folder / f"{name}.txt")
        else:
            item["text"] = text
        _keep(folder / f"{name}.json", item)
        return item

    def _paths(self, source: str | None, besides: frozenset[str] = frozenset()) -> list[Path]:
        if source and not SOURCE.match(source):
            return []
        folders = [self.root / source] if source else [folder for folder in self.root.glob("*")
                                                         if folder.is_dir() and folder.name not in besides]
        return sorted((path for folder in folders for path in folder.glob("*.json")), key=lambda path: path.name)

    def unread(self, source: str | None = None, after: str | None = None) -> list[dict]:
        found = []
        for path in self._paths(source):
            try:
                item = json.loads(path.read_text())
            except (OSError, ValueError):
                continue
            if not item.get("read") and not item.get("taken") and (after is None or item["at"] > after):
                found.append(item)
        return found

    def give(self, sources) -> str:
        """Gives these sources to a handler job for one run: what it reads of
        them is only taken, until the run ends (`settle`)."""
        token = uuid.uuid4().hex
        for source in sources:
            self.given[source] = token
        return token

    def settle(self, token: str, handled: bool) -> None:
        """The run a token was given for ended: what it took is read when it
        ended well, and waits again otherwise."""
        self.given = {source: held for source, held in self.given.items() if held != token}
        self._settle(token, handled)

    def _settle(self, token: str | None, handled: bool) -> None:
        """Without a token, everything taken waits again: no run survives a restart."""
        for path in self._paths(None):
            try:
                item = json.loads(path.read_text())
            except (OSError, ValueError):
                continue
            if "taken" not in item or (token is not None and item["taken"] != token):
                continue
            del item["taken"]
            _keep(path, {**item, "read": now()} if handled else item)

    def take(self, source: str | None = None, since: str | None = None, limit: int = 20,
             besides: frozenset[str] = frozenset()) -> list[dict]:
        """The arrivals not read yet, oldest first, now marked read, or only
        taken when their source is given to a handler job whose run is under
        way; with `since`, every arrival after that time, read or not. Without
        a source, those of every source but `besides`."""
        found = []
        for path in self._paths(source, besides):
            try:
                item = json.loads(path.read_text())
            except (OSError, ValueError):
                continue
            if since and item["at"] <= since or not since and (item.get("read") or item.get("taken")):
                continue
            if not item.get("read") and not item.get("taken"):
                token = self.given.get(item["source"])
                _keep(path, {**item, "taken": token} if token else {**item, "read": now()})
            found.append(item)
            if len(found) == limit:
                break
        return found

    @staticmethod
    def text(item: dict) -> str:
        if "text" in item:
            return item["text"]
        try:
            return Path(item["file"]).read_text()
        except OSError:
            return ""

    @staticmethod
    def shown(item: dict) -> dict:
        """An arrival as a job reads it: a long text stays in its file, with its start."""
        shown = {key: value for key, value in item.items() if value not in ("", None)}
        if "file" in item:
            shown["start"] = Inbox.text(item)[:600]
        return shown


def handlers(jobs: list[dict]) -> dict[str, str]:
    """The jobs that handle arrivals, by source (`*` for every other)."""
    found = {}
    for job in jobs:
        name = (job.get("name") or "").strip()
        if name == "inbox":
            found["*"] = job["id"]
        elif name.startswith("inbox/") and SOURCE.match(name.removeprefix("inbox/")):
            found[name.removeprefix("inbox/")] = job["id"]
    return found


def handled_by(found: dict[str, str], job: str, sources) -> list[str]:
    """Of these sources, those the job handles: its own, or every source
    without a handler of its own when it is the job named `inbox`."""
    return sorted({source for source in sources if found.get(source, found.get("*")) == job})


def allowed(scope: dict | None, action: str, target: str | None) -> bool:
    """Whether a token's scope lets it do this: `None` is the shared secret,
    which may do anything."""
    if scope is None:
        return True
    if action == "notify":
        return bool(scope.get("notify"))
    allowed_targets = scope.get("stores" if action == "store" else "sources") or []
    return "*" in allowed_targets or target in allowed_targets


async def serve(server, port: int, secret: str, host: str | None = None, tokens=None):
    """The listener: `/in/<source>`, `/note`, `/notify` and `/store/<id>`
    from the network, signed with the shared secret or carrying a token with a
    scope (`tokens.json`); `/forward` from this machine only."""
    from aiohttp import web

    def bearer(request: web.Request):
        """The scope of the token a request carries; None for the shared
        secret; False when neither is good."""
        header = request.headers.get("Authorization", "")
        if header.startswith("Bearer "):
            found = (tokens() if tokens else {}).get(header[7:].strip())
            return found if isinstance(found, dict) else False
        return None

    async def check(request: web.Request, body: bytes, action: str, target: str | None, what: str):
        scope = bearer(request)
        if scope is False:
            logger.warning("[app] refused %s with an unknown token", what)
            return web.json_response({"error": "unknown token"}, status=401)
        if scope is None and not signed(secret, request.headers.get("X-Webhook-Timestamp", ""), body, request.headers.get("X-Webhook-Signature-V2", "")):
            logger.warning("[app] refused %s with a missing or bad signature", what)
            return web.json_response({"error": "bad signature"}, status=401)
        if not allowed(scope, action, target):
            logger.warning("[app] refused %s: the token %s may not", what, scope.get("id"))
            return web.json_response({"error": f"this token may not {action}" + (f" {target}" if target else "")}, status=403)
        return None

    async def arrive(request: web.Request, source: str, identifier: str | None) -> web.Response:
        body = await request.read()
        if refused := await check(request, body, "source", source, f"an arrival for {source}"):
            return refused
        try:
            payload = json.loads(body)
        except ValueError:
            return web.json_response({"error": "body is not JSON"}, status=400)
        if not isinstance(payload, dict) or not str(payload.get("text") or "").strip():
            return web.json_response({"status": "ignored", "reason": "empty"})
        item = await server.arrived(source, payload, identifier)
        if item is None:
            return web.json_response({"status": "duplicate"})
        return web.json_response({"status": "accepted", "id": item["id"]}, status=202)

    async def inbound(request: web.Request) -> web.Response:
        source = request.match_info["source"]
        if not SOURCE.match(source):
            return web.json_response({"error": "a source is a short lowercase name"}, status=400)
        return await arrive(request, source, request.headers.get("X-Request-ID"))

    async def note(request: web.Request) -> web.Response:
        identifier = request.headers.get("X-Request-ID") or ""
        named, _, rest = identifier.partition(":")
        if rest and SOURCE.match(named):
            return await arrive(request, named, rest)
        return await arrive(request, "tp7", identifier or None)

    async def notify(request: web.Request) -> web.Response:
        body = await request.read()
        if refused := await check(request, body, "notify", None, "a notification"):
            return refused
        try:
            payload = json.loads(body)
        except ValueError:
            return web.json_response({"error": "body is not JSON"}, status=400)
        if not isinstance(payload, dict):
            return web.json_response({"error": "body is {title, body, open, collapse}"}, status=400)
        if problem := await server.notify(payload):
            return web.json_response({"error": problem}, status=400)
        return web.json_response({"status": "sent"})

    async def store(request: web.Request) -> web.Response:
        body = await request.read()
        name = request.match_info["store"]
        if refused := await check(request, body, "store", name, f"a write to the store {name}"):
            return refused
        try:
            payload = json.loads(body)
        except ValueError:
            return web.json_response({"error": "body is not JSON"}, status=400)
        if problem := await server.write_store(name, payload):
            return web.json_response({"error": problem}, status=400)
        return web.json_response({"status": "written", "store": name})

    async def forward(request: web.Request) -> web.Response:
        if request.remote not in ("127.0.0.1", "::1"):
            return web.json_response({"error": "only from this machine"}, status=403)
        try:
            asked = await request.json()
        except ValueError:
            return web.json_response({"error": "body is not JSON"}, status=400)
        source = str(asked.get("source") or "")
        if not SOURCE.match(source):
            return web.json_response({"error": "name the source"}, status=400)
        forwarded = await server.forward(source, str(asked.get("conversation") or "main"))
        return web.json_response({"forwarded": forwarded})

    app = web.Application(client_max_size=MAX_BODY_BYTES)
    app.router.add_post("/in/{source}", inbound)
    app.router.add_post("/note", note)
    app.router.add_post("/notify", notify)
    app.router.add_post("/store/{store}", store)
    app.router.add_post("/forward", forward)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, host, port).start()
    logger.info("[app] inbox listening on %s:%d", host or "*", port)
    return runner
