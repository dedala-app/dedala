# SPDX-FileCopyrightText: 2026 Julien Malka
# SPDX-License-Identifier: MIT

"""What the agent did, one line per tool call, for the trace above its next
message in the app. The app's own tools are said here; the agent's own, in the
words it gives for them (`Agent.describe`), with what helps any agent say a
shell line or a script."""

import re
import shlex
from itertools import dropwhile
from pathlib import PurePath
from urllib.parse import urlparse

# The cards show for themselves.
DRAWN = {"app_card", "app_patch"}

# The app's tools while the model writes their call.
APP_TOOLS = {"app_card": "Drawing a card", "app_patch": "Updating a card",
             "app_topic": "Opening a topic", "app_activity": "Binding a Live Activity", "app_ops": "Updating the app",
             "app_page": "Building a page", "app_data": "Keeping data", "app_events": "Reading what happened",
             "app_search": "Searching the app", "app_command": "Binding a command",
             "app_widget": "Making a widget", "app_token": "Making a key"}


def filename(path) -> str:
    return PurePath(str(path or "")).name or str(path or "a file")


def short(text, length: int = 80) -> str:
    line = str(text or "").strip().splitlines()[0] if str(text or "").strip() else ""
    return line if len(line) <= length else line[: length - 1] + "…"


OPERATORS = set("();<>|&\n")
LEADING = {"do", "then", "else", "elif", "if", "while", "until", "!", "{", "sudo", "time", "nohup", "env", "exec", "timeout"}
PLUMBING = {"cd", "echo", "printf", "export", "set", "source", ".", "read", "for", "done", "fi", "case", "esac", "[", "[[", "test", "true", "sleep", "mkdir"}
INTERPRETERS = {"python": "Python", "bash": "shell", "sh": "shell", "zsh": "shell", "node": "JavaScript"}
BEFORE = re.compile(r"\w+=|\d+[smh]?$")
CODE = set("|{}[]\\$")


def _commands(line: str) -> list[list[str]]:
    """The simple commands of a shell line in order, each as its words up to its first redirection;
    what follows a here-document is left out."""
    lexer = shlex.shlex(line.replace("\\\n", " "), posix=True, punctuation_chars="".join(OPERATORS))
    lexer.whitespace, lexer.whitespace_split = " \t\r", True
    commands, words, redirected = [], [], False
    try:
        for token in lexer:
            if not token or not set(token) <= OPERATORS:
                if not redirected:
                    words.append(token)
            elif set(token) & set("<>"):
                if words and words[-1].isdigit():
                    words.pop()
                redirected = True
                if "<<" in token:
                    break
            else:
                commands.append(words)
                words, redirected = [], False
    except ValueError:
        pass
    return [words for words in commands + [words] if words]


def _given(word: str) -> str:
    """An argument as it is said: a URL by its host, a long path by its last name."""
    if "://" in word:
        return urlparse(word).netloc or short(word, 24)
    if "/" in word and len(word) > 24:
        return short(PurePath(word).name, 24)
    return short(word, 24)


def _called(words: list[str]) -> str:
    """A command by its program and the first thing it is given, a name rather than an expression
    when it has both: the script an interpreter runs stands for the interpreter, and the row has
    no room for the options."""
    program, rest = PurePath(words[0]).name, words[1:]
    if kind := INTERPRETERS.get(program.rstrip("0123456789.")):
        if rest[:1] == ["-m"] and len(rest) > 1:
            rest = rest[1:]
        else:
            rest = list(dropwhile(lambda word: word.startswith("-") and word != "-" and not word.endswith("c"), rest))
        if not rest or rest[0].startswith("-"):
            return f"a {kind} snippet"
        program, rest = PurePath(rest[0]).name, rest[1:]
    given = [word for word in rest if word[:1] not in ("-", "+") and not word.isdigit()]
    plain = [word for word in given if not set(word) & CODE]
    first = next((word for word in rest if "://" in word), None) or next(iter(plain + given), None)
    return f"{program} {_given(first)}" if first else program


def ran(args: dict) -> str:
    """A shell line by the first command in it that does the work, past the cd and the echo."""
    line = str(args.get("command") or "")
    for words in _commands(line):
        words = list(dropwhile(lambda word: word in LEADING or BEFORE.match(word), words))
        if words and words[0] not in PLUMBING:
            return f"Ran {_called(words)}"
    return f"Ran {short(line, 30)}" if line.strip() else "Ran a command"


def _page(args: dict) -> str:
    if not args.get("id"):
        return "Listed his pages"
    if args.get("remove"):
        return f"Removed the page {args['id']}"
    if not any(args.get(name) for name in ("view", "components", "data", "patch", "title", "symbol", "state")):
        return f"Looked at the page {args['id']}"
    return f"Worked on the page {args.get('title') or args['id']}"


def _topic(args: dict) -> str:
    if not args.get("id"):
        return "Looked at his topics"
    if args.get("closed"):
        return f"Closed the topic {args.get('title') or args['id']}"
    if args.get("title") or args.get("opening"):
        return f"Opened the topic {args.get('title') or args['id']}"
    return f"Looked at the topic {args['id']}"


