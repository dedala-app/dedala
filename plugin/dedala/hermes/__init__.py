# SPDX-FileCopyrightText: 2026 Julien Malka
# SPDX-License-Identifier: MIT

"""Hermes, as far as the plugin goes: the only part of it that knows the agent
it runs in. `plugin` is what Hermes loads, `adapter` the app as one of its
platforms, `agent` Hermes as the app's server sees it (`agents.Agent`),
`vocabulary` its tools in words, `internals` what is taken from Hermes beyond
its plugin API."""
