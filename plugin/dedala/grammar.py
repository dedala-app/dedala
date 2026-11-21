# SPDX-FileCopyrightText: 2026 Julien Malka
# SPDX-License-Identifier: MIT

"""Hermes UI checked before it leaves: the shape mistakes the phone would only
find while drawing, when it is open to say so. The names are the app's own
(grammar.json, kept equal to the app by its tests)."""

import json
from pathlib import Path

GRAMMAR = json.loads(Path(__file__).with_name("grammar.json").read_text())
VIEWS = set(GRAMMAR["views"])
CONTAINERS = set(GRAMMAR["containers"])
MODIFIERS = set(GRAMMAR["modifiers"])
ARGUMENTS = set(GRAMMAR["arguments"])
KNOWN = MODIFIERS | ARGUMENTS
TAKES = {view: set(names) for view, names in GRAMMAR["takes"].items()}
ANYWHERE = set(GRAMMAR["anywhere"])
LIVE = set(GRAMMAR["live"])
ACTIONS = set(GRAMMAR["actions"])
ACTION_ARGUMENTS = {"require", "say", "input", "args", "with", "as", "replace"}
FLOW = {"ForEach", "If"}
CHILD_SLOTS = ("content", "then", "else")
MAX_DEPTH = 40
REGIONS = {"lock", "lockCompact", "leading", "trailing", "center", "bottom", "compactLeading", "compactTrailing", "minimal"}


def problems(node, components: set[str] = frozenset()) -> list[str]:
    """What is wrong with a view, each with where it is; empty when it is sound."""
    found: list[str] = []
    _node(node, "view", set(components), found, 0)
    return found


def _node(node, path: str, components: set[str], found: list[str], depth: int) -> None:
    if depth > MAX_DEPTH:
        found.append(f"{path}: nested deeper than {MAX_DEPTH} levels")
        return
    if isinstance(node, list):
        for index, child in enumerate(node):
            _node(child, f"{path}[{index}]", components, found, depth + 1)
        return
    if not isinstance(node, dict):
        return
    node = {key: value for key, value in node.items() if key != "state"}
    keys = sorted(key for key in node if key[:1].isupper())
    if not keys:
        hint = ""
        if "children" in node:
            hint = ' Children are the view\'s own value, with its arguments beside it: {"VStack": [ … ], "spacing": 10}.'
        found.append(f"{path}: a node needs one capitalised view key, got {sorted(node)}.{hint}")
        return
    if len(keys) > 1:
        found.append(f"{path}: several view keys {keys}; one node is one view")
    key = keys[0]
    here = f"{path}.{key}"
    if key not in VIEWS and key not in FLOW and key not in components:
        found.append(f"{here}: unknown view '{key}' (not a Hermes UI view nor a defined component)")
        return
    if key in components:
        return
    for name in node:
        if name != key and name not in KNOWN:
            found.append(f"{here}: unknown modifier or argument '{name}'")
    if key in CONTAINERS:
        value = node[key]
        if isinstance(value, dict) and not any(name[:1].isupper() for name in value):
            found.append(f"{here}: takes its children as a list, got an object with {sorted(value)}. "
                         f'Write {{"{key}": [ … ], "spacing": 10}}.')
        else:
            _node(value, here, components, found, depth + 1)
    for slot in CHILD_SLOTS:
        if slot in node:
            _node(node[slot], f"{here}.{slot}", components, found, depth + 1)
    for name in ("background", "overlay", "label"):
        if isinstance(node.get(name), (dict, list)) and _looks_like_view(node[name]):
            _node(node[name], f"{here}.{name}", components, found, depth + 1)


def shown(view, components: set[str], commands: set[str] | None = None, pages: set[str] | None = None) -> list[str]:
    """Every `show` in a view names a defined component, the screen it opens,
    every `command` a command the agent bound, every action a verb the phone
    knows and every `page` it opens one that is there."""
    found: dict[str, None] = {}
    _shown(view, components, commands, pages, found, 0)
    return list(found)


