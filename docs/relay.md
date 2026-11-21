<!-- SPDX-FileCopyrightText: 2026 Julien Malka -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->

# Relay

How the app and a Hermes agent reach each other once the USB cable is gone. The
relay runs at `relay.dedala.app`. It carries [protocol](protocol.md)
ops and events between the plugin and the app, holds them for a device that is
offline, and sends pushes with the app's APNs key. It cannot read any of it.

```
Hermes + plugin ──WebSocket──▶  relay  ◀──WebSocket── app (while open)
                                  │
                                  └──APNs──▶ phone (app closed: notifications,
                                             Live Activities)
```

Both sides connect out. The Hermes machine opens no port and needs no domain.

## Decisions

| | |
|---|---|
| Encryption | End to end from v1. The relay sees ciphertext, sizes and timing |
| Pairing | `hermes dedala pair` prints a QR code where Hermes runs: the app is for people who run their own Hermes and have a shell on it |
| Access | Agents register with an invite token issued on the relay's host |
| Devices | One per agent for now, to keep the scope small. Pairing a new device revokes the previous one |
| History | Hermes keeps its own history and memory; the plugin keeps the app's conversations as the phone drew them, in `dedala/conversations.jsonl` (every `say`, `patch`, `receipt` and `topic` sent, what you wrote, answered and loved). The first pairing makes the app Hermes's home channel and starts a new session; a phone paired again gets the conversations back (`history` ops) and the session goes on |
| Artifacts | On pairing, the plugin sends how you arranged the app on the last phone (`arrangement`: the bar, tab names, page settings), then the assets, components and scripts, stores, pages, the vault, kinds and items, then the conversations, so a reinstalled phone gets everything back. The Live Activities that were running start again from where their stores are; the phone ends the ones a previous pairing left, which nothing could update |
| Notifications | Full text, decrypted on the phone by a notification service extension |
| Retention | Undelivered messages are kept 7 days |

## Accounts

- **Invite.** On the relay's host, `hermes-relay invite` prints a one-use token.
- **Agent.** Registered once with `POST /agents {invite}`, which answers its
  `agent_id` and `agent_token`; the token goes in the plugin's config
  (`platforms.app.extra.token`). The plugin generates a long-lived X25519 key
  pair itself, on its first start.
- **Device.** Created by pairing. It gets its own `device_token`.

Every later request carries its bearer token. The relay stores tokens hashed.

## Pairing

1. `hermes dedala pair` asks the relay for a pairing slot
   (`POST /pairings`, as the agent) and gets `pairing_id`.
2. The plugin draws a random `claim` (checked by the relay) and a random `proof`
   (known only to the plugin), registers `sha256(claim)` with the slot, and
   prints a QR code:
   ```json
   {"v": 1, "relay": "https://relay.dedala.app", "pairing": "<pairing_id>",
    "claim": "<claim>", "proof": "<proof>", "agent_key": "<agent X25519 public key>",
    "name": "Ada"}
   ```
   The slot expires after 10 minutes.
3. The app scans it, generates its own X25519 key pair (kept in a keychain group
   the extensions share), and sends `POST /pairings/<id>/claim`:
   `{claim, device_key, mac: HMAC-SHA256(proof, device_key), name, apns}`
   where `apns` is `{environment, token, start_token}`.
4. The relay checks `claim`, revokes any previous device, creates the device,
   and hands `{device_key, mac, name}` to the plugin.
5. The plugin checks `mac` with `proof`. The relay never saw `proof`, so it
   cannot substitute its own key. The plugin then sends how you arranged the
   app, the agent's artifacts (`define`, every `page` with its
   `store`, the activity designs and every `vault` item with its versions) and
   the conversations, starts the Live Activities that were running, and, the
   first time, tells Hermes that the app is now the home channel and starts a
   new session. The plugin keeps the artifacts as it sends them, which is also
   its copy of the vault.

## Encryption

Both sides derive the same keys from their X25519 pair and the other's public
key:

```
shared  = X25519(own private, other public)
to_app  = HKDF-SHA256(shared, salt = pairing_id, info = "hermes-app v1 to-app")
to_agent = HKDF-SHA256(shared, salt = pairing_id, info = "hermes-app v1 to-agent")
```

A message is a JSON array of ops (to the app) or events (to the agent), sealed
with ChaCha20-Poly1305 under the key for its direction, a random 12-byte nonce,
and its sequence number, written in decimal ASCII, as associated data:

```json
{"seq": 41, "nonce": "<base64>", "box": "<base64 ciphertext+tag>"}
```

