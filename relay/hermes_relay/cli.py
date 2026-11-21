# SPDX-FileCopyrightText: 2026 Julien Malka
# SPDX-License-Identifier: AGPL-3.0-or-later

"""`hermes-relay serve` runs the relay; the other commands manage it on its host."""

import argparse
import json
import logging
import os

from aiohttp import web

from .apns import APNs
from .server import create_app
from .store import Store


def main() -> None:
    parser = argparse.ArgumentParser(prog="hermes-relay")
    parser.add_argument("--db", default=os.environ.get("HERMES_RELAY_DB", "relay.sqlite"))
    commands = parser.add_subparsers(dest="command", required=True)

    serve = commands.add_parser("serve", help="run the relay")
    serve.add_argument("--host", default=os.environ.get("HERMES_RELAY_HOST", "127.0.0.1"))
    serve.add_argument("--port", type=int, default=int(os.environ.get("HERMES_RELAY_PORT", "8790")))
    serve.add_argument("--apns-key", default=os.environ.get("HERMES_RELAY_APNS_KEY"))
    serve.add_argument("--apns-key-id", default=os.environ.get("HERMES_RELAY_APNS_KEY_ID"))
    serve.add_argument("--team", default=os.environ.get("HERMES_RELAY_TEAM", "KHZGP69E97"))
    serve.add_argument("--bundle", default=os.environ.get("HERMES_RELAY_BUNDLE", "app.dedala"))

    commands.add_parser("invite", help="print a one-use invite for a new agent")
    commands.add_parser("agents", help="list agents and their devices")
    revoke = commands.add_parser("revoke", help="remove an agent, its device and its messages")
    revoke.add_argument("agent")

    args = parser.parse_args()
    store = Store(args.db)
    if args.command == "serve":
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
        apns = APNs(args.apns_key, args.apns_key_id, args.team, args.bundle) if args.apns_key and args.apns_key_id else None
        if apns is None:
            logging.warning("No APNs key: pushes are refused")
        web.run_app(create_app(store, apns), host=args.host, port=args.port, print=None, shutdown_timeout=5)
    elif args.command == "invite":
        print(store.invite())
    elif args.command == "agents":
        for agent in store.agents():
            print(json.dumps(agent))
    elif args.command == "revoke":
        store.remove_agent(args.agent)
        print(f"removed {args.agent}")


if __name__ == "__main__":
    main()
