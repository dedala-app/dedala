# SPDX-FileCopyrightText: 2026 Julien Malka
# SPDX-License-Identifier: MIT

"""Commands: a tap on his phone that runs something here with no model on the
way. The agent binds a name to a program (a script beside the monitor
scripts, a Windmill flow) or to a Hermes job, with a contract, what a run
must achieve. Every run is traced: its arguments, outcome, duration, what it
wrote, the end of its stderr. A supervisor job, made with the command, reads
the trace when a run fails, on a sample of the runs, and when one is unlike
the others: it judges them against the contract and improves the program,
so a command gets better without him asking."""

import json
import logging
import os
import statistics
import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from .agents import Agent, Unavailable
from .files import write
from .stores import fingerprint

logger = logging.getLogger(__name__)

BINDINGS = ("script", "flow", "job")
DEFAULT_TIMEOUT = 120
MAX_TIMEOUT = 3600
# A supervisor is fired on signals, never by the clock: the date is one that never comes.
SUPERVISOR_SCHEDULE = "0 4 31 2 *"
# How many runs a sample waits for, by how many audits found nothing to fix: every
# run for a new command, then doubling to a ceiling.
SAMPLE_CEILING = 20
# A run slower or faster than the others by this factor is drift.
DRIFT = 3
# Once a day, when there were runs, the supervisor looks even without a signal.
FLOOR = 24 * 3600
TRACE_KEPT = 2000
RESULT_KEPT = 4000
STDERR_KEPT = 1500

