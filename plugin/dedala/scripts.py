# SPDX-FileCopyrightText: 2026 Julien Malka
# SPDX-License-Identifier: MIT

"""Scripts are run here before they reach the phone, in QuickJS (the plugin's
WebAssembly module, native.py) with the same
helpers (helpers.js) and the same inputs: derived values on the data and the
first state, handlers on the agent's examples or once on the first state. A
script that throws, runs out of time or returns what is not JSON is not sent.
The live values are samples of the right shape: the phone computes the real ones."""

import json
import logging
import re
from collections import Counter
from datetime import datetime
from pathlib import Path

from . import native

logger = logging.getLogger(__name__)

HELPERS = Path(__file__).with_name("helpers.js")
TIMEOUT = 5
RESULT_LIMIT = 256 * 1024
# The stores a script names, `stores.daily` or `stores['daily']`: only they are given to it, as on the phone.
STORES = re.compile(r"""stores\s*(?:\.\s*([A-Za-z_$][\w$]*)|\[\s*['"]([^'"]+)['"]\s*\])""")
HANDLER_KEYS = {"state", "send", "say", "edit", "command", "args", "open", "page", "conversation", "card", "haptic"}
NAME = r"^[A-Za-z_$][A-Za-z0-9_$]*$"

def run(source: str, calls: list[tuple[str, dict]], modules: dict[str, str]) -> list[dict]:
    """Each call's result: {"value"} or {"error"}."""
    lines = [HELPERS.read_text()]
    for name, module in sorted(modules.items()):
        lines.append(f"var {name}; try {{ {name} = (function () {{\n{module}\n}})() }} catch (e) {{ console.log(JSON.stringify({{load: 'the module {name} threw: ' + String(e && e.message || e)}})) }}")
    lines.append(f"var __scope; try {{ __scope = __load({json.dumps(source)}) }} catch (e) {{ console.log(JSON.stringify({{load: String(e && e.message || e)}})) }}")
    for index, (function, value) in enumerate(calls):
        lines.append(
            f"if (__scope) try {{ console.log(JSON.stringify({{i: {index}, value: __call(__scope, {json.dumps(function)}, {json.dumps(json.dumps(value))})}})) }}"
            f" catch (e) {{ console.log(JSON.stringify({{i: {index}, error: String(e && e.message || e)}})) }}")
    ran = native.run_script("\n".join(lines), TIMEOUT)
    missing = ran.get("error") or "did not run"
    return [result or {"error": missing} for result in _parse(ran.get("output") or "", len(calls))]


def _parse(output: str, count: int) -> list[dict | None]:
    """Each call's result by its number, None for one that printed none: what
    the script prints itself is not a result."""
    results: list[dict | None] = [None] * count
    for line in output.splitlines():
        try:
            found = json.loads(line)
        except ValueError:
            continue
        if not isinstance(found, dict):
            continue
        if isinstance(found.get("load"), str) and "i" not in found:
            return [{"error": f"the script does not load: {found['load']}"}] * count
        index = found.get("i")
        if not isinstance(index, int) or isinstance(index, bool) or not 0 <= index < count or results[index] is not None:
            continue
        if "error" in found:
            results[index] = {"error": found["error"]}
            continue
        text = found.get("value") or "null"
        if len(text.encode()) > RESULT_LIMIT:
            results[index] = {"error": f"returned {len(text.encode()) // 1024} KB, more than 256 KB"}
        else:
            results[index] = {"value": json.loads(text)}
    return results


def samples(runs: list[dict]) -> dict:
    """The live values, shaped as the phone computes them."""
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    return {
        "waiting": [{"card": "sample", "conversation": "main", "topic": None, "said": "A sample question", "at": now}],
        "running": {"turns": [], "runs": [{"id": run.get("id"), "job": run.get("job"), "name": run.get("name"),
                                           "doing": run.get("doing") or "Thinking", "since": run.get("started")}
                                          for run in runs if run.get("status") == "running"]},
        "today": {"answered": [], "runs": [], "messages": 0},
        "pages": [],
    }


def _handlers(view, components: dict, seen: frozenset = frozenset()) -> dict[str, object]:
    """The handlers a view's actions run, with the args written there."""
    found: dict[str, object] = {}
    if isinstance(view, dict):
        if isinstance(view.get("run"), str):
            found[view["run"]] = view.get("args")
        for key, value in view.items():
            if key[:1].isupper() and key not in seen and isinstance(components.get(key), dict):
                found.update(_handlers(components[key].get("body"), components, seen | {key}))
            found.update(_handlers(value, components, seen))
    elif isinstance(view, list):
        for item in view:
            found.update(_handlers(item, components, seen))
    return found


