# SPDX-FileCopyrightText: 2026 Julien Malka
# SPDX-License-Identifier: MIT

"""Live Activities bound to stores: a design over a store's value, started by
the agent, then kept current by whoever writes the store's file. Each change
to the file is a push on the activity's channel; `ended: true` in the store
ends it; an `alert` in the store sounds once per distinct alert."""

import contextlib
import json
import logging
import zlib
from typing import Callable, Optional

from .stores import fingerprint

logger = logging.getLogger(__name__)

# What a push can carry of the store, compressed: iOS caps a payload at 4KB.
STATE_BUDGET = 3000
OWN_KEYS = ("ended", "alert")
KINDS = {str: "a string", list: "a list", bool: "true or false", int: "a number", float: "a number", type(None): "nothing"}


def too_large(data) -> Optional[str]:
    """Why the store's value cannot ride in a push, or None."""
    body = json.dumps(shown(data), ensure_ascii=False).encode()
    size = len(zlib.compress(body, 9))
    if size > STATE_BUDGET:
        return f"the store is {size} bytes compressed, more than a push carries ({STATE_BUDGET}): keep in it only what the design reads"
    return None


def shown(data) -> dict:
    """The store's value as the activity's data: its own keys left out."""
    if not isinstance(data, dict):
        return {"value": data}
    return {key: value for key, value in data.items() if key not in OWN_KEYS}


class Activities:
    def __init__(self, state: dict, save: Callable[[], None], stores):
        self.state = state
        self.save = save
        self.stores = stores

    @property
    def bound(self) -> dict:
        return self.state.setdefault("activities", {})

    def problem(self, store: str, design: dict) -> Optional[str]:
        if store not in self.stores.held:
            return f"There is no store {store}: make it with app_data first, holding what the design reads"
        if self.stores.kind(store) is not None:
            return f"The store {store} is a {self.stores.kind(store)} store: bind an activity to a JSON store"
        data = self.stores.held[store]
        if isinstance(data, dict) and data.get("ended"):
            return f"The store {store} says ended: true; an activity bound to it would end at once"
        if not isinstance(data, dict) and (missing := self.missing(store, design)):
            return (f"The store {store} holds {KINDS.get(type(data), 'a value')}, not an object: the design reads "
                    f"{', '.join(f'${name}' for name in missing)} by name and would draw nothing. "
                    "Write the store as an object with those keys")
        return too_large(data)

    def missing(self, store: str, design: dict) -> list[str]:
        """The names a design reads that its store does not have."""
        from .analysis import names_read
        from .grammar import LIVE

        own = design.get("state") if isinstance(design.get("state"), dict) else {}
        return sorted(names_read(design.get("views")) - set(shown(self.stores.held.get(store))) - LIVE - set(own))

    def remarks(self, store: str, design: dict) -> list[str]:
        """What an activity about to start would show empty."""
        if missing := self.missing(store, design):
            return [f"The design reads {', '.join(f'${name}' for name in missing)}, which the store {store} does not have: "
                    "they show empty until it does"]
        return []

    async def start(self, link, activity: str, store: str, design: dict, alert: Optional[dict], again: bool = True) -> dict:
        """Starts an activity; one already running under that id ends first, since
        iOS keeps drawing the design an activity started with."""
        if again and activity in self.bound:
            with contextlib.suppress(Exception):
                await link.update_activity(activity, {}, True, None)
        data = self.stores.held.get(store)
        answer = await link.start_activity(activity, design, shown(data), alert)
        if answer.get("error"):
            return answer
        self.bound[activity] = {"store": store, "design": design, "sent": fingerprint(shown(data)),
                                "alert": fingerprint(data.get("alert")) if isinstance(data, dict) and data.get("alert") else None}
        self.save()
        return answer

    async def restart(self, link) -> None:
        """The activities that were running, started on a newly paired phone from
        where their stores are now; one started before designs were kept ends."""
        for activity, binding in list(self.bound.items()):
            design = binding.get("design")
            problem = self.problem(binding["store"], design) if isinstance(design, dict) else "its design was not kept"
            answer = {"error": problem} if problem else await self.start(link, activity, binding["store"], design, None, again=False)
            if answer.get("error"):
                logger.info("[app] the activity %s does not start again on the new phone: %s", activity, answer["error"])
                self.bound.pop(activity, None)
                self.save()

    async def end(self, link, activity: str) -> dict:
        binding = self.bound.pop(activity, None)
        self.save()
        if binding is None and activity not in link.state.get("channels", {}):
            return {"error": f"No activity {activity} is running"}
        return await link.update_activity(activity, {}, True, None)

    async def sync(self, link) -> None:
        """A bound store that moved since its last push is pushed: an update,
        with its alert when that is new, or the end."""
        for activity, binding in list(self.bound.items()):
            store = binding["store"]
            if store not in self.stores.held:
                logger.info("[app] the store %s of the activity %s is gone; the activity ends", store, activity)
                await self.end(link, activity)
                continue
            data = self.stores.held[store]
            if isinstance(data, dict) and data.get("ended"):
                await self.end(link, activity)
                continue
            current = fingerprint(shown(data))
            if current == binding.get("sent"):
                continue
            if too_large(data):
                logger.warning("[app] the store %s grew past what a push carries; the activity %s is not updated", store, activity)
                binding["sent"] = current
                self.save()
                continue
            alert = data.get("alert") if isinstance(data, dict) and isinstance(data.get("alert"), dict) else None
            ringing = alert if alert and fingerprint(alert) != binding.get("alert") else None
            answer = await link.update_activity(activity, shown(data), False, ringing)
            if answer.get("error"):
                logger.warning("[app] the activity %s could not be updated: %s", activity, answer["error"])
                self.bound.pop(activity, None)
            else:
                binding["sent"] = current
                if ringing:
                    binding["alert"] = fingerprint(alert)
            self.save()

    def shown(self) -> list[dict]:
        return [{"id": activity, "store": binding["store"]} for activity, binding in self.bound.items()]


async def tool(args: dict, **_) -> str:
    """`app_activity`: starts an activity over a store, or ends one."""
    from . import checks, server, session

    link = session.link()
    activities = server.current.activities
    action = args.get("action") or ("start" if args.get("design") else None)
    if not args.get("id"):
        return session.answer({"activities": activities.shown()})
    if action == "end" or args.get("remove"):
        return session.answer(await session.on_gateway(activities.end(link, args["id"])))
    if action != "start":
        return session.answer({"error": "action is start (with store and design) or end"})
    if not args.get("store") or not isinstance(args.get("design"), dict):
        return session.answer({"error": "start needs store, the JSON store the activity shows, and design, the regions over it"})
    if refused := checks.refused([{"op": "activity", "design": args["design"]}]):
        return refused
    if problem := activities.problem(args["store"], args["design"]):
        return session.answer({"error": problem})
    remarks = activities.remarks(args["store"], args["design"])
    answer = await session.on_gateway(activities.start(link, args["id"], args["store"], args["design"], args.get("alert")))
    if answer.get("error"):
        return session.answer(answer)
    answer["bound"] = {"activity": args["id"], "store": args["store"],
                       "then": f"Every write to the store's file ({link.stores.path(args['store'])}) updates it; "
                               "\"ended\": true in the store ends it; \"alert\": {title, body} in the store rings once"}
    return checks.with_warnings(session.answer(answer), remarks)
