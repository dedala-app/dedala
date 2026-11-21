# SPDX-FileCopyrightText: 2026 Julien Malka
# SPDX-License-Identifier: MIT

"""What Hermes loads: the app as a platform, the tools to draw in it, the hooks
that see the agent work, and `hermes dedala pair`."""

import asyncio
import logging
import os
import shutil
import subprocess
from pathlib import Path

from .. import schemas, steps
from . import agent, internals

logger = logging.getLogger(__name__)


def _observe(tool_name: str = "", args=None, status=None, task_id: str = "", session_id: str = "", tool_call_id: str = "", **_) -> None:
    """Every tool call in an app session becomes a step of the trace above the agent's next message,
    and in a cron run a step of that run in Activity."""
    from . import adapter

    if run := agent.run_of(task_id):
        if adapter.current and (step := steps.describe(tool_name, args or {}, adapter.current.agent)):
            line, symbol = step
            adapter.current.server.runs.step(*run, session_id, {"text": line, "symbol": symbol, **({"failed": True} if status == "error" else {})})
        return
    if internals.session("HERMES_SESSION_PLATFORM") != "app":
        return
    conversation = internals.session("HERMES_SESSION_CHAT_ID") or "main"
    if adapter.current is None:
        return
    step = steps.describe(tool_name, args or {}, adapter.current.agent)
    adapter.current.stepped(conversation, tool_call_id or "",
                            step and {"text": step[0], "symbol": step[1], **({"failed": True} if status == "error" else {})})


def _starting(tool_name: str = "", args=None, task_id: str = "", tool_call_id: str = "", **_) -> None:
    """A tool call about to run in an app session is said in the words of the step it will leave."""
    from . import adapter

    if adapter.current is None or agent.run_of(task_id) or internals.session("HERMES_SESSION_PLATFORM") != "app":
        return
    if step := steps.running(tool_name, args if isinstance(args, dict) else {}, adapter.current.agent):
        adapter.current.server.starting(internals.session("HERMES_SESSION_CHAT_ID") or "main", tool_call_id or "", *step)


def _streamed(delta: str = "", kind: str = "text", session_id: str = "", **_) -> None:
    from . import adapter

    if not (adapter.current and delta):
        return
    server = adapter.current.server
    if _in_cron():
        server.runs.stream(session_id, len(delta), "Thinking" if kind == "reasoning" else "Writing", server.running)
    else:
        server.note_stream(len(delta), None if kind == "reasoning" else "Writing the reply")


def _in_cron() -> bool:
    return internals.session("HERMES_CRON_SESSION") == "1"


def _counted(characters: int, tool: str | None) -> None:
    """A chunk of a tool call's arguments, as the model writes them."""
    from . import adapter

    if adapter.current is None:
        return
    server = adapter.current.server
    doing = steps.preparing(tool, server.agent)
    if _in_cron():
        server.runs.stream("", characters, doing, server.running)
    else:
        server.note_stream(characters, doing, steps.symbol(tool, "", server.agent))


def _pair_setup(parser) -> None:
    commands = parser.add_subparsers(dest="app_command")
    pair = commands.add_parser("pair", help="pair the app: prints a QR code to scan in its Settings")
    pair.add_argument("--token-file", default=os.environ.get("DEDALA_TOKEN_FILE"), help="file holding the relay's agent token")
    pair.add_argument("--relay", default=os.environ.get("DEDALA_RELAY", "https://relay.dedala.app"))
    pair.add_argument("--name", default=os.environ.get("DEDALA_NAME", "Assistant"))


def _show(code: str) -> None:
    if shutil.which("qrencode"):
        subprocess.run(["qrencode", "-t", "ANSIUTF8", "-m", "2", code], check=False)
    print("\nIn the app: Settings › Pair with your agent, and scan this code (or paste the text below).\n")
    print(code, flush=True)


def _pair(args) -> int:
    from ..link import pair

    if getattr(args, "app_command", None) != "pair":
        print("usage: hermes dedala pair [--token-file FILE]")
        return 2
    token = os.environ.get("DEDALA_TOKEN") or (Path(args.token_file).read_text().strip() if args.token_file else "")
    if not token:
        print("No relay token: pass --token-file or set DEDALA_TOKEN")
        return 2
    result = asyncio.run(pair(internals.home(), args.relay, token, args.name, _show))
    print(f"\nPaired with {result['device']}. The gateway sends it what you built and what was said.")
    return 0


def skills() -> list[tuple[str, Path, str]]:
    """The skills the plugin brings, read-only: each folder under skills/ with
    its SKILL.md, named and described by the file's front matter."""
    found = []
    for path in sorted((Path(__file__).resolve().parents[1] / "skills").glob("*/SKILL.md")):
        text = path.read_text()
        head = text.split("---")[1] if text.startswith("---") else ""
        fields = dict(line.split(": ", 1) for line in head.strip().splitlines() if ": " in line)
        found.append((fields.get("name") or path.parent.name, path, fields.get("description", "")))
    return found


def register(ctx) -> None:
    agent.context = ctx
    for gone in internals.missing():
        logger.warning("[app] this Hermes differs from the one the plugin was written for: %s", gone)
    internals.surface_directly()
    internals.count_tool_arguments(_counted)
    from .adapter import AppAdapter

    configured = lambda cfg: bool((getattr(cfg, "extra", None) or {}).get("token"))  # noqa: E731
    ctx.register_platform(
        name="app", label="Dedala", adapter_factory=lambda cfg: AppAdapter(cfg), check_fn=lambda: True,
        validate_config=configured, is_connected=configured, emoji="📱", cron_deliver_env_var="APP_HOME_CHANNEL",
        allowed_users_env="APP_ALLOWED_USERS", platform_hint=schemas.PLATFORM_HINT,
        display_tier="high", display_overrides={"tool_progress": "off", "busy_steer_ack_enabled": False})
    for handler, schema in schemas.TOOLS:
        run = schemas.structured(handler, schema)
        schema["parameters"]["properties"]["from_file"] = schemas.FROM_FILE
        schema["parameters"]["required"] = []
        ctx.register_tool(name=schema["name"], toolset="app", schema=schema, handler=run, is_async=True,
                          description=schema["description"], emoji="📱")
    ctx.register_hook("pre_tool_call", _starting)
    ctx.register_hook("post_tool_call", _observe)
    ctx.register_hook("on_stream_delta", _streamed)
    for name, path, description in skills():
        ctx.register_skill(name, path, description)
    ctx.register_cli_command(name="dedala", help="the Dedala app", setup_fn=_pair_setup, handler_fn=_pair,
                             description="Pair the iPhone app with this Hermes")
