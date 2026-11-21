# SPDX-FileCopyrightText: 2026 Julien Malka
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Talks to APNs with the app's key: alerts, Live Activity starts, broadcasts on
channels, and managing those channels. Development builds of the app live in
APNs' sandbox, store builds in production; each device says which."""

import base64
import json
import time
from dataclasses import dataclass

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

HOSTS = {"development": "https://api.sandbox.push.apple.com", "production": "https://api.push.apple.com"}
CHANNEL_HOSTS = {
    "development": "https://api-manage-broadcast.sandbox.push.apple.com:2195",
    "production": "https://api-manage-broadcast.push.apple.com:2196",
}


@dataclass
class Result:
    status: int
    reason: str = ""
    channel: str | None = None

    @property
    def ok(self) -> bool:
        return self.status in (200, 201)

    @property
    def gone(self) -> bool:
        return self.status == 410 or self.reason in ("BadDeviceToken", "Unregistered")


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


class APNs:
    def __init__(self, key_path: str, key_id: str, team: str, bundle: str):
        with open(key_path, "rb") as f:
            self.key = serialization.load_pem_private_key(f.read(), password=None)
        self.key_id, self.team, self.bundle = key_id, team, bundle
        self.client = httpx.AsyncClient(http2=True, timeout=15)
        self._jwt: tuple[float, str] | None = None

    def jwt(self) -> str:
        if self._jwt and time.time() - self._jwt[0] < 50 * 60:
            return self._jwt[1]
        issued = time.time()
        header = b64(json.dumps({"alg": "ES256", "kid": self.key_id}).encode())
        claims = b64(json.dumps({"iss": self.team, "iat": int(issued)}).encode())
        r, s = decode_dss_signature(self.key.sign(f"{header}.{claims}".encode(), ec.ECDSA(hashes.SHA256())))
        signed = f"{header}.{claims}.{b64(r.to_bytes(32, 'big') + s.to_bytes(32, 'big'))}"
        self._jwt = (issued, signed)
        return signed

    async def _post(self, url: str, headers: dict, payload: dict) -> Result:
        headers = {"authorization": f"bearer {self.jwt()}", **{k: str(v) for k, v in headers.items()}}
        response = await self.client.post(url, headers=headers, content=json.dumps(payload, separators=(",", ":")))
        reason = ""
        if response.content:
            try:
                reason = response.json().get("reason", "")
            except ValueError:
                reason = response.text[:200]
        return Result(response.status_code, reason, response.headers.get("apns-channel-id"))

    async def alert(self, environment: str, device: str, payload: dict, collapse: str | None = None, silent: bool = False) -> Result:
        headers = {"apns-topic": self.bundle, "apns-push-type": "background" if silent else "alert", "apns-priority": 5 if silent else 10}
        if collapse:
            headers["apns-collapse-id"] = collapse
        return await self._post(f"{HOSTS[environment]}/3/device/{device}", headers, payload)

    async def activity(self, environment: str, device: str, payload: dict) -> Result:
        headers = {"apns-topic": f"{self.bundle}.push-type.liveactivity", "apns-push-type": "liveactivity", "apns-priority": 10}
        return await self._post(f"{HOSTS[environment]}/3/device/{device}", headers, payload)

    async def broadcast(self, environment: str, channel: str, payload: dict) -> Result:
        headers = {
            "apns-channel-id": channel,
            "apns-push-type": "liveactivity",
            "apns-priority": 10,
            "apns-expiration": int(time.time()) + 3600,
        }
        return await self._post(f"{HOSTS[environment]}/4/broadcasts/apps/{self.bundle}", headers, payload)

    async def create_channel(self, environment: str) -> Result:
        return await self._post(
            f"{CHANNEL_HOSTS[environment]}/1/apps/{self.bundle}/channels",
            {},
            {"message-storage-policy": 1, "push-type": "LiveActivity"},
        )

    async def delete_channel(self, environment: str, channel: str) -> Result:
        headers = {"authorization": f"bearer {self.jwt()}", "apns-channel-id": channel}
        response = await self.client.delete(f"{CHANNEL_HOSTS[environment]}/1/apps/{self.bundle}/channels", headers=headers)
        return Result(response.status_code)

    async def close(self) -> None:
        await self.client.aclose()
