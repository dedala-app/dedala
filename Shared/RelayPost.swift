// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import Foundation

/// Sending to the agent without the app's WebSocket, for the extensions: files
/// as sealed blobs, events sealed with the next number of the app's sequence
/// and left in the mailbox.
nonisolated enum RelayPost {
    /// A blob carries at most this much of a file.
    static let chunk = 1024 * 1024

    /// The file's blobs on the relay, in order; nil when one could not go.
    static func upload(_ data: Data, pairing: Pairing, keys: Seal.Keys) async -> [String]? {
        var blobs: [String] = []
        var start = data.startIndex
        repeat {
            let end = min(start + chunk, data.endIndex)
            guard let sealed = try? Seal.seal(data[start..<end], seq: 0, key: keys.toAgent),
                  let body = try? JSONEncoder().encode(sealed),
                  let answer = await post(body, to: pairing.relay.appending(path: "blobs"), token: pairing.deviceToken),
                  let blob = (try? JSONValue.parse(answer))?["blob"]?.string else { return nil }
            blobs.append(blob)
            start = end
        } while start < data.endIndex
        return blobs
    }

    /// Whether the relay took the events.
    @discardableResult
    static func send(_ events: [JSONValue], pairing: Pairing, keys: Seal.Keys) async -> Bool {
        guard let message = try? Seal.seal(JSONValue.array(events).data(), seq: PairingStore.nextOut(), key: keys.toAgent),
              let body = try? JSONEncoder().encode(message) else { return false }
        return await post(body, to: pairing.relay.appending(path: "mailbox"), token: pairing.deviceToken) != nil
    }

    private static func post(_ body: Data, to url: URL, token: String) async -> Data? {
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.httpBody = body
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        guard let (data, response) = try? await URLSession.shared.data(for: request),
              (200..<300).contains((response as? HTTPURLResponse)?.statusCode ?? 0) else { return nil }
        return data
    }
}
