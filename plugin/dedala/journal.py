# SPDX-FileCopyrightText: 2026 Julien Malka
# SPDX-License-Identifier: MIT

"""What was said in the app's conversations, kept so a phone paired again gets
it back: every say, patch, receipt and topic as it went to the phone, and what
he wrote, answered and loved there, one line each in conversations.jsonl.
Folded into the messages as they stand, the way the phone folds them, when a
phone asks for them, and on disk when the lines run far past the messages."""

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

KINDS = ("say", "patch", "receipt", "topic")
# The history goes in ops of about this size, several to a sealed message.
HISTORY_BUDGET = 120 * 1024
# The file is folded on disk once it holds this many lines more than messages.
SLACK = 2000


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def iso(value) -> str | None:
    """A date as the phone reads it, from what the plugin kept before the journal."""
    if not isinstance(value, str):
        return None
    for shape in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(value, shape).isoformat(timespec="seconds")
        except ValueError:
            continue
    return value


def merged(base, patch):
    """A card's data patched as the phone patches it: objects merge, null removes."""
    if not isinstance(base, dict) or not isinstance(patch, dict):
        return patch
    result = dict(base)
    for key, value in patch.items():
        if value is None:
            result.pop(key, None)
        elif isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = merged(result[key], value)
        else:
            result[key] = value
    return result


def fold(lines: list[dict]) -> tuple[dict[str, list[dict]], dict[str, dict]]:
    """The messages of each conversation as the phone holds them after these
    lines, and the topics: a message said again replaces itself where it is
    unless he wrote since, then it comes back at the end."""
    conversations: dict[str, list[dict]] = {}
    where: dict[str, str] = {}
    topics: dict[str, dict] = {}

    def find(identifier) -> tuple[list[dict], int] | None:
        conversation = where.get(identifier)
        if conversation is None:
            return None
        messages = conversations[conversation]
        return messages, next(index for index, message in enumerate(messages) if message["id"] == identifier)

    def answered(messages: list[dict], index: int) -> bool:
        return any(message.get("from") == "you" for message in messages[index + 1:])

    for line in lines:
        kind, at = line.get("op"), line.get("at")
        if kind == "topic" and line.get("id"):
            topic = topics.setdefault(line["id"], {"id": line["id"], "title": line["id"], "started": at})
            topic.update({key: line[key] for key in ("title", "symbol", "color", "outcome") if line.get(key)})
            if "closed" in line:
                topic["closed"] = (line["closed"] if isinstance(line["closed"], str) else at) if line["closed"] else None
        elif kind == "say" and line.get("id"):
            conversation = line.get("conversation") or "main"
            message = {key: value for key, value in line.items() if key not in ("op", "conversation", "settled")}
            found = find(message["id"])
            if found and where[message["id"]] == conversation and not answered(*found):
                messages, index = found
                if "steps" not in message and "steps" in messages[index]:
                    message["steps"] = messages[index]["steps"]
                messages[index] = message
                continue
            if found:
                del found[0][found[1]]
            conversations.setdefault(conversation, []).append(message)
            where[message["id"]] = conversation
        elif kind == "patch" and (found := find(line.get("id"))):
            messages, index = found
            message = messages[index]
            retold = "say" in line and answered(messages, index)
            if "say" in line:
                message["text"] = line["say"] if isinstance(line["say"], str) else json.dumps(line["say"], ensure_ascii=False)
            if isinstance(card := message.get("card"), dict) and "view" in card:
                card = dict(card)
                if "data" in line:
                    card["data"] = merged(card.get("data") if card.get("data") is not None else {}, line["data"])
                card.update({key: line[key] for key in ("view", "script", "derive") if key in line})
                if isinstance(line.get("state"), dict):
                    card["state"] = {**(card.get("state") or {}), **line["state"]}
                message["card"] = card
            if retold:
                message["at"] = at
                messages.append(messages.pop(index))
        elif kind in ("receipt", "answered", "loved") and (found := find(line.get("message"))):
            message = found[0][found[1]]
            if kind == "receipt":
                message["receipt"] = line.get("text") or "Done"
            elif kind == "answered":
                message["answered"] = at
            else:
                message["loved"] = True
    return conversations, topics


