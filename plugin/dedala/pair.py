# SPDX-FileCopyrightText: 2026 Julien Malka
# SPDX-License-Identifier: MIT

"""`python -m dedala.pair`: pairs the app without going through the hermes
CLI, for machines where the plugin's `hermes dedala` command is not loaded."""

import argparse
import sys

from .hermes.plugin import _pair, _pair_setup


def main() -> int:
    parser = argparse.ArgumentParser(prog="dedala-pair")
    _pair_setup(parser)
    return _pair(parser.parse_args(["pair", *sys.argv[1:]]))


if __name__ == "__main__":
    sys.exit(main())
