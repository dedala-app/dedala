# SPDX-FileCopyrightText: 2026 Julien Malka
# SPDX-License-Identifier: MIT

import hashlib
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dedala import native  # noqa: E402


@pytest.mark.skipif(not os.environ.get("DEDALA_WASM"), reason="needs a build of native/wasm.nix")
def test_the_plugin_names_the_module_its_sources_build():
    """After a change in native/, native.py takes the new build's hash and the next release's name."""
    assert hashlib.sha256(Path(os.environ["DEDALA_WASM"]).read_bytes()).hexdigest() == native.SHA256


@pytest.fixture
def released(tmp_path, monkeypatch):
    """A release served from a file, and an empty cache."""
    monkeypatch.delenv("DEDALA_WASM", raising=False)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    asset = tmp_path / "dedala.wasm"
    monkeypatch.setattr(native, "SOURCE", asset.as_uri())
    return asset


def test_the_release_is_downloaded_once_and_kept(released, monkeypatch):
    released.write_bytes(b"module")
    monkeypatch.setattr(native, "SHA256", hashlib.sha256(b"module").hexdigest())
    kept = native.module()
    assert kept.read_bytes() == b"module"
    released.unlink()
    assert native.module() == kept


def test_a_module_with_another_hash_is_refused(released):
    released.write_bytes(b"something else")
    with pytest.raises(RuntimeError):
        native.module()
    assert not any((released.parent / "cache").rglob("*.wasm"))
