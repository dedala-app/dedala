# SPDX-FileCopyrightText: 2026 Julien Malka
# SPDX-License-Identifier: MIT

"""What the next contract needs of this one, written while the code that
reads a JSON view is still here. The app's Lisp takes the place of Dedala
UI's JSON, and the plugin that speaks it cannot work out what a view drew. So
this one leaves, in transition/2/ of its folder, what it holds and every page
and card as the literal tree it draws:

    prepared.json             {"at", "plugin", "now", "offset", "failed": {"cards": n, "pages": [ids]}}
    stores/<name>.json        each store as the trees were drawn over it, which is as the phone holds it: a
                              JSON store as held, a text store and each record of a folder store with its sync
    pages/<id>/page.json      the page as its file says
    pages/<id>/expected.json  {"view": the tree it draws, "state"}, or {"error": why} when it cannot be drawn
    components/<Name>.json    every component
    scripts/<name>.js         every script module
    search.json               the stores' declarations
    cards.json                the cards said: {"conversation", "text", "view": the tree, "state", "capture"?},
                              the state what each input showed, under the name the tree binds it to
    conversations.jsonl       the history folded, a topic or a message a line, each card frozen the same way

Written whole each time: at the gateway's start, when it stops, and every ten
minutes when something it reads changed. One moment for a whole preparation,
kept in prepared.json (`now`, seconds since 1970, and `offset`, the phone's
seconds east of UTC), so that "in 3 h" in a tree can be drawn again and
compared. Nothing here changes what the plugin sends or keeps."""

import asyncio
import json
import logging
import math
import os
import shutil
import subprocess
import threading
import tomllib
import urllib.parse
from contextlib import contextmanager
from datetime import datetime, timezone
from functools import cached_property, lru_cache, partial
from pathlib import Path

from . import grammar, scripts, twin
from .files import digest
from .folder import _stamp
from .journal import fold

logger = logging.getLogger(__name__)

EVERY = 600
LASTING = grammar.ACTIONS - {"run", "set", "toggle", "show", "close"}
TITLED = ("title", "symbol", "role", "edge")
CARRIED = ("components", "scripts")


