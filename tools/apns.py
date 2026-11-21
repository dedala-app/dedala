# SPDX-FileCopyrightText: 2026 Julien Malka
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Sends pushes straight to APNs while Hermes is mocked; the relay takes this
place once the plugin talks to a real Hermes, with the same messages.

    apns.py channel                       creates a broadcast channel, prints its id
    apns.py start <start-token> < {"id", "design", "channel", "data", "alert"}
    apns.py broadcast <channel> < {"event": "update"|"end", "data", "alert"}
    apns.py activity <token> < {"event": "update"|"end", "data", "alert"}
    apns.py alert <token> < {"title", "body"}
"""

import base64
import json
import os
import subprocess
import sys
import time
import zlib

TEAM = "KHZGP69E97"
KEY_ID = os.environ.get("APNS_KEY_ID", "")
KEY = os.path.expanduser(f"~/.config/hermes/AuthKey_{KEY_ID}.p8")
BUNDLE = "app.dedala"
HOST = os.environ.get("APNS_HOST", "api.sandbox.push.apple.com")
CHANNELS = os.environ.get("APNS_CHANNELS", "api-manage-broadcast.sandbox.push.apple.com:2195")
CACHE = os.path.expanduser("~/.cache/hermes/apns-jwt.json")


def b64(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def raw_signature(der):
    def integer(at):
        length = der[at + 1]
        value = der[at + 2 : at + 2 + length].lstrip(b"\0").rjust(32, b"\0")
        return value, at + 2 + length

    r, after = integer(2)
    s, _ = integer(after)
    return r + s


def jwt():
    try:
        with open(CACHE) as f:
            cached = json.load(f)
        if time.time() - cached["iat"] < 50 * 60:
            return cached["jwt"]
    except (OSError, ValueError, KeyError):
        pass
    iat = int(time.time())
    header = b64(json.dumps({"alg": "ES256", "kid": KEY_ID}).encode())
    claims = b64(json.dumps({"iss": TEAM, "iat": iat}).encode())
    signing = f"{header}.{claims}".encode()
    der = subprocess.run(["openssl", "dgst", "-sha256", "-sign", KEY], input=signing, capture_output=True, check=True).stdout
    token = f"{header}.{claims}.{b64(raw_signature(der))}"
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    with open(CACHE, "w") as f:
        json.dump({"iat": iat, "jwt": token}, f)
    return token


def request(url, headers, payload):
    command = ["curl", "-sS", "--http2", "-D", "-", "-o", "-", "-w", "\n%{http_code}", "-H", f"authorization: bearer {jwt()}"]
    for name, value in headers.items():
        command += ["-H", f"{name}: {value}"]
    command += ["--data-binary", "@-", url]
    result = subprocess.run(command, input=json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode(), capture_output=True)
    text, _, status = result.stdout.decode().rpartition("\n")
    head, _, body = text.partition("\r\n\r\n")
    found = {line.split(":", 1)[0].lower(): line.split(":", 1)[1].strip() for line in head.splitlines()[1:] if ":" in line}
    return status, found, body or result.stderr.decode()


def send(device, payload, push_type, topic, priority=10):
    status, _, body = request(f"https://{HOST}/3/device/{device}", {"apns-topic": topic, "apns-push-type": push_type, "apns-priority": priority}, payload)
    return status, body


def aps(message, event):
    payload = {
        "timestamp": int(time.time()),
        "event": event,
        "content-state": {"data": json.dumps(message.get("data", {}), separators=(",", ":"), ensure_ascii=False)},
    }
    if event == "end":
        payload["dismissal-date"] = int(time.time()) + 15 * 60
    if message.get("alert"):
        payload["alert"] = {"title": message["alert"].get("title", ""), "body": message["alert"].get("body", ""), "sound": "default"}
    return payload


def activity(device, message):
    return send(device, {"aps": aps(message, message.get("event", "update"))}, "liveactivity", f"{BUNDLE}.push-type.liveactivity")


def start(device, message):
    payload = aps(message, "start")
    payload["attributes-type"] = "HermesActivityAttributes"
    payload["attributes"] = {"id": message["id"]}
    if message.get("design"):
        packed = zlib.compressobj(9, zlib.DEFLATED, -15)
        raw = json.dumps(message["design"], separators=(",", ":"), ensure_ascii=False).encode()
        payload["attributes"]["design"] = base64.b64encode(packed.compress(raw) + packed.flush()).decode()
    payload.setdefault("alert", {"title": "", "body": "", "sound": "default"})
    if message.get("channel"):
        payload["input-push-channel"] = message["channel"]
    else:
        payload["input-push-token"] = 1
    return send(device, {"aps": payload}, "liveactivity", f"{BUNDLE}.push-type.liveactivity")


def broadcast(channel, message):
    headers = {"apns-channel-id": channel, "apns-push-type": "liveactivity", "apns-priority": 10, "apns-expiration": int(time.time()) + 3600}
    status, _, body = request(f"https://{HOST}/4/broadcasts/apps/{BUNDLE}", headers, {"aps": aps(message, message.get("event", "update"))})
    return status, body


def channel():
    status, headers, body = request(f"https://{CHANNELS}/1/apps/{BUNDLE}/channels", {}, {"message-storage-policy": 1, "push-type": "LiveActivity"})
    return status, headers.get("apns-channel-id") or body


def alert(device, message):
    aps = {"alert": {"title": message.get("title", ""), "body": message.get("body", "")}, "sound": "default"}
    return send(device, {"aps": aps}, "alert", BUNDLE)


if __name__ == "__main__":
    kind = sys.argv[1]
    if kind == "channel":
        status, body = channel()
    else:
        status, body = {"activity": activity, "start": start, "broadcast": broadcast, "alert": alert}[kind](sys.argv[2], json.load(sys.stdin))
    print(status, body.strip())
    sys.exit(0 if status in ("200", "201") else 1)
