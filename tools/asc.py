# SPDX-FileCopyrightText: 2026 Julien Malka
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Reads App Store Connect: the builds, the purchases, the testers.

    asc.py <path>      GET https://api.appstoreconnect.apple.com/<path>, prints the JSON
    asc.py next-build  the build number after the highest one uploaded for app.dedala

The key lives in ~/.config/hermes/asc/AuthKey_<id>.p8; a team key also needs
its issuer id in ~/.config/hermes/asc/issuer, an individual key does not.
"""

import glob
import json
import os
import sys
import time
import urllib.error
import urllib.request

from apns import b64, raw_signature

import subprocess

HOME = os.path.expanduser("~/.config/hermes/asc")


def token():
    key = sorted(glob.glob(f"{HOME}/AuthKey_*.p8"))[-1]
    key_id = os.path.basename(key)[len("AuthKey_") : -len(".p8")]
    now = int(time.time())
    claims = {"iat": now, "exp": now + 15 * 60, "aud": "appstoreconnect-v1"}
    try:
        with open(f"{HOME}/issuer") as f:
            claims["iss"] = f.read().strip()
    except OSError:
        claims["sub"] = "user"
    header = b64(json.dumps({"alg": "ES256", "kid": key_id, "typ": "JWT"}).encode())
    body = b64(json.dumps(claims).encode())
    signing = f"{header}.{body}".encode()
    der = subprocess.run(["openssl", "dgst", "-sha256", "-sign", key], input=signing, capture_output=True, check=True).stdout
    return f"{header}.{body}.{b64(raw_signature(der))}"


def get(path):
    request = urllib.request.Request(f"https://api.appstoreconnect.apple.com/{path.lstrip('/')}",
                                     headers={"Authorization": f"Bearer {token()}"})
    try:
        with urllib.request.urlopen(request) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        return {"status": error.code, "error": json.loads(error.read() or b"{}")}


def next_build():
    app = get("v1/apps?filter[bundleId]=app.dedala")["data"][0]["id"]
    builds = get(f"v1/builds?filter[app]={app}&fields[builds]=version&limit=200")["data"]
    return max((int(build["attributes"]["version"]) for build in builds), default=0) + 1


if __name__ == "__main__":
    if sys.argv[1] == "next-build":
        print(next_build())
    else:
        print(json.dumps(get(sys.argv[1]), indent=2))
