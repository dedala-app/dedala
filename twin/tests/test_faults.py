# SPDX-FileCopyrightText: 2026 Julien Malka
# SPDX-License-Identifier: MIT

"""What the twin calls broken and what it only notes: one small card per kind, then every real card of the corpus
against what it says of it today (faults.json).

    TWIN_ACCEPT=1 python -m pytest twin/tests/test_faults.py     takes today's answers for the corpus, after a change
                                                                  made on purpose"""

import json
import os
from pathlib import Path

import pytest

from dedala.twin import calibrate, layout, preview, twincheck

LONG = "The quick brown fox jumps over the lazy dog while the band plays on and on into the night"
LONE = "Meet at the north gate before the concert starts tonight"
PHONE = {"textSize": "large", "cardWidth": 361}
GOLDEN = Path(__file__).with_name("faults.json")
CLOCK = "2026-11-01T12:00:00+01:00"


def said(view, display=PHONE, **card):
    return twincheck.found({"view": view, **card}, display)


@pytest.fixture(autouse=True)
def at_a_fixed_moment():
    layout.CLOCK = layout.parse_date(CLOCK)
    yield
    layout.CLOCK = None
    layout.set_text_size("large")


def test_a_sound_card_has_nothing_against_it():
    assert said({"VStack": [{"Text": "Flight 1457", "font": "headline"}, {"Text": "Boarding at 17:15"}]}) == ([], [])


def test_a_text_cut_by_a_line_is_a_fault():
    faults, notes = said({"Text": LONG, "lineLimit": 2})
    assert faults == ["“The quick brown fox jumps over the lazy…” is cut: it needs 3 lines and shows 2 (at 361 pt wide)"]
    assert notes == []


def test_a_text_cut_by_its_frame_is_a_fault():
    faults, _ = said({"Text": LONG, "height": 30})
    assert faults == ["“The quick brown fox jumps over the lazy…” is cut: it needs 3 lines and shows 1 (at 361 pt wide)"]


def test_a_long_text_limited_on_purpose_is_only_noted():
    faults, notes = said({"Text": LONG * 3, "lineLimit": 2})
    assert faults == []
    assert notes == ["“The quick brown fox jumps over the lazy…” shows 2 of its 7 lines (at 361 pt wide)"]


def test_a_word_broken_across_lines_is_a_fault():
    faults, _ = said({"Text": "Internationalisation of everything", "font": {"size": 40}, "frame": {"width": 200}})
    assert faults == ["“Internationalisation” is broken across two lines in “Internationalisation of everything” (at 361 pt wide)"]


def test_a_short_label_that_wraps_is_a_fault():
    faults, _ = said({"HStack": [{"Label": ["Stockholm Central", "tram.fill"], "width": 100}, {"Spacer": {}}]})
    assert "the label “Stockholm Central” wraps onto 2 lines (at 361 pt wide)" in faults


def test_a_button_whose_label_does_not_fit_is_a_fault():
    row = [{"Button": label, "style": "bordered"} for label in ("Approve the invoice", "Reject the invoice now", "Ask me again tomorrow")]
    faults, _ = said({"HStack": row})
    assert len(faults) == 3
    assert all(fault.startswith("the button “") and "does not fit on one line" in fault for fault in faults)


def test_a_symbol_wider_than_its_frame_beside_something_is_a_fault():
    faults, _ = said({"HStack": [{"Image": "airplane", "font": "largeTitle", "frame": {"width": 12}}, {"Text": "Flight"}], "spacing": 0})
    assert faults == ["the symbol airplane is 42 pt wide in a 12 pt frame: it runs into what is beside it (at 361 pt wide)"]


def test_text_under_eleven_points_is_a_fault():
    faults, _ = said({"Text": "Fine print", "font": {"size": 9}})
    assert faults == ["“Fine print” is 9 pt, under the 11 pt minimum (at 361 pt wide)"]


def test_a_text_that_reads_nothing_is_a_fault():
    faults, _ = said({"Text": "$missing"})
    assert faults == ["“$missing” is empty: the text shows nothing (at 361 pt wide)"]


