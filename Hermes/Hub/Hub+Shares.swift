// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import Foundation

/// Photos you send in a message: kept on the phone with their share until
/// each is on the relay as sealed blobs, then the share joins the outbox like
/// one from the share extension. What could not go is tried again when the
/// relay is back.
extension Hub {
    static var sharesFolder: URL { PhotoPicking.folder.appending(path: "shares", directoryHint: .isDirectory) }

    func sendShare(_ event: JSONValue, photos: [Data]) {
        guard let id = event["id"]?.string else { return }
        let folder = Self.sharesFolder.appending(path: id, directoryHint: .isDirectory)
        try? FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        var items = event["items"]?.array ?? []
        for (index, data) in photos.enumerated() where index < items.count {
            let url = folder.appending(path: "\(index).jpg")
            guard (try? data.write(to: url, options: .atomic)) != nil else { continue }
            items[index] = items[index].merging(.object(["local": .string(url.path)]))
        }
        try? event.merging(.object(["items": .array(items)])).data().write(to: folder.appending(path: "share.json"), options: .atomic)
        Task { await uploadShares() }
    }

    func uploadShares() async {
        guard !uploadingShares else { return }
        uploadingShares = true
        defer { uploadingShares = false }
        let folders = (try? FileManager.default.contentsOfDirectory(at: Self.sharesFolder, includingPropertiesForKeys: [.creationDateKey])) ?? []
        let made = { (url: URL) in (try? url.resourceValues(forKeys: [.creationDateKey]).creationDate) ?? .distantPast }
        for folder in folders.sorted(by: { made($0) < made($1) }) {
            let file = folder.appending(path: "share.json")
            guard var event = (try? Data(contentsOf: file)).flatMap({ try? JSONValue.parse($0) }) else {
                try? FileManager.default.removeItem(at: folder)
                continue
            }
            var items = event["items"]?.array ?? []
            for (index, item) in items.enumerated() {
                guard let path = item["local"]?.string else { continue }
                var sent = item.object ?? [:]
                sent["local"] = nil
                if let data = try? Data(contentsOf: URL(fileURLWithPath: path)) {
                    guard let blobs = await uploader(data) else { return }
                    sent["blobs"] = .array(blobs.map(JSONValue.string))
                }
                items[index] = .object(sent)
                event = event.merging(.object(["items": .array(items)]))
                try? event.data().write(to: file, options: .atomic)
            }
            try? FileManager.default.removeItem(at: folder)
            emit(outgoing.add(event))
        }
    }
}
