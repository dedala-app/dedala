# SPDX-FileCopyrightText: 2026 Julien Malka
# SPDX-License-Identifier: MIT

"""What every card and page goes through before it leaves: the grammar, its
script run here, the twin's layout as his phone will draw it, and a designer's
review of the picture. What does not pass is held back for the agent's next try."""

import asyncio
import json
import logging
import re
import time
from pathlib import Path

from . import analysis, session
from .state import safe as _safe

logger = logging.getLogger(__name__)


def refused(ops: list[dict]) -> str | None:
    """Ops whose views would break on the phone are not sent: the answer says what to fix."""
    from .grammar import check_ops

    artifacts = session.link().state.get("artifacts", {})
    found = check_ops(ops, set(artifacts.get("components", {})), set(artifacts.get("command", {})), set(artifacts.get("page", {}))) + analysis.still_drawn(ops, artifacts)
    if not found:
        return None
    return session.answer({"sent": False, "error": "Not sent: these views would not draw. Fix them and send again.", "problems": found})


def check_file(op: dict, loaded: dict) -> list[str]:
    """What is wrong with an op built from a file someone wrote by hand: the
    same checks a tool call gets, components and commands known from the files."""
    from .grammar import check_ops

    found = check_ops([op], set(loaded.get("components", {})), set(loaded.get("command", {})), set(loaded.get("page", {}))) + analysis.still_drawn([op], loaded)
    if op.get("op") == "widget":
        if op.get("component") not in loaded.get("components", {}):
            found.append(f"the component {op.get('component')!r} is not defined")
        if op.get("store") is None:
            found.append("a widget names its store")
    if op.get("op") == "buttons":
        if problem := buttons_problem(op):
            found.append(problem)
    return found


def notify_problem(op: dict, artifacts: dict, topics: dict) -> str | None:
    """Why a notify op cannot ring: no line, or an `open` naming nothing."""
    if not str(op.get("title") or op.get("body") or "").strip():
        return "a notification needs a title or a body"
    target = op.get("open")
    if target is None:
        return None
    if not isinstance(target, dict) or len(target) == 0:
        return "open is {page: id}, {show: Name, with: {…}} or {conversation: id}"
    if "page" in target and target["page"] not in artifacts.get("page", {}):
        return f"open names the page {target['page']}, which does not exist"
    if "show" in target and target["show"] not in artifacts.get("components", {}):
        return f"open names the component {target['show']}, which is not defined"
    if "conversation" in target and target["conversation"] not in ("main", *topics):
        return f"open names the conversation {target['conversation']}, which is neither main nor a topic"
    if not any(key in target for key in ("page", "show", "conversation")):
        return "open is {page: id}, {show: Name, with: {…}} or {conversation: id}"
    return None


def notify_buttons_problem(op: dict, artifacts: dict) -> str | None:
    """Why a notification's buttons cannot be shown: a kind nobody declared,
    an action for a button the kind lacks, an action naming nothing."""
    kind, actions = op.get("kind"), op.get("actions")
    if kind is None and actions is None:
        return None
    declared = artifacts.get("buttons", {}).get(kind) if kind else None
    if declared is None:
        return f"kind names {kind!r}, which no buttons op declared: declare its buttons first (app_ops buttons)"
    if not isinstance(actions, dict):
        return "actions maps each button's id to what it does"
    ids = {button.get("id") for button in declared}
    for identifier, action in actions.items():
        if identifier not in ids:
            return f"actions names the button {identifier!r}, which the kind {kind} does not have ({', '.join(sorted(ids))})"
        if not isinstance(action, dict):
            return f"the action of {identifier} is an object, as a page writes it"
        if "command" in action and action["command"] not in artifacts.get("command", {}):
            return f"the action of {identifier} names the command {action['command']!r}, which is not bound"
        if "show" in action and action["show"] not in artifacts.get("components", {}):
            return f"the action of {identifier} names the component {action['show']!r}, which is not defined"
        if "page" in action and action["page"] not in artifacts.get("page", {}):
            return f"the action of {identifier} names the page {action['page']!r}, which does not exist"
    return None


def buttons_problem(op: dict) -> str | None:
    kinds = op.get("kinds")
    if not isinstance(kinds, dict) or not kinds:
        return "buttons is {kinds: {name: [{id, title, destructive}] | null}}"
    for name, buttons in kinds.items():
        if buttons is None:
            continue
        if not isinstance(buttons, list) or not 1 <= len(buttons) <= 4:
            return f"the kind {name} has one to four buttons"
        for button in buttons:
            if not isinstance(button, dict) or not button.get("id") or not button.get("title"):
                return f"a button of {name} needs an id and a title"
        if len({button["id"] for button in buttons}) != len(buttons):
            return f"the buttons of {name} share an id"
    return None


