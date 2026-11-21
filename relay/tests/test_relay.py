# SPDX-FileCopyrightText: 2026 Julien Malka
# SPDX-License-Identifier: AGPL-3.0-or-later

import secrets

import pytest
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

from hermes_relay import seal
from hermes_relay.apns import Result
from hermes_relay.server import create_app
from hermes_relay.store import Store


class FakeAPNs:
    def __init__(self):
        self.sent = []
        self.answer = Result(200)

    async def alert(self, environment, device, payload, collapse=None, silent=False):
        self.sent.append(("background" if silent else "alert", environment, device, payload))
        return self.answer

    async def activity(self, environment, device, payload):
        self.sent.append(("activity", environment, device, payload))
        return self.answer

    async def broadcast(self, environment, channel, payload):
        self.sent.append(("broadcast", environment, channel, payload))
        return self.answer

    async def create_channel(self, environment):
        return Result(201, channel=f"channel-{len(self.sent)}")

    async def delete_channel(self, environment, channel):
        self.sent.append(("delete_channel", environment, channel, None))
        return Result(200)

    async def close(self):
        pass


@pytest.fixture
def store(tmp_path):
    return Store(str(tmp_path / "relay.sqlite"))


@pytest.fixture
def apns():
    return FakeAPNs()


@pytest.fixture
async def client(aiohttp_client, store, apns):
    return await aiohttp_client(create_app(store, apns))


def auth(token):
    return {"Authorization": f"Bearer {token}"}


async def agent(client, store, name="Jacques"):
    response = await client.post("/agents", json={"invite": store.invite(), "name": name})
    assert response.status == 201
    return (await response.json())["agent_token"]


async def pair(client, agent_token, apns=None):
    """Runs the whole pairing as the plugin and the app would, and returns both sides' keys."""
    agent_key, device_key = X25519PrivateKey.generate(), X25519PrivateKey.generate()
    claim, proof = secrets.token_urlsafe(16), secrets.token_urlsafe(16)
    opened = await (await client.post("/pairings", json={"claim_hash": seal.claim_hash(claim)}, headers=auth(agent_token))).json()
    pairing = opened["pairing"]
    claimed = await client.post(f"/pairings/{pairing}/claim", json={
        "claim": claim, "device_key": seal.public(device_key), "mac": seal.proof_mac(proof, seal.public(device_key)),
        "name": "iPhone", "apns": apns or {"environment": "development", "token": "device-token", "start_token": "start-token"},
    })
    assert claimed.status == 201
    device_token = (await claimed.json())["device_token"]
    status = await (await client.get(f"/pairings/{pairing}", headers=auth(agent_token))).json()
    assert status["status"] == "paired"
    assert status["device"]["mac"] == seal.proof_mac(proof, status["device"]["key"])
    agent_side = seal.keys(agent_key, status["device"]["key"], pairing)
    device_side = seal.keys(device_key, seal.public(agent_key), pairing)
    assert agent_side == device_side
    return device_token, agent_side, pairing, claim


async def test_invites_are_used_once(client, store):
    invite = store.invite()
    assert (await client.post("/agents", json={"invite": invite})).status == 201
    assert (await client.post("/agents", json={"invite": invite})).status == 403
    assert (await client.post("/agents", json={"invite": "made-up"})).status == 403


async def test_pairing_checks_the_claim_and_runs_once(client, store):
    token = await agent(client, store)
    claim = "the-claim"
    pairing = (await (await client.post("/pairings", json={"claim_hash": seal.claim_hash(claim)}, headers=auth(token))).json())["pairing"]
    attempt = {"claim": "wrong", "device_key": "k", "mac": "m", "apns": {"environment": "development"}}
    assert (await client.post(f"/pairings/{pairing}/claim", json=attempt)).status == 403
    attempt["claim"] = claim
    assert (await client.post(f"/pairings/{pairing}/claim", json=attempt)).status == 201
    assert (await client.post(f"/pairings/{pairing}/claim", json=attempt)).status == 410


async def test_an_expired_pairing_is_refused(client, store):
    token = await agent(client, store)
    pairing = (await (await client.post("/pairings", json={"claim_hash": seal.claim_hash("c")}, headers=auth(token))).json())["pairing"]
    store.db.execute("update pairings set expires = 0")
    attempt = {"claim": "c", "device_key": "k", "mac": "m"}
    assert (await client.post(f"/pairings/{pairing}/claim", json=attempt)).status == 410


