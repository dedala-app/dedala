// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import Foundation

/// Text stores and the files of folder stores (docs/protocol.md, Data): what
/// the plugin last sent is the truth, and your line edits it has not
/// acknowledged yet are shown over it, with whether the file is in sync:
/// pending, synced, or failed with the reason. Keyed by the store, or by the
/// store and the record for a file of a folder.
@MainActor
final class FileSync {
    private var failures: [String: String]

    static let lineEdits = ["append", "change", "remove", "toggle", "text"]
    static let folderEdits = ["add", "delete"]

    init() {
        failures = (Storage.load("files.json")?["failures"]?.object ?? [:]).compactMapValues(\.string)
    }

    static func key(_ store: String, _ record: String?) -> String {
        record.map { "\(store)/\($0)" } ?? store
    }

    /// An edit as the plugin will make it, or the reason it cannot be one.
    /// `current` is the file as the truth holds it, for a whole text to carry
    /// what it was written over.
    func edit(_ store: String, record: String?, folder: Bool, _ fields: [String: JSONValue], current: JSONValue?) throws -> JSONValue {
        let known = Self.lineEdits + (folder ? Self.folderEdits : [])
        let named = known.filter { fields[$0] != nil && !($0 == "text" && folder && fields["add"] != nil) }
        guard named.count == 1, let kind = named.first else {
            throw Hub.OperationError(description: "edit of '\(store)' is one of \(known.joined(separator: ", "))")
        }
        if kind == "change", fields["to"]?.string?.isEmpty != false {
            throw Hub.OperationError(description: "edit of '\(store)' with change needs the new line in to")
        }
        if kind == "add", fields["add"]?.string?.isEmpty != false {
            throw Hub.OperationError(description: "edit of '\(store)' with add needs the new file's name")
        }
        if folder, record == nil, kind != "add" {
            throw Hub.OperationError(description: "edit of the folder '\(store)' names the file with id, or adds one with add")
        }
        if kind == "delete", record == nil {
            throw Hub.OperationError(description: "edit of '\(store)' with delete names the file with id")
        }
        var edit = fields
        if kind == "text", edit["base"] == nil {
            edit["base"] = current?["text"] ?? ""
        }
        failures[Self.key(store, record)] = nil
        save()
        return .object(edit)
    }

    /// The plugin has these edits: the ones it refused failed with its reason.
    func acknowledged(_ keys: Set<String>, failed: [String: String]) {
        for key in keys {
            failures[key] = failed[key]
        }
        save()
    }

    func forget(_ store: String) {
        for key in failures.keys where key == store || key.hasPrefix("\(store)/") {
            failures[key] = nil
        }
        save()
    }

    /// A text file as a page sees it: the truth, with the pending edits made
    /// to its text as the plugin will make them to the file, and its sync.
    func data(_ truth: JSONValue, key: String, pending: [JSONValue]) -> JSONValue {
        var data = truth.object ?? [:]
        let format = FileFormat.of(data["name"]?.string ?? "")
        for edit in pending {
            if let edited = try? TextEdits.apply(data["text"]?.string ?? "", edit, format: format) {
                data["text"] = .string(edited)
            }
        }
        data["sync"] = .string(!pending.isEmpty ? "pending" : failures[key] != nil ? "failed" : "synced")
        data["error"] = failures[key].map(JSONValue.string) ?? .null
        return .object(data)
    }

    /// A folder as a page sees it: each file with its pending edits, the files
    /// you added not yet there, the ones you deleted gone.
    func records(_ truth: JSONValue, store: String, pending: [JSONValue]) -> JSONValue {
        var records = truth.array ?? []
        for edit in pending where edit["record"] == nil {
            guard let name = edit["edit"]?["add"]?.string else { continue }
            let text = edit["edit"]?["text"]?.string ?? ""
            records.append(.object(["id": .string(name), "name": .string(name), "path": .null, "title": .string(name), "tags": [],
                                    "text": .string(text), "updated": edit["at"] ?? .null, "added": true]))
        }
        return .array(records.compactMap { record in
            guard let id = record["id"]?.string else { return record }
            let own = pending.filter { $0["record"]?.string == id || $0["edit"]?["add"]?.string == id }.compactMap { $0["edit"] }
            if own.contains(where: { $0["delete"]?.truthy == true }) { return nil }
            return data(record, key: Self.key(store, id), pending: own.filter { $0["delete"] == nil })
        })
    }

    private func save() {
        Storage.save(.object(["failures": .object(failures.mapValues(JSONValue.string))]), to: "files.json")
    }
}
