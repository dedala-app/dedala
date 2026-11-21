# SPDX-FileCopyrightText: 2026 Julien Malka
# SPDX-License-Identifier: MIT

"""The plugin's side of the twin (plugin/dedala/twin/ and the `checks.look` that calls it): the package loads from
the plugin's folder, its faults reach the tool, and a card the twin cannot lay out leaves unchecked: neither refused
nor a crash."""

import asyncio
import logging
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "plugin"))

dedala = pytest.importorskip("dedala")

LONG = "The quick brown fox jumps over the lazy dog while the band plays on and on into the night"


@pytest.fixture
def phone(monkeypatch, tmp_path):
    link = types.SimpleNamespace(state={"display": {"textSize": "large", "cardWidth": 361}}, home=tmp_path)
    monkeypatch.setattr(dedala.session, "link", lambda: link)
    monkeypatch.setattr(dedala.checks, "all_stores", lambda: {"day": {"hero": "Sunny"}})
    return link


def test_the_plugin_loads_its_twin():
    from dedala import twin as shim

    assert shim.available()
    assert shim._load().__name__ == "dedala.twin.preview"
    assert Path(shim._load().__file__).parent == ROOT / "plugin" / "dedala" / "twin"


def test_the_twin_s_faults_reach_the_card_tool(phone):
    looked = asyncio.run(dedala.checks.look({"view": {"Text": LONG, "lineLimit": 2}}, None, "card-1", picture=False))
    assert looked["faults"] == ["“The quick brown fox jumps over the lazy…” is cut: it needs 3 lines and shows 2 (at 361 pt wide)"]
    assert looked["png"] is None
    assert "stores" not in looked["card"]


def test_a_card_reads_the_stores_the_phone_holds(phone):
    looked = asyncio.run(dedala.checks.look({"view": {"Text": "$day.hero"}}, None, "card-2", picture=False))
    assert looked["faults"] == []


def test_a_card_the_twin_cannot_lay_out_leaves_unchecked(phone, caplog):
    with caplog.at_level(logging.WARNING):
        looked = asyncio.run(dedala.checks.look({"view": {"VStack": [{"Sparkline": [1, 2]}]}}, None, "card-3", picture=False))
    assert looked is None
    assert "the twin could not lay out card-3" in caplog.text
    assert "Sparkline" in caplog.text