def remarks(view, data=None, state=None, derive=None, store: str | None = None) -> list[str]:
    """What is worth a second look in a card or page as written and blocks
    nothing: an argument on a view that does not take it, a name that is also
    one of the app's live values."""
    from .grammar import LIVE, idle

    found = idle(view)
    if store in LIVE:
        found.append(f"This page's store is named {store}, like the app's own ${store} (a live value): every card and page "
                     f"that reads ${store} gets this page's data instead. Give the page another id")
    for what, names in (("data key", data), ("state", state), ("derived value", derive)):
        for name in sorted(LIVE & set(names if isinstance(names, dict) else ())):
            found.append(f"The {what} {name} has the name of the app's own ${name} (a live value): the view reads yours while "
                         "it is there, and the app's when it is missing. Rename it")
    return found


# What the vision model is asked about every card before it leaves: a reviewer's
# eye, since the twin finding nothing cut only means nothing is cut.
CRITIQUE = (
    "You are a demanding iOS product designer reviewing one card an assistant drew in a chat app, drawn as the "
    "phone will draw it (the rounded rectangle, or for a page the screen of widgets; ignore anything around it). "
    "Maps, pictures (remote or sent beside the card), a quoted message (a grey box standing in for it) and the "
    "assistant's face (a drawn face in a circle) are stand-ins here: an empty or plain area where they are is "
    "expected; judge their place and size, not their look or content. Judge it against the bar of Apple's own apps: "
    "1. Is it a familiar object drawn the way Apple's own apps draw it (Mail, Maps, Calendar, Clock, Weather), "
    "with the assistant's call shown inside it (a warning line, the recommended option first, the next item "
    "highlighted) rather than shouted as a giant headline or a slogan? Does the weight follow what it leads with, "
    "rather than every line drawn the same? "
    "2. Is the hierarchy clear (size, weight, colour), or is everything the same grey text? "
    "3. Are things aligned and balanced, with consistent spacing? "
    "4. Does any text wrap mid-phrase or get cut? A single word alone on a text's last line is fine, never a reason to "
    "fix. "
    "5. Is it cramped or empty? "
    "6. Is colour restrained and meaningful, and everything legible? "
    "7. Is what should be centred actually centred (a score between two teams, a title over a row), whatever the "
    "lengths around it? "
    "8. Does anything look broken, clipped or amateur? "
    "Say VERDICT: FIX only for problems a user would notice at a glance: something cut, wrapped badly, "
    "unreadable, unbalanced, missing or broken. A card with only polish left is VERDICT: GOOD, with that polish "
    "listed as notes. After the verdict, list at most five changes, most important first, naming the card's "
    "elements by what they say. "
    "Judge the design only. What it says is the assistant's call, made from what you cannot see (what the user "
    "already settled or asked for): never ask to add, drop or move a subject, a fact or a section. Shortening a "
    "line so it fits is design."
)

MAX_ROUNDS = 3

ROUND_WINDOW = 600


_rounds: dict[str, tuple[int, int, float]] = {}


# Each message, tap or flag from him starts a new request: its review rounds
# count from one.
_turn = 0


def new_turn() -> None:
    global _turn
    _turn += 1


def round_of(card: str) -> int:
    """Which try at sending this card or page this is, in this request: a new
    message from him, or ROUND_WINDOW seconds without one (a cron job's run),
    starts again at one."""
    turn, done, at = _rounds.get(card, (None, 0, 0.0))
    now = time.monotonic()
    rounds = done + 1 if turn == _turn and now - at < ROUND_WINDOW else 1
    _rounds[card] = (_turn, rounds, now)
    return rounds


async def ask_critic(picture: str) -> str:
    """The vision model's eye on the card as the phone will draw it, asked our
    question: the agent does not get to soften it."""
    return await session.agent().see(picture, CRITIQUE)

REPLY = ("He sees it in the app: your reply is at most one short line that adds what it does not show (a question, "
         "a next step, something to decide), or nothing more. Never restate what it shows, nor what you fixed. Its line above carries "
         "the gist: it is what a notification shows.")


def on_phone(page: bool = False) -> str:
    display = session.link().state.get("display") or {}
    width = display.get("pageWidth") if page else display.get("cardWidth")
    if not width:
        return f"on a phone at the default text size and {'page' if page else 'card'} widths"
    return f"on his phone (text size {display.get('textSize') or 'large'}, {'pages' if page else 'cards'} {width:.0f} pt wide)"


