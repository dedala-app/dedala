# SPDX-FileCopyrightText: 2026 Julien Malka
# SPDX-License-Identifier: MIT

"""`app_data`: the one tool for what the agent keeps for him. A store is a
file here (stores.py): written with data or a patch, linked to a path of his
own, declared so its records show in the phone's Search, read back as the
phone sees it, removed; a record of a declared store can be handed to him in
the conversation."""

import difflib
from pathlib import Path

from . import analysis, checks, session
from .stores import DECLARATION, records_of

SAMPLE = 20


def _summary(link, name: str, full: bool = False) -> dict:
    stores = link.stores
    data = stores.held.get(name)
    kind = stores.kind(name)
    found: dict = {"id": name, "kind": kind or "json"}
    if name in stores.links:
        found["path"] = stores.links[name]["path"]
    else:
        found["file"] = str(stores.path(name))
    if name in stores.declared:
        found["declared"] = stores.declared[name]
    if name in stores.unreadable:
        found["unreadable"] = stores.unreadable[name]
    if kind == "folder":
        found["records"] = len(data or [])
        if stores.ignore(name):
            found["ignore"] = stores.ignore(name)
            found["ignored"] = stores.ignored.get(name, 0)
        shown = [{key: item.get(key) for key in ("id", "title", "tags", "updated")} for item in (data or [])]
        found["files"] = shown if full else shown[:SAMPLE]
    elif kind == "text":
        found.update({key: (data or {}).get(key) for key in ("name", "exists", "updated")})
        text = (data or {}).get("text") or ""
        found["text"] = text if full else text[:1200]
    elif (records := records_of(data)) is not None:
        found["records"] = len(records)
        if full:
            found["data"] = data
        else:
            found["sample"] = records[:5]
        if attachments := stores.attachments(name):
            found["attachments"] = [{"id": identifier, "file": str(path), "exists": path.is_file()} for identifier, path in attachments]
    elif full:
        found["data"] = data
    elif isinstance(data, dict):
        found["keys"] = sorted(data)[:SAMPLE]
    readers = sorted(analysis._readers(name, link.state.get("artifacts", {})))
    if readers:
        found["read_by"] = readers
    if job := (link.app.loaded.get("triggers", {}).get("store") or {}).get(name):
        found["handled_by"] = job
    return found


def _declaration_problem(link, declaration: dict) -> str | None:
    screen = declaration.get("screen")
    if screen and screen not in link.state.get("artifacts", {}).get("components", {}):
        return f"screen names the component {screen}, which is not defined: define it first (app_page components, or app_ops define), with a title and an id prop"
    for key in ("title", "subtitle"):
        if declaration.get(key) is not None and not isinstance(declaration[key], str):
            return f"{key} is an expression over a record, a string like \"$name\""
    if declaration.get("words") is not None and not (isinstance(declaration["words"], list) and all(isinstance(word, str) for word in declaration["words"])):
        return "words is a list of expressions over a record, like [\"$email\", \"$text\"]"
    return None