def _data(args: dict) -> str:
    name = args.get("id")
    if not name:
        return "Looked at the stores"
    if args.get("remove"):
        return f"Removed the store {name}"
    if args.get("path"):
        return f"Linked {filename(args['path'])} as {name}"
    if args.get("record") is not None:
        return f"Handed {args['record']} from {name}"
    if args.get("data") is not None or args.get("patch") is not None:
        return f"Wrote the store {name}"
    if any(args.get(key) for key in ("name", "symbol", "screen", "title", "subtitle", "words")):
        return f"Declared the store {name}"
    return f"Read the store {name}"


def code(args: dict) -> str:
    """A script by the comment it opens with, which the platform hint asks for; else by its length."""
    lines = [line.strip() for line in str(args.get("code") or "").splitlines() if line.strip() and not line.startswith("#!")]
    if lines and lines[0].startswith("#") and (purpose := lines[0].lstrip("# ").strip()):
        return f"Ran code: {short(purpose, 60)}"
    if not lines:
        return "Ran code"
    return "Ran a line of code" if len(lines) == 1 else f"Ran {len(lines)} lines of code"


def _command(args: dict) -> str:
    name = args.get("id")
    if not name:
        return "Looked at the commands"
    if args.get("remove"):
        return f"Removed the command {name}"
    if any(args.get(key) for key in ("script", "flow", "job", "description", "timeout", "sample")):
        return f"Bound the command {name}"
    return f"Looked at the runs of {name}"


VERBS = {"reading": "doc.text", "writing": "square.and.pencil", "editing": "square.and.pencil", "running": "terminal",
         "searching": "magnifyingglass", "browsing": "globe", "fetching": "globe", "looking": "eye", "remembering": "brain",
         "scheduling": "calendar.badge.clock", "delegating": "person.2", "building": "square.grid.2x2", "drawing": "rectangle.on.rectangle",
         "updating": "rectangle.on.rectangle", "opening": "bubble.left.and.bubble.right", "keeping": "externaldrive"}


def preparing(tool: str | None, agent) -> str:
    """What the agent is doing while the model writes a tool call's arguments, in words:
    a tool's name says nothing to him."""
    tool = tool or ""
    return APP_TOOLS.get(tool) or agent.preparing(tool) or "Preparing a step"


def symbol(tool: str | None, line: str, agent) -> str | None:
    """The SF Symbol for what the agent is at, shown in the app's pill: the
    tool's when it is known, else the verb's; None leaves the app its dots."""
    if tool in DRAWN:
        return "rectangle.on.rectangle"
    if tool and (step := describe(tool, {}, agent)):
        return step[1]
    return VERBS.get(line.split(" ", 1)[0].lower()) if line else None


PRESENT = {"Ran": "Running", "Read": "Reading", "Wrote": "Writing", "Edited": "Editing", "Searched": "Searching", "Listed": "Listing",
           "Updated": "Updating", "Looked": "Looking", "Delegated": "Delegating", "Scheduled": "Scheduling", "Browsed": "Browsing",
           "Used": "Using", "Removed": "Removing", "Worked": "Working", "Closed": "Closing", "Opened": "Opening", "Linked": "Linking",
           "Handed": "Handing", "Declared": "Declaring", "Bound": "Binding", "Made": "Making", "Revoked": "Revoking",
           "Started": "Starting", "Ended": "Ending"}


def present(line: str) -> str:
    """A step as it is said while the turn runs: "Read notes.org" is "Reading notes.org"."""
    done, _, rest = line.partition(" ")
    return f"{PRESENT.get(done, done)} {rest}".strip()


def running(tool: str, args: dict, agent) -> tuple[str, str] | None:
    """(line, SF Symbol) for a call of one of the agent's own tools as it starts: the step it will
    leave, in the present. None leaves what the agent says of it, which cuts a command or a path mid-way."""
    if tool.startswith("app_") or not (step := describe(tool, args, agent)) or step[0].startswith("Used "):
        return None
    return present(step[0]), step[1]


def describe(tool: str, args: dict, agent) -> tuple[str, str] | None:
    """(line, SF Symbol) for one call, None for what leaves no step."""
    args = args if isinstance(args, dict) else {}
    if tool in DRAWN:
        return None
    table = {
        "app_page": (_page(args), "square.grid.2x2"),
        "app_topic": (_topic(args), "bubble.left.and.bubble.right"),
        "app_data": (_data(args), "externaldrive"),
        "app_events": (f"Read what happened{' from ' + str(args['source']) if args.get('source') else ''}", "tray.and.arrow.down"),
        "app_search": (f"Searched the app for {short(args.get('query'), 40)}" if args.get("query") else "Looked at what the app holds", "magnifyingglass"),
        "app_activity": (f"{'Ended' if args.get('action') == 'end' else 'Started'} a Live Activity over {args.get('store') or args.get('id')}" if args.get("id") else "Looked at the Live Activities", "livephoto"),
        "app_ops": ("Updated the app", "iphone"),
        "app_command": (_command(args), "terminal"),
        "app_token": (f"{'Revoked' if args.get('remove') else 'Made'} the key {args['id']}" if args.get("id") else "Looked at the keys", "key"),
        "app_widget": (f"{'Removed' if args.get('remove') else 'Made'} the widget {args['id']}" if args.get("id") else "Looked at the widgets", "square.grid.2x2.fill"),
    }
    return table[tool] if tool in table else agent.describe(tool, args)
