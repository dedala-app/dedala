# SPDX-FileCopyrightText: 2026 Julien Malka
# SPDX-License-Identifier: MIT

"""What the link and adapter tests share: a phone as the relay sees it, and a
Hermes small enough to load the adapter without the gateway."""

import asyncio
import dataclasses
import enum
import json
import sys
import types
from pathlib import Path

import aiohttp
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "relay"))
sys.path.insert(0, str(ROOT / "plugin"))

from dedala import seal  # noqa: E402
from dedala.link import Link, pair  # noqa: E402


class Phone:
    """The app, as far as the relay can tell: claims the code, reads sealed ops, sends sealed events."""

    def __init__(self, relay: str):
        self.relay = relay
        self.key = X25519PrivateKey.generate()
        self.token = None
        self.keys = None
        self.seq = 0

    async def claim(self, code: str) -> None:
        parsed = json.loads(code)
        device_key = seal.public(self.key)
        async with aiohttp.ClientSession() as http:
            async with http.post(f"{self.relay}/pairings/{parsed['pairing']}/claim", json={
                "claim": parsed["claim"], "device_key": device_key, "mac": seal.proof_mac(parsed["proof"], device_key),
                "name": "Test iPhone", "apns": {"environment": "development"},
            }) as response:
                self.token = (await response.json())["device_token"]
        self.keys = seal.keys(self.key, parsed["agent_key"], parsed["pairing"])

    async def ops(self) -> list:
        async with aiohttp.ClientSession(headers={"Authorization": f"Bearer {self.token}"}) as http:
            async with http.get(f"{self.relay}/mailbox") as response:
                messages = (await response.json())["messages"]
        return [op for message in messages for op in seal.unseal(self.keys[0], message)]

    async def send(self, events: list, socket=None) -> None:
        self.seq += 1
        message = seal.seal(self.keys[1], self.seq, events)
        if socket is not None:
            await socket.send_json({"send": message})
            return
        async with aiohttp.ClientSession(headers={"Authorization": f"Bearer {self.token}"}) as http:
            await http.post(f"{self.relay}/mailbox", json=message)


async def held_for_the_agent(relay) -> list:
    """What the relay still holds for the agent: nothing once it acknowledged everything."""
    url, token = relay
    async with aiohttp.ClientSession(headers={"Authorization": f"Bearer {token}"}) as http:
        async with http.get(f"{url}/mailbox") as response:
            return (await response.json())["messages"]


async def paired(relay, home):
    url, token = relay
    link = Link(home, url, token, "Jacques")
    await link.start()
    phone = Phone(url)
    codes = asyncio.Queue()
    pairing = asyncio.create_task(pair(home, url, token, "Jacques", codes.put_nowait))
    await phone.claim(await codes.get())
    assert (await pairing)["device"] == "Test iPhone"
    for _ in range(50):
        if link.identity.paired and link.state["seq_out"] >= 1:
            break
        await asyncio.sleep(0.05)
    return link, phone


async def online(relay, link, phone):
    http = aiohttp.ClientSession(headers={"Authorization": f"Bearer {phone.token}"})
    socket = await http.ws_connect(f"{phone.relay}/ws")
    for _ in range(50):
        if link.app_online:
            break
        await asyncio.sleep(0.05)
    assert link.app_online
    return http, socket


async def until(condition):
    for _ in range(100):
        if condition():
            return
        await asyncio.sleep(0.05)
    assert condition()


def fake_hermes() -> None:
    """The parts of Hermes's gateway the adapter builds on, recording what it is given."""
    if "gateway.platforms.base" in sys.modules:
        return

    class MessageType(enum.Enum):
        TEXT = "text"

    @dataclasses.dataclass
    class MessageEvent:
        text: str
        message_type: MessageType = MessageType.TEXT
        source: object = None
        message_id: str | None = None
        media_urls: list = dataclasses.field(default_factory=list)
        media_types: list = dataclasses.field(default_factory=list)

    @dataclasses.dataclass
    class SendResult:
        success: bool
        message_id: str | None = None
        error: str | None = None

    @dataclasses.dataclass
    class PlatformConfig:
        extra: dict

    class BasePlatformAdapter:
        def __init__(self, config, platform):
            self.config, self.platform = config, platform
            self.heard: list[MessageEvent] = []

        def build_source(self, **source):
            return source

        async def handle_message(self, event) -> None:
            self.heard.append(event)

        def set_status_text(self, chat_id, text) -> None:
            store = self.__dict__.setdefault("_status_text", {})
            if text:
                store[str(chat_id)] = text
            else:
                store.pop(str(chat_id), None)

        def _mark_connected(self) -> None:
            pass

        def _mark_disconnected(self) -> None:
            pass

    modules = {
        "gateway": {},
        "gateway.config": {"Platform": lambda name: name, "PlatformConfig": PlatformConfig},
        "gateway.platforms": {},
        "gateway.platforms.base": {"BasePlatformAdapter": BasePlatformAdapter, "SendResult": SendResult},
        "gateway.platforms.event": {"MessageEvent": MessageEvent, "MessageType": MessageType},
    }
    for name, contents in modules.items():
        module = types.ModuleType(name)
        module.__dict__.update(contents)
        sys.modules[name] = module