SUPERVISOR_PROMPT = """You supervise the command `{id}` of the app. A tap on his phone runs it here with no model on the way; you are the judgment it stands in for, after the fact.

Its contract: {description}
It is bound to {binding}.

Above this prompt are the runs since you last looked, each with its arguments, its outcome, how long it took, which stores it wrote (files under {stores}) and the end of its stderr, and why you were woken: a failure, a sample of the runs, or a run unlike the others.

Judge the runs against the contract: open what they wrote, and when it is cheap, do one run's work yourself and compare. Then do one of these:
- nothing, when the runs did what the contract says;
- fix the program: the script under {scripts} or the flow in Windmill is yours to change. Make the change, replay it with the arguments of a run that went wrong (a script reads its arguments as JSON on stdin), and if the binding changes, app_command {{"id": "{id}", …}};
- when it is bound to a job and the runs are mechanical, the same steps each time, write the program and bind it with app_command {{"id": "{id}", "script" | "flow": …}}: the next taps run it, and you keep supervising;
- ask him, in one line, only when you cannot tell what a good run is.

Otherwise say nothing, and never tell him what you fixed. Look at the whole trace with app_command {{"id": "{id}"}}."""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Commands:
    def __init__(self, home: Path, artifacts: dict, write: Callable[[str, Optional[dict]], None], stores, windmill: Optional[dict] = None,
                 agent: Optional[Agent] = None):
        self.home = home
        self.agent = agent or Agent()
        self.artifacts = artifacts
        self.write = write
        self.stores = stores
        self.windmill = windmill or {}
        self.scripts = home.parent / "scripts"
        self.trace_path = home / "commands.jsonl"
        self._running: set[str] = set()

    # Bindings

    @property
    def records(self) -> dict:
        return self.artifacts.setdefault("command", {})

    def get(self, name: str) -> Optional[dict]:
        return self.records.get(name)

    def binding(self, record: dict) -> str:
        for key in BINDINGS:
            if record.get(key):
                return f"{key} {record[key]}"
        return "nothing"

    def define(self, name: str, fields: dict) -> dict:
        """Creates or changes a command: a new binding replaces the old one,
        the other fields stay as they were."""
        record = {**self.records.get(name, {"id": name, "runs": 0, "audits": 0, "audited": 0, "failed": 0})}
        if any(fields.get(key) for key in BINDINGS):
            for key in BINDINGS:
                record.pop(key, None)
            key = next(key for key in BINDINGS if fields.get(key))
            record[key] = fields[key]
            record["audits"] = 0
        for key in ("description", "timeout", "sample", "supervised_by"):
            if fields.get(key) is not None:
                record[key] = fields[key]
        if record.get("timeout"):
            record["timeout"] = max(1, min(int(record["timeout"]), MAX_TIMEOUT))
        self.records[name] = record
        self.save(name)
        return record

    def save(self, name: str) -> None:
        if name in self.records:
            self.write(name, self.records[name])

    def remove(self, name: str) -> Optional[dict]:
        record = self.records.pop(name, None)
        if record is not None:
            self.write(name, None)
        return record

    def problem(self, fields: dict) -> Optional[str]:
        """Why a binding cannot be taken, before it is kept."""
        bound = [key for key in BINDINGS if fields.get(key)]
        if len(bound) > 1:
            return f"A command is bound to one thing: {', '.join(bound)} were given"
        if fields.get("script"):
            path = self.script_path(str(fields["script"]))
            if path is None:
                return f"script is a file under {self.scripts}, named relative to it"
            if not path.is_file():
                return f"There is no script {path}: write it first, executable, reading its arguments as JSON on stdin"
            if not os.access(path, os.X_OK):
                return f"{path} is not executable: chmod +x it"
        if fields.get("flow") and not (self.windmill.get("url") and self.windmill.get("workspace") and os.environ.get("WINDMILL_TOKEN")):
            return "No Windmill here: the app platform has no windmill_url and windmill_workspace, or WINDMILL_TOKEN is not set"
        return None

    def script_path(self, name: str) -> Optional[Path]:
        if not name or name.startswith("/") or ".." in Path(name).parts:
            return None
        return self.scripts / name

    # Running

    def running(self, name: str) -> bool:
        return name in self._running

    def run(self, record: dict, args, source: str, identifier: Optional[str], run_job: Callable[[str, str], Optional[str]]) -> dict:
        """Runs the command, in the thread that calls, and traces the run:
        what it was given, what came of it, and what it wrote."""
        name = record["id"]
        self._running.add(name)
        self.stores.folder.mkdir(parents=True, exist_ok=True)
        before = self._snapshot()
        started = time.monotonic()
        entry = {"command": name, "args": args, "from": source, "at": now(), "id": identifier}
        try:
            entry.update(self._execute(record, args, run_job))
        except Exception as error:
            logger.warning("[app] the command %s broke: %r", name, error)
            entry.update(status="failed", error=f"{type(error).__name__}: {error}")
        finally:
            self._running.discard(name)
        entry["duration"] = round(time.monotonic() - started, 2)
        self.stores.scan()
        entry["wrote"] = sorted(name for name, print_ in self._snapshot().items() if before.get(name) != print_)
        self._trace(entry)
        record.setdefault("unaudited_since", entry["at"])
        record["runs"] = record.get("runs", 0) + 1
        record["last"] = {key: entry[key] for key in ("at", "status", "duration") if key in entry}
        if entry["status"] == "failed":
            record["failed"] = record.get("failed", 0) + 1
            record["audits"] = 0
        self.save(name)
        return entry

    def _snapshot(self) -> dict[str, str]:
        return {name: fingerprint(data) for name, data in self.stores.held.items()}

    def _execute(self, record: dict, args, run_job) -> dict:
        timeout = record.get("timeout") or DEFAULT_TIMEOUT
        if record.get("script"):
            return self._script(record["script"], args, timeout)
        if record.get("flow"):
            return self._flow(record["flow"], args, timeout)
        if record.get("job"):
            return self._job(record, args, run_job)
        return {"status": "failed", "error": "The command is bound to nothing"}

    def _script(self, name: str, args, timeout: int) -> dict:
        path = self.script_path(name)
        if path is None or not path.is_file():
            return {"status": "failed", "error": f"No script {name} under {self.scripts}"}
        env = {**os.environ, "APP_COMMAND": name, "APP_STORES": str(self.stores.folder)}
        try:
            done = subprocess.run([str(path)], input=json.dumps(args, ensure_ascii=False), capture_output=True, text=True,
                                  timeout=timeout, cwd=self.scripts, env=env)
        except subprocess.TimeoutExpired:
            return {"status": "failed", "error": f"Ran out of time after {timeout}s", "exit": None}
        except OSError as error:
            return {"status": "failed", "error": f"Could not start it: {error}", "exit": None}
        stderr = done.stderr.strip()[-STDERR_KEPT:]
        if done.returncode != 0:
            return {"status": "failed", "exit": done.returncode, "stderr": stderr,
                    "error": stderr.splitlines()[-1] if stderr else f"Exited with {done.returncode}"}
        return {"status": "done", "exit": 0, "result": _result(done.stdout), **({"stderr": stderr} if stderr else {})}

    def _flow(self, path: str, args, timeout: int) -> dict:
        url = f"{self.windmill['url'].rstrip('/')}/api/w/{self.windmill['workspace']}/jobs/run_wait_result/f/{path.removeprefix('f/')}"
        request = urllib.request.Request(url, data=json.dumps(args if isinstance(args, dict) else {"args": args}).encode(),
                                         headers={"Authorization": f"Bearer {os.environ.get('WINDMILL_TOKEN', '')}",
                                                  "Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = response.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", "replace")[:STDERR_KEPT]
            return {"status": "failed", "error": f"Windmill answered {error.code}: {detail or error.reason}"}
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            return {"status": "failed", "error": f"Windmill could not be reached: {getattr(error, 'reason', error)}"}
        return {"status": "done", "result": _result(body)}

    def _job(self, record: dict, args, run_job) -> dict:
        job = record["job"]
        since = time.time()
        prompt = (f"[app: he ran the command {record['id']} with {json.dumps(args, ensure_ascii=False)}. "
                  f"Do what its contract says: {record.get('description') or 'see the job'}]")
        error = run_job(job, prompt)
        if error:
            return {"status": "failed", "error": error if error != "busy" else "The job is already running"}
        result = self.agent.job_result(job, since)
        return {"status": "done", "result": result[:RESULT_KEPT] if result else result}

    # The trace

    def _trace(self, entry: dict) -> None:
        try:
            lines = self.trace_path.read_text().splitlines() if self.trace_path.exists() else []
        except OSError:
            lines = []
        lines.append(json.dumps(entry, ensure_ascii=False))
        try:
            write(self.trace_path, "\n".join(lines[-TRACE_KEPT:]) + "\n")
        except OSError as error:
            logger.warning("[app] could not trace the run of %s: %s", entry.get("command"), error)

    def runs(self, name: Optional[str] = None, limit: int = 50, after: Optional[str] = None) -> list[dict]:
        """The runs traced, oldest first: of one command, after a time."""
        found = []
        try:
            lines = self.trace_path.read_text().splitlines()
        except OSError:
            return []
        for line in lines:
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if (name is None or entry.get("command") == name) and (after is None or (entry.get("at") or "") > after):
                found.append(entry)
        return found[-limit:]

    def status(self, name: str) -> Optional[dict]:
        """A command as its live value shows it: the last run."""
        last = self.runs(name, limit=1)
        if not last:
            return None
        return self.live_entry(last[-1])

    @staticmethod
    def live_entry(entry: dict) -> dict:
        return {"status": entry.get("status"), "result": entry.get("result"), "error": entry.get("error"),
                "at": entry.get("at"), "duration": entry.get("duration"), "args": entry.get("args")}

    def live(self) -> dict:
        """`$commands` as the phone holds it: each command's last run."""
        return {name: status for name in self.records if (status := self.status(name)) is not None}

    @staticmethod
    def op(entry: dict) -> dict:
        return {"op": "command", "name": entry["command"], **Commands.live_entry(entry)}

    def told(self, after: Optional[str]) -> list[str]:
        """The runs since a time, one line each, for the agent's context."""
        lines = []
        for entry in self.runs(after=after, limit=10):
            what = f"{entry['command']}({json.dumps(entry.get('args'), ensure_ascii=False)})"
            outcome = entry.get("status") or "?"
            if entry.get("error"):
                outcome += f": {entry['error']}"
            wrote = f", wrote {', '.join(entry['wrote'])}" if entry.get("wrote") else ""
            lines.append(f"{what} {outcome} in {entry.get('duration')}s{wrote}")
        return lines

    # Signals

    def signal(self, record: dict, entry: dict) -> Optional[str]:
        """Why the supervisor should look now, after this run; None when it should not."""
        if entry.get("status") == "failed":
            return "a run failed"
        earlier = [run for run in self.runs(record["id"], limit=11)[:-1] if run.get("status") == "done"]
        if drift := _drift(entry, earlier):
            return drift
        due = record.get("sample") or min(SAMPLE_CEILING, 2 ** record.get("audits", 0))
        if record.get("runs", 0) - record.get("audited", 0) >= due:
            return f"a sample: {due} runs since you last looked"
        return None

    def overdue(self, record: dict) -> bool:
        """A day of runs it has not looked at."""
        since = record.get("unaudited_since")
        return bool(since) and time.time() - _epoch(since) > FLOOR

    def audit_prompt(self, record: dict, why: str) -> str:
        """What the supervisor is given for this run, above its own prompt."""
        pending = record.get("runs", 0) - record.get("audited", 0)
        since = self.runs(record["id"], limit=200)[-pending:] if pending > 0 else []
        shown = [{key: value for key, value in entry.items() if key not in ("id", "from")} for entry in since]
        return f"[app: why you were woken: {why}.\n\nThe runs of {record['id']} since you last looked:\n{json.dumps(shown, ensure_ascii=False, indent=1)}]"

    def audited(self, record: dict, handled: bool) -> None:
        if handled:
            record["audited"] = record.get("runs", 0)
            record["audits"] = record.get("audits", 0) + 1
            record["audited_at"] = now()
            record.pop("unaudited_since", None)
            self.save(record["id"])

    def supervisor_prompt(self, record: dict) -> str:
        return SUPERVISOR_PROMPT.format(id=record["id"], description=record.get("description") or "(none given: ask for one)",
                                        binding=self.binding(record), stores=self.stores.folder, scripts=self.scripts)


class Audit:
    """What waits for a command's supervisor: the runs since it last looked."""

    def __init__(self, commands: Commands, name: str, why: str):
        self.commands = commands
        self.name = name
        self.why = why
        self._claimed = False

    def claim(self) -> Optional[str]:
        record = self.commands.get(self.name)
        if self._claimed or record is None or record.get("runs", 0) <= record.get("audited", 0):
            return None
        self._claimed = True
        return self.commands.audit_prompt(record, self.why)

    def settle(self, handled: bool) -> None:
        if record := self.commands.get(self.name):
            self.commands.audited(record, handled)


def make_supervisor(commands: Commands, record: dict) -> tuple[Optional[str], Optional[str]]:
    """The job that audits a command, made with it; its id, or why there is none."""
    try:
        return commands.agent.create_job(commands.supervisor_prompt(record), SUPERVISOR_SCHEDULE, f"command/{record['id']}"), None
    except Unavailable as missing:
        return None, f"{missing}: the command runs, but nothing supervises it"
    except Exception as error:
        return None, f"The supervisor job could not be made: {error}"


def update_supervisor(agent: Agent, job_id: str, prompt: str) -> None:
    try:
        agent.update_job(job_id, prompt)
    except Exception as error:
        logger.warning("[app] the supervisor %s keeps its old prompt: %s", job_id, error)


def drop_supervisor(agent: Agent, job_id: str) -> None:
    try:
        agent.remove_job(job_id)
    except Exception as error:
        logger.warning("[app] the supervisor %s could not be removed: %s", job_id, error)


async def tool(args: dict, **_) -> str:
    """`app_command`: binds a name to a program or a job, with its contract;
    lists the commands; shows one with its runs; removes one."""
    import asyncio

    from . import records, server, session

    session.link()
    commands = server.current.commands
    name = args.get("id")
    if not name:
        return session.answer({"commands": [_summary(commands, record) for record in commands.records.values()],
                               "use": "On a page or a card: {\"command\": id, \"args\": {…}}; the page reads $commands.<id> "
                                      "({status: running | done | failed, result, error, at, duration, args})"})
    if args.get("remove"):
        record = await session.on_gateway(session.run(commands.remove, name))
        if record is None:
            return session.answer({"error": f"There is no command {name}"})
        if record.get("supervised_by"):
            await asyncio.to_thread(drop_supervisor, commands.agent, record["supervised_by"])
        return session.answer({"removed": name})
    changing = {key: args.get(key) for key in (*BINDINGS, "description", "timeout", "sample") if args.get(key) is not None}
    known = commands.get(name)
    if not changing:
        if known is None:
            return session.answer({"error": f"There is no command {name}: bind it to a script, a flow or a job, with a description"})
        return session.answer({"command": _summary(commands, known), "runs": commands.runs(name, limit=20)})
    if known is None and not any(changing.get(key) for key in BINDINGS):
        return session.answer({"error": "A new command is bound to one thing: script (a file under the scripts folder, executable, "
                                        "reading its arguments as JSON on stdin), flow (a Windmill flow's path) or job (a cron job's id)"})
    if (known is None or not known.get("description")) and not changing.get("description"):
        return session.answer({"error": "A command needs a description: its contract, what one run must achieve. The supervisor judges the runs against it"})
    if problem := commands.problem(changing):
        return session.answer({"error": problem})
    if changing.get("job") and (problem := await records.no_job(changing["job"])):
        return problem
    record = await session.on_gateway(session.run(commands.define, name, changing))
    warning = None
    if not record.get("supervised_by"):
        job, warning = await asyncio.to_thread(make_supervisor, commands, record)
        if job:
            record = await session.on_gateway(session.run(commands.define, name, {"supervised_by": job}))
    else:
        await asyncio.to_thread(update_supervisor, commands.agent, record["supervised_by"], commands.supervisor_prompt(record))
    answer = {"command": _summary(commands, record),
              "use": {"command": name, "args": "{…}"},
              "live": f"$commands.{name}: {{status: running | done | failed, result, error, at, duration, args}}; "
                      f"what the program writes to a store shows through that store"}
    if warning:
        answer["warning"] = warning
    return session.answer(answer)


def _summary(commands: Commands, record: dict) -> dict:
    return {key: value for key, value in record.items() if key not in ("audited", "unaudited_since", "audited_at")} | {"binding": commands.binding(record)}


def _result(text: str):
    text = text.strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except ValueError:
        return text[:RESULT_KEPT]


def _drift(entry: dict, earlier: list[dict]) -> Optional[str]:
    if entry.get("status") != "done" or len(earlier) < 3:
        return None
    durations = [run["duration"] for run in earlier if isinstance(run.get("duration"), (int, float))]
    if durations:
        usual = statistics.median(durations)
        taken = entry.get("duration") or 0
        if usual >= 1 and (taken > usual * DRIFT or taken < usual / DRIFT):
            return f"a run unlike the others: it took {taken}s where the others take about {round(usual, 1)}s"
    writers = sum(1 for run in earlier if run.get("wrote"))
    if not entry.get("wrote") and writers * 2 >= len(earlier):
        return "a run unlike the others: it wrote no store where the others do"
    return None


def _epoch(stamp: Optional[str]) -> float:
    if not stamp:
        return 0
    try:
        return datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0