async def look(spec: dict, derived: dict | None, name: str, picture: bool, components: dict | None = None,
                page: bool = False) -> dict | None:
    """The twin's look at a card or page before it leaves: {card, faults,
    notes, png}, or None when the twin cannot lay it out here."""
    from . import twin

    link = session.link()
    known = link.state.get("artifacts", {}).get("components") or {}
    try:
        looked = await asyncio.to_thread(twin.look, {"stores": all_stores(), **spec}, link.state.get("display"),
                                         {**known, **(components or {})}, derived,
                                         link.home / "previews" if picture else None, _safe(name), page)
    except Exception as error:
        logger.warning("[app] the twin could not lay out %s: %s", name, error)
        return None
    from . import server

    if server.current is not None and server.current.loop is not None:
        await session.on_gateway(server.current.measure_wanted())
    looked["card"].pop("stores", None)
    return looked


def all_stores() -> dict:
    """Every store as the phone holds it, by name, text and folder stores
    with the sync the phone adds."""
    from . import server

    link = session.link()
    stores = {}
    for name, data in link.stores.held.items():
        kind = link.stores.kind(name)
        if kind == "text":
            stores[name] = {**data, "sync": "synced", "error": None}
        elif kind == "folder":
            stores[name] = [{**item, "sync": "synced", "error": None} for item in data]
        else:
            stores[name] = data
    stores["commands"] = server.current.commands.live()
    return stores


async def review(looked: dict | None) -> dict | None:
    if not looked or not looked.get("png"):
        return {"error": f"No review: {looked['error']}"} if looked and looked.get("error") else None
    try:
        critique = await ask_critic(looked["png"])
    except Exception as error:
        return {"error": f"The vision model could not look at the card: {error}"}
    return {"verdict": "GOOD" if re.search(r"VERDICT:\W*GOOD", critique) else "FIX", "critique": critique}


# Cards held back by the twin or the review, waiting for the agent's next try:
# each leaves as it stands when his turn ends, or after HOLD seconds.
HOLD = 180


held_back: dict[str, dict] = {}


def hold(key: str, conversation: str, send) -> None:
    """`send` is the coroutine function that delivers what is held."""
    from . import server

    held = {"conversation": conversation, "send": send}
    held_back[key] = held
    asyncio.run_coroutine_threadsafe(_release_later(key, held), server.current.loop)


async def _release_later(key: str, held: dict) -> None:
    await asyncio.sleep(HOLD)
    if held_back.get(key) is held:
        await _release(key)


async def _release(key: str) -> None:
    if held := held_back.pop(key, None):
        await held["send"]()


async def release_held(conversation: str) -> None:
    """The turn is over: the cards and pages it held back leave as they stand."""
    for key, held in list(held_back.items()):
        if held["conversation"] == conversation:
            await _release(key)

SCRIPTED = ("script", "derive")


def merge(base: dict, patch: dict) -> dict:
    from .link import _merged

    return _merged(base, patch)


def modules() -> dict[str, str]:
    return dict(session.link().state.get("artifacts", {}).get("scripts") or {})


async def script_check(surface: dict, data) -> dict:
    """The script of a card or page run here first; {} when it has none."""
    if not surface.get("script"):
        return {}
    from . import scripts, server

    artifacts = session.link().state.get("artifacts", {})
    runs = ((server.current._activity_sent or {}).get("runs") or []) if server.current else []
    live = {**scripts.samples(runs), "stores": all_stores()}
    return await asyncio.to_thread(scripts.check, surface, data, modules(), artifacts.get("components") or {}, live)


async def derived_values(surface: dict, data) -> dict | None:
    """The derived values as the phone has them now, for the twin: the script
    check's live values hold a sample of each list, which the twin would draw."""
    if not surface.get("script") or not surface.get("derive"):
        return None
    from . import scripts, server

    artifacts = session.link().state.get("artifacts", {})
    runs = ((server.current._activity_sent or {}).get("runs") or []) if server.current else []
    live = {**scripts.samples(runs), "waiting": [], "stores": all_stores()}
    found = await asyncio.to_thread(scripts.check, surface, data, modules(), artifacts.get("components") or {}, live, False)
    return found.get("derived")


def script_refused(found: dict) -> str | None:
    if not found.get("errors"):
        return None
    return session.answer({"sent": False, "error": "Not sent: the script does not work here. Fix it and send again.", "problems": found["errors"]})


def checked(answer: str, found: dict) -> str:
    """What the script computed here, beside the answer."""
    if not found:
        return answer
    result = json.loads(answer)
    result["script_check"] = {key: value for key, value in found.items() if value}
    return session.answer(result)


def with_warnings(answer: str, warnings: list[str]) -> str:
    if not warnings:
        return answer
    result = json.loads(answer)
    result["data_check"] = warnings
    return session.answer(result)
