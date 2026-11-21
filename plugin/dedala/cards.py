# SPDX-FileCopyrightText: 2026 Julien Malka
# SPDX-License-Identifier: MIT

"""The card tools: say a card once it passes, patch one in place, keep one in the bank."""

import os

from . import analysis, checks, session


async def _deliver(op: dict) -> None:
    """The card, finished, to the phone, once. With the app closed it rings,
    drawn by the notification; the phone's own report comes back in the
    background, and only a problem reaches the agent."""
    link = session.link()
    checks.held_back.pop(op["id"], None)
    session.said_cards().said(op)
    if not link.app_online:
        op = {**op, "components": analysis.used(op["card"]["view"], link.state.get("artifacts", {}).get("components", {}), {})}
        if op["card"].get("script"):
            op["scripts"] = checks.modules()
    await link.send([op], notify=True, collapse=op["id"])


async def _ring(card: str) -> None:
    """A card changed while the app is closed: one notification that rings, with
    the card as it now stands, replacing the last one."""
    spec = session.said_cards().get(card)
    link = session.link()
    if spec is None or link.app_online:
        return
    body = {"view": spec["view"], "data": spec["data"], "state": spec["state"], **{key: spec[key] for key in checks.SCRIPTED if spec.get(key)}}
    op = {"op": "say", "id": card, "conversation": spec["conversation"], "text": spec["text"], "settled": True, "card": body,
          "components": analysis.used(spec["view"], link.state.get("artifacts", {}).get("components", {}), {})}
    if body.get("script"):
        op["scripts"] = checks.modules()
    await link.ring([op], card)


async def card(args: dict, **_) -> str:
    if args.get("keep"):
        if not args.get("id"):
            return session.answer({"error": "keep needs the id of a card you drew"})
        return await keep_card(args)
    if args.get("view") is None:
        return session.answer({"error": "A card needs a view; keep: true with an id puts a drawn card in the bank"})
    message = args.get("id") or f"card-{os.urandom(4).hex()}"
    spec = {"view": args["view"], "data": args.get("data") or {}, "state": args.get("state") or {}}
    spec.update({key: args[key] for key in checks.SCRIPTED if args.get(key)})
    op = {"op": "say", "id": message, "conversation": session.conversation_of(args), "text": args.get("text", ""), "card": spec}
    if refused := checks.refused([op]):
        return refused
    found = await checks.script_check({**spec, "examples": args.get("examples")}, spec["data"])
    if refused := checks.script_refused(found):
        return refused
    rounds = checks.round_of(message)
    last = rounds >= checks.MAX_ROUNDS
    looked = await checks.look(spec, await checks.derived_values(spec, spec["data"]), message, picture=True)
    if looked:
        op["card"] = looked["card"]
    faults = looked["faults"] if looked else []
    worth = ((looked or {}).get("notes") or []) + checks.remarks(spec["view"], spec["data"], spec["state"], spec.get("derive"))
    notes = {"notes": worth} if worth else {}
    stores = checks.all_stores()
    gaps = analysis.store_gaps(analysis.store_reads(spec["view"], session.link().state.get("artifacts", {}).get("components", {}), set(stores)), stores)
    gaps += analysis.unresolved(spec["view"], set(stores) | set(spec["data"] if isinstance(spec["data"], dict) else ())
                                | set(spec["state"] or {}) | set(spec.get("derive") or {}), card=True, script=spec.get("script"))
    if gaps:
        notes["data_check"] = gaps
    if faults and not last:
        checks.hold(message, op["conversation"], lambda: _deliver(op))
        return checks.checked(session.answer({"sent": False, "card": message, "round": rounds, "problems": faults, **notes,
                                 "error": f"Not sent: drawn {checks.on_phone()}, this card has problems he would see.",
                                 "then": "Fix them and send the whole card again with app_card on this id."}), found)
    review = None if faults or rounds > checks.MAX_ROUNDS else await checks.review(looked)
    redo = bool(review) and review.get("verdict") == "FIX"
    if redo and not last:
        checks.hold(message, op["conversation"], lambda: _deliver(op))
        return checks.checked(session.answer({"sent": False, "card": message, "review": {"round": rounds, **review}, **notes,
                                 "then": "Not sent yet: apply the critique and send the whole card again with app_card on this "
                                         f"id. It reaches him once the review passes, or as it stands after round {checks.MAX_ROUNDS}."}), found)
    await session.on_gateway(_deliver(op))
    if looked and looked.get("png"):
        session.said_cards().captured(message, looked["png"])
    answer = {"sent": True, "card": message, "reply": checks.REPLY, **notes}
    if review:
        answer["review"] = {"round": rounds, **review}
    if faults:
        answer["problems"] = faults
    if rounds > checks.MAX_ROUNDS:
        answer["then"] = (f"It is on his phone as it stands, unreviewed: this card had its {checks.MAX_ROUNDS} rounds in this request. "
                          "Stop changing it unless he asks.")
    elif faults or redo:
        answer["then"] = ("That was the last round: it is on his phone as it stands. Do not tell him it is fixed: say in one "
                          "line what is left.")
    elif looked is None:
        answer["then"] = "It is on his phone, unchecked: the twin could not lay it out. If the phone finds a problem, you will hear."
    else:
        answer["then"] = "It is on his phone: you are done with it. If the phone finds a problem when it draws it, you will hear."
    return checks.checked(session.answer(answer), found)


