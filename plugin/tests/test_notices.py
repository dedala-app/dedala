# SPDX-FileCopyrightText: 2026 Julien Malka
# SPDX-License-Identifier: MIT

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "plugin"))

from dedala.notices import notice  # noqa: E402


def test_a_new_session_reads_as_one_line():
    reply = "✨ Session reset! Starting fresh.\n\n◆ Model: deepseek-v4-flash\n◆ Provider: custom\n◆ Context: 1.0M tokens (detected)"
    assert notice(reply) == {"title": "New session", "symbol": "sparkles", "details": ["deepseek-v4-flash", "1.0M context"]}


def test_warnings_are_marked():
    shown = notice("⚠️ Hermes is shutting down — your current task will be interrupted. When it is back online, "
                   "send any message and I'll try to pick up where we left off.")
    assert shown["warning"]
    assert shown["title"] == "Hermes is shutting down — your current task will be interrupted."
    assert shown["details"] == ["When it is back online, send any message and I'll try to pick up where we left off."]
