# SPDX-FileCopyrightText: 2026 Julien Malka
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Writes Hermes/Settings/Acknowledgements.json, what the app's Acknowledgements
screen lists: the components the app is built with, each with its copyright and
the licence it is used under, whose text the app reads from LICENSES/. The Rust
crates come from Cargo's metadata for the iOS library; the others are listed
here. Run it after a dependency changes:

    nix shell nixpkgs#rustup -c python3 tools/acknowledgements.py
"""

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "Hermes" / "Settings" / "Acknowledgements.json"
LICENCES = {"MIT", "Zlib"}

OTHERS = [
    {"name": "SwiftDraw", "url": "https://github.com/swhitty/SwiftDraw", "copyright": "Copyright (c) 2019 Simon Whitty", "license": "Zlib"},
    {"name": "DiceBear", "url": "https://www.dicebear.com", "copyright": "Copyright (c) Florian Körner", "license": "MIT"},
    {"name": "Avataaars", "url": "https://avataaars.com", "copyright": "Pablo Stanley", "license": "LicenseRef-Avataaars"},
]


def chosen(expression: str) -> str:
    """The licence a crate is used under: MIT where it is offered, else its only one."""
    options = {part.strip() for part in expression.replace("/", " OR ").split(" OR ")}
    for licence in ("MIT", "Zlib"):
        if licence in options:
            return licence
    raise SystemExit(f"no licence the app can use in {expression!r}")


def crates() -> list[dict]:
    metadata = json.loads(subprocess.run(
        ["cargo", "+stable", "metadata", "--format-version", "1", "--filter-platform", "aarch64-apple-ios"],
        cwd=ROOT / "native", capture_output=True, text=True, check=True).stdout)
    packages = {package["id"]: package for package in metadata["packages"]}
    nodes = {node["id"]: node for node in metadata["resolve"]["nodes"]}
    root = next(package["id"] for package in metadata["packages"] if package["name"] == "dedala-native")
    seen, stack = set(), [root]
    while stack:
        for dependency in nodes[stack.pop()]["deps"]:
            normal = any(kind["kind"] is None for kind in dependency["dep_kinds"])
            if normal and dependency["pkg"] not in seen:
                seen.add(dependency["pkg"])
                stack.append(dependency["pkg"])
    found = {}
    for identifier in seen:
        package = packages[identifier]
        authors = ", ".join(author.split(" <")[0] for author in package.get("authors") or []) or f"the {package['name']} authors"
        found[package["name"]] = {"name": package["name"], "url": package.get("repository") or f"https://crates.io/crates/{package['name']}",
                                  "copyright": f"Copyright (c) {authors}", "license": chosen(package.get("license") or "")}
    return sorted(found.values(), key=lambda entry: entry["name"].lower())


def main() -> None:
    entries = sorted(OTHERS + crates(), key=lambda entry: entry["name"].lower())
    OUT.write_text(json.dumps(entries, indent=1, ensure_ascii=False) + "\n")
    print(f"{OUT.relative_to(ROOT)}: {len(entries)} components")


if __name__ == "__main__":
    main()
