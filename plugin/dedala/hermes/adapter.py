# SPDX-FileCopyrightText: 2026 Julien Malka
# SPDX-License-Identifier: MIT

"""The app as a Hermes platform. The main conversation is the chat `main` and
each topic is a chat of its own, so each is its own session. What the app's
server gives the agent comes in as your messages; what the agent says goes to
the server, and so does what the gateway says of the turn under way.

config.yaml `platforms.app.extra`: `token` (the agent token the relay gave for
an invite; required), `relay` (default https://relay.dedala.app), `name` (the
agent's name in the app), `user_name` (yours, for the sessions), and the
server's settings (`server.Server`).

Everything from the app comes from the user `app`: only the paired phone can
seal what the plugin opens. Allow it with APP_ALLOWED_USERS=app."""

import logging
from typing import Any, Dict, List, Optional

from gateway.config import Platform, PlatformConfig
from gateway.platforms.base import BasePlatformAdapter, SendResult
from gateway.platforms.event import MessageEvent, MessageType

from ..server import Server
from ..steps import symbol
from . import internals, vocabulary
from .agent import HermesAgent

logger = logging.getLogger(__name__)

PLATFORM = "app"

current: Optional["AppAdapter"] = None

# The message id given to the gateway's mid-turn status, so it edits it in place.
STATUS = "status"

# Hermes telling a chat app that a message arrived mid-turn: the app notes it
# under the message itself.
BUSY_ACKS = ("Queued for the next turn", "Steered into current run")


class AppAdapter(BasePlatformAdapter):
    # The gateway hands what the agent is doing ("Reading a file") to set_status_text
    # instead of sending each tool call as a message; it shows as the working line.
    supports_status_text = True

    def __init__(self, config: PlatformConfig):
        super().__init__(config=config, platform=Platform(PLATFORM))
        extra = config.extra or {}
        self.user_name = extra.get("user_name") or "You"
        self.agent_name = extra.get("name") or "Assistant"
        self.agent = HermesAgent(self)
        self.server = Server(internals.home(), self.agent, self.agent_name, str(extra.get("token") or ""), extra.get("relay"), extra)
        self._slashed: set = set()
        global current
        current = self

    async def connect(self, *, is_reconnect: bool = False) -> bool:
        if not self.server.link.token:
            logger.error("[app] no relay token configured (platforms.app.extra.token)")
            return False
        await self.server.start()
        self._mark_connected()
        return True

    async def disconnect(self) -> None:
        self._mark_disconnected()
        await self.server.stop()

    async def send(self, chat_id: str, content: str, reply_to: Optional[str] = None,
                   metadata: Optional[Dict[str, Any]] = None) -> SendResult:
        if (metadata or {}).get("_interim_send"):
            await self._status(chat_id, content)
            return SendResult(success=True, message_id=STATUS)
        if any(ack in content for ack in BUSY_ACKS):
            return SendResult(success=True)
        content = content.split("\n✦ Tip:")[0].rstrip()
        chat = chat_id or "main"
        aside = chat in self._slashed or content.lstrip().startswith("⚠")
        self._slashed.discard(chat)
        try:
            await self.server.said(chat, content, aside=aside)
        except Exception as error:
            logger.warning("[app] could not send: %s", error)
            return SendResult(success=False, error=str(error))
        return SendResult(success=True)

    async def edit_message(self, chat_id: str, message_id: str, content: str, *, finalize: bool = False) -> SendResult:
        if message_id != STATUS:
            return SendResult(success=False, error="the app edits only the working status")
        await self._status(chat_id, content)
        return SendResult(success=True, message_id=STATUS)

    async def _status(self, chat_id: str, content: str) -> None:
        """Mid-turn sends are not messages: what the agent says between steps
        ("Found it, filing it") becomes what it is doing; the gateway's "Working —
        3 min" heartbeat only refreshes it, the app counts the time itself."""
        line = content.strip()
        if line.startswith("⚠"):
            await self.server.said(chat_id or "main", line, aside=True, meanwhile=True)
            return
        if not (line.startswith("⏳") or line.lower().startswith("working")):
            self.server.interim(str(chat_id or "main"), line)
        await self.send_typing(chat_id)

    def set_status_text(self, chat_id: str, text: Optional[str]) -> None:
        """The tool the agent is running in the gateway's words, shown for a call `starting` gave
        no name. Called from its worker thread."""
        super().set_status_text(chat_id, vocabulary.step(text) if text else None)
        if text:
            self.server.status(str(chat_id or "main"), symbol(vocabulary.named(text), vocabulary.step(text), self.agent))

    def stepped(self, chat_id: Optional[str], call: str = "", step: Optional[dict] = None) -> None:
        """A tool call ended: the gateway's words for it are over before its step joins the others,
        so that no view of the turn shows it twice. Called from its worker thread."""
        chat = str(chat_id or "main")
        BasePlatformAdapter.set_status_text(self, chat, None)
        self.server.stepped(chat, call, step)

    async def send_typing(self, chat_id: str, metadata: Optional[Dict[str, Any]] = None) -> None:
        """The gateway's refresh of a turn, every couple of seconds."""
        chat = str(chat_id or "main")
        await self.server.working(chat, lambda: getattr(self, "_status_text", {}).get(chat))

    async def stop_typing(self, chat_id: str) -> None:
        await self.server.rested(chat_id)

    async def get_chat_info(self, chat_id: str) -> Dict[str, Any]:
        return {"name": f"{self.agent_name} app" if chat_id == "main" else f"Topic {chat_id}", "type": "dm"}

    def source_for(self, conversation: str):
        return self.build_source(chat_id=conversation, chat_name=conversation, chat_type="dm",
                                 user_id="app", user_name=self.user_name)

    async def hear(self, conversation: str, text: str, media: Optional[str | List[str]] = None, message_id: Optional[str] = None) -> None:
        """A message from the app, as yours. A command's reply is Hermes speaking for itself."""
        if text.startswith("/"):
            self._slashed.add(conversation)
        event = MessageEvent(text=text, message_type=MessageType.TEXT, source=self.source_for(conversation), message_id=message_id)
        if media:
            event.media_urls = [media] if isinstance(media, str) else list(media)
            event.media_types = ["image/jpeg"] * len(event.media_urls)
        await self.handle_message(event)
