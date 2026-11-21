# SPDX-FileCopyrightText: 2026 Julien Malka
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The relay's HTTP and WebSocket API, as described in docs/relay.md."""

import asyncio
import contextlib
import json
import logging
import time

from aiohttp import WSMsgType, web

from .apns import APNs
from .store import TO_AGENT, TO_APP, Device, Refused, Store

log = logging.getLogger("hermes_relay")

STORE = web.AppKey("store", Store)
APNS = web.AppKey("apns", APNs)
SOCKETS = web.AppKey("sockets", dict)
CLOSING = web.AppKey("closing", set)
CHANNEL_LIMIT = 20
MESSAGE_LIMIT = 512 * 1024


class Caller:
    """Who is calling: an agent, or the device paired with it."""

    def __init__(self, agent: str, device: Device | None = None):
        self.agent = agent
        self.device = device

    @property
    def side(self) -> str:
        return "app" if self.device else "agent"

    @property
    def outbox(self) -> str:
        return TO_AGENT if self.device else TO_APP

    @property
    def inbox(self) -> str:
        return TO_APP if self.device else TO_AGENT

    @property
    def other(self) -> str:
        return "agent" if self.device else "app"


def bearer(request: web.Request) -> str:
    header = request.headers.get("Authorization", "")
    return header.removeprefix("Bearer ").strip()


def caller(request: web.Request) -> Caller:
    store, secret = request.app[STORE], bearer(request)
    if agent := store.agent(secret):
        return Caller(agent)
    if device := store.device(secret):
        return Caller(device.agent, device)
    raise web.HTTPUnauthorized(text=json.dumps({"error": "Unknown token"}), content_type="application/json")


def agent_only(request: web.Request) -> str:
    who = caller(request)
    if who.device:
        raise web.HTTPForbidden(text=json.dumps({"error": "Only the agent can do this"}), content_type="application/json")
    return who.agent


def device_only(request: web.Request) -> Device:
    who = caller(request)
    if not who.device:
        raise web.HTTPForbidden(text=json.dumps({"error": "Only the paired device can do this"}), content_type="application/json")
    return who.device


async def body(request: web.Request) -> dict:
    try:
        value = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise web.HTTPBadRequest(text=json.dumps({"error": "The body is not JSON"}), content_type="application/json")
    if not isinstance(value, dict):
        raise web.HTTPBadRequest(text=json.dumps({"error": "The body is a JSON object"}), content_type="application/json")
    return value


@web.middleware
async def refusals(request: web.Request, handler):
    try:
        return await handler(request)
    except Refused as refused:
        return web.json_response({"error": refused.reason}, status=refused.status)


async def deliver(app: web.Application, agent: str, side: str, frame: dict) -> None:
    socket = app[SOCKETS].get((agent, side))
    if socket is not None and not socket.closed:
        with contextlib.suppress(ConnectionResetError):
            await socket.send_json(frame)


async def accept(app: web.Application, who: Caller, message: dict) -> int:
    if len(json.dumps(message)) > MESSAGE_LIMIT:
        raise Refused(413, "A message is at most 512KB; send bigger things in several")
    seq = app[STORE].put(who.agent, who.outbox, message)
    log.info("%s %s → %s seq %s, %d bytes", who.agent, who.side, who.other, seq, len(message.get("box", "")))
    await deliver(app, who.agent, who.other, {"message": {"seq": seq, "nonce": message["nonce"], "box": message["box"]}})
    return seq


# Accounts and pairing


async def health(request: web.Request) -> web.Response:
    return web.json_response({"ok": True})


async def register(request: web.Request) -> web.Response:
    value = await body(request)
    agent, secret = request.app[STORE].register(str(value.get("invite", "")), str(value.get("name", "Hermes"))[:60])
    log.info("%s registered", agent)
    return web.json_response({"agent_id": agent, "agent_token": secret}, status=201)


async def open_pairing(request: web.Request) -> web.Response:
    agent = agent_only(request)
    claim_hash = (await body(request)).get("claim_hash")
    if not isinstance(claim_hash, str) or len(claim_hash) != 64:
        raise Refused(400, "claim_hash is the hex SHA-256 of the claim")
    pairing, expires = request.app[STORE].open_pairing(agent, claim_hash)
    return web.json_response({"pairing": pairing, "expires": expires}, status=201)


