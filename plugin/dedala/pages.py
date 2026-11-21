# SPDX-FileCopyrightText: 2026 Julien Malka
# SPDX-License-Identifier: MIT

"""The page tool, and the raw ops beside it: a page built widget by widget,
reading stores by name, laid out as his phone draws it. No designer reviews
a page: a review judged the whole page on every edit (docs/footguns.md)."""

import asyncio
import json
import re

from . import analysis, checks, records, session
from .stores import records_of


def _page_spec(view, state) -> dict:
    """A page as the twin lays it out: every store as it stands."""
    return {"view": view, "data": {}, "stores": checks.all_stores(), "state": state or {}}


def _screens(view, components: dict) -> dict[str, dict]:
    """The screens a page opens (a `show` naming a titled component), each with
    the props its `show` writes out literally."""
    found: dict[str, dict] = {}

    def walk(node, seen: frozenset) -> None:
        if isinstance(node, list):
            for child in node:
                walk(child, seen)
        elif isinstance(node, dict):
            name = node.get("show")
            if isinstance(name, str) and isinstance(components.get(name), dict) and components[name].get("title"):
                given = node.get("with") if isinstance(node.get("with"), dict) else {}
                found.setdefault(name, {}).update({key: value for key, value in given.items()
                                                   if not (isinstance(value, str) and "$" in value)})
                if name not in seen:
                    walk(components[name].get("body"), seen | {name})
            for key, value in node.items():
                if key[:1].isupper() and key not in seen and isinstance(components.get(key), dict):
                    walk(components[key].get("body"), seen | {key})
                walk(value, seen)

    walk(view, frozenset())
    return found


def _looked_up(body, stores: dict) -> list:
    """The lists a screen's body finds its record in by `$id`
    (`find(sofia.emails, 'id', $id)`), as they stand in the stores."""
    found = []
    for path, key in re.findall(r"find\(\s*([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)\s*,\s*'(\w+)'\s*,\s*\$id\s*\)", json.dumps(body)):
        held = stores
        for step in path.split("."):
            held = held.get(step) if isinstance(held, dict) else None
        if isinstance(held, list):
            found += [item[key] for item in held[:1] if isinstance(item, dict) and isinstance(item.get(key), str)]
    return found


def _sample(name: str, props: dict, definition: dict, stores: dict, declared: dict) -> dict:
    """Props to lay a screen out with: what its `show` writes, and for its id
    the first record of the list its body finds it in, of the store it is the
    screen of, or of any store."""
    if "id" in (definition.get("props") or ()) and "id" not in props:
        if ids := _looked_up(definition.get("body"), stores):
            return {**props, "id": ids[0]}
        own = [store for store, declaration in declared.items() if (declaration or {}).get("screen") == name]
        for store in own + sorted(stores):
            if (found := records_of(stores.get(store))) and isinstance(found[0], dict) and found[0].get("id"):
                return {**props, "id": found[0]["id"]}
    return props


async def _screen_check(view, every: dict, link) -> dict[str, list[str]]:
    """Each screen the page opens laid out as his phone would open it, over a
    sample record: what the twin finds in each."""
    shown = _screens(view, every)
    if not shown:
        return {}
    stores = checks.all_stores()
    found = {}
    for name, props in sorted(shown.items()):
        props = _sample(name, props, every[name], stores, link.stores.declared)
        looked = await checks.look(_page_spec({name: props}, None), None, f"screen-{name}", picture=False, components=every, page=True)
        if looked and looked["faults"]:
            found[name] = looked["faults"]
    return found


def _pages(link) -> str:
    artifacts = link.state.get("artifacts", {})
    components = artifacts.get("components", {})
    stores = set(artifacts.get("store", {}))
    pages = []
    read = set()
    for page_id, recorded in artifacts.get("page", {}).items():
        reads = sorted(analysis.store_reads(recorded.get("view"), components, stores))
        read |= set(reads)
        pages.append({"id": page_id, "title": recorded.get("title"), "symbol": recorded.get("symbol"),
                      "widgets": list(analysis.used(recorded.get("view"), components, {})),
                      **({"reads": reads} if reads else {}),
                      "maintained_by": recorded.get("maintained_by"), "handled_by": recorded.get("handled_by"),
                      "file": str(link.app.path("page", page_id))})
    answer = {"pages": pages}
    if unread := sorted(stores - read):
        answer["stores_no_page_reads"] = unread
    return session.answer(answer)


def _page_op(page_id: str, args: dict, recorded: dict, view) -> dict:
    """The page as it will stand: what the call gives, else what it had."""
    op = {"op": "page", "id": page_id, "title": args.get("title") or recorded.get("title") or page_id, "view": view}
    for name in ("symbol", "state", "toolbar", *checks.SCRIPTED):
        if args.get(name) is not None or recorded.get(name):
            op[name] = args[name] if args.get(name) is not None else recorded.get(name)
    return op


