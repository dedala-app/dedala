# SPDX-FileCopyrightText: 2026 Julien Malka
# SPDX-License-Identifier: AGPL-3.0-or-later

"""What the relay remembers: invites, agents, pairings, the device of each agent,
the two queues between them, and broadcast channels. Tokens are kept hashed;
messages are kept as the sealed boxes they arrived as."""

import hashlib
import json
import secrets
import sqlite3
import time
from dataclasses import dataclass

SCHEMA = """
create table if not exists invites (hash text primary key, created real not null, used_by text);
create table if not exists agents (id text primary key, token text not null unique, name text not null, created real not null);
create table if not exists pairings (
    id text primary key, agent text not null, claim text not null, expires real not null,
    device text, device_key text, mac text, device_name text
);
create table if not exists devices (
    id text primary key, agent text not null unique, token text not null unique, key text not null,
    name text not null, environment text not null, apns text, start text, created real not null
);
create table if not exists messages (
    rowid integer primary key autoincrement, agent text not null, direction text not null,
    seq integer not null, body text not null, size integer not null, created real not null,
    unique (agent, direction, seq)
);
create table if not exists blobs (id text primary key, agent text not null, owner text not null, body blob not null, size integer not null, created real not null);
create table if not exists channels (id text primary key, agent text not null, environment text not null, created real not null);
"""

TO_APP = "to_app"
TO_AGENT = "to_agent"
RETENTION = 7 * 24 * 3600
QUEUE_LIMIT = 50 * 1024 * 1024
BLOB_LIMIT = 2 * 1024 * 1024
BLOBS_LIMIT = 50 * 1024 * 1024
PAIRING_LIFETIME = 10 * 60