async def patch(args: dict, **_) -> str:
    if args["id"] in checks.held_back:
        return session.answer({"sent": False, "error": "This card has not reached him yet: send the whole card again with app_card on this id."})
    known = session.said_cards().get(args["id"])
    if known is None:
        recent = [{"id": card, "text": spec.get("text")} for card, spec in session.said_cards().recent(5)]
        return session.answer({"sent": False, "error": f"There is no card {args['id']}: nothing was patched. A card is patched by the id "
                                                       "app_card answered with; to say a new one, use app_card.", "recent_cards": recent})
    op = {"op": "patch", "id": args["id"]}
    for key in ("data", "view", "state", *checks.SCRIPTED):
        if args.get(key) is not None:
            op[key] = args[key]
    if args.get("text") is not None:
        op["say"] = args["text"]
    if refused := checks.refused([op]):
        return refused
    worth = checks.remarks(op.get("view"), op.get("data"), op.get("state"), op.get("derive"))
    notes = {"notes": worth} if worth else {}
    warnings = analysis.lists_replaced(known.get("data") or {}, op.get("data") or {})
    after = {**known, **{key: op[key] for key in ("view", *checks.SCRIPTED) if key in op},
             "data": checks.merge(known.get("data") or {}, op.get("data") or {}),
             "state": {**(known.get("state") or {}), **(op.get("state") or {})}}
    found = await checks.script_check({**after, "examples": args.get("examples")}, after["data"])
    if refused := checks.script_refused(found):
        return refused
    body = {key: after[key] for key in ("view", "data", "state", *checks.SCRIPTED) if after.get(key) is not None}
    looked = await checks.look(body, await checks.derived_values(after, after["data"]), args["id"], picture=False)
    if looked and looked["faults"] and checks.round_of(args["id"]) < checks.MAX_ROUNDS:
        return checks.checked(session.answer({"sent": False, "card": args["id"], "problems": looked["faults"], **notes,
                                 "error": f"Not sent: drawn {checks.on_phone()}, the card would have problems he would see after this change.",
                                 "then": "Fix them and send the change again."}), found)
    session.said_cards().patched(op)
    await session.on_gateway(session.link().send([op]))
    if not session.link().app_online:
        await session.on_gateway(_ring(args["id"]))
    return checks.with_warnings(checks.checked(session.answer({"sent": True, "card": args["id"], "reply": checks.REPLY, **notes}), found), warnings)


async def keep_card(args: dict) -> str:
    from .bank import annotate, keep

    spec = session.said_cards().get(args["id"])
    if spec is None:
        if path := annotate(session.link().home, args["id"], args.get("note") or ""):
            return session.answer({"kept": str(path), "note": "added to the card already in the bank"})
        return session.answer({"error": f"No card {args['id']} is known here: the bank keeps cards you drew with app_card"})
    path = keep(session.link().home, args["id"], spec, args.get("note") or "", "said")
    return session.answer({"kept": str(path)})
