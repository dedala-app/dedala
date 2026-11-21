# SPDX-FileCopyrightText: 2026 Julien Malka
# SPDX-License-Identifier: MIT

"""Where a tool call runs: the conversation it belongs to, the agent that makes
it, the link to the phone, and the server's loop, where the connection and the
plugin's state live."""

import asyncio
import json

from .agents import Agent


def agent() -> Agent:
    """The agent the server serves; one that can do nothing where no server runs."""
    from . import server

    return server.current.agent if server.current is not None else Agent()


def conversation_of(args: dict) -> str:
    return args.get("conversation") or agent().conversation() or "main"


def link():
    from . import server

    if server.current is None or server.current.loop is None:
        raise RuntimeError("The app platform is not running in this gateway")
    return server.current.link


async def on_gateway(work):
    """Runs relay work on the server's loop, where the connection lives: the agent
    may run async tools on a loop of their own in another thread."""
    from . import server

    return await asyncio.wrap_future(asyncio.run_coroutine_threadsafe(work, server.current.loop))


async def run(change, *args):
    """A change to the plugin's state, for `on_gateway`: the state has one
    writer, the gateway's loop."""
    return change(*args)


def answer(value) -> str:
    return json.dumps(value, ensure_ascii=False)


def said_cards():
    """The cards drawn, as they last stood (bank.Cards), kept by the server."""
    from . import server

    return server.current.cards