async def claim_pairing(request: web.Request) -> web.Response:
    value = await body(request)
    apns = value.get("apns") or {}
    if not isinstance(apns, dict):
        raise Refused(400, "apns is {environment, token, start_token}")
    environment = apns.get("environment", "development")
    if environment not in ("development", "production"):
        raise Refused(400, "apns.environment is development or production")
    for field in ("claim", "device_key", "mac"):
        if not isinstance(value.get(field), str):
            raise Refused(400, f"{field} is required")
    agent, device, secret = request.app[STORE].claim(
        request.match_info["pairing"],
        value["claim"],
        value["device_key"],
        value["mac"],
        str(value.get("name", "iPhone"))[:60],
        environment,
        apns.get("token"),
        apns.get("start_token"),
    )
    log.info("%s paired with %s", agent, device)
    paired = {"pairing": request.match_info["pairing"], "device": {"key": value["device_key"], "mac": value["mac"], "name": value.get("name", "iPhone")}}
    await deliver(request.app, agent, "app", {"replaced": True})
    retire(request.app, (agent, "app"))
    await free_channels(request.app, agent)
    await deliver(request.app, agent, "agent", {"paired": paired})
    return web.json_response({"device_id": device, "device_token": secret, "agent_name": request.app[STORE].agent_name(agent)}, status=201)


async def pairing_status(request: web.Request) -> web.Response:
    status = request.app[STORE].pairing(agent_only(request), request.match_info["pairing"])
    if status is None:
        raise Refused(404, "No such pairing")
    return web.json_response(status)


async def device_info(request: web.Request) -> web.Response:
    device = request.app[STORE].device_of(agent_only(request))
    if device is None:
        raise Refused(404, "No device is paired")
    return web.json_response({
        "id": device.id, "name": device.name, "key": device.key, "environment": device.environment,
        "notifications": device.apns is not None, "activities": device.start is not None,
        "online": (socket := request.app[SOCKETS].get((device.agent, "app"))) is not None and not socket.closed,
    })


async def update_apns(request: web.Request) -> web.Response:
    device = device_only(request)
    value = await body(request)
    environment = value.get("environment", device.environment)
    if environment not in ("development", "production"):
        raise Refused(400, "environment is development or production")
    request.app[STORE].update_apns(device.id, environment, value.get("token", device.apns), value.get("start_token", device.start))
    return web.json_response({"ok": True})


# Mailbox


async def mailbox(request: web.Request) -> web.Response:
    who = caller(request)
    try:
        after = int(request.query.get("after", "-1"))
    except ValueError:
        raise Refused(400, "after is a sequence number")
    return web.json_response({"messages": request.app[STORE].waiting(who.agent, who.inbox, after)})


async def post_mailbox(request: web.Request) -> web.Response:
    who = caller(request)
    if who.device is None and request.app[STORE].device_of(who.agent) is None:
        raise Refused(409, "No device is paired")
    return web.json_response({"stored": await accept(request.app, who, await body(request))})


async def ack_mailbox(request: web.Request) -> web.Response:
    who = caller(request)
    seq = (await body(request)).get("seq")
    if not isinstance(seq, int):
        raise Refused(400, "seq is required")
    request.app[STORE].ack(who.agent, who.inbox, seq)
    return web.json_response({"ok": True})


def retire(app: web.Application, key: tuple[str, str]) -> None:
    """Takes a side's connection out of live delivery and closes it without
    waiting: a peer that died silently takes seconds to close."""
    previous = app[SOCKETS].pop(key, None)
    if previous is None or previous.closed:
        return
    closing = asyncio.create_task(previous.close())
    app[CLOSING].add(closing)
    closing.add_done_callback(app[CLOSING].discard)


async def free_channels(app: web.Application, agent: str) -> None:
    """The activities of the phone that was paired before are no longer the agent's to update."""
    for channel in app[STORE].channels(agent):
        if APNS in app and (environment := app[STORE].channel_environment(agent, channel)):
            await app[APNS].delete_channel(environment, channel)
        app[STORE].remove_channel(agent, channel)


async def backlog(app: web.Application, who: Caller, ws: web.WebSocketResponse) -> None:
    """Sends what waited, then joins live delivery: a message stored meanwhile
    is sent here too, so nothing live ever overtakes what waited."""
    sent: set[int] = set()
    while fresh := [message for message in app[STORE].waiting(who.agent, who.inbox) if message["seq"] not in sent]:
        for message in fresh:
            await ws.send_json({"message": message})
            sent.add(message["seq"])
    retire(app, (who.agent, who.side))
    app[SOCKETS][(who.agent, who.side)] = ws


