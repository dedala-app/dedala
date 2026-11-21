// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import Foundation

/// The files records point at (protocol.md, Data): a record's `file` names a
/// path on the agent's machine. The plugin describes each (name, size,
/// version); the phone asks for the file when a page shows it and gets it
/// in parts, kept here under the store and the record, up to a budget: the
/// least recently opened go when it is full, and come back when asked again.
@MainActor
final class Attachments {
    struct Held: Equatable {
        var name: String
        var size: Int
        var version: String = ""
        var ready = false
        var missing = false
        var received = 0
        var asked: Date?
        var opened: Date?
        var error: String?

        var fetching: Bool { asked.map { Date.now.timeIntervalSince($0) < Attachments.patience } ?? false }
    }

    /// What the phone keeps of the files it fetched, all stores together.
    static var budget = 2 * 1024 * 1024 * 1024
    /// A file asked for and not arriving is asked for again after this long.
    static let patience: TimeInterval = 120
    /// Beyond this a file is fetched on a tap, not when it shows.
    static let askFirst = 50 * 1024 * 1024

    private(set) var held: [String: Held]
    /// Asks the plugin for a file: `{"kind": "fetch", "store", "record"}`.
    var fetch: ((_ store: String, _ record: String) -> Void)?

    init() {
        held = (Storage.load("attachments.json")?.object ?? [:]).compactMapValues { value in
            guard let name = value["name"]?.string else { return nil }
            return Held(name: name, size: value["size"]?.int ?? 0, version: value["version"]?.string ?? "", ready: value["ready"]?.truthy ?? false,
                        missing: value["missing"]?.truthy ?? false, received: value["received"]?.int ?? 0, opened: value["opened"]?.date, error: value["error"]?.string)
        }
    }

    static func key(_ store: String, _ record: String) -> String { "\(store)/\(record)" }

    static func folder(_ store: String, _ record: String) -> URL {
        Storage.url("attachments").appending(path: safe(store)).appending(path: safe(record))
    }

    static func safe(_ name: String) -> String {
        name.map { $0.isLetter || $0.isNumber || $0 == "-" || $0 == "_" || $0 == "." ? String($0) : "_" }.joined()
    }

    /// The file when it is here, noted as opened.
    func url(_ store: String, _ record: String) -> URL? {
        let key = Self.key(store, record)
        guard let kept = held[key], kept.ready else { return nil }
        if kept.opened.map({ Date.now.timeIntervalSince($0) > 3600 }) ?? true {
            held[key]?.opened = .now
            save()
        }
        return Self.folder(store, record).appending(path: kept.name)
    }

    /// `{"op": "attachment", "store", "id", "name", "size", "version"}` describes a
    /// file; with `"part", "of"` and its blobs joined into `local` it is one
    /// part of the file; `"missing": true` when the agent's machine lacks it.
    func apply(_ op: JSONValue) throws {
        guard let store = op["store"]?.string, let record = op["id"]?.string, let name = op["name"]?.string else {
            throw Hub.OperationError(description: "attachment needs store, id and name")
        }
        let key = Self.key(store, record)
        let folder = Self.folder(store, record)
        var kept = held[key] ?? Held(name: name, size: 0)
        if op["missing"]?.truthy == true {
            try? FileManager.default.removeItem(at: folder)
            kept = Held(name: name, size: op["size"]?.int ?? kept.size, version: kept.version, missing: true)
        } else if let part = op["part"]?.int, let of = op["of"]?.int, let local = op["local"]?.string {
            try? FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
            let partial = folder.appending(path: "\(name).part")
            if part == 1 {
                try? FileManager.default.removeItem(at: partial)
                try? FileManager.default.removeItem(at: folder.appending(path: name))
            }
            if let data = try? Data(contentsOf: URL(filePath: local)) {
                if let handle = try? FileHandle(forWritingTo: partial) {
                    try? handle.seekToEnd()
                    try? handle.write(contentsOf: data)
                    try? handle.close()
                } else {
                    try? data.write(to: partial)
                }
                kept.received += data.count
            }
            try? FileManager.default.removeItem(at: URL(filePath: local))
            kept.name = name
            kept.size = op["size"]?.int ?? kept.size
            kept.missing = false
            kept.error = nil
            if part >= of {
                try? FileManager.default.removeItem(at: folder.appending(path: name))
                kept.ready = (try? FileManager.default.moveItem(at: partial, to: folder.appending(path: name))) != nil
                kept.received = kept.ready ? kept.size : 0
                kept.asked = nil
                kept.opened = .now
            } else {
                kept.asked = .now
            }
        } else {
            let version = op["version"]?.string ?? ""
            let same = kept.ready && kept.version == version && kept.name == name && FileManager.default.fileExists(atPath: folder.appending(path: name).path)
            if !same {
                try? FileManager.default.removeItem(at: folder)
                kept = Held(name: name, size: op["size"]?.int ?? 0, version: version)
            }
            kept.size = op["size"]?.int ?? kept.size
            kept.version = version
        }
        held[key] = kept
        save()
        if kept.ready { keepWithinBudget(except: key) }
    }