async def data(args: dict, **_) -> str:
    link = session.link()
    stores = link.stores
    name = args.get("id") or ""
    if not name:
        return session.answer({"stores": [_summary(link, known) for known in sorted(stores.held)]})
    if args.get("remove"):
        if name not in stores.held and name not in stores.links:
            return session.answer({"error": f"There is no store {name}"})
        linked = name in stores.links
        await session.on_gateway(session.run(_remove, link, name))
        checked = await session.on_gateway(link.send_and_check([{"op": "store", "id": name, "data": None}]))
        return session.answer({"removed": name, **({"note": "The file stays where it was; only the link is gone"} if linked else {}), **checked})
    declaration = {key: args[key] for key in DECLARATION if args.get(key) is not None}
    writing = any(key in args and args[key] is not None for key in ("data", "patch", "path")) or "ignore" in args
    if args.get("say") is not None and not args.get("record"):
        return session.answer({"error": "say hands him a record: give record, its id in this store"})
    if args.get("handled_by") is not None:
        from . import records

        if args["handled_by"] and (problem := await records.no_job(args["handled_by"])):
            return problem
        triggers = dict(link.app.loaded["triggers"])
        on_store = dict(triggers.get("store") or {})
        if args["handled_by"]:
            on_store[name] = args["handled_by"]
        else:
            on_store.pop(name, None)
        triggers["store"] = on_store
        await session.on_gateway(session.run(link.app.write, "triggers", None, triggers))
        if not writing and not declaration and args.get("record") is None:
            return session.answer({"store": _summary(link, name), "handled_by": args["handled_by"] or None})
    if not writing and not declaration and args.get("record") is None and not args.get("declare_clear"):
        if name not in stores.held:
            return session.answer({"error": f"There is no store {name}: give data, or path, to make it"})
        return session.answer({"store": _summary(link, name, full=True)})
    ops = []
    if args.get("path"):
        path = Path(args["path"]).expanduser()
        if not path.exists():
            return session.answer({"error": f"{path} does not exist: make the file or the folder first, then link it"})
        if args.get("data") is not None or args.get("patch") is not None:
            return session.answer({"error": "A linked store is written through its file: give path alone, then data only for a JSON file"})
        await session.on_gateway(session.run(stores.link, name, str(path)))
    if "ignore" in args:
        if stores.kind(name) != "folder":
            return session.answer({"error": f"ignore is for a folder store; {name} is {stores.kind(name) or 'a JSON store'}"})
        if args["ignore"] is not None and not (isinstance(args["ignore"], list) and all(isinstance(pattern, str) for pattern in args["ignore"])):
            return session.answer({"error": "ignore is a list of patterns (\"npins/\", \"*.nix\", \"assets/*.mp4\"), or null to clear"})
        await session.on_gateway(session.run(stores.set_ignore, name, args["ignore"]))
        link.stores_written()
    if args.get("patch") is not None and args.get("data") is None and name not in stores.held:
        near = difflib.get_close_matches(name, list(stores.held), n=3, cutoff=0.6)
        return session.answer({"error": f"There is no store {name} to patch" + (f"; did you mean {', '.join(near)}?" if near else ": give data to make it")})
    if (args.get("data") is not None or args.get("patch") is not None) and stores.kind(name) in ("text", "folder"):
        return session.answer({"error": f"The store {name} is a {stores.kind(name)} store: write its file, or edit its items from a page"})
    if declaration:
        if problem := _declaration_problem(link, {**stores.declared.get(name, {}), **declaration}):
            return session.answer({"error": problem})
    op: dict = {"op": "store", "id": name}
    if args.get("data") is not None:
        op["data"] = args["data"]
    elif args.get("patch") is not None:
        op["patch"] = args["patch"]
    if declaration:
        op["declare"] = {**stores.declared.get(name, {}), **declaration}
    elif args.get("declare_clear"):
        op["declare"] = None
    if "data" not in op and "patch" not in op and name not in stores.held and not args.get("path"):
        return session.answer({"error": f"There is no store {name} to declare: give data, or path, with it"})
    ops.append(op)
    if args.get("record") is not None:
        records = records_of(stores.held.get(name)) or []
        if args.get("data") is not None:
            records = records_of(args["data"]) or []
        if not any(item.get("id") == args["record"] for item in records):
            return session.answer({"error": f"There is no record {args['record']} in {name}"})
        ops.append({"op": "say", "conversation": session.conversation_of(args), "text": args.get("say") or "",
                    "record": {"store": name, "id": args["record"]}})
    warnings: list[str] = []
    if "data" in op or "patch" in op:
        held = stores.held.get(name) or {}
        new = op["data"] if "data" in op else checks.merge(held if isinstance(held, dict) else {}, op.get("patch") or {})
        _, warnings = analysis.sharing(name, new, link.state.get("artifacts", {}))
    checked = await session.on_gateway(link.send_and_check(ops))
    attachments = await session.on_gateway(link.unsent_attachments())
    if attachments:
        await session.on_gateway(link.send(attachments, record=False))
    answer = {"store": _summary(link, name), **checked}
    if attachments:
        answer["attachments"] = [f"{item['store']}/{item['id']}" for item in attachments]
    if args.get("record") is not None:
        answer["handed"] = args["record"]
    return checks.with_warnings(session.answer(answer), warnings)


def _remove(link, name: str) -> None:
    if name in link.stores.links:
        link.stores.unlink(name)
        link.stores.declare(name, None)
    else:
        link.stores.put(name, None)
    link._mirror([name])
    link._stores_sent([name])


