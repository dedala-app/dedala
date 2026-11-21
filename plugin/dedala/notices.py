# SPDX-FileCopyrightText: 2026 Julien Malka
# SPDX-License-Identifier: MIT

"""Hermes speaking for itself, told apart from the agent."""

import re


def notice(content: str) -> dict:
    """Hermes speaking for itself (a command's reply, a warning) as a notice the
    app draws as an event, not as the agent talking: "✨ Session reset!" with its
    "◆ Model: …" lines reads "New session · deepseek-v4-flash · 1.0M context"."""
    lines = [line.strip() for line in content.strip().splitlines() if line.strip()]
    if not lines:
        return {"title": "Done", "symbol": "info.circle"}
    warning = lines[0].startswith("⚠")
    title = re.sub(r"^[^\w«\"'(/]+", "", lines[0]).strip()
    facts = {}
    details = []
    for line in lines[1:]:
        line = re.sub(r"^[◆•·*\-]+\s*", "", line)
        key, _, value = line.partition(":")
        if value and len(key) < 24:
            facts[key.strip().lower()] = value.strip()
        details.append(line)
    first, dot, rest = title.partition(". ")
    if dot and len(title) > 70:
        title, details = first + ".", [rest.strip()] + details
    if title.lower().startswith("session reset") or title.lower().startswith("new session"):
        title = "New session"
        details = [facts["model"]] if "model" in facts else []
        if "context" in facts:
            details.append(facts["context"].replace(" tokens", "").replace(" (detected)", "") + " context")
    return {"title": title, "symbol": "exclamationmark.triangle" if warning else "sparkles" if title == "New session" else "info.circle",
            "details": details[:4], **({"warning": True} if warning else {})}
