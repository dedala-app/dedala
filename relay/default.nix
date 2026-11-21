# SPDX-FileCopyrightText: 2026 Julien Malka
# SPDX-License-Identifier: AGPL-3.0-or-later

{
  buildPythonApplication,
  setuptools,
  aiohttp,
  cryptography,
  httpx,
  h2,
  pytestCheckHook,
  pytest-aiohttp,
  pytest-asyncio,
}:

buildPythonApplication {
  pname = "hermes-relay";
  version = "0.1.0";
  pyproject = true;
  src = ./.;
  build-system = [ setuptools ];
  dependencies = [ aiohttp cryptography httpx h2 ];
  nativeCheckInputs = [ pytestCheckHook pytest-aiohttp pytest-asyncio ];
}
