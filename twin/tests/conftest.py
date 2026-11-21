# SPDX-FileCopyrightText: 2026 Julien Malka
# SPDX-License-Identifier: MIT

"""The twin lays out with the phone's fonts and calibrates against Apple's symbol catalog, neither of which the
repository holds: BENCH_FONTS names a folder of the phone's fonts (as the plugin keeps them in twin/fonts/ of its
home), BENCH_SYMBOLS the catalog. Without them, the tests that need them are skipped."""

import os
import sys

import pytest

os.environ.setdefault("BENCH_TZ", "Europe/Stockholm")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "plugin")))

from dedala.twin import layout  # noqa: E402

FONTS = os.path.exists(os.path.join(layout.FONTS_DIR, layout.FONT_FILES["default"]))
CALIBRATING = ("test_calibration.py", "test_faults.py", "test_text.py")


def pytest_configure(config):
    config.addinivalue_line("markers", "fonts: lays out, so needs the phone's fonts")


def pytest_collection_modifyitems(config, items):
    for item in items:
        name = os.path.basename(str(item.fspath))
        if not FONTS and (name != "test_expressions.py" or item.get_closest_marker("fonts")):
            item.add_marker(pytest.mark.skip(reason="no fonts: set BENCH_FONTS to a folder of the phone's fonts"))
        elif layout.GLYPHS is None and name in CALIBRATING:
            item.add_marker(pytest.mark.skip(reason="no symbol catalog: set BENCH_SYMBOLS to compare with the phone's frames"))
