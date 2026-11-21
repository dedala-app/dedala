# SPDX-FileCopyrightText: 2026 Julien Malka
# SPDX-License-Identifier: MIT

"""Hermes's own tools and phrases, in the app's words."""

from typing import Optional
from urllib.parse import urlparse

from ..steps import APP_TOOLS, code, filename, ran, short

# The bridge's bookkeeping: the tools it calls are observed themselves.
BOOKKEEPING = {"tool_search", "tool_describe", "tool_call", "clarify"}

# Hermes's tools while the model writes their call, in words: a tool's name says nothing to him.
WRITING = {"terminal": "Writing a command", "execute_code": "Writing code", "read_file": "Opening a file",
           "write_file": "Writing a file", "patch": "Editing a file", "search_files": "Searching files",
           "web_search": "Searching the web", "web_extract": "Opening a web page", "session_search": "Searching past conversations",
           "skill_view": "Opening a skill", "skills_list": "Listing skills", "skill_manage": "Updating a skill",
           "memory": "Updating memory", "vision_analyze": "Looking at an image", "todo_list": "Updating tasks",
           "delegate_task": "Delegating a task", "cronjob_manage": "Scheduling a job"}


def preparing(tool: str) -> Optional[str]:
    return "Using the browser" if tool.startswith("browser_") else WRITING.get(tool)


def step(phrase: str) -> str:
    """Hermes's Slack-style "is reading /var/……" reads "Reading /var/…"."""
    line = phrase.strip().removeprefix("is ").rstrip("…").strip()
    if tool := named(phrase):
        line = APP_TOOLS.get(tool, "Running a step")
    return line[:1].upper() + line[1:]


def named(phrase: str) -> Optional[str]:
    """The tool named in "is using web_search", else None."""
    line = phrase.strip().removeprefix("is ").rstrip("…").strip()
    if line.startswith("using ") and line != "using":
        return line.removeprefix("using ").split()[0]
    return None


def _skills(args: dict) -> str:
    names = [operation.get("name") for operation in args.get("operations") or [] if isinstance(operation, dict)]
    names = list(dict.fromkeys(filter(None, names + [args.get("name")])))
    if not names:
        return "Updated a skill"
    return f"Updated the {names[0]} skill" if len(names) == 1 else f"Updated the {', '.join(names)} skills"


def describe(tool: str, args: dict) -> Optional[tuple[str, str]]:
    """(line, SF Symbol) for one call of a tool of Hermes's, None for the bridge's own bookkeeping."""
    if tool in BOOKKEEPING:
        return None
    table = {
        "terminal": (ran(args), "terminal"),
        "execute_code": (code(args), "chevron.left.forwardslash.chevron.right"),
        "read_file": (f"Read {filename(args.get('path'))}", "doc.text"),
        "write_file": (f"Wrote {filename(args.get('path'))}", "square.and.pencil"),
        "patch": (f"Edited {filename(args.get('path'))}", "square.and.pencil"),
        "search_files": (f"Searched files for {short(args.get('pattern'), 40)}", "magnifyingglass"),
        "web_search": (f"Searched the web for {short(args.get('query'), 50)}", "globe"),
        "session_search": (f"Searched past conversations for {short(args.get('query'), 40)}", "clock.arrow.circlepath"),
        "skill_view": (f"Read the {args.get('name')} skill", "book"),
        "skills_list": ("Listed skills", "books.vertical"),
        "skill_manage": (_skills(args), "book"),
        "memory": ("Updated memory", "brain"),
        "vision_analyze": ("Looked at an image", "eye"),
        "todo_list": ("Updated tasks", "checklist"),
        "delegate_task": ("Delegated a task", "person.2"),
        "cronjob_manage": ("Scheduled a job", "calendar.badge.clock"),
    }
    if tool in table:
        return table[tool]
    if tool == "web_extract":
        urls = args.get("urls") or [args.get("url")]
        return (f"Read {', '.join(urlparse(str(url)).netloc for url in urls if url)}", "globe")
    if tool.startswith("browser_"):
        return (f"Browsed {urlparse(str(args.get('url'))).netloc}" if args.get("url") else "Used the browser", "safari")
    return (f"Used {tool}", "wrench.and.screwdriver")
