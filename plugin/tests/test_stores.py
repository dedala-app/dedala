# SPDX-FileCopyrightText: 2026 Julien Malka
# SPDX-License-Identifier: MIT

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "plugin"))

from dedala.link import Link  # noqa: E402
from dedala.stores import Stores  # noqa: E402


def later(path: Path) -> None:
    """A write the clock could not tell from the last one is still seen."""
    stat = path.stat()
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))


def test_a_store_is_a_file_and_what_is_written_to_it_is_taken_in(tmp_path):
    stores = Stores(tmp_path / "stores")
    stores.put("groceries", {"list": ["milk"]})
    assert json.loads((tmp_path / "stores" / "groceries.json").read_text()) == {"list": ["milk"]}
    assert stores.scan() == []
    stores.path("groceries").write_text('{"list": ["milk", "eggs"]}')
    later(stores.path("groceries"))
    (tmp_path / "stores" / "wm%2Fjobs.json").write_text('[{"id": 1}]')
    assert sorted(stores.scan()) == ["groceries", "wm/jobs"]
    assert stores.held == {"groceries": {"list": ["milk", "eggs"]}, "wm/jobs": [{"id": 1}]}
    assert stores.path("wm/jobs").name == "wm%2Fjobs.json" and stores.scan() == []
    stores.path("wm/jobs").unlink()
    assert stores.scan() == ["wm/jobs"] and "wm/jobs" not in stores.held
    assert Stores(tmp_path / "stores").held == {"groceries": {"list": ["milk", "eggs"]}}


def test_a_file_that_stops_being_json_changes_nothing_and_says_why(tmp_path):
    stores = Stores(tmp_path / "stores")
    stores.put("day", {"hero": "Dentist at 9"})
    stores.path("day").write_text('{"hero": "Dentist')
    later(stores.path("day"))
    assert stores.scan() == [] and stores.held["day"] == {"hero": "Dentist at 9"}
    assert stores.unreadable["day"].startswith("it is not JSON")
    assert stores.read("day") == {"hero": "Dentist at 9"}
    stores.path("day").write_text('{"hero": "Dentist at 10"}')
    later(stores.path("day"))
    later(stores.path("day"))
    assert stores.scan() == ["day"] and stores.unreadable == {}
    stores.put("day", None)
    assert not stores.path("day").exists() and stores.held == {}


def test_a_patch_and_his_edit_are_made_to_the_file_as_it_stands(tmp_path):
    link = Link(tmp_path, "http://relay", "token", "Jacques")
    sent = link._record([{"op": "store", "id": "trip", "data": {"days": 3, "who": ["Marta"]}}, {"op": "say", "text": "Done"}])
    assert [op["op"] for op in sent] == ["store", "say"]
    link.stores.path("trip").write_text('{"days": 3, "who": ["Marta"], "weather": "rain"}')
    later(link.stores.path("trip"))
    sent = link._record([{"op": "store", "id": "trip", "patch": {"days": 4, "who": None}}])
    assert sent == [{"op": "store", "id": "trip", "data": {"days": 4, "weather": "rain"}}]
    link.stores.path("trip").write_text('{"days": 4, "weather": "sun"}')
    later(link.stores.path("trip"))
    link.edited({"at": "2026-11-06T10:00:00Z", "changes": [{"store": "trip", "patch": {"packed": True}, "from": "trip"}]})
    assert json.loads(link.stores.path("trip").read_text()) == {"days": 4, "weather": "sun", "packed": True}
    link.edited({"at": "2026-11-06T10:01:00Z", "changes": [{"store": "trip", "patch": {"replace": {"days": 1}, "packed": False}, "from": "trip"}]})
    assert json.loads(link.stores.path("trip").read_text()) == {"days": 1, "packed": False}
    link._record([{"op": "store", "id": "trip", "data": None}])
    assert not link.stores.path("trip").exists() and "trip" not in link.state["artifacts"]["store"]


def test_the_phone_is_sent_what_it_does_not_have_and_only_that(tmp_path):
    link = Link(tmp_path, "http://relay", "token", "Jacques")
    assert link.unsent_stores() == [{"op": "store", "id": "profile", "data": {"name": "Jacques"}}]
    link._record([{"op": "store", "id": "trip", "data": {"days": 3}}])
    assert link.unsent_stores() == []
    link.stores.path("trip").write_text('{"days": 4}')
    later(link.stores.path("trip"))
    (tmp_path / "stores" / "jobs.json").write_text('{"running": 2}')
    assert link.unsent_stores() == []
    link.stores_written()
    assert link.unsent_stores() == [{"op": "store", "id": "trip", "data": {"days": 4}}, {"op": "store", "id": "jobs", "data": {"running": 2}}]
    assert link.unsent_stores() == []
    link.stores.path("jobs").unlink()
    link.stores_written()
    assert link.unsent_stores() == [{"op": "store", "id": "jobs", "data": None}] and link.unsent_stores() == []
    assert Link(tmp_path, "http://relay", "token", "Jacques").unsent_stores() == []