async def socket(request: web.Request) -> web.WebSocketResponse:
    who = caller(request)
    ws = web.WebSocketResponse(heartbeat=30)
    await ws.prepare(request)
    sockets = request.app[SOCKETS]
    retire(request.app, (who.agent, who.side))
    log.info("%s %s connected", who.agent, who.side)
    if who.device:
        agent_socket = sockets.get((who.agent, "agent"))
        await ws.send_json({"agent": "online" if agent_socket is not None and not agent_socket.closed else "offline"})
    else:
        await deliver(request.app, who.agent, "app", {"agent": "online"})
    await backlog(request.app, who, ws)
    await ws.send_json({"caught_up": True})
    if who.device:
        await deliver(request.app, who.agent, "agent", {"app": "online"})
    elif (app_socket := sockets.get((who.agent, "app"))) is not None and not app_socket.closed:
        await ws.send_json({"app": "online"})
    try:
        async for frame in ws:
            if frame.type != WSMsgType.TEXT:
                continue
            seq = None
            try:
                value = json.loads(frame.data)
                if "send" in value:
                    seq = value["send"].get("seq")
                    await ws.send_json({"stored": await accept(request.app, who, value["send"])})
                elif isinstance(value.get("ack"), int):
                    request.app[STORE].ack(who.agent, who.inbox, value["ack"])
            except Refused as refused:
                await ws.send_json({"error": refused.reason, **({"seq": seq} if isinstance(seq, int) else {})})
            except (json.JSONDecodeError, TypeError, AttributeError):
                await ws.send_json({"error": "Frames are {send: message} or {ack: seq}"})
    finally:
        if sockets.get((who.agent, who.side)) is ws:
            del sockets[(who.agent, who.side)]
            await deliver(request.app, who.agent, who.other, {"app" if who.device else "agent": "offline"})
        log.info("%s %s disconnected", who.agent, who.side)
    return ws


# Blobs


async def put_blob(request: web.Request) -> web.Response:
    who = caller(request)
    body = await request.read()
    blob = request.app[STORE].put_blob(who.agent, who.side, body)
    log.info("%s %s stored a blob of %d bytes", who.agent, who.side, len(body))
    return web.json_response({"blob": blob}, status=201)


async def get_blob(request: web.Request) -> web.Response:
    who = caller(request)
    body = request.app[STORE].blob(who.agent, request.match_info["blob"])
    if body is None:
        raise Refused(404, "No such blob")
    return web.Response(body=body, content_type="application/json")


async def delete_blob(request: web.Request) -> web.Response:
    who = caller(request)
    request.app[STORE].remove_blob(who.agent, request.match_info["blob"])
    return web.json_response({"ok": True})


async def clear_blobs(request: web.Request) -> web.Response:
    """The caller takes back the blobs it stored and nothing fetched, those
    older than `older` seconds: what a failed upload left behind, so the store
    has room again, while what the other side is still fetching stays."""
    who = caller(request)
    try:
        older = max(0.0, float(request.query.get("older", 0)))
    except ValueError:
        raise Refused(400, "older is a number of seconds") from None
    gone = request.app[STORE].clear_blobs(who.agent, who.side, older)
    log.info("%s %s cleared %d blob(s) older than %ss", who.agent, who.side, gone, older)
    return web.json_response({"cleared": gone})


# Push


def push(request: web.Request) -> APNs:
    if APNS not in request.app:
        raise Refused(503, "This relay has no APNs key; pushes are off")
    return request.app[APNS]


def push_target(request: web.Request) -> tuple[str, Device]:
    agent = agent_only(request)
    device = request.app[STORE].device_of(agent)
    if device is None:
        raise Refused(409, "No device is paired")
    return agent, device


def answer(request: web.Request, device: Device, which: str, result) -> web.Response:
    if result.gone:
        request.app[STORE].drop_apns(device.id, which)
    return web.json_response({"status": result.status, "reason": result.reason}, status=200 if result.ok else 502)


async def notify(request: web.Request) -> web.Response:
    agent, device = push_target(request)
    value = await body(request)
    if not device.apns:
        raise Refused(409, "The device has not allowed notifications")
    name = request.app[STORE].agent_name(agent)
    if value.get("silent"):
        payload = {"aps": {"content-available": 1}, "wake": True}
        result = await push(request).alert(device.environment, device.apns, payload, value.get("collapse"), silent=True)
        return answer(request, device, "apns", result)
    payload = {
        "aps": {"alert": {"title": name, "body": f"New message from {name}"}, "mutable-content": 1, "sound": "default", "thread-id": "agent"},
    }
    if "box" in value:
        payload["sealed"] = value["box"]
    else:
        payload["wake"] = True
    if value.get("ring"):
        payload["ring"] = True
    result = await push(request).alert(device.environment, device.apns, payload, value.get("collapse"))
    return answer(request, device, "apns", result)


async def create_channel(request: web.Request) -> web.Response:
    agent, device = push_target(request)
    if len(request.app[STORE].channels(agent)) >= CHANNEL_LIMIT:
        raise Refused(429, f"An agent has at most {CHANNEL_LIMIT} channels; delete the ones whose activity ended")
    result = await push(request).create_channel(device.environment)
    if not result.ok or not result.channel:
        return web.json_response({"status": result.status, "reason": result.reason}, status=502)
    request.app[STORE].add_channel(agent, result.channel, device.environment)
    return web.json_response({"channel": result.channel}, status=201)