def _actions(action, pages: set[str] | None, found: dict[str, None]) -> None:
    for step in action if isinstance(action, list) else [action]:
        if not isinstance(step, dict):
            continue
        if unknown := sorted(set(step) - ACTIONS - ACTION_ARGUMENTS):
            found[f"action: {', '.join(unknown)} is not an action, so the phone skips it; the verbs are {', '.join(sorted(ACTIONS))}"] = None
        target = step.get("page")
        if pages is not None and isinstance(target, str) and not target.startswith("$") and target not in pages:
            found[f"action: no page '{target}' to open; the pages are {', '.join(sorted(pages)) or 'none yet'}"] = None


def _shown(node, components: set[str], commands: set[str] | None, pages: set[str] | None, found: dict[str, None], depth: int) -> None:
    if depth > MAX_DEPTH:
        return
    if isinstance(node, list):
        for child in node:
            _shown(child, components, commands, pages, found, depth + 1)
        return
    if not isinstance(node, dict):
        return
    for key in ("action", "onTap"):
        if key in node:
            _actions(node[key], pages, found)
    name = node.get("show")
    if isinstance(name, str) and not name.startswith("$") and name not in components:
        found[f"show: no component '{name}' to open as a screen; define it, with a title"] = None
    name = node.get("command")
    if commands is not None and isinstance(name, str) and not name.startswith("$") and name not in commands:
        found[f"command: no command '{name}' is bound; app_command binds it to a script, a flow or a job first"] = None
    for value in node.values():
        _shown(value, components, commands, pages, found, depth + 1)


def idle(view) -> list[str]:
    """Arguments written on a view that does not take them: the phone accepts
    them and they do nothing there. Each said once, with the views that do."""
    found: dict[str, None] = {}
    _idle(view, found, 0)
    return list(found)


def _idle(node, found: dict[str, None], depth: int) -> None:
    if depth > MAX_DEPTH:
        return
    if isinstance(node, list):
        for child in node:
            _idle(child, found, depth + 1)
        return
    if not isinstance(node, dict):
        return
    view = next((key for key in sorted(node) if key[:1].isupper()), None)
    if view in TAKES:
        for name in sorted((set(node) & ARGUMENTS) - MODIFIERS - ANYWHERE - TAKES[view] - {view}):
            takers = sorted(other for other, names in TAKES.items() if name in names)
            found[f"{name} does nothing on {view}: it is an argument of {', '.join(takers)}"] = None
    for value in node.values():
        _idle(value, found, depth + 1)


def _looks_like_view(value) -> bool:
    if isinstance(value, list):
        return any(_looks_like_view(item) for item in value)
    return isinstance(value, dict) and any(key[:1].isupper() for key in value)


def defined(ops: list[dict]) -> set[str]:
    """Components a batch defines, usable by the views in the same batch."""
    return {name for op in ops if op.get("op") == "define"
            for name, definition in (op.get("components") or {}).items() if definition is not None}


def removed(ops: list[dict]) -> set[str]:
    """Components a batch deletes, defined as null."""
    return {name for op in ops if op.get("op") == "define" and isinstance(op.get("components"), dict)
            for name, definition in op["components"].items() if definition is None}


def _definitions(components) -> list[str]:
    """Each component is {Name: {props, body, state}}, its name capitalised."""
    if not isinstance(components, dict):
        return ["components: an object of {Name: {props, body}}"]
    names = [name for name in components if name[:1].isupper()]
    found = []
    for name, definition in components.items():
        if not name[:1].isupper():
            where = f" inside {names[0]}" if len(names) == 1 else " inside the component it belongs to"
            found.append(f"components.{name}: component names are capitalised; if '{name}' belongs to a component, "
                         f"it sits beside the components here: move it{where}")
        elif definition is not None and (not isinstance(definition, dict) or "body" not in definition):
            found.append(f"components.{name}: a component is {{\"props\": {{…}}, \"body\": view}}, or null to delete it")
    return found


TOOLBAR_MOST = 3


