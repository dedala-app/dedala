# SPDX-FileCopyrightText: 2026 Julien Malka
# SPDX-License-Identifier: MIT

import ast
from pathlib import Path

from pyflakes import checker, messages

PLUGIN = Path(__file__).resolve().parents[1] / "dedala"
HERMES = {"gateway", "cron", "tools", "agent", "hermes_cli"}


def test_the_plugin_uses_no_name_it_does_not_define():
    undefined = [f"{path.name}:{message.lineno} {message.message_args[0]}"
                 for path in sorted(PLUGIN.rglob("*.py"))
                 for message in checker.Checker(ast.parse(path.read_text()), filename=str(path)).messages
                 if isinstance(message, messages.UndefinedName)]
    assert undefined == []


def test_only_the_hermes_side_knows_hermes():
    """The server and the tools reach the agent through `agents.Agent`: what Hermes loads
    (`__init__`, `pair`) is all that names the Hermes side, and nothing outside it imports Hermes."""
    reaching = []
    for path in sorted(PLUGIN.glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                named = [(0, alias.name) for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                named = [(node.level, node.module or alias.name) for alias in node.names]
            else:
                continue
            for level, module in named:
                root = module.split(".")[0]
                if (level == 0 and root in HERMES) or (level == 1 and root == "hermes" and path.name not in ("__init__.py", "pair.py")):
                    reaching.append(f"{path.name}:{node.lineno} {module}")
    assert reaching == []


def test_the_plugin_folder_stands_alone():
    """Hermes installs the plugin folder by itself: no link may point out of it."""
    assert [path.name for path in PLUGIN.rglob("*") if path.is_symlink()] == []


def test_the_plugin_seals_as_the_relay_s_tests_do():
    """The relay's tests play the agent and the phone with their own copy of the sealing."""
    relay = PLUGIN.parents[1] / "relay" / "hermes_relay" / "seal.py"
    assert (PLUGIN / "seal.py").read_text() == relay.read_text()


def test_no_text_reads_as_hermes_inline_shell():
    """Hermes's install scan holds back a plugin whose text has an exclamation mark right before a
    backtick-quoted run (its inline-shell syntax), even in a sentence about operators."""
    import re

    inline = re.compile(r"!`[^`\s][^`\n]*`")
    assert [f"{path.relative_to(PLUGIN)}:{number}" for path in sorted(PLUGIN.rglob("*.md"))
            for number, line in enumerate(path.read_text().splitlines(), 1) if inline.search(line)] == []


def test_every_file_of_the_repository_states_its_licence():
    """REUSE: a header or an entry in REUSE.toml for every file, and every licence's text in LICENSES/."""
    import shutil
    import subprocess

    import pytest

    if shutil.which("reuse") is None:
        pytest.skip("reuse is not installed")
    done = subprocess.run(["reuse", "--root", str(PLUGIN.parents[1]), "lint", "--quiet"], capture_output=True, text=True)
    assert done.returncode == 0, done.stdout[-2000:]