async def _link_jobs(args: dict, recorded: dict, op: dict) -> str | None:
    """Puts on a page's op the jobs it is linked to, as the call gives them or
    as they were, and whether it opens; the refusal when a job does not exist."""
    maintainer = args["maintained_by"] if args.get("maintained_by") is not None else recorded.get("maintained_by")
    if maintainer:
        from .maintenance import state as upkeep

        if (await asyncio.to_thread(upkeep, session.agent(), maintainer) or {}).get("missing"):
            return session.answer({"error": f"No cron job {maintainer}: create it first, then link it with its id"})
        op["maintained_by"] = maintainer
    handler = args["handled_by"] if args.get("handled_by") is not None else recorded.get("handled_by")
    if handler:
        if problem := await records.no_job(handler):
            return problem
        op["handled_by"] = handler
    if args.get("focus"):
        op["focus"] = True
    return None


async def _upkeep(answer: dict, maintainer: str | None) -> None:
    """How fresh the job that maintains a page keeps it, for the answer and for the app."""
    if not maintainer:
        return
    from . import server
    from .maintenance import state as upkeep

    answer["maintained_by"] = await asyncio.to_thread(upkeep, session.agent(), maintainer)
    if server.current:
        await session.on_gateway(server.current.sync_upkeep())


SETTINGS = ("state", "focus", "maintained_by", "handled_by")


async def page(args: dict, **_) -> str:
    link = session.link()
    if not args.get("id"):
        return _pages(link)
    page_id = args["id"]
    if args.get("remove"):
        checked = await session.on_gateway(link.send_and_check([{"op": "page", "id": page_id, "remove": True}]))
        return session.answer({"page": page_id, "removed": True, **checked})
    if args.get("data") is not None or args.get("patch") is not None:
        return session.answer({"sent": False, "error": "A page has no data of its own: it reads stores by name. Write the store with app_data "
                                                       "{id: <store>, data | patch}; the page shows it at once."})
    held = checks.held_back.get(f"page:{page_id}") or {}
    recorded = held.get("page") or link.state.get("artifacts", {}).get("page", {}).get(page_id) or {}
    view = args.get("view") or recorded.get("view")
    if view is None:
        known = ", ".join(f"{other} ({recorded.get('title')})" for other, recorded in link.state.get("artifacts", {}).get("page", {}).items())
        return session.answer({"error": f"There is no page {page_id}" + (f"; his pages are {known}" if known else "") + ". To make a new one, send its view"})
    ops = [carried for carried in held.get("ops", []) if carried.get("op") != "page"]
    if args.get("components"):
        ops.append({"op": "define", "components": args["components"]})
    op = _page_op(page_id, args, recorded, view)
    if refused := await _link_jobs(args, recorded, op):
        return refused
    ops.append(op)
    if refused := checks.refused(ops):
        return refused
    defined = {name: body for carried in ops if carried.get("op") == "define" for name, body in (carried.get("components") or {}).items()}
    artifacts = link.state.get("artifacts", {})
    every = {**artifacts.get("components", {}), **defined}
    stores = {name: (entry or {}).get("data") for name, entry in artifacts.get("store", {}).items()}
    warnings = analysis.store_gaps(analysis.store_reads(view, every, set(stores)), stores)
    warnings += analysis.unresolved(view, set(stores) | set(op.get("state") or {}) | set(op.get("derive") or {}), card=False,
                                    script=op.get("script"))
    found = await checks.script_check({**op, "examples": args.get("examples")}, {})
    if refused := checks.script_refused(found):
        return refused
    looking = recorded and not any(args.get(name) is not None for name in ("view", "components", "title", "symbol", "toolbar", *SETTINGS, *checks.SCRIPTED))
    settling = recorded and not looking and not any(args.get(name) is not None for name in ("view", "components", "title", "symbol", "toolbar", *checks.SCRIPTED))
    key = f"page:{page_id}"
    rounds = 1 if looking or settling else checks.round_of(key)
    last = rounds >= checks.MAX_ROUNDS
    looked = await checks.look(_page_spec(view, op.get("state")), await checks.derived_values(op, {}), f"page-{page_id}", picture=False,
                               components=defined, page=True)
    faults = looked["faults"] if looked else []
    answer = {"page": page_id, "reply": checks.REPLY}
    drawn = [view, *(body.get("body") for body in defined.values() if isinstance(body, dict))]
    if worth := ((looked or {}).get("notes") or []) + checks.remarks(drawn, None, op.get("state"), op.get("derive")):
        answer["notes"] = worth
    if faults:
        answer["problems"] = faults
    if screens := await _screen_check(view, every, link):
        answer["screens"] = {"problems": screens, "laid_out": "each screen this page opens, over a sample record: fix them in its "
                                                               "component (app_page components)"}

    async def send():
        await link.send(ops, notify=not recorded)

    if looking:
        answer["then"] = ("Fix what it lists with app_page, sending only the components or view you change."
                          if faults else f"This is the page as it stands {checks.on_phone(page=True)}.")
    elif faults and not last and not settling:
        checks.hold(key, session.conversation_of(args), send)
        checks.held_back[key].update(page=op, ops=ops)
        answer.update(sent=False, error=f"Not sent: drawn {checks.on_phone(page=True)}, this page has problems he would see.",
                      then="Fix them and send again with app_page, only the components or view you change. It reaches him "
                           f"once it passes, or as it stands after round {checks.MAX_ROUNDS}.")
    else:
        await session.on_gateway(send())
        checks.held_back.pop(key, None)
        answer["sent"] = True
        if settling:
            answer["page_updated"] = sorted(name for name in SETTINGS if args.get(name) is not None)
        if rounds > checks.MAX_ROUNDS:
            answer["then"] = (f"It is on his phone as it stands: this page had its {checks.MAX_ROUNDS} rounds in this request. "
                              "Stop changing it unless he asks.")
        elif faults:
            answer["then"] = "That was the last round: it is on his phone as it stands. Say in one line what is left."
        elif looked is None:
            answer["then"] = "It is on his phone, unchecked: the twin could not lay it out. If the phone finds a problem, you will hear."
        else:
            answer["then"] = "It is on his phone. If the phone finds a problem when it draws it, you will hear."
    answer["file"] = str(link.app.path("page", page_id))
    if shared := analysis.shared(view, every, artifacts, page_id):
        answer["stores"] = shared
    await _upkeep(answer, op.get("maintained_by"))
    if looking:
        answer["definition"] = {"view": view, "components": analysis.used(view, artifacts.get("components", {}), {}),
                                **{key: op[key] for key in checks.SCRIPTED if op.get(key)}}
    return checks.with_warnings(checks.checked(session.answer(answer), found), warnings)