async def test_sealed_ops_reach_the_device_and_only_it_can_read_them(client, store):
    token = await agent(client, store)
    device_token, (to_app, to_agent), _, _ = await pair(client, token)
    ops = [{"op": "say", "text": "Hello from Jacques"}]
    assert (await client.post("/mailbox", json=seal.seal(to_app, 1, ops), headers=auth(token))).status == 200
    stored = store.db.execute("select body from messages").fetchone()["body"]
    assert "Hello" not in stored
    waiting = (await (await client.get("/mailbox", headers=auth(device_token))).json())["messages"]
    assert [seal.unseal(to_app, m) for m in waiting] == [ops]
    with pytest.raises(Exception):
        seal.unseal(to_agent, waiting[0])
    await client.post("/mailbox/ack", json={"seq": 1}, headers=auth(device_token))
    assert (await (await client.get("/mailbox", headers=auth(device_token))).json())["messages"] == []


async def test_a_message_is_bound_to_its_sequence_number(client, store):
    token = await agent(client, store)
    _, (to_app, _), _, _ = await pair(client, token)
    message = seal.seal(to_app, 7, ["op"])
    message["seq"] = 8
    with pytest.raises(Exception):
        seal.unseal(to_app, message)


async def test_websockets_carry_both_ways_and_deliver_what_waited(client, store):
    token = await agent(client, store)
    device_token, (to_app, to_agent), _, _ = await pair(client, token)
    await client.post("/mailbox", json=seal.seal(to_app, 1, ["waited"]), headers=auth(token))
    app = await client.ws_connect("/ws", headers=auth(device_token))
    assert await app.receive_json() == {"agent": "offline"}
    assert seal.unseal(to_app, (await app.receive_json())["message"]) == ["waited"]
    assert await app.receive_json() == {"caught_up": True}
    await app.send_json({"ack": 1})
    plugin = await client.ws_connect("/ws", headers=auth(token))
    assert await app.receive_json() == {"agent": "online"}
    assert await plugin.receive_json() == {"caught_up": True}
    assert await plugin.receive_json() == {"app": "online"}
    await plugin.send_json({"send": seal.seal(to_app, 2, ["live"])})
    assert await plugin.receive_json() == {"stored": 2}
    assert seal.unseal(to_app, (await app.receive_json())["message"]) == ["live"]
    await app.send_json({"send": seal.seal(to_agent, 1, [{"kind": "message", "text": "Hi"}])})
    assert await app.receive_json() == {"stored": 1}
    assert seal.unseal(to_agent, (await plugin.receive_json())["message"]) == [{"kind": "message", "text": "Hi"}]
    await app.close()
    await plugin.close()


async def test_the_plugin_hears_about_pairing_live(client, store):
    token = await agent(client, store)
    plugin = await client.ws_connect("/ws", headers=auth(token))
    assert await plugin.receive_json() == {"caught_up": True}
    await pair(client, token)
    frame = await plugin.receive_json()
    assert frame["paired"]["device"]["name"] == "iPhone"
    await plugin.close()


async def test_pairing_again_replaces_the_device(client, store):
    token = await agent(client, store)
    old_token, (to_app, _), _, _ = await pair(client, token)
    await client.post("/mailbox", json=seal.seal(to_app, 1, ["for the old phone"]), headers=auth(token))
    new_token, _, _, _ = await pair(client, token)
    assert (await client.get("/mailbox", headers=auth(old_token))).status == 401
    assert (await (await client.get("/mailbox", headers=auth(new_token))).json())["messages"] == []


async def test_the_device_cannot_act_as_the_agent(client, store):
    token = await agent(client, store)
    device_token, _, _, _ = await pair(client, token)
    assert (await client.post("/push/notify", json={}, headers=auth(device_token))).status == 403
    assert (await client.post("/pairings", json={"claim_hash": "0" * 64}, headers=auth(device_token))).status == 403
    assert (await client.get("/mailbox", headers=auth("nobody"))).status == 401


async def test_notifications_carry_the_sealed_message(client, store, apns):
    token = await agent(client, store)
    device_token, (to_app, _), _, _ = await pair(client, token)
    sealed = seal.seal(to_app, 1, {"text": "Marta agreed to two months"})
    assert (await client.post("/push/notify", json={"box": sealed}, headers=auth(token))).status == 200
    kind, environment, device, payload = apns.sent[-1]
    assert (kind, environment, device) == ("alert", "development", "device-token")
    assert payload["aps"]["mutable-content"] == 1
    assert "Marta" not in str(payload["aps"])
    assert seal.unseal(to_app, payload["sealed"]) == {"text": "Marta agreed to two months"}
    assert (await client.post("/push/notify", json={"box": sealed, "ring": True}, headers=auth(token))).status == 200
    assert apns.sent[-1][3]["ring"] is True and apns.sent[-1][0] == "alert"
    assert (await client.post("/push/notify", json={"silent": True}, headers=auth(token))).status == 200
    kind, _, _, payload = apns.sent[-1]
    assert kind == "background" and payload == {"aps": {"content-available": 1}, "wake": True}