def toolbar_problems(toolbar) -> list[str]:
    """What is wrong with a screen's or page's bar buttons, beyond what each
    is as a view: Buttons and Menus with a symbol, at most three."""
    if not isinstance(toolbar, list):
        return ["toolbar: a list of up to 3 Buttons or Menus with a symbol, drawn in the bar"]
    found = []
    for index, item in enumerate(toolbar):
        if not isinstance(item, dict) or not ({"Button", "Menu"} & set(item)):
            found.append(f"toolbar[{index}]: the bar takes only a Button or a Menu")
        elif "symbol" not in item:
            found.append(f"toolbar[{index}]: a bar button needs a symbol; its title is the label read aloud")
        elif "style" in item:
            found.append(f"toolbar[{index}]: the bar styles its own buttons; drop style")
    if len(toolbar) > TOOLBAR_MOST:
        found.append(f"toolbar: at most {TOOLBAR_MOST} items beside the app's own; put the rest in a Menu")
    return found


def _toolbar_views(prefix: str, toolbar) -> list[tuple[str, dict, set]]:
    if not isinstance(toolbar, list):
        return []
    return [(f"{prefix}toolbar[{index}]", item, set()) for index, item in enumerate(toolbar) if isinstance(item, dict)]


def _designs(op: dict) -> list[tuple[str, dict]]:
    """The Live Activity designs an op carries, each with where it is: the
    design of a start or a preview, and an `activity` op, which is one itself."""
    found = [("design.", op["design"])] if isinstance(op.get("design"), dict) else []
    return found + ([("", op)] if op.get("op") == "activity" else [])


def check_ops(ops: list[dict], components: set[str], commands: set[str] | None = None, pages: set[str] | None = None) -> list[str]:
    """Every view an op carries: cards, pages, documents, components, Live Activity designs."""
    components = (components | defined(ops)) - removed(ops)
    if pages is not None:
        pages = (pages | {op["id"] for op in ops if op.get("op") == "page" and op.get("id") and not op.get("remove")}) - \
                {op.get("id") for op in ops if op.get("op") == "page" and op.get("remove")}
    found = []
    for index, op in enumerate(ops):
        where = f"ops[{index}] {op.get('op')}"
        views = []
        if isinstance(op.get("card"), dict):
            views.append(("card.view", op["card"].get("view"), set()))
        for key in ("view", "summary"):
            if key in op:
                views.append((key, op[key], set()))
        if op.get("op") == "page" and "toolbar" in op:
            found += [f"{where} {problem}" for problem in toolbar_problems(op["toolbar"])]
            views += _toolbar_views("", op["toolbar"])
        if op.get("op") == "define":
            found += [f"{where} {problem}" for problem in _definitions(op.get("components"))]
            for name, body in (op.get("components") or {}).items():
                if isinstance(body, dict) and "toolbar" in body:
                    found += [f"{where} components.{name}.{problem}" for problem in toolbar_problems(body["toolbar"])]
                    views += _toolbar_views(f"components.{name}.", body["toolbar"])
            views += [(f"components.{name}", body.get("body"), set()) for name, body in (op.get("components") or {}).items()
                      if isinstance(body, dict)]
        for prefix, design in _designs(op):
            if misplaced := sorted(set(design) & REGIONS):
                found.append(f"{where} {prefix}{misplaced[0]}: a design's regions go inside views: "
                             f'{{"views": {{"{misplaced[0]}": …}}}}; the phone draws nothing of a region beside it')
            own = design.get("components")
            if own is not None:
                found += [f"{where} {prefix}{problem}" for problem in _definitions(own)]
            own = own if isinstance(own, dict) else {}
            local = {name for name, body in own.items() if body is not None}
            views += [(f"{prefix}components.{name}", body.get("body"), local) for name, body in own.items() if isinstance(body, dict)]
            if isinstance(design.get("views"), dict):
                views += [(f"{prefix}views.{region}", view, local) for region, view in design["views"].items()]
        for label, view, local in views:
            found += [f"{where} {label}: {problem}" for problem in problems(view, components | local) + shown(view, components | local, commands, pages)]
    return found