async def delete_channel(request: web.Request) -> web.Response:
    agent = agent_only(request)
    channel = request.match_info["channel"]
    environment = request.app[STORE].channel_environment(agent, channel)
    if environment is None:
        raise Refused(404, "No such channel")
    await push(request).delete_channel(environment, channel)
    request.app[STORE].remove_channel(agent, channel)
    return web.json_response({"ok": True})


def activity_aps(request: web.Request, agent: str, value: dict, event: str) -> dict:
    if not isinstance(value.get("data"), str):
        raise Refused(400, "data is the activity's state as a string (a sealed box)")
    aps = {"timestamp": int(time.time()), "event": event, "content-state": {"data": value["data"]}}
    if value.get("alert") is not None or event == "start":
        name = request.app[STORE].agent_name(agent)
        alert = value.get("alert") or {"title": name, "body": "Live update"}
        aps["alert"] = {"title": alert.get("title", name), "body": alert.get("body", ""), "sound": "default"}
    if event == "end":
        aps["dismissal-date"] = int(value.get("dismiss_at", time.time() + 15 * 60))
    return aps


async def start_activity(request: web.Request) -> web.Response:
    agent, device = push_target(request)
    if not device.start:
        raise Refused(409, "The device has not allowed Live Activities")
    value = await body(request)
    aps = activity_aps(request, agent, value, "start")
    aps["attributes-type"] = "HermesActivityAttributes"
    aps["attributes"] = {"id": str(value.get("id", "activity")), "design": value.get("design")}
    if value.get("channel"):
        if request.app[STORE].channel_environment(agent, value["channel"]) is None:
            raise Refused(404, "No such channel")
        aps["input-push-channel"] = value["channel"]
    result = await push(request).activity(device.environment, device.start, {"aps": aps})
    return answer(request, device, "start", result)


async def broadcast(request: web.Request) -> web.Response:
    agent = agent_only(request)
    value = await body(request)
    environment = request.app[STORE].channel_environment(agent, str(value.get("channel")))
    if environment is None:
        raise Refused(404, "No such channel")
    event = value.get("event", "update")
    if event not in ("update", "end"):
        raise Refused(400, "event is update or end")
    result = await push(request).broadcast(environment, value["channel"], {"aps": activity_aps(request, agent, value, event)})
    return web.json_response({"status": result.status, "reason": result.reason}, status=200 if result.ok else 502)


# Application


async def sweep(app: web.Application):
    async def loop():
        while True:
            gone = app[STORE].sweep()
            if gone:
                log.info("dropped %d messages older than 7 days", gone)
            await asyncio.sleep(3600)

    task = asyncio.create_task(loop())
    yield
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    if APNS in app:
        await app[APNS].close()


async def close_sockets(app: web.Application) -> None:
    """Stopping closes the agents' and apps' connections instead of waiting for
    them: they reconnect to the next relay on their own."""
    for socket in list(app[SOCKETS].values()):
        await socket.close(code=1001, message=b"relay restarting")
    for closing in list(app[CLOSING]):
        closing.cancel()


def create_app(store: Store, apns: APNs | None) -> web.Application:
    app = web.Application(middlewares=[refusals], client_max_size=2 * 1024 * 1024 + 4096)
    app[STORE] = store
    if apns is not None:
        app[APNS] = apns
    app[SOCKETS] = {}
    app[CLOSING] = set()
    app.cleanup_ctx.append(sweep)
    app.on_shutdown.append(close_sockets)
    app.add_routes([
        web.get("/health", health),
        web.post("/agents", register),
        web.post("/pairings", open_pairing),
        web.post("/pairings/{pairing}/claim", claim_pairing),
        web.get("/pairings/{pairing}", pairing_status),
        web.get("/device", device_info),
        web.post("/device/apns", update_apns),
        web.get("/mailbox", mailbox),
        web.post("/mailbox", post_mailbox),
        web.post("/mailbox/ack", ack_mailbox),
        web.get("/ws", socket),
        web.post("/blobs", put_blob),
        web.get("/blobs/{blob}", get_blob),
        web.delete("/blobs/{blob}", delete_blob),
        web.delete("/blobs", clear_blobs),
        web.post("/push/notify", notify),
        web.post("/channels", create_channel),
        web.delete("/channels/{channel}", delete_channel),
        web.post("/push/activity/start", start_activity),
        web.post("/push/activity/broadcast", broadcast),
    ])
    return app