async def test_live_activities_start_on_a_channel_and_broadcast(client, store, apns):
    token = await agent(client, store)
    await pair(client, token)
    channel = (await (await client.post("/channels", headers=auth(token))).json())["channel"]
    started = await client.post("/push/activity/start", json={"id": "ol-live", "design": "sealed-design", "data": "sealed-data", "channel": channel}, headers=auth(token))
    assert started.status == 200
    kind, _, device, payload = apns.sent[-1]
    assert (kind, device) == ("activity", "start-token")
    assert payload["aps"]["input-push-channel"] == channel
    assert payload["aps"]["attributes"] == {"id": "ol-live", "design": "sealed-design"}
    assert payload["aps"]["alert"]["title"] == "Jacques"
    ended = await client.post("/push/activity/broadcast", json={"channel": channel, "data": "sealed-end", "event": "end"}, headers=auth(token))
    assert ended.status == 200
    assert apns.sent[-1][3]["aps"]["event"] == "end"
    assert (await client.delete(f"/channels/{channel}", headers=auth(token))).status == 200
    assert (await client.post("/push/activity/broadcast", json={"channel": channel, "data": "x"}, headers=auth(token))).status == 404


async def test_a_token_apns_rejects_is_forgotten(client, store, apns):
    token = await agent(client, store)
    await pair(client, token)
    apns.answer = Result(410, "Unregistered")
    assert (await client.post("/push/notify", json={}, headers=auth(token))).status == 502
    device = await (await client.get("/device", headers=auth(token))).json()
    assert device["notifications"] is False


async def test_old_messages_are_swept(client, store):
    token = await agent(client, store)
    _, (to_app, _), _, _ = await pair(client, token)
    await client.post("/mailbox", json=seal.seal(to_app, 1, ["old"]), headers=auth(token))
    store.db.execute("update messages set created = 0")
    assert store.sweep() == 1


async def test_captures_travel_sealed_as_blobs(client, store):
    token = await agent(client, store)
    device_token, (_, to_agent), _, _ = await pair(client, token)
    image = bytes(range(256)) * 400
    sealed = seal.seal_bytes(to_agent, 0, image)
    stored = await client.post("/blobs", json=sealed, headers=auth(device_token))
    assert stored.status == 201
    blob = (await stored.json())["blob"]
    assert b"\x00\x01\x02" not in store.db.execute("select body from blobs").fetchone()["body"]
    other = await agent(client, store, "Someone else")
    assert (await client.get(f"/blobs/{blob}", headers=auth(other))).status == 404
    fetched = await client.get(f"/blobs/{blob}", headers=auth(token))
    assert seal.unseal_bytes(to_agent, await fetched.json()) == image
    await client.delete(f"/blobs/{blob}", headers=auth(token))
    assert (await client.get(f"/blobs/{blob}", headers=auth(token))).status == 404


async def test_a_side_takes_back_every_blob_it_stored(client, store):
    token = await agent(client, store)
    device_token, (_, to_agent), _, _ = await pair(client, token)
    mine = [(await (await client.post("/blobs", json=seal.seal_bytes(to_agent, 0, b"agent"), headers=auth(token))).json())["blob"] for _ in range(3)]
    theirs = (await (await client.post("/blobs", json=seal.seal_bytes(to_agent, 0, b"phone"), headers=auth(device_token))).json())["blob"]
    assert (await (await client.delete("/blobs?older=3600", headers=auth(token))).json()) == {"cleared": 0}
    assert (await (await client.delete("/blobs", headers=auth(token))).json()) == {"cleared": 3}
    for blob in mine:
        assert (await client.get(f"/blobs/{blob}", headers=auth(device_token))).status == 404
    assert (await client.get(f"/blobs/{theirs}", headers=auth(token))).status == 200
    assert (await client.delete("/blobs?older=soon", headers=auth(token))).status == 400


async def test_blobs_have_a_size_limit(client, store):
    token = await agent(client, store)
    device_token, _, _, _ = await pair(client, token)
    response = await client.post("/blobs", data=b"x" * (2 * 1024 * 1024 + 1), headers=auth(device_token))
    assert response.status == 413


async def test_the_agent_knows_when_the_app_is_open(client, store):
    token = await agent(client, store)
    device_token, _, _, _ = await pair(client, token)
    plugin = await client.ws_connect("/ws", headers=auth(token))
    assert await plugin.receive_json() == {"caught_up": True}
    assert (await (await client.get("/device", headers=auth(token))).json())["online"] is False
    app = await client.ws_connect("/ws", headers=auth(device_token))
    assert await plugin.receive_json() == {"app": "online"}
    assert (await (await client.get("/device", headers=auth(token))).json())["online"] is True
    await app.close()
    assert await plugin.receive_json() == {"app": "offline"}
    await plugin.close()


