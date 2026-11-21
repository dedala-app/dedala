# SPDX-FileCopyrightText: 2026 Julien Malka
# SPDX-License-Identifier: AGPL-3.0-or-later

{ pkgs ? import <nixpkgs> { } }:
pkgs.mkShell {
  packages = [
    (pkgs.python3.withPackages (ps: with ps; [ aiohttp cryptography httpx h2 pyflakes pytest pytest-aiohttp pytest-asyncio qrcode uharfbuzz fonttools wasmtime ]))
    pkgs.reuse
  ];
  DEDALA_WASM = "${import ../native/wasm.nix}/dedala.wasm";
}