def check(surface: dict, data, modules: dict[str, str], components: dict, live: dict, handlers: bool = True) -> dict:
    """What a card's or page's script computes here: {"derived", "handlers"},
    and its "errors", each a sentence for the agent; without `handlers`, only
    the derived values."""
    import re

    source = surface.get("script")
    if not source:
        return {}
    errors: list[str] = []
    derive = surface.get("derive") or {}
    if not isinstance(derive, dict):
        return {"errors": ["derive maps each derived value's name to a function of the script"]}
    keys = set(data) if isinstance(data, dict) else set()
    for name, function in derive.items():
        if name in keys:
            errors.append(f"The derived value {name} has the name of a data key; rename one of them")
        if not isinstance(function, str) or not re.match(NAME, function):
            errors.append(f"The derived value {name} needs the name of a function of the script")
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    state = surface.get("state") or {}
    named = set(STORES.findall(source))
    stores = {name: value for name, value in (live.get("stores") or {}).items() if name in {a or b for a, b in named}}
    base = {"data": data if data is not None else {}, "state": state, "now": now, **live, "stores": stores}
    calls: list[tuple[str, dict]] = [(function, base) for function in derive.values() if isinstance(function, str)]
    labels = [("derived", name, f"the derived value {name} ({function})") for name, function in derive.items() if isinstance(function, str)]
    examples = (surface.get("examples") or [{"run": name, "args": args} for name, args in _handlers(surface.get("view"), components).items()]
                if handlers else [])
    for example in examples:
        if not isinstance(example, dict) or not isinstance(example.get("run"), str):
            errors.append("Each example is {run, args, state, now}")
            continue
        calls.append((example["run"], {**base, "state": {**state, **(example.get("state") or {})},
                                       "now": example.get("now") or now, "args": example.get("args")}))
        labels.append(("handler", example["run"], f"the handler {example['run']}"))
    defined = source + "\n" + "\n".join(module for module in (modules or {}).values() if isinstance(module, str))
    if handlers:
        errors += [f"The view runs {name}, which the script does not define" for name in sorted(_handlers(surface.get("view"), components))
                   if re.fullmatch(NAME, name) and not re.search(rf"\b{re.escape(name)}\b", defined)]
    repeated = Counter(name for kind, name, _ in labels if kind == "handler")
    results = run(source, calls, modules)
    found: dict = {"derived": {}, "handlers": {}}
    for (kind, name, label), result in zip(labels, results):
        if "error" in result:
            errors.append(f"Script: {label} {result['error']}")
        elif kind == "derived":
            found["derived"][name] = result["value"]
        else:
            value = result["value"]
            if value is not None and not isinstance(value, dict):
                errors.append(f"Script: {label} returns an object of what happens next, or nothing")
            elif isinstance(value, dict) and (unknown := set(value) - HANDLER_KEYS):
                buttons = " (close and set are what a button's action does, not what a handler returns)" if unknown & {"close", "set"} else ""
                errors.append(f"Script: {label} returns {', '.join(sorted(unknown))}, which a handler cannot do; it can return "
                              f"{', '.join(sorted(HANDLER_KEYS))}{buttons}")
            elif repeated[name] > 1:
                found["handlers"].setdefault(name, []).append(value)
            else:
                found["handlers"][name] = value
    if errors:
        found["errors"] = errors
    if re.search(r"\.toLocale\w*String\(", defined):
        found["notes"] = ["toLocale…String formats with his locale on the phone and without one here, so what it gives "
                          "differs: build the text yourself, or pass the date to the view's own date functions"]
    return found


def check_modules(modules: dict, existing: dict[str, str]) -> list[str]:
    """Modules load on their own and with the others."""
    import re

    errors = []
    for name, source in modules.items():
        if not re.match(NAME, name):
            errors.append(f"A script module's name is a JavaScript name: {name}")
        elif source is not None and not isinstance(source, str):
            errors.append(f"The module {name} is JavaScript source, ending with return {{…}}")
    if errors:
        return errors
    merged = {**existing, **{name: source for name, source in modules.items() if source is not None}}
    for result in run("function __ok() { return true }", [("__ok", {"now": datetime.now().astimezone().isoformat()})], merged):
        if "error" in result:
            errors.append(f"The modules do not load: {result['error']}")
    return errors
