# SPDX-FileCopyrightText: 2026 Julien Malka
# SPDX-License-Identifier: MIT

"""The plugin's native code as one WebAssembly module, built from native/ in
the repository: the Org reader the phone links too, the phone's text boundaries
(ICU's, through ICU4X) and a QuickJS for page scripts. wasmtime runs it, so
nothing is compiled where the plugin is installed. The module is the one the
RELEASE named below carries, downloaded once and taken only with the SHA256
below; DEDALA_WASM names a local build instead (`nix-build native/wasm.nix`).
Scripts get an instance of their own, so one running for seconds does not hold
the text calls up; each instance takes one call at a time."""

import atexit
import hashlib
import json
import os
import struct
import threading
import urllib.request
from functools import lru_cache
from pathlib import Path

RELEASE = "native-1"
SHA256 = "03203d28f1790f70fb4fcec97472aa18d7afc85697e1bc8404e31b7f75fdfa4a"
SOURCE = f"https://github.com/dedala-app/dedala/releases/download/{RELEASE}/dedala.wasm"
LINE, WORD, GRAPHEME = 0, 1, 2

_locks = {"text": threading.Lock(), "scripts": threading.Lock()}
_modules: dict = {}
atexit.register(_modules.clear)


def module() -> Path:
    """The module's file: DEDALA_WASM's, or the release's, kept in the user's
    cache once its hash is checked."""
    if given := os.environ.get("DEDALA_WASM"):
        return Path(given)
    cache = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "dedala" / f"{SHA256}.wasm"
    if not cache.exists():
        with urllib.request.urlopen(SOURCE, timeout=60) as response:
            data = response.read()
        if hashlib.sha256(data).hexdigest() != SHA256:
            raise RuntimeError(f"{SOURCE} is not the module this plugin was made for")
        cache.parent.mkdir(parents=True, exist_ok=True)
        partial = cache.with_suffix(f".{os.getpid()}.part")
        partial.write_bytes(data)
        partial.replace(cache)
    return cache


class _Module:
    def __init__(self):
        import wasmtime

        config = wasmtime.Config()
        try:
            config.cache = True
        except Exception:
            pass
        engine = wasmtime.Engine(config)
        linker = wasmtime.Linker(engine)
        linker.define_wasi()
        self.store = wasmtime.Store(engine)
        self.store.set_wasi(wasmtime.WasiConfig())
        self.exports = linker.instantiate(self.store, wasmtime.Module.from_file(engine, str(module()))).exports(self.store)
        self.memory = self.exports["memory"]

    def put(self, data: bytes) -> int:
        pointer = self.exports["dedala_alloc"](self.store, len(data))
        self.memory.write(self.store, data, pointer)
        return pointer

    def free(self, pointer: int, length: int) -> None:
        self.exports["dedala_free"](self.store, pointer, length)

    def call(self, name: str, *arguments) -> bytes:
        """`name` called with each str argument as a pointer and a length,
        each int as itself; its result read and given back."""
        given, held = [], []
        try:
            for argument in arguments:
                if isinstance(argument, str):
                    data = argument.encode("utf-8")
                    pointer = self.put(data)
                    held.append((pointer, len(data)))
                    given += [pointer, len(data)]
                else:
                    given.append(argument)
            word = self.exports[name](self.store, *given)
        finally:
            for pointer, length in held:
                self.free(pointer, length)
        pointer, length = word >> 32, word & 0xFFFFFFFF
        result = bytes(self.memory.read(self.store, pointer, pointer + length)) if length else b""
        self.free(pointer, length)
        return result


def _instance(role: str) -> _Module:
    if role not in _modules:
        _modules[role] = _Module()
    return _modules[role]


def _call(name: str, *arguments, role: str = "text") -> bytes:
    with _locks[role]:
        return _instance(role).call(name, *arguments)


def available() -> bool:
    try:
        _call("dedala_breaks", WORD, "")
        return True
    except Exception:
        return False


def org_parse(text: str, format: str = "") -> dict:
    """The org-element tree of a text; `format` is "org" or "markdown", told
    from the text when empty."""
    return json.loads(_call("dedala_org_parse", text, format) or b"{}")


@lru_cache(maxsize=20000)
def breaks(kind: int, text: str) -> tuple[int, ...]:
    """A text's boundaries of one kind, in characters, its start included."""
    data = _call("dedala_breaks", kind, text)
    return struct.unpack(f"<{len(data) // 4}I", data)


@lru_cache(maxsize=4096)
def is_emoji(code_point: int) -> bool:
    with _locks["text"]:
        module = _instance("text")
        return bool(module.exports["dedala_is_emoji"](module.store, code_point))


def run_script(source: str, seconds: float) -> dict:
    """A script run in QuickJS: {"output": what it printed, "error": why it
    stopped, or None}."""
    return json.loads(_call("dedala_run_script", source, int(seconds * 1000), role="scripts"))
