# SPDX-FileCopyrightText: 2026 Julien Malka
# SPDX-License-Identifier: MIT

import sys
from pathlib import Path

import aiohttp
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "relay"))

from hermes_relay.server import create_app  # noqa: E402
from hermes_relay.store import Store  # noqa: E402


@pytest.fixture
async def relay(aiohttp_server, tmp_path):
    store = Store(str(tmp_path / "relay.sqlite"))
    server = await aiohttp_server(create_app(store, None))
    url = str(server.make_url("")).rstrip("/")
    async with aiohttp.ClientSession() as http:
        async with http.post(f"{url}/agents", json={"invite": store.invite(), "name": "Jacques"}) as response:
            token = (await response.json())["agent_token"]
    return url, token