async def test_the_app_hears_the_agent_only_after_what_waited(client, store):
    token = await agent(client, store)
    device_token, (to_app, _), _, _ = await pair(client, token)
    plugin = await client.ws_connect("/ws", headers=auth(token))
    assert await plugin.receive_json() == {"caught_up": True}
    for seq in (1, 2):
        await client.post("/mailbox", json=seal.seal(to_app, seq, [f"waited {seq}"]), headers=auth(token))
    app = await client.ws_connect("/ws", headers=auth(device_token))
    assert await app.receive_json() == {"agent": "online"}
    assert [seal.unseal(to_app, (await app.receive_json())["message"]) for _ in range(2)] == [["waited 1"], ["waited 2"]]
    assert await app.receive_json() == {"caught_up": True}
    assert await plugin.receive_json() == {"app": "online"}
    await plugin.close()
    assert await app.receive_json() == {"agent": "offline"}
    await app.close()


async def test_what_waited_arrives_before_anything_live(client, store, monkeypatch):
    token = await agent(client, store)
    device_token, (to_app, to_agent), _, _ = await pair(client, token)
    app = await client.ws_connect("/ws", headers=auth(device_token))
    assert await app.receive_json() == {"agent": "offline"}
    assert await app.receive_json() == {"caught_up": True}
    await client.post("/mailbox", json=seal.seal(to_agent, 1, ["typed while the agent was away"]), headers=auth(device_token))
    waiting, sent_live = store.waiting, []

    def waiting_then_live(agent_id, direction, after=-1):
        found = waiting(agent_id, direction, after)
        if direction == "to_agent" and not sent_live:
            sent_live.append(store.put(agent_id, direction, seal.seal(to_agent, 2, ["typed as it reconnected"])))
        return found

    monkeypatch.setattr(store, "waiting", waiting_then_live)
    plugin = await client.ws_connect("/ws", headers=auth(token))
    received = [seal.unseal(to_agent, (await plugin.receive_json())["message"]) for _ in range(2)]
    assert received == [["typed while the agent was away"], ["typed as it reconnected"]]
    assert await plugin.receive_json() == {"caught_up": True}
    await app.close()
    await plugin.close()


async def test_a_second_connection_replaces_the_first(client, store):
    token = await agent(client, store)
    device_token, (to_app, _), _, _ = await pair(client, token)
    first = await client.ws_connect("/ws", headers=auth(device_token))
    assert await first.receive_json() == {"agent": "offline"}
    assert await first.receive_json() == {"caught_up": True}
    second = await client.ws_connect("/ws", headers=auth(device_token))
    assert await second.receive_json() == {"agent": "offline"}
    assert await second.receive_json() == {"caught_up": True}
    await client.post("/mailbox", json=seal.seal(to_app, 1, ["live"]), headers=auth(token))
    assert seal.unseal(to_app, (await second.receive_json())["message"]) == ["live"]
    assert (await first.receive()).type.name in ("CLOSE", "CLOSING", "CLOSED")
    assert (await (await client.get("/device", headers=auth(token))).json())["online"] is True
    await second.close()


async def test_pairing_again_frees_the_old_phones_channels(client, store, apns):
    token = await agent(client, store)
    await pair(client, token)
    channel = (await (await client.post("/channels", headers=auth(token))).json())["channel"]
    await pair(client, token)
    assert ("delete_channel", "development", channel, None) in apns.sent
    assert store.channels(store.agent(token)) == []


async def test_malformed_requests_are_refused_not_crashed(client, store):
    token = await agent(client, store)
    device_token, _, _, _ = await pair(client, token)
    assert (await client.get("/mailbox?after=soon", headers=auth(device_token))).status == 400
    pairing = (await (await client.post("/pairings", json={"claim_hash": seal.claim_hash("c")}, headers=auth(token))).json())["pairing"]
    attempt = {"claim": "c", "device_key": "k", "mac": "m", "apns": "development"}
    assert (await client.post(f"/pairings/{pairing}/claim", json=attempt)).status == 400
    socket = await client.ws_connect("/ws", headers=auth(device_token))
    assert await socket.receive_json() == {"agent": "offline"}
    assert await socket.receive_json() == {"caught_up": True}
    await socket.send_str("[1, 2]")
    assert "error" in await socket.receive_json()
    await socket.send_json({"send": "not a message"})
    assert "error" in await socket.receive_json()
    await socket.close()
