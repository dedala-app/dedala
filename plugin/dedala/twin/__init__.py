# SPDX-FileCopyrightText: 2026 Julien Malka
# SPDX-License-Identifier: MIT

"""The phone's layout twin, run before a card or a page leaves: a card or a page
laid out the way the app does, with the phone's fonts, hyphenation and symbol
sizes, without the phone; what would look broken on his phone at the text size
and widths it reported, and the card or page drawn as the phone will draw it,
for the review. This module loads it on first use; the rest of the plugin
works without its libraries.

    layout      every node's frame and every text's lines
    twincheck   what a reader would see as broken, from those
    paint       the frames as an HTML page
    preview     the three together, with a picture
    calibrate, textcheck   the twin against what the phone reported (twin/calibration/ in the repository)

The data beside the modules is read, never written."""

import logging
import threading
import time
from pathlib import Path

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_preview = None
_data: Path | None = None


def configure(home: Path) -> None:
    """Where the phone's fonts and symbol pictures are kept: twin/ in the
    plugin's home. The twin lays out with nothing of Apple's in the repository."""
    global _data
    _data = home / "twin"


def refresh() -> None:
    """The twin takes what the phone sent since it loaded."""
    if _preview is not None:
        with _lock:
            _apply(_preview)


def _apply(preview) -> None:
    if _data is None:
        return
    fonts = _data / "fonts"
    if (fonts / "fonts.json").exists():
        preview.layout.use_fonts(str(fonts))
    preview.paint.glyphs.FOLDER = str(_data / "glyphs")


def _load():
    global _preview
    if _preview is None:
        from . import preview

        _apply(preview)
        _preview = preview
    return _preview


def available() -> bool:
    try:
        _load()
        return True
    except Exception as error:
        logger.warning("[app] the layout twin is not available here: %s", error)
        return False


def look(card: dict, display: dict | None, components: dict, derived: dict | None, folder: Path | None, name: str,
         page: bool = False) -> dict:
    """{card (lone last words tied), faults, notes, png, size, fixed}, for a card or
    a page (`page`); raises when the twin cannot lay it out. Blocking: run it in a
    thread."""
    preview = _load()
    png = None
    if folder is not None:
        folder.mkdir(parents=True, exist_ok=True)
        png = str(folder / f"{name}-{int(time.time())}.png")
    with _lock:
        return preview.look(card, display, components, derived, png, page)


def widget(component: str, data: dict, families: list[str], display: dict | None, components: dict, stores: dict) -> list[str]:
    """What would look broken in a widget at each of its sizes; raises when the
    twin cannot lay it out. Blocking: run it in a thread."""
    preview = _load()
    with _lock:
        return [fault for family in families for fault in preview.twincheck.widget(component, data, family, display, components, stores)]


def measured(change):
    """`change` applied to the twin's measured symbols (layout.MEASURED), between
    two layouts; raises when the twin cannot load here."""
    preview = _load()
    with _lock:
        return change(preview.layout.MEASURED)


def text_sizes(text_size: str | None) -> set[float]:
    """The point sizes of the text styles at this text size."""
    table = _load().layout.TEXT_SIZES
    return {float(size) for size, _ in table.get(text_size or "large", table["large"])}


def font_files() -> dict:
    """The file each design's font is kept in."""
    return dict(_load().layout.FONT_FILES)
