# SPDX-FileCopyrightText: 2026 Julien Malka
# SPDX-License-Identifier: MIT

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "plugin"))

from dedala import steps  # noqa: E402
from dedala.hermes import vocabulary  # noqa: E402
from dedala.hermes.agent import HermesAgent  # noqa: E402

HERMES = HermesAgent()


def describe(tool, args):
    return steps.describe(tool, args, HERMES)


def running(tool, args):
    return steps.running(tool, args, HERMES)


def test_steps_read_as_what_was_done():
    assert describe("read_file", {"path": "/var/lib/hermes/notes/20260512T120000==phd--tosem-revision-plan__project.org"}) == \
        ("Read 20260512T120000==phd--tosem-revision-plan__project.org", "doc.text")
    assert describe("search_files", {"pattern": "tosem"}) == ("Searched files for tosem", "magnifyingglass")
    assert describe("terminal", {"command": "find /var/lib/hermes -iname '*tosem*'\necho done"})[0] == "Ran find /var/lib/hermes"
    assert describe("app_data", {"id": "documents", "record": "tosem-revision-plan", "say": "Here it is"})[0] == "Handed tosem-revision-plan from documents"
    assert describe("mcp_windmill_run", {})[0] == "Used mcp_windmill_run"


def test_a_command_is_named_by_its_program_and_what_it_is_given():
    named = {
        'notmuch search --format=text --output=messages "date:2026-11-09..2026-11-10 and tag:inbox" | sed \'s/ *$//\' | sort': "Ran notmuch search",
        'echo "unread inbox today:"; notmuch count -- "date:2026-11-09 and tag:unread"': "Ran notmuch count",
        "cd /var/lib/hermes/cache/scratch && python3 wm_refresh_fetch.py 2>&1 | tail -40": "Ran wm_refresh_fetch.py",
        'python3 /var/lib/hermes/skills/calendar/scripts/agenda.py show "356A58A6-0A03" 2>&1 | head -30': "Ran agenda.py show",
        'cd ~/cache/scratch && python3 -c "\nimport json\nprint(json.load(open(\'a.json\')))"': "Ran a Python snippet",
        "python3 - <<'EOF'\nimport json, os\nprint(os.getcwd())\nEOF": "Ran a Python snippet",
        "python3 -m pytest -q tests": "Ran pytest tests",
        "ls -la /var/lib/hermes/cache/scratch/ | grep -i wm_ | head -30": "Ran ls scratch",
        "for t in 95d3 95d5; do notmuch show --format=text thread:$t 2>/dev/null | head; done": "Ran notmuch show",
        "TZ=Europe/Stockholm date -Is": "Ran date",
        "date '+%Y-%m-%d %H:%M %A'": "Ran date",
        "cd /var/lib/hermes/cron && timeout 120 jq -r '.jobs[] | select(.id==\"9f48\") | .prompt' jobs.json": "Ran jq jobs.json",
        "cd sc && \\\ncurl -s -m 30 -H 'Authorization: Bearer abc' \"https://api.github.com/repos/NixOS/nixpkgs\"": "Ran curl api.github.com",
        "cd /var/lib/hermes && echo done": "Ran cd /var/lib/hermes && echo do…",
        "": "Ran a command",
    }
    for command, line in named.items():
        assert describe("terminal", {"command": command})[0] == line


def test_a_tool_at_work_is_said_as_the_step_it_will_leave():
    assert running("terminal", {"command": "cd /tmp && python3 wm_today.py"}) == ("Running wm_today.py", "terminal")
    assert running("read_file", {"path": "/var/lib/hermes/skills/drawing-cards/dedala-ui.md"}) == ("Reading dedala-ui.md", "doc.text")
    assert running("execute_code", {"code": "# count today's runs\nprint(1)"})[0] == "Running code: count today's runs"
    assert running("app_page", {"id": "windmill"}) is None and running("mcp_windmill_run", {}) is None and running("tool_search", {}) is None


def test_a_script_is_named_by_its_opening_comment_else_by_its_length():
    assert describe("execute_code", {"code": "\n# count today's Windmill runs\nprint(len(jobs))\n"})[0] == "Ran code: count today's Windmill runs"
    assert describe("execute_code", {"code": "from collections import Counter\n\nprint(Counter(days))\n"})[0] == "Ran 2 lines of code"
    assert describe("execute_code", {"code": "print(1)"})[0] == "Ran a line of code"
    assert describe("execute_code", {})[0] == "Ran code"


def test_a_call_being_written_is_said_in_words_never_by_the_tools_name():
    _step, preparing = vocabulary.step, lambda tool: steps.preparing(tool, HERMES)
    assert preparing("execute_code") == "Writing code" and preparing("terminal") == "Writing a command"
    assert preparing("app_card") == "Drawing a card" and preparing("browser_navigate") == "Using the browser"
    assert preparing("mcp_windmill_run") == "Preparing a step" and preparing(None) == "Preparing a step"
    assert _step("is using mcp_windmill_run…") == "Running a step" and _step("is reading /var/lib…") == "Reading /var/lib"


def test_bookkeeping_and_cards_are_not_steps():
    for tool in ("tool_search", "tool_call", "app_card", "app_patch"):
        assert describe(tool, {}) is None


def test_skill_edits_name_their_skills():
    assert describe("skill_manage", {"operations": [{"name": "drawing-cards", "action": "patch"}]})[0] == "Updated the drawing-cards skill"
    assert describe("skill_manage", {})[0] == "Updated a skill"


def test_page_steps_say_what_was_done():
    assert describe("app_page", {})[0] == "Listed his pages"
    assert describe("app_page", {"id": "sc-recap"})[0] == "Looked at the page sc-recap"
    assert describe("app_page", {"id": "sc-recap", "components": {"SCReport": {}}})[0] == "Worked on the page sc-recap"


def test_topic_and_data_steps_say_what_was_done():
    assert describe("app_topic", {})[0] == "Looked at his topics"
    assert describe("app_topic", {"id": "backups", "title": "Paris backups failing"})[0] == "Opened the topic Paris backups failing"
    assert describe("app_topic", {"id": "backups", "closed": True, "outcome": "He does not care"})[0] == "Closed the topic backups"
    assert describe("app_topic", {"id": "backups"})[0] == "Looked at the topic backups"
    assert describe("app_data", {"id": "daily", "path": "/var/lib/hermes/notes/2026-11-06.org"})[0] == "Linked 2026-11-06.org as daily"
    assert describe("app_data", {"id": "people", "data": [{"id": "a"}]})[0] == "Wrote the store people"
    assert describe("app_data", {"id": "people", "name": "People"})[0] == "Declared the store people"
    assert describe("app_data", {})[0] == "Looked at the stores" and describe("app_data", {"id": "x"})[0] == "Read the store x"
    assert describe("app_events", {"source": "grain"})[0] == "Read what happened from grain"
    assert describe("app_search", {"query": "lease"})[0] == "Searched the app for lease"


def test_every_app_tool_is_known_wherever_tools_are_listed():
    import dedala

    names = {schema["name"] for _, schema in dedala.schemas.TOOLS}
    manifest = (Path(dedala.__file__).with_name("plugin.yaml")).read_text()
    listed = {line.strip().removeprefix("- ") for line in manifest.split("provides_tools:")[1].splitlines() if line.strip().startswith("- ")}
    assert listed == names
    for name in names:
        assert name in steps.APP_TOOLS, f"{name} has no working line in steps.APP_TOOLS"
        assert name in steps.DRAWN or not describe(name, {})[0].startswith("Used "), f"{name} has no step line"
