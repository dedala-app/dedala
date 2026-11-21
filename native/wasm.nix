# SPDX-FileCopyrightText: 2026 Julien Malka
# SPDX-License-Identifier: MIT

# The plugin's WebAssembly module, dedala.wasm: the Org reader, ICU4X's text
# boundaries and QuickJS. `nix-build native/wasm.nix` builds it with the pinned
# nixpkgs below, so the same sources give the same file on any machine: the one a
# native-* release carries, whose hash plugin/dedala/native.py names.
let
  pkgs = import (fetchTarball {
    url = "https://github.com/NixOS/nixpkgs/archive/5d2b81a7a3be3e2f832879028e4d60abbf58e9a0.tar.gz";
    sha256 = "1szspd29nva1v6w5d1lknljaqf99m9sldgc4p8fv7rdmihcchsfw";
  }) { };
  cross = pkgs.pkgsCross.wasi32;
in
cross.rustPlatform.buildRustPackage {
  pname = "dedala-wasm";
  version = "0.1.0";
  src = pkgs.lib.fileset.toSource {
    root = ./.;
    fileset = pkgs.lib.fileset.unions [
      ./Cargo.toml
      ./Cargo.lock
      ./src
    ];
  };
  cargoLock = {
    lockFile = ./Cargo.lock;
    outputHashes = {
      "orgize-0.10.0-alpha.10" = "sha256-R4DtaEIeCRdrTKML697j+gDiY6BExlEfgmPhlUMr7No=";
    };
  };
  buildFeatures = [ "plugin" ];
  cargoBuildFlags = [
    "--lib"
    "--config"
    "profile.release.opt-level=\"s\""
    "--config"
    "profile.release.strip=\"symbols\""
  ];
  env = {
    RQUICKJS_SYS_NO_WASI_SDK = "1";
    RUSTFLAGS = "-Clinker=${pkgs.lld}/bin/wasm-ld -Clink-self-contained=no -L${cross.wasilibc}/lib/wasm32-wasip1";
  };
  doCheck = false;
  installPhase = ''
    runHook preInstall
    install -Dm444 target/wasm32-wasip1/release/dedala_native.wasm $out/dedala.wasm
    runHook postInstall
  '';
}
