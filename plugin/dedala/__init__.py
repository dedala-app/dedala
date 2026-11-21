# SPDX-FileCopyrightText: 2026 Julien Malka
# SPDX-License-Identifier: MIT

"""Dedala: the iPhone app as a home for an agent. `server` is the app's
side of it, the same whichever agent it serves; `hermes/` is Hermes's, and what
Hermes loads as a plugin (`register`). The protocol is docs/protocol.md in the
app's repository; how to draw well is the hermes-ui skill."""

from . import schemas, session  # noqa: F401
from .hermes.plugin import register  # noqa: F401
