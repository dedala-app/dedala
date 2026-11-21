# SPDX-FileCopyrightText: 2026 Julien Malka
# SPDX-License-Identifier: MIT

"""The twin's text engine against the 16,399 lines the phone's own engine laid out (calibration/text), and its
hyphenation against the points the phone gave. The counts are today's: a regression fails.

    python -m twin.textcheck     the same numbers, with the first lines that disagree"""

import pytest

from dedala.twin import textcheck
from dedala.twin.hyphenate import Hyphenator

CASES = 16399
MISMATCHES = 0
WIDTHS_OFF = 47
WORST = 0.831
BROKEN_ELSEWHERE = 2
POINTS = {
    ("hyphenation", "en_US"): [2, 6],
    ("internationalisation", "en_US"): [2, 5, 7, 11, 13, 14, 16],
    ("camelCaseWord", "en_US"): [5, 9],
    ("Stockholm", "en_US"): [],
    ("don't", "en_US"): [],
}


@pytest.fixture(scope="module")
def measured():
    return textcheck.measure()


def test_every_line_count_is_the_phone_s(measured):
    total, mismatches, _, examples = measured
    assert total == CASES
    assert mismatches <= MISMATCHES, examples[:3]


def test_line_widths_are_the_phone_s_to_a_thousandth_of_a_point(measured):
    errors = measured[2]
    assert abs(errors[int(0.01 * len(errors))]) <= 0.001
    assert abs(errors[int(0.99 * len(errors))]) <= 0.001
    assert sum(abs(error) > 0.001 for error in errors) <= WIDTHS_OFF
    assert sum(abs(error) > WORST for error in errors) <= BROKEN_ELSEWHERE


@pytest.mark.parametrize("word,language", POINTS)
def test_a_word_hyphenates_where_it_does_today(word, language):
    assert Hyphenator.points(word, language) == POINTS[(word, language)]
