// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import CryptoKit
import Foundation
import Security

/// What pairing left on this phone: the relay, who the agent is, the device's
/// token and private key. Kept in a keychain group the extensions share, so
/// they can open what arrives while the app is closed.
nonisolated struct Pairing: Codable, Sendable {
    var relay: URL
    var agentName: String
    var agentKey: String
    var pairing: String
    var deviceToken: String
    var deviceKey: Data

    func keys() throws -> Seal.Keys {
        try Seal.keys(own: try Curve25519.KeyAgreement.PrivateKey(rawRepresentation: deviceKey), other: agentKey, pairing: pairing)
    }
}

nonisolated enum PairingStore {
    static let accessGroup = "KHZGP69E97.app.dedala.shared"
    private static let service = "hermes.pairing"

    private static var query: [String: Any] {
        [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: "current",
            kSecAttrAccessGroup as String: accessGroup,
        ]
    }

    static func load() -> Pairing? {
        var found: AnyObject?
        var request = query
        request[kSecReturnData as String] = true
        guard SecItemCopyMatching(request as CFDictionary, &found) == errSecSuccess, let data = found as? Data else { return nil }
        return try? JSONDecoder().decode(Pairing.self, from: data)
    }

    static func save(_ pairing: Pairing) throws {
        clear()
        var item = query
        item[kSecValueData as String] = try JSONEncoder().encode(pairing)
        item[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlock
        let status = SecItemAdd(item as CFDictionary, nil)
        guard status == errSecSuccess else { throw NSError(domain: NSOSStatusErrorDomain, code: Int(status)) }
    }

    static func clear() {
        SecItemDelete(query as CFDictionary)
    }

    /// The agent's name as the extensions show it: on notifications, in the
    /// share sheet.
    static func rename(_ name: String) {
        guard var pairing = load(), pairing.agentName != name else { return }
        pairing.agentName = name
        try? save(pairing)
    }

    /// The key that opens what the agent sends, as a file in the app group:
    /// the process that draws Live Activities may not reach the keychain. Only
    /// this key is there, never the device's private key.
    private static var activityKeyURL: URL? {
        FileManager.default
            .containerURL(forSecurityApplicationGroupIdentifier: HermesActivityAttributes.group)?
            .appending(path: "Keys")
            .appending(path: "to-app.key")
    }

    static func saveActivityKey(_ key: SymmetricKey) {
        guard let url = activityKeyURL else { return }
        try? FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
        try? key.withUnsafeBytes { Data($0) }.write(to: url, options: [.atomic, .completeFileProtectionUntilFirstUserAuthentication])
    }

    static func activityKey() -> SymmetricKey? {
        guard let url = activityKeyURL, let data = try? Data(contentsOf: url), data.count == 32 else { return nil }
        return SymmetricKey(data: data)
    }

    static func clearActivityKey() {
        if let url = activityKeyURL { try? FileManager.default.removeItem(at: url) }
    }

    /// Sequence numbers, shared with the extensions: the last message opened
    /// from the agent, and the last one sent to it.
    static var counters: UserDefaults {
        UserDefaults(suiteName: HermesActivityAttributes.group) ?? .standard
    }

    private static var group: URL? {
        FileManager.default.containerURL(forSecurityApplicationGroupIdentifier: HermesActivityAttributes.group)
    }

    /// The number of the next message to the agent. The app, the notification
    /// extension and the share extension all send, and the relay keeps one
    /// message per number: the count lives in a file taken under a lock.
    static func nextOut() -> Int {
        guard let group else {
            let seq = counters.integer(forKey: "relay.lastOut") + 1
            counters.set(seq, forKey: "relay.lastOut")
            return seq
        }
        let lock = open(group.appending(path: "relay.lock").path, O_CREAT | O_RDWR, 0o600)
        if lock >= 0 { flock(lock, LOCK_EX) }
        defer {
            if lock >= 0 {
                flock(lock, LOCK_UN)
                close(lock)
            }
        }
        let file = group.appending(path: "relay.out")
        let last = (try? String(contentsOf: file, encoding: .utf8)).flatMap { Int($0) } ?? counters.integer(forKey: "relay.lastOut")
        try? String(last + 1).write(to: file, atomically: true, encoding: .utf8)
        return last + 1
    }

    static func resetOut() {
        counters.set(0, forKey: "relay.lastOut")
        if let group { try? FileManager.default.removeItem(at: group.appending(path: "relay.out")) }
    }
}