class Journal:
    def __init__(self, path: Path):
        self.path = path
        self._compact()

    def _read(self) -> list[dict]:
        try:
            text = self.path.read_text()
        except FileNotFoundError:
            return []
        lines = []
        for number, raw in enumerate(text.splitlines(), 1):
            try:
                lines.append(json.loads(raw))
            except ValueError:
                logger.warning("[app] line %d of %s cannot be read; left out of the history", number, self.path.name)
        return lines

    @property
    def empty(self) -> bool:
        return not self.path.exists() or self.path.stat().st_size == 0

    def add(self, line: dict) -> None:
        try:
            with open(self.path, "a", opener=lambda name, flags: os.open(name, flags, 0o600)) as out:
                out.write(json.dumps({**line, "at": line.get("at") or now()}, ensure_ascii=False) + "\n")
        except OSError as error:
            logger.warning("[app] could not keep a line of the conversation: %s", error)

    def sent(self, op: dict) -> dict:
        """A conversation op on its way to the phone, kept; a message without
        an id gets one here, so the phone and the history name it alike, and the
        time it was said, which the phone weighs against the turn it shows."""
        if op.get("op") not in KINDS:
            return op
        if op["op"] == "say":
            op = {**op, "id": op.get("id") or f"m-{uuid.uuid4().hex[:16]}",
                  "at": op.get("at") or datetime.now(timezone.utc).isoformat(timespec="milliseconds")}
        self.add(op)
        return op

    def yours(self, conversation: str, text: str, identifier: str | None, at: str | None) -> None:
        self.add({"op": "say", "conversation": conversation, "id": identifier or f"y-{uuid.uuid4().hex[:16]}",
                  "from": "you", "text": text, "at": at})

    def history(self, kept_topics: dict) -> list[dict]:
        """The conversations as history ops for a newly paired phone: the
        topics first, then the messages in order, a few hundred kilobytes an op."""
        conversations, topics = fold(self._read())
        for identifier, kept in kept_topics.items():
            if identifier not in topics:
                topics[identifier] = {"id": identifier, "title": kept.get("title") or identifier, "started": iso(kept.get("opened")),
                                      **({"closed": iso(kept["closed"])} if kept.get("closed") else {}),
                                      **({"outcome": kept["outcome"]} if kept.get("outcome") else {})}
        ops: list[dict] = []
        current: dict = {"op": "history", "topics": list(topics.values()), "messages": []}
        size = len(json.dumps(current, ensure_ascii=False).encode())
        for conversation, messages in conversations.items():
            for message in messages:
                entry = {"conversation": conversation, **message}
                length = len(json.dumps(entry, ensure_ascii=False).encode())
                if length > HISTORY_BUDGET:
                    logger.warning("[app] message %s is too large to send again (%d bytes); left out of the history", message["id"], length)
                    continue
                if current["messages"] and size + length > HISTORY_BUDGET:
                    ops.append(current)
                    current, size = {"op": "history", "messages": []}, 0
                current["messages"].append(entry)
                size += length
        if current["messages"] or current.get("topics"):
            ops.append(current)
        return ops

    def _compact(self) -> None:
        """The lines folded on disk once most of them are changes to messages already kept."""
        lines = self._read()
        conversations, topics = fold(lines)
        if len(lines) - sum(map(len, conversations.values())) - len(topics) < SLACK:
            return
        folded = [{"op": "topic", **{key: value for key, value in topic.items() if key != "started"}, "at": topic.get("started")}
                  for topic in topics.values()]
        folded += [{"op": "say", "conversation": conversation, **message} for conversation, messages in conversations.items()
                   for message in messages]
        temporary = self.path.with_name(f"{self.path.name}.tmp")
        temporary.write_text("".join(json.dumps(line, ensure_ascii=False) + "\n" for line in folded))
        temporary.chmod(0o600)
        temporary.replace(self.path)
        logger.info("[app] folded the conversation history: %d lines into %d", len(lines), len(folded))