    /// Asks for a record's file, unless it is here, missing, or already asked for.
    func request(_ store: String, _ record: String) {
        let key = Self.key(store, record)
        guard var kept = held[key], !kept.ready, !kept.missing, !kept.fetching else { return }
        kept.asked = .now
        kept.error = nil
        kept.received = 0
        held[key] = kept
        save()
        fetch?(store, record)
    }

    /// The plugin could not give the file: said on the record until asked again.
    func refused(_ store: String, _ record: String, _ reason: String) {
        let key = Self.key(store, record)
        guard var kept = held[key] else { return }
        kept.asked = nil
        kept.error = reason
        held[key] = kept
        save()
    }

    /// The record's `file` field as a page reads it: the path on the agent's
    /// machine, the name, format and size, whether the file is here, on its
    /// way (`received` bytes), missing there, or refused (`error`).
    func describe(_ path: String, store: String, record: String) -> JSONValue {
        let kept = held[Self.key(store, record)]
        let name = kept?.name ?? (path as NSString).lastPathComponent
        var described: [String: JSONValue] = ["path": .string(path), "name": .string(name), "format": .string(FileFormat.of(name)),
                                              "ready": .bool(kept?.ready ?? false), "size": .number(Double(kept?.size ?? 0)),
                                              "store": .string(store), "id": .string(record)]
        if let kept {
            if kept.fetching { described["fetching"] = true; described["received"] = .number(Double(kept.received)) }
            if kept.missing { described["missing"] = true }
            if let error = kept.error { described["error"] = .string(error) }
        }
        return .object(described)
    }

    func forget(store: String, record: String? = nil) {
        let gone = held.keys.filter { key in record.map { key == Self.key(store, $0) } ?? key.hasPrefix("\(store)/") }
        guard !gone.isEmpty else { return }
        for key in gone {
            held[key] = nil
        }
        try? FileManager.default.removeItem(at: record.map { Self.folder(store, $0) } ?? Storage.url("attachments").appending(path: Self.safe(store)))
        save()
    }

    /// The files here stay under the budget: the least recently opened go
    /// first, their records keep saying the file is not here.
    func keepWithinBudget(except kept: String? = nil) {
        var total = held.values.filter(\.ready).reduce(0) { $0 + $1.size }
        guard total > Self.budget else { return }
        let order = held.filter { $0.value.ready && $0.key != kept }.sorted { ($0.value.opened ?? .distantPast) < ($1.value.opened ?? .distantPast) }
        for (key, value) in order where total > Self.budget {
            let parts = key.split(separator: "/", maxSplits: 1).map(String.init)
            if parts.count == 2 { try? FileManager.default.removeItem(at: Self.folder(parts[0], parts[1])) }
            held[key]?.ready = false
            held[key]?.received = 0
            total -= value.size
        }
        save()
    }

    private func save() {
        Storage.save(.object(held.mapValues { kept in
            var value: [String: JSONValue] = ["name": .string(kept.name), "size": .number(Double(kept.size)), "version": .string(kept.version),
                                              "ready": .bool(kept.ready), "received": .number(Double(kept.received))]
            if kept.missing { value["missing"] = true }
            if let opened = kept.opened { value["opened"] = JSONValue.iso(opened) }
            if let error = kept.error { value["error"] = .string(error) }
            return .object(value)
        }), to: "attachments.json")
    }
}

/// The format a file is read as, from its name.
enum FileFormat {
    static func of(_ name: String) -> String {
        switch (name as NSString).pathExtension.lowercased() {
        case "pdf": "pdf"
        case "md", "markdown": "markdown"
        case "org": "org"
        case "png", "jpg", "jpeg", "heic", "gif", "webp": "image"
        case "txt", "text", "": "text"
        default: "document"
        }
    }
}