@lru_cache(maxsize=1)
def version() -> str:
    """The plugin's version as a person reads it: pyproject.toml's, with the
    commit it was installed from when git knows it."""
    here = Path(__file__).parent
    number = tomllib.loads((here / "pyproject.toml").read_text())["project"]["version"]
    try:
        commit = subprocess.run(["git", "-C", str(here), "rev-parse", "--short", "HEAD"], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return number
    return f"{number}+{commit.stdout.strip()}" if commit.returncode == 0 and commit.stdout.strip() else number


class Undrawn(Exception):
    """Why a card or a page cannot be drawn, in words."""


def why(error: Exception) -> str:
    return str(error) if isinstance(error, Undrawn) else f"{type(error).__name__}: {error}" if str(error) else type(error).__name__


def whole(value):
    """A tree with 3 for the 3.0 an expression computes, as the phone writes it."""
    if isinstance(value, float) and value.is_integer() and abs(value) < 1e15:
        return int(value)
    if isinstance(value, list):
        return [whole(item) for item in value]
    if isinstance(value, dict):
        return {key: whole(item) for key, item in value.items()}
    return value



CLOCK = """
var changes = CHANGES, R = __RealDate, P = R.prototype
function off(ms) { var held = changes[0][1]; for (var i = 1; i < changes.length && changes[i][0] <= ms; i++) held = changes[i][1]; return held * 1000 }
function instant(wall) { return wall - off(wall - off(wall)) }
function shown(date) { return new R(date.getTime() + off(date.getTime())) }
;['FullYear', 'Month', 'Date', 'Day', 'Hours', 'Minutes', 'Seconds', 'Milliseconds'].forEach(function (part) {
  P['get' + part] = function () { return shown(this)['getUTC' + part]() }
  if (part !== 'Day') P['set' + part] = function () { var wall = shown(this); wall['setUTC' + part].apply(wall, arguments); this.setTime(instant(wall.getTime())); return this.getTime() }
})
P.getTimezoneOffset = function () { return -off(this.getTime()) / 60000 }
function Local() {
  var given = arguments
  if (given.length === 0) return new R()
  if (given.length > 1) return new R(instant(R.UTC.apply(null, given)))
  return typeof given[0] === 'string' ? new R(Local.parse(given[0])) : new R(given[0])
}
Local.prototype = P
Local.UTC = R.UTC
Local.now = R.now
Local.parse = function (text) { return /^\\d{4}-\\d\\d-\\d\\dT\\d\\d:\\d\\d(:\\d\\d(\\.\\d+)?)?$/.test(text) ? instant(R.parse(text + 'Z')) : R.parse(text) }
__RealDate = Local
Date.parse = Local.parse
"""


class Drawing:
    """What a card or a page draws at one moment over the stores it is given:
    a view walked the way the app's renderer walks it (Hermes/UI/Tree.swift),
    with the twin's evaluator and scopes (twin/layout.py), leaving the
    literal tree where the twin leaves frames. `ForEach` and `If` are written
    out, a `List` holds its rows, a component is its body, and what is left
    of a tap is what still means something with no state and no script."""

    def __init__(self, stores: dict, live: dict, components: dict, modules: dict, moment: datetime, display: dict | None = None):
        """`stores` as the phone holds them, `live` the app's live values,
        `display` what the phone said of itself, for its time zone."""
        from .twin import layout

        self.layout = layout
        self.stores, self.live, self.components, self.modules, self.moment = stores, live, components, modules, moment
        self._bound: dict | None = None
        with twin._lock:
            kept = layout.LOCAL
            layout.set_time_zone((display or {}).get("timeZone"), (display or {}).get("utcOffset"))
            self.zone, layout.LOCAL = layout.LOCAL, kept

    @property
    def offset(self) -> int:
        return int(self.moment.astimezone(self.zone).utcoffset().total_seconds())

    @cached_property
    def clock(self) -> str:
        """The phone's clock for a script, as a module loaded before it: the
        script engine here has no time zone and would read every local hour
        and day in UTC, where the phone read them in its own. The offsets are
        those of the phone's zone, ten years back and two ahead."""
        start = int(self.moment.timestamp()) // 3600 * 3600 - 3650 * 86400
        at = lambda seconds: int(datetime.fromtimestamp(seconds, self.zone).utcoffset().total_seconds())
        changes, held = [[0, at(start)]], at(start)
        for hour in range(1, 4380 * 24 + 1):
            if (offset := at(start + hour * 3600)) != held:
                changes.append([(start + hour * 3600) * 1000, offset])
                held = offset
        return CLOCK.replace("CHANGES", json.dumps(changes))

    def of(self, spec: dict) -> dict:
        """{"view": the literal tree, "state": the state it was drawn with},
        of a card (`view`, `data`, `state`, `script`, `derive`) or a page,
        which has no data, to be compared with what is drawn again: an input
        holds the `value` it showed. Raises when its view or its script
        cannot be worked out."""
        return self._drawn(spec, None)

    def frozen(self, spec: dict) -> dict:
        """{"view": the literal tree, "state"} of a card the app draws as it
        is, with nothing behind it: each input is bound to a name of its own
        (`$f1`, `$f2`… in the order met), and the state holds what each
        showed under that name, and nothing else."""
        bound: dict = {}
        return {"view": self._drawn(spec, bound)["view"], "state": whole(bound)}

    def _drawn(self, spec: dict, bound: dict | None) -> dict:
        layout = self.layout
        self._bound = bound
        if spec.get("view") is None:
            raise Undrawn("it has no view")
        data = spec.get("data") if isinstance(spec.get("data"), dict) else {}
        layers = [self.live, self.stores, data]
        with self._held():
            state = layout.resolve(spec["state"], layout.Scope(layers)) if isinstance(spec.get("state"), dict) else {}
        derived = self._derived(spec, data, state)
        with self._held():
            drawn = self._nodes(spec["view"], layout.Scope([*layers, derived, state]))
        return {"view": whole(self._one(drawn)), "state": state}

    @contextmanager
    def _held(self):
        """The twin's evaluator for the time of one drawing: its clock at this
        moment, its time zone the phone's, `until` worked out where the twin
        keeps a stand-in of its width. Under the twin's lock, which every
        layout takes, and as it was afterwards."""
        layout = self.layout
        with twin._lock:
            kept = layout.CLOCK, layout.LOCAL, layout.call
            layout.CLOCK, layout.LOCAL, layout.call = self.moment, self.zone, partial(self._call, layout.call)
            try:
                yield
            finally:
                layout.CLOCK, layout.LOCAL, layout.call = kept

    def _call(self, own, name: str, args: list):
        """The twin's functions, with `until(date)` and `date(x, 'relative')`
        in the words the scripts' helper has for them (helpers.js): "in 12
        min", "in 3 h", "in 3 days", "now", and the twin's `ago` for what is
        past."""
        if name != "until" and not (name == "date" and len(args) > 1 and args[1] == "relative"):
            return own(name, args)
        date = self.layout.parse_date(args[0]) if args else None
        if date is None:
            return None if name == "until" else own(name, args)
        left = (date - self.moment).total_seconds()
        if abs(left) < 60:
            return "now"
        if left < 0:
            return own("ago", args[:1])
        unit, span = ("min", 60) if left < 3600 else ("h", 3600) if left < 86400 else ("day", 86400)
        count = math.floor(left / span + 0.5)
        return f"in {count} {unit}{'s' if unit == 'day' and count != 1 else ''}"

    def _derived(self, spec: dict, data: dict, state: dict) -> dict:
        """The derived values of its script, computed here as the phone
        computes them: on its data and state, the stores the script names,
        the live values and this moment."""
        source, derive = spec.get("script"), spec.get("derive")
        if not isinstance(source, str) or not isinstance(derive, dict):
            return {}
        names = [name for name, function in derive.items() if isinstance(function, str)]
        named = {dotted or quoted for dotted, quoted in scripts.STORES.findall(source)}
        given = {"data": data, "state": state, "now": self.moment.astimezone(self.zone).isoformat(timespec="seconds"), **self.live,
                 "stores": {name: value for name, value in self.stores.items() if name in named}}
        results = scripts.run(source, [(derive[name], given) for name in names], {**self.modules, "__clock": self.clock}) if names else []
        for name, result in zip(names, results):
            if "error" in result:
                raise Undrawn(f"the derived value {name} ({derive[name]}) fails: {result['error']}")
        return {name: result["value"] for name, result in zip(names, results)}

    def _nodes(self, node, scope) -> list:
        """The literal nodes one written node becomes: none when it is
        hidden, several for a `ForEach`."""
        layout = self.layout
        if node is None:
            return []
        if isinstance(node, str):
            value = layout.resolve(node, scope)
            if isinstance(value, (dict, list)) and node.startswith("$"):
                return self._nodes(value, scope)
            return [layout.text_of(value)]
        if isinstance(node, list):
            return [self._children(node, scope)]
        if isinstance(node, dict):
            return self._element(node, scope)
        return [node]

    def _children(self, value, scope) -> list:
        if isinstance(value, list):
            return [made for child in value for made in self._nodes(child, scope)]
        return self._nodes(value, scope)

    @staticmethod
    def _one(made: list):
        """Where one view is expected: the node itself, or a `Group` of what a
        `ForEach` or an `If` left there."""
        return made[0] if len(made) == 1 else {"Group": made}

    def _bare(self, value, scope):
        """A condition as the phone reads it: an expression written bare, a
        reference or a `${…}`."""
        layout = self.layout
        if isinstance(value, str) and "${" not in value and not layout.REFERENCE.fullmatch(value):
            return layout.evaluate(value, scope)
        return layout.resolve(value, scope)

    def _value(self, value, scope):
        """What a view is given, or one of its arguments, with its
        expressions worked out. A value written as a choice (`If`, `then`,
        `else` in the place of a value) is the value of the branch its
        condition picks: Dedala UI has `If` for views only and the phone
        makes nothing of such an object, but what was meant is plain, and it
        is what the rewritten page will be held against."""
        if isinstance(value, dict):
            if "If" in value and ("then" in value or "else" in value):
                return self._value(value.get("then") if self.layout.truthy(self._bare(value["If"], scope)) else value.get("else"), scope)
            return {key: self._value(item, scope) for key, item in value.items()}
        if isinstance(value, list):
            return [self._value(item, scope) for item in value]
        return self.layout.resolve(value, scope)

    def _element(self, node: dict, scope) -> list:
        layout = self.layout
        node = dict(node)
        declared = node.pop("state", None)
        if isinstance(declared, dict):
            scope = scope.with_values({name: layout.resolve(value, scope) for name, value in declared.items() if not scope.lookup(name)[1]})
        if "hidden" in node and layout.truthy(self._bare(node["hidden"], scope)):
            return []
        if "visible" in node and not layout.truthy(self._bare(node["visible"], scope)):
            return []
        if "ForEach" in node:
            return [made for row in self._rows(node, scope) for made in row]
        if "List" in node:
            return [{"List": [row[0] if len(row) == 1 else {"VStack": row, "alignment": "leading", "spacing": 0} for row in self._rows(node, scope)]}]
        if "If" in node:
            return self._children(node.get("then") if layout.truthy(self._bare(node["If"], scope)) else node.get("else"), scope)
        kinds = sorted(key for key in node if key[:1].isupper())
        if not kinds:
            return []
        kind = kinds[0]
        value = node[kind]
        worn = self._arguments(kind, {key: given for key, given in node.items() if key not in (kind, "hidden", "visible")}, scope)
        if kind not in grammar.VIEWS and isinstance(self.components.get(kind), dict):
            made = self._component(self.components[kind], value, scope)
            return [{"Group": made, **worn}] if worn else made
        if kind in grammar.CONTAINERS:
            drawn = self._children(value, scope)
        elif kind in ("Button", "Menu") and isinstance(value, (dict, list)):
            drawn = self._one(self._nodes(value, scope))
        elif kind == "Text" and not isinstance(value, dict):
            drawn = layout.text_of(layout.resolve(value, scope))
        else:
            drawn = self._value(value, scope)
        return [{kind: drawn, **worn}]

    def _rows(self, node: dict, scope) -> list[list]:
        """What each element of a `ForEach` or a `List` draws; what else is
        written on the loop is on each row, as the phone pushes it."""
        layout = self.layout
        source = node["ForEach"] if "ForEach" in node else node["List"]
        found = layout.evaluate(source, scope) if isinstance(source, str) and not source.startswith("$") else layout.resolve(source, scope)
        if isinstance(found, dict):
            found = [{"key": key, "value": value} for key, value in sorted(found.items())]
        pushed = {key: value for key, value in node.items() if key not in layout.LOOP_OWN}
        content = layout.push_into(pushed, node.get("content")) if pushed else node.get("content")
        name, place = node.get("as") or "item", node.get("index") or "index"
        return [self._children(content, scope.with_values({name: element, place: float(index)}))
                for index, element in enumerate(found if isinstance(found, list) else [])]

    def _component(self, definition: dict, value, scope) -> list:
        """A component's body over its props, its own state, the stores and
        the live values: what it is called with is worked out where it is
        written, a view among it left for the body to draw."""
        layout = self.layout
        props = definition.get("props") or {}
        props = dict(props) if isinstance(props, dict) else {name: None for name in props if isinstance(name, str)}
        if isinstance(value, dict):
            props.update({name: layout.resolve(given, scope, known_only=layout.is_view(given)) for name, given in value.items()})
        elif (given := layout.resolve(value, scope)) is not None:
            props["value"] = given
        body = definition.get("body")
        if isinstance(body, dict) and isinstance(definition.get("state"), dict):
            body = {**body, "state": {**definition["state"], **(body["state"] if isinstance(body.get("state"), dict) else {})}}
        return self._nodes(body, layout.Scope([self.live, self.stores, props]))

    def _arguments(self, kind: str, written: dict, scope) -> dict:
        """A node's arguments and modifiers with their values worked out: the
        views among them drawn, a tap as what lasts of it and a `Button` left
        with none disabled, an input as the `value` it shows, or bound to a
        name of its own in a frozen card (`frozen`), with no `onChange`,
        which only knew its `$value` then."""
        layout = self.layout
        out = {}
        for key, value in written.items():
            if key in ("action", "onTap"):
                steps = self._steps(value, scope)
                if steps:
                    out[key] = steps[0] if len(steps) == 1 else steps
                elif key == "action" and kind == "Button":
                    out["disabled"] = True
            elif key == "onChange":
                continue
            elif key == "actions" or (key == "items" and kind == "Menu"):
                kept = self._titled(value, scope)
                if kept or key == "items":
                    out[key] = kept
            elif key == "bind" and isinstance(value, str):
                shown = layout.evaluate(value.removeprefix("$"), scope)
                if self._bound is None:
                    out["value"] = shown
                else:
                    name = f"f{len(self._bound) + 1}"
                    self._bound[name] = shown
                    out[key] = f"${name}"
            elif key == "expanded" and isinstance(value, str):
                out[key] = layout.truthy(layout.evaluate(value.removeprefix("$"), scope))
            elif key == "disabled":
                if layout.truthy(self._bare(value, scope)):
                    out[key] = True
            elif key == "content":
                out[key] = self._children(value, scope)
            elif key in ("overlay", "background") and (isinstance(value, list) or layout.is_view(value)):
                out[key] = self._one(self._nodes(value, scope))
            elif key == "modifiers" and isinstance(value, list):
                out[key] = [self._arguments(kind, entry, scope) if isinstance(entry, dict) else entry for entry in value]
            else:
                out[key] = self._value(value, scope)
        return out

    def _titled(self, items, scope) -> list[dict]:
        """The titled actions of a node or a `Menu` that still do something."""
        kept = []
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict):
                continue
            steps = self._steps({name: given for name, given in item.items() if name not in TITLED}, scope)
            if steps:
                kept.append({**{name: self.layout.resolve(item[name], scope) for name in TITLED if name in item}, **steps[0]})
        return kept

    def _steps(self, action, scope, written: bool = True) -> list[dict]:
        """The steps of a tap that still mean something once nothing is
        computed: those that only ask the phone for something (`LASTING`),
        their values worked out; one that changed the state, ran the script,
        or opened or closed a screen is gone. A step written as a reference
        is the action it names, worked out already where it was handed."""
        kept = []
        for step in action if isinstance(action, list) else [action]:
            if isinstance(step, str) and written:
                kept += self._steps(self.layout.resolve(step, scope), scope, written=False)
            elif isinstance(step, dict) and (verbs := set(step) & grammar.ACTIONS) and verbs <= LASTING:
                kept.append(self.layout.resolve(step, scope) if written else step)
        return kept


