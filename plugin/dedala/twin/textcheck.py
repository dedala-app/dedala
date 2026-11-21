# SPDX-FileCopyrightText: 2026 Julien Malka
# SPDX-License-Identifier: MIT

"""Checks the layout twin's line breaking against lines the phone's text engine laid out.

    python -m dedala.twin.textcheck [file.jsonl.gz]      default: twin/calibration/text/ios-lines.jsonl.gz

Each case holds a text, font size and weight, a width and an optional lineLimit, with what iOS
reported through the app's debug route (`POST /lines`): the line count and size from the string
drawing engine `Text` uses, and TextKit's line strings and widths.
"""

import gzip
import json
import os
import statistics
import sys

from . import layout


LINES = os.path.join(os.environ.get("BENCH_CALIBRATION") or os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "twin", "calibration")),
                     "text", "ios-lines.jsonl.gz")


def measure(path=LINES):
    """How many cases, how many whose line count differs from the phone's, the widest line's error (twin minus phone)
    for each unlimited case that agrees, sorted, and the first ten that disagree."""
    total = bad = 0
    errors = []
    examples = []
    for line in gzip.open(path, "rt", encoding="utf-8"):
        case = json.loads(line)
        font = dict(layout.DEFAULT_FONT, size=case["size"], weight=case.get("weight") or "regular")
        limit = case.get("lineLimit")
        strings = []
        widths = layout.text_lines(case["text"], font, float(case["width"]), strings)
        count = min(len(widths), limit) if limit else len(widths)
        total += 1
        if count != case["lines"]:
            bad += 1
            if len(examples) < 10:
                examples.append((case, strings))
        elif not limit:
            errors.append(min(max(widths), float(case["width"])) - case["w"])
    errors.sort()
    return total, bad, errors, examples


def check(path=LINES):
    total, bad, errors, examples = measure(path)
    print(f"cases {total}  line count mismatches {bad} ({bad / max(1, total):.2%})")
    if errors:
        print(f"widest line, twin minus phone: median {statistics.median(errors):+.3f}  p1 {errors[int(0.01 * len(errors))]:+.3f}  p99 {errors[int(0.99 * len(errors))]:+.3f}")
    for case, strings in examples:
        print(f"  w={case['width']} {case['size']}/{case.get('weight')} limit={case.get('lineLimit')}: phone {case['lines']} lines: {' | '.join(case['tk2'])}")
        print(f"      twin {len(strings)}: {' | '.join(strings)}")


if __name__ == "__main__":
    check(sys.argv[1] if len(sys.argv) > 1 else LINES)
