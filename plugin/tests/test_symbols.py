# SPDX-FileCopyrightText: 2026 Julien Malka
# SPDX-License-Identifier: MIT

import base64
import json

from dedala import twin
from dedala.symbols import SCALES, WEIGHTS, Symbols, named


def rows(width=51, height=54, baseline=12, aspect=1.25):
    return [[width, height, baseline, aspect] for _ in WEIGHTS for _ in SCALES]


def layout():
    return twin._load().layout


def test_an_app_without_its_ios_version_is_not_asked(tmp_path):
    assert Symbols(tmp_path).display({"textSize": "large"}, {}) == []


def test_the_display_asks_for_the_skills_and_his_pages_symbols_at_the_text_sizes(tmp_path):
    ops = Symbols(tmp_path).display({"os": "27.2", "textSize": "large"}, {"page": {"home": {"view": {"Image": "terminal"}}}})
    asked = {name: sizes for op in ops for name, sizes in op["symbols"].items()}
    assert asked["terminal"] == sorted({float(size) for size, _ in layout().TEXT_SIZES["large"]})
    assert all(op["op"] == "measure" and len(op["symbols"]) <= 10 for op in ops)


def test_what_the_phone_measured_feeds_the_twin_and_survives_a_restart(tmp_path):
    symbols = Symbols(tmp_path)
    symbols.display({"os": "27.2", "textSize": "large"}, {})
    symbols.received({"os": "27.2", "symbols": {"made.up.symbol": {"sizes": {"17.0": rows()}}}})
    font = {"size": 17, "weight": "bold", "imageScale": "medium"}
    pad = layout().symbol_padding("medium", 17)
    expected = [51, 54, 12 - pad, pad, round(1.25 * (54 - 2 * pad)), 54 - 2 * pad]
    assert layout().symbol_pixels("made.up.symbol", font) == expected
    layout().MEASURED.sizes.clear()
    Symbols(tmp_path)._measured(lambda target: None)
    assert layout().symbol_pixels("made.up.symbol", font) == expected


def test_the_twin_asks_once_for_what_it_met_unmeasured_and_never_for_an_unknown_name(tmp_path):
    symbols = Symbols(tmp_path)
    symbols.display({"os": "27.2", "textSize": "large"}, {})
    symbols._measured(lambda target: None)
    layout().symbol_pixels("other.symbol", {"size": 13, "weight": "regular"})
    layout().symbol_pixels("not.a.symbol", {"size": 13, "weight": "regular"})
    symbols.received({"os": "27.2", "symbols": {"not.a.symbol": None}})
    assert symbols.wanted() == [{"op": "measure", "symbols": {"other.symbol": [13.0]}}]
    layout().symbol_pixels("other.symbol", {"size": 13, "weight": "regular"})
    assert symbols.wanted() == []


def test_a_new_ios_measures_every_name_again(tmp_path):
    symbols = Symbols(tmp_path)
    symbols.display({"os": "27.2", "textSize": "large"}, {})
    symbols.received({"os": "27.2", "symbols": {"made.up.symbol": {"sizes": {"17.0": rows()}}}})
    ops = symbols.display({"os": "27.3", "textSize": "large"}, {})
    assert any("made.up.symbol" in op["symbols"] for op in ops)
    assert symbols.data["symbols"]["made.up.symbol"] == {"sizes": {}}


def test_symbol_names_come_from_images_labels_and_buttons():
    found = set()
    named({"VStack": [{"Image": "book"}, {"Label": ["Run", "terminal"]}, {"Button": "Go", "symbol": "play.fill"},
                      {"Image": {"symbol": "star"}}]}, found)
    assert found == {"book", "terminal", "play.fill", "star"}


def test_the_phone_s_pictures_of_a_symbol_are_kept_for_the_twin_s_drawings(tmp_path):
    symbols = Symbols(tmp_path)
    picture = {"png": base64.b64encode(b"\x89PNG fake").decode(), "size": [20.5, 18.0]}
    symbols.received({"os": "27.2", "symbols": {"made.up.symbol": {"sizes": {"17.0": rows()}, "images": {"regular": picture, "../escape": picture}}}})
    assert (tmp_path / "twin" / "glyphs" / "made.up.symbol-regular.png").read_bytes() == b"\x89PNG fake"
    assert json.loads((tmp_path / "twin" / "glyphs" / "sizes.json").read_text()) == {"made.up.symbol": {"regular": [20.5, 18.0]}}
    assert "images" not in json.loads((tmp_path / "twin" / "symbols.json").read_text())["symbols"]["made.up.symbol"]
