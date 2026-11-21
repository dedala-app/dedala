// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import Foundation

/// What you shared with the agent from another app, kept in the app group
/// until the plugin acknowledges it: the share extension sends it at once, and
/// the app sends it again when it opens if it has not arrived. Beside each,
/// small images of the photos it carried, for the app to draw your message.
nonisolated enum ShareOutbox {
    /// The relay keeps blobs this long; a share older than that cannot arrive.
    static let kept: TimeInterval = 7 * 24 * 3600

    private static var root: URL? {
        FileManager.default
            .containerURL(forSecurityApplicationGroupIdentifier: HermesActivityAttributes.group)?
            .appending(path: "Shares")
    }

    private static var waitingFolder: URL? { root?.appending(path: "waiting") }

    static func add(_ event: JSONValue) {
        guard let folder = waitingFolder, let id = event["id"]?.string else { return }
        try? FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        try? event.data().write(to: folder.appending(path: "\(id).json"), options: .atomic)
    }

    static func waiting(at now: Date = .now) -> [JSONValue] {
        guard let folder = waitingFolder,
              let files = try? FileManager.default.contentsOfDirectory(at: folder, includingPropertiesForKeys: nil) else { return [] }
        var found: [JSONValue] = []
        for file in files where file.pathExtension == "json" {
            guard let event = (try? Data(contentsOf: file)).flatMap({ try? JSONValue.parse($0) }) else { continue }
            if let at = event["at"]?.date, now.timeIntervalSince(at) > kept {
                try? FileManager.default.removeItem(at: file)
            } else {
                found.append(event)
            }
        }
        return found.sorted { ($0["at"]?.string ?? "") < ($1["at"]?.string ?? "") }
    }

    static func acknowledge(_ ids: Set<String>) {
        guard let folder = waitingFolder else { return }
        for id in ids {
            try? FileManager.default.removeItem(at: folder.appending(path: "\(id).json"))
        }
    }

    /// The small image of a share's photo, by its place among the shared items.
    static func thumbnail(share: String, item: Int) -> URL? {
        root?.appending(path: "thumbnails").appending(path: share).appending(path: "\(item).jpg")
    }
}