async def search(args: dict, **_) -> str:
    from .search import entries, search as find

    link = session.link()
    artifacts = link.state.get("artifacts", {})
    query = (args.get("query") or "").strip()
    if not query:
        return session.answer({"stores": [{"id": name, **link.stores.declared[name], "records": len(records_of(link.stores.held.get(name)) or [])}
                                          for name in sorted(link.stores.declared)],
                               "pages": len(artifacts.get("page", {}))})
    return session.answer({"query": query, "results": find(entries(artifacts, link.stores), query, args.get("in"))})


FAMILIES = ("small", "medium", "large")


async def widget(args: dict, **_) -> str:
    """`app_widget`: a Home Screen widget, a component over a store."""
    link = session.link()
    artifacts = link.state.get("artifacts", {})
    widgets = artifacts.get("widget", {})
    name = args.get("id")
    if not name:
        return session.answer({"widgets": [{key: value for key, value in op.items() if key != "op"} for op in widgets.values()],
                               "note": "He adds a widget on his Home Screen himself and picks one of these by name"})
    if args.get("remove"):
        if name not in widgets:
            return session.answer({"error": f"There is no widget {name}"})
        checked = await session.on_gateway(link.send_and_check([{"op": "widget", "id": name, "remove": True}]))
        return session.answer({"removed": name, **checked})
    known = widgets.get(name, {})
    store = args.get("store") or known.get("store")
    component = args.get("component") or known.get("component")
    families = args.get("families") or known.get("families") or list(FAMILIES)
    if not store or not component:
        return session.answer({"error": "A widget needs store, the JSON store it shows, and component, the component drawn over it as its data"})
    if store not in link.stores.held:
        return session.answer({"error": f"There is no store {store}: make it with app_data first"})
    if link.stores.kind(store) is not None:
        return session.answer({"error": f"The store {store} is a {link.stores.kind(store)} store: a widget shows a JSON store"})
    if component not in artifacts.get("components", {}):
        return session.answer({"error": f"The component {component} is not defined: define it first (app_ops define), reading the store's fields as $data"})
    if any(family not in FAMILIES for family in families):
        return session.answer({"error": f"families are among {', '.join(FAMILIES)}"})
    op = {"op": "widget", "id": name, "store": store, "component": component, "families": families}
    checked = await session.on_gateway(link.send_and_check([op]))
    return session.answer({"widget": {key: value for key, value in op.items() if key != "op"},
                           "then": "He adds the widget on his Home Screen and picks it by name; it redraws as the store changes", **checked})


async def token(args: dict, **_) -> str:
    """`app_token`: a key a program holds to write stores, ring him or post
    arrivals through the inbox listener, with that scope only."""
    import secrets

    link = session.link()
    tokens = dict(link.app.loaded["tokens"])
    name = args.get("id")
    if not name:
        return session.answer({"tokens": [{"id": scope.get("id"), **{key: scope[key] for key in ("stores", "sources", "notify") if key in scope}}
                                          for scope in tokens.values()]})
    held = next((key for key, scope in tokens.items() if scope.get("id") == name), None)
    if args.get("remove"):
        if held is None:
            return session.answer({"error": f"There is no token {name}"})
        tokens.pop(held)
        await session.on_gateway(session.run(link.app.write, "tokens", None, tokens))
        return session.answer({"removed": name})
    scope = {"id": name}
    for key in ("stores", "sources"):
        if args.get(key) is not None:
            if not isinstance(args[key], list) or not all(isinstance(item, str) for item in args[key]):
                return session.answer({"error": f"{key} is a list of names, or [\"*\"] for all"})
            scope[key] = args[key]
    if args.get("notify"):
        scope["notify"] = True
    if not any(key in scope for key in ("stores", "sources", "notify")):
        return session.answer({"error": "A token needs a scope: stores it may write, sources it may post to, or notify"})
    if held:
        tokens.pop(held)
    key = secrets.token_urlsafe(24)
    tokens[key] = scope
    await session.on_gateway(session.run(link.app.write, "tokens", None, tokens))
    return session.answer({"token": key, "scope": scope,
                           "use": "Authorization: Bearer <token> on POST /store/<id>, /notify or /in/<source> of the inbox listener, no signature needed; "
                                  "shown once, keep it where the program reads it (a Windmill resource, a file 0600)"})