def digest(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def token() -> str:
    return secrets.token_urlsafe(32)


class Refused(Exception):
    """A request the relay will not carry out, with the reason to give back."""

    def __init__(self, status: int, reason: str):
        super().__init__(reason)
        self.status = status
        self.reason = reason


@dataclass
class Device:
    id: str
    agent: str
    key: str
    name: str
    environment: str
    apns: str | None
    start: str | None


class Store:
    def __init__(self, path: str):
        self.db = sqlite3.connect(path, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("pragma journal_mode = wal")
        self.db.executescript(SCHEMA)

    # Invites and agents

    def invite(self) -> str:
        secret = token()
        self.db.execute("insert into invites values (?, ?, null)", (digest(secret), time.time()))
        return secret

    def register(self, invite: str, name: str) -> tuple[str, str]:
        row = self.db.execute("select used_by from invites where hash = ?", (digest(invite),)).fetchone()
        if row is None or row["used_by"] is not None:
            raise Refused(403, "This invite is unknown or already used")
        agent, secret = "a_" + secrets.token_hex(8), token()
        self.db.execute("insert into agents values (?, ?, ?, ?)", (agent, digest(secret), name, time.time()))
        self.db.execute("update invites set used_by = ? where hash = ?", (agent, digest(invite)))
        return agent, secret

    def agent(self, secret: str) -> str | None:
        row = self.db.execute("select id from agents where token = ?", (digest(secret),)).fetchone()
        return row["id"] if row else None

    def agent_name(self, agent: str) -> str:
        row = self.db.execute("select name from agents where id = ?", (agent,)).fetchone()
        return row["name"] if row else "Hermes"

    def agents(self) -> list[dict]:
        rows = self.db.execute(
            "select a.id, a.name, a.created, d.name as device, d.environment from agents a left join devices d on d.agent = a.id"
        ).fetchall()
        return [dict(row) for row in rows]

    def remove_agent(self, agent: str) -> None:
        for table in ("devices", "pairings", "messages", "channels", "blobs"):
            self.db.execute(f"delete from {table} where agent = ?", (agent,))
        self.db.execute("delete from agents where id = ?", (agent,))

    # Pairing

    def open_pairing(self, agent: str, claim_hash: str) -> tuple[str, float]:
        pairing, expires = "p_" + secrets.token_hex(8), time.time() + PAIRING_LIFETIME
        self.db.execute("insert into pairings (id, agent, claim, expires) values (?, ?, ?, ?)", (pairing, agent, claim_hash, expires))
        return pairing, expires

    def claim(self, pairing: str, claim: str, key: str, mac: str, name: str, environment: str, apns: str | None, start: str | None) -> tuple[str, str, str]:
        row = self.db.execute("select * from pairings where id = ?", (pairing,)).fetchone()
        if row is None or row["expires"] < time.time() or row["device"] is not None:
            raise Refused(410, "This pairing code has expired or was already used")
        if not secrets.compare_digest(row["claim"], digest(claim)):
            raise Refused(403, "This pairing code does not match")
        agent = row["agent"]
        self.forget_device(agent)
        device, secret = "d_" + secrets.token_hex(8), token()
        self.db.execute(
            "insert into devices values (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (device, agent, digest(secret), key, name, environment, apns, start, time.time()),
        )
        self.db.execute(
            "update pairings set device = ?, device_key = ?, mac = ?, device_name = ? where id = ?",
            (device, key, mac, name, pairing),
        )
        return agent, device, secret

    def pairing(self, agent: str, pairing: str) -> dict | None:
        row = self.db.execute("select * from pairings where id = ? and agent = ?", (pairing, agent)).fetchone()
        if row is None:
            return None
        if row["device"] is None:
            return {"status": "waiting" if row["expires"] > time.time() else "expired"}
        return {"status": "paired", "device": {"key": row["device_key"], "mac": row["mac"], "name": row["device_name"]}}

    # Devices

    def device(self, secret: str) -> Device | None:
        row = self.db.execute("select * from devices where token = ?", (digest(secret),)).fetchone()
        return self._device(row)

    def device_of(self, agent: str) -> Device | None:
        return self._device(self.db.execute("select * from devices where agent = ?", (agent,)).fetchone())

    def update_apns(self, device: str, environment: str, apns: str | None, start: str | None) -> None:
        self.db.execute("update devices set environment = ?, apns = ?, start = ? where id = ?", (environment, apns, start, device))

    def drop_apns(self, device: str, which: str) -> None:
        column = "start" if which == "start" else "apns"
        self.db.execute(f"update devices set {column} = null where id = ?", (device,))

    def forget_device(self, agent: str) -> None:
        self.db.execute("delete from devices where agent = ?", (agent,))
        self.db.execute("delete from messages where agent = ?", (agent,))
        self.db.execute("delete from blobs where agent = ?", (agent,))

    @staticmethod
    def _device(row) -> Device | None:
        if row is None:
            return None
        return Device(row["id"], row["agent"], row["key"], row["name"], row["environment"], row["apns"], row["start"])

    # Queues

    def put(self, agent: str, direction: str, message: dict) -> int:
        seq = message.get("seq")
        if not isinstance(seq, int) or not isinstance(message.get("box"), str) or not isinstance(message.get("nonce"), str):
            raise Refused(400, "A message is {seq, nonce, box}")
        body = json.dumps({"seq": seq, "nonce": message["nonce"], "box": message["box"]})
        held = self.db.execute("select coalesce(sum(size), 0) from messages where agent = ? and direction = ?", (agent, direction)).fetchone()[0]
        if held + len(body) > QUEUE_LIMIT:
            raise Refused(507, "The queue is full until the other side catches up")
        self.db.execute(
            "insert or ignore into messages (agent, direction, seq, body, size, created) values (?, ?, ?, ?, ?, ?)",
            (agent, direction, seq, body, len(body), time.time()),
        )
        return seq

    def waiting(self, agent: str, direction: str, after: int = -1) -> list[dict]:
        rows = self.db.execute(
            "select body from messages where agent = ? and direction = ? and seq > ? order by seq", (agent, direction, after)
        ).fetchall()
        return [json.loads(row["body"]) for row in rows]

    def ack(self, agent: str, direction: str, seq: int) -> None:
        self.db.execute("delete from messages where agent = ? and direction = ? and seq <= ?", (agent, direction, seq))

    def sweep(self) -> int:
        now = time.time()
        gone = self.db.execute("delete from messages where created < ?", (now - RETENTION,)).rowcount
        gone += self.db.execute("delete from blobs where created < ?", (now - RETENTION,)).rowcount
        self.db.execute("delete from pairings where device is null and expires < ?", (now - PAIRING_LIFETIME,))
        return gone

    # Blobs: sealed captures and files too big for a message

    def put_blob(self, agent: str, owner: str, body: bytes) -> str:
        if len(body) > BLOB_LIMIT:
            raise Refused(413, "A blob is at most 2MB")
        held = self.db.execute("select coalesce(sum(size), 0) from blobs where agent = ?", (agent,)).fetchone()[0]
        if held + len(body) > BLOBS_LIMIT:
            raise Refused(507, "Too many blobs waiting; fetch and delete some")
        blob = "b_" + secrets.token_hex(12)
        self.db.execute("insert into blobs values (?, ?, ?, ?, ?, ?)", (blob, agent, owner, body, len(body), time.time()))
        return blob

    def blob(self, agent: str, blob: str) -> bytes | None:
        row = self.db.execute("select body from blobs where id = ? and agent = ?", (blob, agent)).fetchone()
        return bytes(row["body"]) if row else None

    def remove_blob(self, agent: str, blob: str) -> None:
        self.db.execute("delete from blobs where id = ? and agent = ?", (blob, agent))

    def clear_blobs(self, agent: str, owner: str, older: float = 0) -> int:
        """The blobs one side stored longer than `older` seconds ago and nothing
        fetched: how many went."""
        return self.db.execute("delete from blobs where agent = ? and owner = ? and created < ?", (agent, owner, time.time() - older)).rowcount

    # Channels

    def add_channel(self, agent: str, channel: str, environment: str) -> None:
        self.db.execute("insert or replace into channels values (?, ?, ?, ?)", (channel, agent, environment, time.time()))

    def channels(self, agent: str) -> list[str]:
        return [row["id"] for row in self.db.execute("select id from channels where agent = ?", (agent,))]

    def channel_environment(self, agent: str, channel: str) -> str | None:
        row = self.db.execute("select environment from channels where id = ? and agent = ?", (channel, agent)).fetchone()
        return row["environment"] if row else None

    def remove_channel(self, agent: str, channel: str) -> None:
        self.db.execute("delete from channels where id = ? and agent = ?", (channel, agent))