class Preparation:
    """transition/2/ in the plugin's folder, written whole from what the
    plugin holds: the app's files and the stores (the link's), the cards said
    and the history. `written` is the mark of what the last one was written
    from: the stamps of the files read, and the phone's time zone."""

    def __init__(self, link, cards, commands=None):
        self.link, self.cards, self.commands = link, cards, commands
        self.folder = link.home / "transition" / "2"
        self.written: str | None = None
        self._writing = threading.Lock()

    async def prepare(self, changed: bool = False) -> None:
        """Writes the folder off the gateway's loop; with `changed`, only when
        something it reads moved since the last time. A preparation that
        fails is said in the log and leaves the one before it."""
        try:
            await asyncio.to_thread(self.write, self.gather(), changed)
        except Exception as error:
            logger.warning("[app] the transition was not prepared, the last preparation stays: %s", why(error))

    def gather(self) -> dict:
        """What a preparation reads of the plugin's state, taken on the
        gateway's loop, where that state has its one writer."""
        link = self.link
        loaded, stores, display = link.app.loaded, link.stores, link.state.get("display") or {}
        pinned = next(iter(link.arrangement()), {}).get("pinned") or []
        pages = dict(loaded["page"])
        return {
            "pages": pages, "components": dict(loaded["components"]), "scripts": dict(loaded["scripts"]), "search": dict(loaded["search"]),
            "stores": {name: (stores.kind(name), data) for name, data in stores.held.items()},
            "display": dict(display),
            "live": {"waiting": [], "running": {"turns": [], "runs": []}, "today": {"answered": [], "runs": [], "messages": 0},
                     "pages": [{"id": identifier, "title": page.get("title") or identifier, "symbol": page.get("symbol") or "square.grid.2x2",
                                "bar": identifier in pinned, "updated": None} for identifier, page in pages.items()],
                     "commands": self.commands.live() if self.commands is not None else {}},
            "mark": repr((sorted(link.app._stamps.items()), sorted(stores._stamps.items()), display.get("timeZone"), display.get("utcOffset"))),
        }

    def write(self, held: dict, changed: bool = False) -> dict | None:
        """The folder written from what `gather` took, and what prepared.json
        says of it; None when nothing moved and only a change was asked for.
        Blocking: run it in a thread."""
        with self._writing:
            mark = digest(repr((held["mark"], _stamp(self.cards.path), _stamp(self.link.journal.path))))
            if changed and mark == self.written:
                return None
            for left in self.folder.parent.glob(f".{self.folder.name}.*"):
                shutil.rmtree(left, ignore_errors=True)
            fresh = self.folder.with_name(f".{self.folder.name}.{os.getpid()}.new")
            fresh.mkdir(parents=True, mode=0o700)
            try:
                prepared = self._fill(fresh, held)
                self._replace(fresh)
            except BaseException:
                shutil.rmtree(fresh, ignore_errors=True)
                raise
            self.written = mark
            logger.info("[app] the transition is prepared: %d pages, %d of them and %d cards that could not be drawn",
                        len(held["pages"]), len(prepared["failed"]["pages"]), prepared["failed"]["cards"])
            return prepared

    def _replace(self, fresh: Path) -> None:
        """The new folder in the place of the old one, which comes back if the new one cannot take it."""
        aside = self.folder.with_name(f".{self.folder.name}.{os.getpid()}.old")
        if self.folder.exists():
            self.folder.rename(aside)
        try:
            fresh.rename(self.folder)
        except OSError:
            if aside.exists():
                aside.rename(self.folder)
            raise
        shutil.rmtree(aside, ignore_errors=True)

    def _fill(self, folder: Path, held: dict) -> dict:
        moment = datetime.now(timezone.utc).replace(microsecond=0)
        shown = {name: {**data, "sync": "synced", "error": None} if kind == "text"
                 else [{**item, "sync": "synced", "error": None} for item in data] if kind == "folder" else data
                 for name, (kind, data) in held["stores"].items()}
        drawing = Drawing(shown, held["live"], held["components"], held["scripts"], moment, held["display"])
        for name, data in shown.items():
            _json(folder / "stores" / _store_file(name), data)
        undrawn = []
        for identifier, page in held["pages"].items():
            _json(folder / "pages" / identifier / "page.json", page)
            try:
                expected = drawing.of(page)
            except Exception as error:
                expected = {"error": why(error)}
                undrawn.append(identifier)
            _json(folder / "pages" / identifier / "expected.json", expected)
        for name, component in held["components"].items():
            _json(folder / "components" / f"{name}.json", component)
        for name, source in held["scripts"].items():
            _text(folder / "scripts" / f"{name}.js", source if source.endswith("\n") else source + "\n")
        _json(folder / "search.json", held["search"])
        dropped: set[str] = set()
        _json(folder / "cards.json", self._cards(drawing, dropped))
        _text(folder / "conversations.jsonl", "".join(json.dumps(line, ensure_ascii=False) + "\n" for line in self._history(drawing, dropped)))
        prepared = {"at": moment.isoformat(timespec="seconds"), "plugin": version(), "now": int(moment.timestamp()), "offset": drawing.offset,
                    "failed": {"cards": len(dropped), "pages": undrawn}}
        _json(folder / "prepared.json", prepared)
        return prepared

    @staticmethod
    def _frozen(drawing: Drawing, identifier: str, card: dict, dropped: set[str]) -> dict | None:
        """A card as the tree it draws, its state what its inputs showed;
        None, and its id among the dropped, when it cannot be drawn."""
        try:
            return drawing.frozen(card)
        except Exception:
            dropped.add(identifier)
            return None

    def _cards(self, drawing: Drawing, dropped: set[str]) -> dict:
        """The cards said, each frozen; one that cannot be drawn keeps its line."""
        with self.cards.lock:
            said = json.loads(json.dumps(self.cards.cards))
        return {identifier: {"conversation": spec.get("conversation", "main"), "text": spec.get("text", ""),
                             **(self._frozen(drawing, identifier, spec, dropped) or {}),
                             **({"capture": spec["capture"]} if spec.get("capture") else {})}
                for identifier, spec in said.items()}

    def _history(self, drawing: Drawing, dropped: set[str]) -> list[dict]:
        """The history folded as this line folds it, patches in their cards:
        the topics, then the messages of each conversation in order, each
        card frozen; a message whose card cannot be drawn keeps its line.
        What a line carried to draw its card with the app closed (`CARRIED`)
        is left out."""
        conversations, topics = fold(self.link.journal._read())
        lines = [{"op": "topic", **{key: value for key, value in topic.items() if key != "started"}, "at": topic.get("started")} for topic in topics.values()]
        for conversation, messages in conversations.items():
            for message in messages:
                line = {"op": "say", "conversation": conversation, **{key: value for key, value in message.items() if key not in CARRIED}}
                if isinstance(line.get("card"), dict):
                    line["card"] = self._frozen(drawing, message["id"], line["card"], dropped)
                    if line["card"] is None:
                        del line["card"]
                lines.append(line)
        return lines


def _store_file(name: str) -> str:
    """A store's file, named as the stores folder names its own (stores.py)."""
    quoted = urllib.parse.quote(name, safe="")
    return f"{'%2E' + quoted[1:] if quoted.startswith('.') else quoted}.json"


def _text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _json(path: Path, value) -> None:
    _text(path, json.dumps(value, indent=1, ensure_ascii=False) + "\n")
