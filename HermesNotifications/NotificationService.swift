// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import UserNotifications

/// Runs before a notification from the agent is shown: opens the sealed message
/// it carries with the device's key and shows what the agent actually said, so
/// neither Apple nor the relay ever sees it. A notification without a message
/// (`wake`) has the extension read the mailbox instead. The icon counts what
/// waits. Nothing is applied or acknowledged here; the app does that when it
/// opens.
final class NotificationService: UNNotificationServiceExtension {
    private var deliver: ((UNNotificationContent) -> Void)?
    private var content: UNMutableNotificationContent?

    override func didReceive(_ request: UNNotificationRequest, withContentHandler handler: @escaping (UNNotificationContent) -> Void) {
        let content = (request.content.mutableCopy() as? UNMutableNotificationContent) ?? UNMutableNotificationContent()
        self.content = content
        deliver = handler
        guard let pairing = PairingStore.load(), let keys = try? pairing.keys() else {
            handler(content)
            return
        }
        content.title = pairing.agentName
        let info = request.content.userInfo
        Task {
            await Self.count(request, into: content)
            if info["ring"] != nil, let sealed = info["sealed"].flatMap(Self.message) {
                ring(sealed, keys: keys, into: content)
            } else if let sealed = info["sealed"].flatMap(Self.message) {
                describe([sealed], keys: keys, into: content)
                await Self.draw(cardsIn: sealed, pairing: pairing, keys: keys, into: content)
            } else if info["wake"] != nil {
                describe(await Self.mailbox(pairing), keys: keys, into: content)
            }
            handler(content)
        }
    }

    /// The icon counts the notifications waiting, this one included; the one
    /// this replaces (same collapse identifier) is not counted twice.
    private static func count(_ request: UNNotificationRequest, into content: UNMutableNotificationContent) async {
        let delivered = await UNUserNotificationCenter.current().deliveredNotifications()
        content.badge = NSNumber(value: delivered.filter { $0.request.identifier != request.identifier }.count + 1)
    }

    override func serviceExtensionTimeWillExpire() {
        if let content { deliver?(content) }
    }

    /// A `notify` op: a line of its own, and what a tap opens, kept for the app.
    private func ring(_ message: Seal.Message, keys: Seal.Keys, into content: UNMutableNotificationContent) {
        guard let plain = try? Seal.open(message, key: keys.toApp), let ops = (try? JSONValue.parse(plain))?.array,
              let op = ops.first(where: { $0["op"]?.string == "notify" }) else { return }
        if let title = op["title"]?.string, !title.isEmpty { content.title = title }
        content.body = op["body"]?.string ?? ""
        content.threadIdentifier = "notify"
        var info = content.userInfo
        info["ring"] = true
        if let open = op["open"], open.object != nil {
            info["open"] = String(decoding: open.data(), as: UTF8.self)
        }
        if let kind = op["kind"]?.string, !kind.isEmpty {
            content.categoryIdentifier = kind
            if let actions = op["actions"], actions.object != nil {
                info["actions"] = String(decoding: actions.data(), as: UTF8.self)
            }
        }
        content.userInfo = info
    }

    /// The last thing worth saying out of the messages: what the agent wrote,
    /// or what it made.
    private func describe(_ messages: [Seal.Message], keys: Seal.Keys, into content: UNMutableNotificationContent) {
        for message in messages.reversed() {
            guard let plain = try? Seal.open(message, key: keys.toApp), let ops = (try? JSONValue.parse(plain))?.array else { continue }
            for op in ops.reversed() {
                let line: String? = switch op["op"]?.string {
                case "say": op["text"]?.string.flatMap { $0.isEmpty ? nil : $0 } ?? (op["card"] != nil ? "Sent you a card" : nil)
                case "page": "Made a page: \(op["title"]?.text ?? "")"
                default: nil
                }
                if let line {
                    content.body = line
                    content.threadIdentifier = op["conversation"]?.string ?? "main"
                    return
                }
            }
        }
    }

    /// Cards in the message are drawn here: reported, so the agent's review does
    /// not wait for the app to be opened, and shown in the notification. A draft
    /// the agent is still fixing (`quiet`) arrives without sound or banner; the
    /// final card (`settled`) rings, and is not reported again.
    private static func draw(cardsIn message: Seal.Message, pairing: Pairing, keys: Seal.Keys, into content: UNMutableNotificationContent) async {
        guard let plain = try? Seal.open(message, key: keys.toApp), let ops = (try? JSONValue.parse(plain))?.array else { return }
        if ops.contains(where: { $0["quiet"]?.truthy == true }) {
            content.interruptionLevel = .passive
            content.sound = nil
        }
        for op in ops where op["op"]?.string == "say" && op["card"] != nil {
            guard let drawn = await CardProbe.report(op) else { continue }
            if let jpeg = drawn.jpeg, let attachment = attachment(jpeg) {
                content.attachments = [attachment]
            }
            if op["settled"]?.truthy != true {
                await CardProbe.send(drawn.report, jpeg: drawn.jpeg, pairing: pairing, keys: keys)
            }
        }
    }

    private static func attachment(_ jpeg: Data) -> UNNotificationAttachment? {
        let url = URL.temporaryDirectory.appending(path: "\(UUID().uuidString).jpg")
        guard (try? jpeg.write(to: url)) != nil else { return nil }
        return try? UNNotificationAttachment(identifier: "card", url: url)
    }

    private static func message(_ value: Any) -> Seal.Message? {
        guard let object = value as? [String: Any], let seq = object["seq"] as? Int,
              let nonce = object["nonce"] as? String, let box = object["box"] as? String else { return nil }
        return Seal.Message(seq: seq, nonce: nonce, box: box)
    }

    private static func mailbox(_ pairing: Pairing) async -> [Seal.Message] {
        let after = PairingStore.counters.integer(forKey: "relay.lastIn")
        var request = URLRequest(url: pairing.relay.appending(path: "mailbox").appending(queryItems: [URLQueryItem(name: "after", value: String(after))]))
        request.setValue("Bearer \(pairing.deviceToken)", forHTTPHeaderField: "Authorization")
        guard let (data, _) = try? await URLSession.shared.data(for: request),
              let value = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let messages = value["messages"] as? [Any] else { return [] }
        return messages.compactMap(message)
    }
}