def test_a_text_held_on_one_line_past_the_edge_is_a_fault():
    faults, _ = said({"VStack": [{"Text": LONG, "fixedSize": True}]})
    assert faults == ["“The quick brown fox jumps over the lazy…” runs past the edge of the screen: 683 pt wide where there "
                      "are 361 (a fixedSize true holds a text on one line; \"vertical\" lets it wrap) (at 361 pt wide)"]


def test_a_fixed_size_by_axes_wraps_like_vertical():
    assert said({"VStack": [{"Text": LONG, "fixedSize": {"horizontal": False, "vertical": True}}]}) == ([], [])
    assert said({"VStack": [{"Text": LONG, "fixedSize": "vertical"}]}) == ([], [])


def test_what_scrolls_sideways_may_run_past_the_edge():
    assert said({"ScrollView": {"HStack": [{"Text": LONG, "fixedSize": True}]}, "axis": "horizontal"}) == ([], [])


def test_an_empty_text_in_no_room_is_laid_out():
    assert said({"VStack": [{"Text": "${missing.subject}"}, {"Text": LONG}], "height": 20})[0]


def test_a_lone_last_word_in_data_is_left_alone():
    assert said({"Text": "$line", "width": 200}, data={"line": LONE}) == ([], [])


def test_a_lone_last_word_in_the_view_is_tied_to_the_word_before():
    looked = preview.look({"Text": LONE, "width": 200}, PHONE)
    assert looked["fixed"] == 1
    assert looked["card"]["view"]["Text"] == "Meet at the north gate before the concert starts tonight"
    assert looked["faults"] == [] and looked["notes"] == []
    assert looked["png"] is None and looked["size"] is None and looked["error"] is None


def test_the_widths_are_the_phone_s_when_it_reported_them():
    assert twincheck.widths(None) == layout.CARD_WIDTHS == (348.0, 395.0)
    assert twincheck.widths({"cardWidth": 361}) == (361.0,)
    assert twincheck.widths(None, page=True) == (370.0, 408.0)
    assert twincheck.widths({"pageWidth": 402}, page=True) == (370.0,)
    assert twincheck.widths({"cardWidth": 361}, page=True) == (370.0, 408.0)


def test_without_a_report_the_faults_come_at_both_widths():
    faults, _ = said({"Text": LONG, "height": 30}, display=None)
    assert [fault.rsplit("(", 1)[1] for fault in faults] == ["at 348 pt wide)", "at 395 pt wide)"]


def test_a_page_is_laid_out_as_it_is_with_no_card_around_it():
    engine = layout.Engine({"view": {"Text": "Flight"}}, {}, 370.0, page=True)
    engine.run()
    assert engine.root.kind == "Text"


def test_a_card_the_twin_cannot_lay_out_raises_and_check_says_so():
    card = {"VStack": [{"Sparkline": [1, 2]}]}
    with pytest.raises(layout.UnknownView):
        twincheck.found(card)
    with pytest.raises(layout.UnknownView):
        preview.look(card)
    assert twincheck.check(card) == ["the twin could not lay this card out (UnknownView: Sparkline at Card › 1.VStack › 1.Sparkline "
                                     "is not a view the twin knows, nor a component of this card)"]


def corpus():
    answers = {}
    for key, card, components, report in calibrate.cards(os.path.join(calibrate.CALIBRATION, "corpus")):
        layout.CLOCK = layout.parse_date(report.get("at") or CLOCK)
        faults, notes = twincheck.found(card, None, components, report.get("derived") or {})
        answers[key] = {"faults": faults, "notes": notes}
    return answers


def test_the_corpus_gets_the_faults_and_notes_it_gets_today():
    answers = corpus()
    if os.environ.get("TWIN_ACCEPT"):
        GOLDEN.write_text(json.dumps(answers, ensure_ascii=False, indent=1) + "\n")
    assert answers == json.loads(GOLDEN.read_text())
