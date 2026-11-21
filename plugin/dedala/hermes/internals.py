# SPDX-FileCopyrightText: 2026 Julien Malka
# SPDX-License-Identifier: MIT

"""Everything the plugin takes from Hermes beyond the plugin API, in one place.
Some of it is internal to Hermes and can move with an upgrade: `missing` says at
start what is gone and what the app loses with it, instead of each part finding
out alone, later, or never."""

import importlib
import json
import logging
import os
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)

# The toolset and the tools Hermes must offer the model directly (see `surface_directly`).
DIRECT_TOOLSET = "app"
DIRECT_TOOLS = {"cronjob_manage"}

# What the plugin uses of each module, and what the app loses without it.
USED = (
    ("gateway.session_context", ("get_session_env",), "tool calls do not know which conversation they are in: they go to main"),
    ("gateway.platforms.base", ("BasePlatformAdapter.handle_message", "BasePlatformAdapter.build_source", "BasePlatformAdapter.set_status_text",
                                "BasePlatformAdapter._mark_connected", "BasePlatformAdapter._mark_disconnected"), "the app platform cannot run"),
    ("tools.vision_tools", ("vision_analyze_tool",), "cards and pages are sent without a review"),
    ("cron.jobs", ("list_jobs", "get_job", "trigger_job", "pause_job", "resume_job"), "Activity, page upkeep and handlers are off"),
    ("cron.jobs", ("create_job", "update_job", "remove_job", "get_cron_output_dir"), "commands run without a supervisor, and one bound to a job has no result"),
    ("cron.executions", ("list_executions",), "Activity shows no runs"),
    ("tools.cronjob_tools", ("execute_job_for_event",), "a job asked for now runs at the cron's next tick, and inbox handlers get no prompt of their own"),
    ("tools.async_delegation", ("list_async_delegations",), "Activity does not show delegated work"),
    ("agent.chat_completion_helpers_tool_calls", ("_ToolCallAccumulator.feed",), "nothing moves in the app while the model writes a long tool call"),
    ("tools.tool_search", ("_DIRECT_SURFACE_TOOLSETS", "ToolSearchConfig.effective_defer_tools"), "the app tools stay behind tool_search, where long arguments break"),
)


def home() -> Path:
    """Where the plugin keeps its state, under HERMES_HOME. The plugin was
    hermes_app before: its folder moves here once, and a link keeps the old
    path working for whatever the agent wrote that names it."""
    root = Path(os.environ.get("HERMES_HOME") or Path.home() / ".hermes")
    current, former = root / "dedala", root / "hermes_app"
    if not current.exists() and former.is_dir() and not former.is_symlink():
        former.rename(current)
        former.symlink_to(current.name)
    return current


def _module(name: str):
    try:
        return importlib.import_module(name)
    except ImportError:
        return None


def missing() -> list[str]:
    """What the plugin uses of Hermes that this Hermes does not have, each with what it costs."""
    found = []
    for name, attributes, cost in USED:
        module = _module(name)
        gone = [attribute for attribute in attributes if not _has(module, attribute)]
        if gone:
            found.append(f"{name} has no {', '.join(gone)}: {cost}" if module is not None else f"no {name}: {cost}")
    return found


def _has(module, path: str) -> bool:
    value = module
    for part in path.split("."):
        if value is None or not hasattr(value, part):
            return False
        value = getattr(value, part)
    return True


def session(name: str) -> str | None:
    """A value of the session a tool call or a hook runs in; None outside Hermes."""
    module = _module("gateway.session_context")
    return module.get_session_env(name) if module is not None else None


def cron():
    """Hermes's cron jobs (`cron.jobs`), or None where there is no cron."""
    return _module("cron.jobs")


def executions(limit: int) -> list[dict] | None:
    """The last runs of cron jobs, newest first; None where there is no cron."""
    module = _module("cron.executions")
    return module.list_executions(limit=limit) if module is not None else None


def execute_now() -> Callable | None:
    """What fires a job at once, the way Hermes's webhooks do; None on a Hermes without it."""
    module = _module("tools.cronjob_tools")
    return getattr(module, "execute_job_for_event", None)


def delegations() -> list[dict]:
    """The work handed to subagents in the background."""
    module = _module("tools.async_delegation")
    return module.list_async_delegations() if module is not None else []


async def see(picture: str, question: str) -> str:
    """What Hermes's vision model answers about a picture."""
    from tools.vision_tools import vision_analyze_tool

    answer = await vision_analyze_tool(picture, question)
    try:
        return json.loads(answer).get("analysis") or answer
    except (ValueError, AttributeError):
        return str(answer)


def count_tool_arguments(counted: Callable[[int, str | None], None]) -> None:
    """Hermes has no hook for the arguments of a tool call while the model writes
    them, which can take minutes for a page: their chunks are counted where they
    are assembled, `counted` given each chunk's length and the tool's name."""
    try:
        from agent import chat_completion_helpers_tool_calls as module

        accumulator = module._ToolCallAccumulator
        original = accumulator.feed
    except (ImportError, AttributeError) as error:
        logger.warning("[app] tool calls are not counted while written: %s", error)
        return
    if getattr(original, "counted_by_app", False):
        return

    def feed(self, tc_delta):
        name = original(self, tc_delta)
        function = getattr(tc_delta, "function", None)
        arguments = getattr(function, "arguments", None)
        if arguments:
            names = [entry.get("function", {}).get("name") for entry in self.acc.values()]
            counted(len(arguments), next((n for n in reversed(names) if n), None))
        return name

    feed.counted_by_app = True
    accumulator.feed = feed


def surface_directly() -> None:
    """Hermes puts plugin tools behind tool_search/tool_call, where arguments
    travel as a JSON string inside JSON: long ones break. The app tools exist
    only in app sessions, like the GUI toolsets Hermes keeps direct; the cron
    tool, which keeps pages up to date with long prompts, is deferred by default
    (in the defaults merged into every config)."""
    try:
        from tools import tool_search

        tool_search._DIRECT_SURFACE_TOOLSETS = frozenset(tool_search._DIRECT_SURFACE_TOOLSETS | {DIRECT_TOOLSET})
        config = tool_search.ToolSearchConfig
        deferred = config.effective_defer_tools.fget
        if not getattr(deferred, "kept_direct_by_app", False):
            def effective(self):
                return frozenset(deferred(self) - DIRECT_TOOLS)

            effective.kept_direct_by_app = True
            config.effective_defer_tools = property(effective)
    except (ImportError, AttributeError) as error:
        logger.warning("[app] the app tools stay behind tool_search: %s", error)
