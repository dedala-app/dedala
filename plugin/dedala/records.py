# SPDX-FileCopyrightText: 2026 Julien Malka
# SPDX-License-Identifier: MIT

"""The tools for topics, Live Activities, and what the phone and the inbox brought."""

import asyncio
import time

from . import session


async def topic(args: dict, **_) -> str:
    link = session.link()
    topics = link.state.get("topics", {})
    if not args.get("id"):
        return session.answer({"topics": [{"id": key, **value} for key, value in sorted(topics.items(), key=lambda kept: kept[1].get("opened") or "")]})
    known = topics.get(args["id"])
    if known is None and not args.get("title"):
        return session.answer({"error": f"There is no topic {args['id']}: a new one needs a title"})
    if known is not None and not any(args.get(key) is not None for key in ("title", "symbol", "color", "outcome", "closed", "opening", "link_line", "brief")):
        return session.answer({"id": args["id"], **known})
    op = {"op": "topic", "id": args["id"]}
    for key in ("title", "symbol", "color", "outcome"):
        if args.get(key):
            op[key] = args[key]
    if args.get("closed") is not None:
        op["closed"] = bool(args["closed"])
    now = time.strftime("%Y-%m-%dT%H:%M:%S%z")

    def keep() -> dict:
        kept = link.state.setdefault("topics", {}).setdefault(
            args["id"], {"title": args.get("title"), "opened": now, "closed": None, "outcome": None})
        if args.get("title"):
            kept["title"] = args["title"]
        if args.get("outcome"):
            kept["outcome"] = args["outcome"]
        if args.get("closed") is not None:
            kept["closed"] = now if args["closed"] else None
        link._save()
        return kept

    kept = await session.on_gateway(session.run(keep))
    first = [op, {"op": "say", "conversation": args["id"], "text": args.get("opening", "")}] if args.get("opening") else [op]
    if args.get("link_line"):
        first.append({"op": "say", "conversation": "main", "topic": args["id"], "text": args["link_line"]})
    checked = await session.on_gateway(link.send_and_check(first))
    answer = {"topic": args["id"], **kept, **checked}
    if args.get("brief"):
        if session.agent().seed(args["id"], args["brief"]):
            answer["brief_seeded"] = True
        else:
            await session.on_gateway(session.run(_keep_brief, link, args["id"], args["brief"]))
            answer["brief_kept"] = "Its session could not be given it now: it comes with the first message in the topic"
    return session.answer(answer)


def _keep_brief(link, topic: str, brief: str) -> None:
    link.state.setdefault("briefs", {})[topic] = brief
    link._save()


async def no_job(job: str) -> str | None:
    from .maintenance import state as upkeep

    if (await asyncio.to_thread(upkeep, session.agent(), job) or {}).get("missing"):
        return session.answer({"error": f"No cron job {job}: create it first (deliver local), then link it with its id"})
    return None


async def events(args: dict, **_) -> str:
    """What happened on his side: his edits, and what arrived from outside."""
    from . import server

    if server.current is None:
        raise RuntimeError("The app platform is not running in this gateway")
    link = session.link()
    answer: dict = {}
    only = args.get("only")
    limit = int(args["limit"]) if args.get("limit") else None
    if only != "arrived":
        after = args.get("after")
        answer["changes"] = link.changes(args.get("since"), limit, int(after) if after is not None else None)
    if only != "changes":
        besides = frozenset(source for source in await asyncio.to_thread(server.current.arrival_jobs) if source != "*")
        taken = await asyncio.to_thread(server.current.inbox.take, args.get("source") or None, args.get("since") or None, limit or 20, besides)
        from .inbox import Inbox

        answer["arrived"] = [Inbox.shown(item) for item in taken]
    if not answer.get("changes") and not answer.get("arrived"):
        answer["note"] = "Nothing happened on his side" + (f" since {args['since']}" if args.get("since") else "") + (f" from {args['source']}" if args.get("source") else "")
    return session.answer(answer)
