# SPDX-FileCopyrightText: 2026 Julien Malka
# SPDX-License-Identifier: MIT

import os
import zlib

import pytest

from dedala import twin
from dedala.fonts import Fonts


@pytest.fixture
def layout():
    module = twin._load().layout
    if not os.path.exists(os.path.join(module.FONTS_DIR, module.FONT_FILES["default"])):
        pytest.skip("no fonts: set BENCH_FONTS to a folder of the phone's fonts")
    before = module.FONTS_DIR
    yield module
    twin._data = None
    module.use_fonts(before)


def uploaded(layout, broken=None):
    """The fonts BENCH_FONTS names, as the relay holds the phone's: deflated, in
    blobs of a few hundred kilobytes."""
    blobs, files = {}, {}
    for design, file in layout.FONT_FILES.items():
        deflate = zlib.compressobj(wbits=-zlib.MAX_WBITS)
        data = deflate.compress(open(os.path.join(layout.FONTS_DIR, file), "rb").read()) + deflate.flush()
        if design == broken:
            data = b"not a font"
        names = []
        for start in range(0, len(data), 300_000):
            names.append(f"b{len(blobs)}")
            blobs[names[-1]] = data[start:start + 300_000]
        files[design] = {"blobs": names, "size": len(data)}

    async def blob(name):
        return blobs.get(name)

    return {"kind": "fonts", "os": "27.2", "files": files}, blob


def test_an_app_without_its_ios_version_is_not_asked_and_a_new_ios_is_asked_once(tmp_path):
    fonts = Fonts(tmp_path)
    assert fonts.display({"textSize": "large"}) == []
    assert fonts.display({"os": "27.2"}) == [{"op": "fonts"}]
    assert fonts.display({"os": "27.2"}) == []


async def test_the_phone_s_fonts_are_kept_and_the_twin_lays_out_with_them(tmp_path, layout):
    twin.configure(tmp_path)
    width = layout.advance("Hyphenation", "default", "regular", 17, False)
    event, blob = uploaded(layout)
    assert await Fonts(tmp_path).received(event, blob)
    assert layout.FONTS_DIR == str(tmp_path / "twin" / "fonts")
    assert layout.advance("Hyphenation", "default", "regular", 17, False) == width
    assert Fonts(tmp_path).os == "27.2"
    assert Fonts(tmp_path).display({"os": "27.2"}) == []


async def test_fonts_that_do_not_inflate_are_not_kept(tmp_path, layout):
    twin.configure(tmp_path)
    event, blob = uploaded(layout, broken="serif")
    assert not await Fonts(tmp_path).received(event, blob)
    assert not (tmp_path / "twin" / "fonts").exists()