# What app_ops sends, and the tool that sends each of the others: what it
# checks (a card's layout, a page's data, a job that exists) is not skipped.
OPS = {"define", "assets", "receipt", "say", "notify", "buttons"}
SENT_BY = {"page": "app_page", "patch": "app_patch", "store": "app_data", "attachment": "app_data",
           "topic": "app_topic", "activity": "app_activity", "preview": "app_activity"}


def _not_ops(batch) -> str | None:
    found = []
    for index, op in enumerate(batch):
        kind = op.get("op") if isinstance(op, dict) else None
        if kind == "say" and op.get("card") is not None:
            found.append(f"ops[{index}]: a card is said with app_card, which lays it out as his phone will draw it")
        elif kind in SENT_BY:
            found.append(f"ops[{index}]: {kind} goes through {SENT_BY[kind]}")
        elif kind not in OPS:
            found.append(f"ops[{index}]: {kind!r} is not an op app_ops sends ({', '.join(sorted(OPS))})")
    if not found:
        return None
    return session.answer({"sent": False, "error": "Not sent: app_ops does not send these. Nothing of this call was sent.", "problems": found})


async def ops(args: dict, **_) -> str:
    batch = args["ops"]
    if refused := _not_ops(batch):
        return refused
    from .scripts import check_modules

    for op in batch:
        if op.get("op") == "define" and op.get("scripts") is not None:
            if not isinstance(op["scripts"], dict):
                return session.answer({"sent": False, "error": "scripts is {name: source}"})
            if problems := await asyncio.to_thread(check_modules, op["scripts"], checks.modules()):
                return session.answer({"sent": False, "error": "Not sent: the script modules do not load. Fix them and send again.", "problems": problems})
    for op in batch:
        if op.get("op") in ("say", "receipt") and "conversation" not in op:
            op["conversation"] = session.conversation_of(args)
    if refused := checks.refused(batch):
        return refused
    link = session.link()
    for op in batch:
        if op.get("op") == "buttons" and (problem := checks.buttons_problem(op)):
            return session.answer({"sent": False, "error": f"Not sent: {problem}"})
    rung = [op for op in batch if op.get("op") == "notify"]
    for op in rung:
        artifacts = link.state.get("artifacts", {})
        if problem := checks.notify_problem(op, artifacts, link.state.get("topics", {})) or checks.notify_buttons_problem(op, artifacts):
            return session.answer({"sent": False, "error": f"Not sent: {problem}"})
    batch = [op for op in batch if op.get("op") != "notify"]
    from . import server

    for op in rung:
        if problem := await session.on_gateway(server.current.notify(op)):
            return session.answer({"sent": False, "error": f"Not sent: {problem}"})
    if not batch:
        return session.answer({"sent": len(rung), "rung": len(rung)})
    checked = await session.on_gateway(link.send_and_check(batch))
    return session.answer({"sent": len(batch) + len(rung), **({"rung": len(rung)} if rung else {}), **checked})
