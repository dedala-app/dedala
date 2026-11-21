# SPDX-FileCopyrightText: 2026 Julien Malka
# SPDX-License-Identifier: MIT

"""The plugin's state files: each a JSON object, replaced whole, read strictly."""

import json
import os
import re
import threading
from pathlib import Path

_writing = threading.Lock()


def write(path: Path, value: dict) -> None:
    """Replaces a state file whole: the old one or the new one, never half of either."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    with _writing:
        with open(temporary, "w", opener=lambda name, flags: os.open(name, flags, 0o600)) as file:
            file.write(json.dumps(value, indent=1, ensure_ascii=False))
            file.flush()
            os.fsync(file.fileno())
        temporary.replace(path)


def read(path: Path) -> dict:
    """A state file, empty when it was never written. One that cannot be read
    stops the plugin: starting over it would lose the pairing and the numbering
    the phone follows."""
    try:
        text = path.read_text()
    except FileNotFoundError:
        return {}
    try:
        value = json.loads(text)
    except ValueError as error:
        raise RuntimeError(f"{path} is not JSON ({error}): restore it or move it away before starting") from error
    if not isinstance(value, dict):
        raise RuntimeError(f"{path} does not hold an object: restore it or move it away before starting")
    return value


def safe(name: str) -> str:
    """A name from the agent or the phone as one path component, never a way out of its folder."""
    cleaned = re.sub(r"[^\w.-]+", "-", str(name)).strip("-")
    return cleaned if cleaned.strip(".") else "item"
