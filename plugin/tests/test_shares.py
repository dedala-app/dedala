# SPDX-FileCopyrightText: 2026 Julien Malka
# SPDX-License-Identifier: MIT

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "plugin"))

from dedala import shares  # noqa: E402

BLOBS = {"b1": b"<page text>", "b2": b"\xff\xd8jpeg", "b3": b"%PDF-1", "b4": b"-rest"}


async def fetch(blob):
    return BLOBS.get(blob)


def share(**extra):
    return {"kind": "share", "id": "S-1", "conversation": "main", "text": "File the receipt and read the article", "at": "2026-11-06T10:00:00Z",
            "items": [{"type": "link", "url": "https://example.com/a", "title": "An article", "selection": "the key line", "page": ["b1"]},
                      {"type": "image", "item": 1, "mime": "image/jpeg", "blobs": ["b2"]},
                      {"type": "file", "name": "receipt.pdf", "mime": "application/pdf", "size": 12, "blobs": ["b3", "b4"]},
                      {"type": "text", "text": "a quote"}], **extra}


def test_a_share_is_kept_once_with_its_files(tmp_path):
    kept = asyncio.run(shares.keep(tmp_path, share(), fetch))
    link, photo, receipt, quote = kept["items"]
    assert Path(link["page"]).read_bytes() == b"<page text>"
    assert Path(photo["path"]).read_bytes() == b"\xff\xd8jpeg"
    assert Path(receipt["path"]).name == "2-receipt.pdf" and Path(receipt["path"]).read_bytes() == b"%PDF-1-rest"
    assert quote["text"] == "a quote"
    assert shares.images(kept) == [photo["path"]]
    assert asyncio.run(shares.keep(tmp_path, share(), fetch)) is None


def test_the_agent_reads_the_note_then_what_came_with_it(tmp_path):
    kept = asyncio.run(shares.keep(tmp_path, share(), fetch))
    told = shares.told(kept)
    assert told.startswith("File the receipt and read the article\n\n[app: he shared this")
    assert "https://example.com/a" in told and "he had selected: \"the key line\"" in told
    assert "receipt.pdf (application/pdf)" in told and "some text: \"a quote\"" in told


def test_his_message_shows_what_he_shared_without_its_content(tmp_path):
    kept = asyncio.run(shares.keep(tmp_path, share(), fetch))
    assert shares.shown(kept) == [{"type": "link", "url": "https://example.com/a", "title": "An article"},
                                  {"type": "image", "size": 6, "item": 1},
                                  {"type": "file", "name": "receipt.pdf", "size": 11},
                                  {"type": "text", "text": "a quote"}]


def test_a_blob_gone_from_the_relay_is_said_missing(tmp_path):
    event = share(id="S-2", items=[{"type": "image", "item": 0, "blobs": ["gone"]}])
    kept = asyncio.run(shares.keep(tmp_path, event, fetch))
    assert "did not arrive" in shares.told(kept) and shares.images(kept) == []
