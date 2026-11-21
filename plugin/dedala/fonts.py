# SPDX-FileCopyrightText: 2026 Julien Malka
# SPDX-License-Identifier: MIT

"""The phone's system fonts for the twin: Apple's font files cannot ship here,
so the phone sends its own, rebuilt from their tables, once per iOS version.
They are kept in twin/fonts/ in the plugin's home, which its fonts.json marks
complete, and the twin lays out with them from then on."""

import logging
import shutil
import time
import zlib
from pathlib import Path
from typing import Awaitable, Callable, Optional

from . import twin
from .state import read, write

logger = logging.getLogger(__name__)

ASKED_AGAIN = 600
FONT_MAGIC = (b"\x00\x01\x00\x00", b"OTTO", b"true")


class Fonts:
    def __init__(self, home: Path):
        self.folder = home / "twin" / "fonts"
        self.marker = self.folder / "fonts.json"
        self.asked = 0.0

    @property
    def os(self) -> Optional[str]:
        return read(self.marker).get("os") if self.marker.exists() else None

    def display(self, display: dict) -> list[dict]:
        """Asks for the fonts when the phone runs an iOS whose fonts are not
        here; nothing for an app too old to send them."""
        if not display.get("os") or display["os"] == self.os or time.time() - self.asked < ASKED_AGAIN:
            return []
        self.asked = time.time()
        return [{"op": "fonts"}]

    async def received(self, event: dict, blob: Callable[[str], Awaitable[Optional[bytes]]]) -> bool:
        """Fetches the fonts the phone uploaded, keeps them, and hands them to
        the twin; False when one is missing or not a font."""
        try:
            names = twin.font_files()
        except Exception as error:
            logger.warning("[app] the twin cannot load here, the phone's fonts are not kept: %s", error)
            return False
        files = event.get("files") or {}
        fonts = {}
        for design, file in names.items():
            entry = files.get(design)
            if not isinstance(entry, dict) or not entry.get("blobs"):
                logger.warning("[app] the phone sent no %s font", design)
                return False
            parts = [await blob(identifier) for identifier in entry["blobs"]]
            if any(part is None for part in parts):
                logger.warning("[app] the %s font is gone from the relay", design)
                return False
            try:
                data = zlib.decompress(b"".join(parts), -zlib.MAX_WBITS)
            except zlib.error as error:
                logger.warning("[app] the %s font could not be inflated: %s", design, error)
                return False
            if data[:4] not in FONT_MAGIC:
                logger.warning("[app] the %s font is not a font", design)
                return False
            fonts[file] = data
        fresh = self.folder.with_name("fonts.new")
        shutil.rmtree(fresh, ignore_errors=True)
        fresh.mkdir(parents=True)
        for file, data in fonts.items():
            (fresh / file).write_bytes(data)
        write(fresh / "fonts.json", {"os": event.get("os")})
        shutil.rmtree(self.folder, ignore_errors=True)
        fresh.rename(self.folder)
        twin.refresh()
        logger.info("[app] the twin lays out with the fonts of iOS %s", event.get("os"))
        return True