Public keys are the raw 32 bytes in standard base64. The salt is the pairing id
in UTF-8. The pairing `mac` is `base64(HMAC-SHA256(key: proof, message:
device_key))`, both as UTF-8 strings; `claim_hash` is the hex SHA-256 of
`claim`. Each sender numbers its own messages from 1. The reference is
`relay/hermes_relay/seal.py`.

No forward secrecy in v1. Pairing again gives the device a new key, and so
new keys for both directions; the agent's own key stays.

## Mailbox

Two queues per pairing, one each way, ordered by `seq`. A side sends a message
and the relay stores it until the other side acknowledges it; acknowledging a
`seq` deletes it and everything before it. Delivery is at least once. A sender
keeps a message until the relay says it holds it, and sends the next only then;
what waited is delivered before anything live. The app drops a `seq` at or
below the last it applied. The phone has three senders (the app and two
extensions) sharing one numbering, so one message can overtake another: the
plugin remembers the numbers skipped and hears a late one once.
Messages older than 7 days are dropped; a message is at most 512KB, and a
queue over 50MB refuses new messages until it drains.

| | |
|---|---|
| `GET /ws` (WebSocket, agent or device token) | live delivery both ways. A side sends `{"send": message}` (answered `{"stored": seq}`, or `{"error", "seq"}` when refused) and `{"ack": seq}`; the relay sends `{"message": …}` (everything waiting, on connect, then `{"caught_up": true}`, then each as it arrives), `{"app": "online"|"offline"}` to the agent (online once what waited for the app has gone out) and `{"agent": "online"|"offline"}` to the app, `{"paired": {pairing, device}}` to the agent, and `{"replaced": true}` to a device another pairing replaced |
| `GET /mailbox?after=<seq>` | what is waiting, for a device woken without a WebSocket |
| `POST /mailbox` | send without a WebSocket |
| `POST /mailbox/ack {seq}` | |

The plugin keeps its WebSocket open as long as Hermes runs. The app opens its
WebSocket while it is in the foreground and drains the mailbox when it opens.

## Blobs

What is too big for a message travels as a sealed blob: the captures of cards and what you share
(app to agent) and vault files (agent to app, in chunks of 1MB). A side sends `POST /blobs` with a box (`seal_bytes`, sequence 0, under
the key for its direction) and puts `{"blob": id, "type"}` where the file would
go; the other side fetches `GET /blobs/<id>`, opens it, and deletes it. A blob
is at most 2MB, an agent's blobs at most 50MB, and they go after 7 days. A side
whose upload failed half-way takes back everything it stored with `DELETE
/blobs` (`{"cleared": n}`), so what nothing names does not fill the store.

## Push

The plugin asks; the relay signs with the APNs key and sends.

| Request (agent token) | Push |
|---|---|
| `POST /push/notify {box, collapse, ring, silent}` | an alert with `mutable-content` carrying the sealed message as `sealed`; `ring` marks one the app shows even while open (a `notify` op); `silent` sends a background push instead (`content-available`, `wake: true`, no alert): the app fetches its mailbox and redraws its widgets. The notification service extension opens it, shows the agent's text and draws its card; nothing is applied or acknowledged there, the app does that when it opens. Without `box`, the alert says only that there is something new (`wake: true`): the plugin sends that when the message is too big for a notification, and the extension reads the mailbox itself |
| `POST /channels` / `DELETE /channels/<id>` | creates or deletes a broadcast channel; 20 per agent, all freed when another phone is paired |
| `POST /push/activity/start {id, design, data, alert, channel}` | push-to-start to the device's start token; `design` and `data` are sealed boxes as strings |
| `POST /push/activity/broadcast {channel, data, alert, event}` | an update or the end (`event: "end"`), on the channel |

Live Activities are sealed too: `attributes.design` is the raw-deflated design
and `content-state.data` the activity's data, each sealed with sequence 0 under
the key to the app and written as a JSON string (`seal_design` and
`seal_state` in `seal.py`). The process that draws them cannot reach the
keychain, so the app keeps that one key in its app group for it. The alert that lights the screen (`alert.title`, `alert.body`) is
shown by iOS itself, so it cannot be sealed: the plugin sends a generic line
unless the agent marks the text as fine to show.

The app tells the relay when its tokens change (`POST /device/apns`). The relay
drops a token APNs reports as gone.

## The relay itself

- Python: aiohttp for HTTP and WebSockets, SQLite for accounts and queues,
  HTTP/2 to APNs.
- `relay/` in this repository, packaged with Nix; deployed behind nginx with
  WebSocket upgrade, as a systemd service, the APNs key as a secret file.
- Logs say who talked to whom, when, and how much, never what.
- `GET /health` for monitoring; `hermes-relay invite`, `hermes-relay agents`,
  `hermes-relay revoke` on the relay's host.

## Not in v1

Several devices per agent, forward secrecy, opening the relay without invites.
