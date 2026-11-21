# SPDX-FileCopyrightText: 2026 Julien Malka
# SPDX-License-Identifier: MIT

"""The twin evaluates Hermes UI expressions as the phone does: the vectors are
the phone's own (HermesTests/expression-vectors.json, checked there against the
interpreter)."""

import json
from pathlib import Path

import pytest

from dedala.twin import layout

VECTORS = json.loads((Path(__file__).resolve().parents[2] / "HermesTests" / "expression-vectors.json").read_text())


def same(found, expected) -> bool:
    if isinstance(expected, bool) or isinstance(found, bool):
        return found is expected
    if isinstance(expected, (int, float)) and isinstance(found, (int, float)):
        return abs(found - expected) < 1e-9
    if isinstance(expected, list) and isinstance(found, list):
        return len(found) == len(expected) and all(same(a, b) for a, b in zip(found, expected))
    return found == expected


@pytest.mark.parametrize("case", VECTORS["cases"], ids=lambda case: case["expr"])
def test_the_twin_evaluates_as_the_phone_does(case):
    found = layout.evaluate(case["expr"], layout.Scope([VECTORS["scope"]]))
    assert same(found, case["value"]), f"{case['expr']} is {found!r}, not {case['value']!r}"
    if case["text"] is not None:
        assert layout.text_of(found) == case["text"]


@pytest.mark.fonts
def test_a_condition_is_an_expression_whatever_it_starts_with():
    cut = {"Text": "The quick brown fox jumps over the lazy dog while the band plays on and on into the night", "lineLimit": 1}
    data = {"a": True, "b": False, "n": 3}

    def drawn(condition) -> bool:
        from dedala.twin import twincheck

        card = {"view": {"If": condition, "then": cut, "else": {"Text": "short"}}, "data": data}
        faults, notes = twincheck.found(card, {"textSize": "large", "cardWidth": 361})
        return bool(faults or notes)

    assert drawn("$a") and not drawn("$b")
    assert not drawn("$a && $b") and drawn("$a && !$b")
    assert not drawn("$n > 5") and drawn("${n > 2}") and drawn("count(pluck([], 'x')) == 0")
