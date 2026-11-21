# SPDX-FileCopyrightText: 2026 Julien Malka
# SPDX-License-Identifier: MIT

"""The twin against the frames the phone reported (calibration/). The counts are what the twin scores today, so a
regression fails; raise them when the twin gets closer to the phone.

    python -m twin.calibrate all | verbose | sizes     the same numbers, with every node that is off

DEFAULT holds, per set, the phone's frames the twin has a frame for, those within 2 pt on every axis, those within 1 pt,
and the phone's frames the twin has none for. UNMATCHED names the cards the comparison does not cover at all: the phone's
report starts at the view, the twin puts a card around it, so no path matches; a known gap, they count in the missing
frames and nowhere else. SIZES holds, per text size and set, the frames compared, those within 2 pt, those within 1 pt."""

import os

import pytest

from dedala.twin import calibrate

DEFAULT = {"corpus": (585, 585, 585, 28), "probes": (1997, 1992, 1990, 789)}
UNMATCHED = {"corpus": {"doc-02-flight"},
             "probes": {"calib-controls", "calib-cov-containers", "calib-flight", "calib-spacing", "calib-stacks"}}
SIZES = {
    "xSmall": {"probes": (1997, 1646, 1605), "corpus": (585, 584, 584)},
    "small": {"probes": (1997, 1597, 1587), "corpus": (585, 585, 585)},
    "medium": {"probes": (1997, 1598, 1587), "corpus": (585, 585, 585)},
    "large": {"probes": (1997, 1673, 1663), "corpus": (585, 585, 585)},
    "xLarge": {"probes": (1997, 1715, 1674), "corpus": (585, 585, 585)},
    "xxLarge": {"probes": (1997, 1584, 1575), "corpus": (585, 585, 585)},
    "xxxLarge": {"probes": (1997, 1645, 1636), "corpus": (585, 581, 581)},
    "accessibility1": {"probes": (1997, 1526, 1505), "corpus": (585, 566, 548)},
    "accessibility2": {"probes": (1997, 1362, 1149), "corpus": (585, 546, 530)},
    "accessibility3": {"probes": (1997, 1089, 991), "corpus": (585, 533, 509)},
    "accessibility4": {"probes": (1997, 721, 604), "corpus": (585, 452, 354)},
    "accessibility5": {"probes": (1997, 270, 234), "corpus": (585, 177, 107)},
}


@pytest.fixture(scope="module")
def sizes():
    return dict(calibrate.by_size())


@pytest.mark.parametrize("name", DEFAULT)
def test_the_twin_is_as_close_to_the_phone_as_today(name):
    compared, close, tight, missing = DEFAULT[name]
    deltas, lost, unmatched = [], 0, set()
    for key, card, components, report in calibrate.cards(os.path.join(calibrate.CALIBRATION, name)):
        found, absent, _, _ = calibrate.compare(card, components, report, verbose=False)
        deltas += found
        lost += absent
        if not found:
            unmatched.add(key)
    assert len(deltas) + lost == compared + missing, "the stored reports changed: measure again and set today's counts"
    assert lost <= missing
    assert unmatched <= UNMATCHED[name]
    assert calibrate.within(deltas, 2) >= close
    assert calibrate.within(deltas, 1) >= tight


def test_every_text_size_has_its_capture(sizes):
    assert list(sizes) == list(SIZES)


@pytest.mark.parametrize("size", SIZES)
@pytest.mark.parametrize("name", ("probes", "corpus"))
def test_the_twin_is_as_close_at_every_text_size_as_today(sizes, size, name):
    compared, close, tight = SIZES[size][name]
    deltas = sizes[size][name]
    assert len(deltas) >= compared
    assert calibrate.within(deltas, 2) >= close
    assert calibrate.within(deltas, 1) >= tight
