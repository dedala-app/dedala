// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import Foundation

/// What you change on the phone: applied at once, kept until you stop, then
/// told to the agent as one event, sent again until the plugin has it. A
/// store you changed comes back from the plugin as its file now holds it,
/// just before the plugin confirms your edit.
extension Hub {
    /// `{"store": id, …}` (docs/hermes-ui.md, Actions): a patch merged into a
    /// JSON store or `replace`, a record patched by `id`, added with `add` or
    /// removed with `remove`, kept to tell the agent once you stop. On a text
    /// store, or on a file of a folder store named by `id`, line edits, shown
    /// at once and sent now to the plugin, which makes them to the file.
    func edit(_ patch: JSONValue, from source: String) throws {
        guard var fields = patch.object else { throw OperationError(description: "edit needs an object: {store: id, …the fields that change}") }
        guard let id = fields.removeValue(forKey: "store")?.string, !id.isEmpty else {
            throw OperationError(description: "edit names the store, by id, with the fields that change")
        }
        guard storeTruth[id] != nil else { throw OperationError(description: "There is no store '\(id)'") }
        guard !fields.isEmpty else { throw OperationError(description: "edit of '\(id)' changes nothing") }
        let kind = storeKinds[id]
        if kind == "text" || kind == "folder" {
            guard kind == "folder" || fields["id"] == nil else { throw OperationError(description: "edit of the text store '\(id)' takes no id: it is one file") }
            let record = kind == "folder" ? fields.removeValue(forKey: "id")?.string : nil
            let current = kind == "folder" ? storeTruth[id]?.array?.first { $0["id"]?.string == record } : storeTruth[id]
            let change = try fileSync.edit(id, record: record, folder: kind == "folder", fields, current: current)
            var event: [String: JSONValue] = ["kind": "file", "store": .string(id), "edit": change, "from": .string(source), "at": JSONValue.iso(.now)]
            if let record { event["record"] = .string(record) }
            let kept = outgoing.add(.object(event))
            showStore(id)
            emit(kept)
            return
        }
        let records = storeTruth[id]?.array != nil
        let change: JSONValue
        if records, let added = fields["add"] {
            guard var record = added.object else { throw OperationError(description: "edit of '\(id)' adds a record: an object") }
            if record["id"]?.string == nil { record["id"] = .string(UUID().uuidString.lowercased()) }
            change = .object(["store": .string(id), "add": .object(record)])
        } else if records, let removed = fields["remove"] {
            change = .object(["store": .string(id), "remove": .string(removed.text)])
        } else if records, let record = fields.removeValue(forKey: "id") {
            guard !fields.isEmpty else { throw OperationError(description: "edit of '\(id)' changes nothing of the record \(record.text)") }
            change = .object(["store": .string(id), "id": .string(record.text), "patch": .object(fields)])
        } else {
            change = .object(["store": .string(id), "patch": .object(fields)])
        }
        pending.change(change, from: source)
        showStore(id)
        let carried = Self.localFiles(in: change["add"] ?? change["patch"] ?? .null)
        if !carried.isEmpty {
            upload(carried, into: id, record: change["id"]?.string ?? change["add"]?["id"]?.string, from: source)
        }
    }

    /// Asks the plugin for a record's file (protocol.md, Events: `fetch`): it
    /// comes in parts, shown as they arrive.
    func requestFile(_ store: String, _ record: String) {
        let event: JSONValue = .object(["kind": "fetch", "store": .string(store), "record": .string(record), "at": JSONValue.iso(.now)])
        emit(outgoing.add(event))
        showStore(store)
    }

    /// The fields of a patch or a record whose value is a file the phone holds
    /// (`Photo`): `{local, name, size, type}`.
    static func localFiles(in fields: JSONValue) -> [(key: String, file: JSONValue)] {
        (fields.object ?? [:]).compactMap { key, value in
            value["local"]?.string != nil && value["blobs"] == nil ? (key, value) : nil
        }.sorted { $0.key < $1.key }
    }

    /// Sends the files an edit carries as sealed blobs, and puts their blobs
    /// in the pending change before it leaves; the change waits meanwhile.
    private func upload(_ carried: [(key: String, file: JSONValue)], into store: String, record: String?, from source: String) {
        pending.hold()
        Task { @MainActor [weak self] in
            defer { self?.pending.release() }
            var uploaded: [String: JSONValue] = [:]
            for (key, file) in carried {
                guard let self, let path = file["local"]?.string, let data = try? Data(contentsOf: URL(fileURLWithPath: path)) else { continue }
                guard let blobs = await uploader(data) else {
                    self.contexts.values.first?.fail("The photo for \(key) could not be sent; it stays on the phone", tapped: nil)
                    continue
                }
                uploaded[key] = file.merging(.object(["blobs": .array(blobs.map(JSONValue.string)), "size": .number(Double(data.count))]))
            }
            guard let self, !uploaded.isEmpty else { return }
            var change: [String: JSONValue] = ["store": .string(store), "patch": .object(uploaded)]
            if let record { change["id"] = .string(record) }
            self.pending.change(.object(change), from: source)
            self.showStore(store)
        }
    }

    /// Files an acknowledged edit carried are no longer needed on the phone.
    private func forgetUploads(in event: JSONValue) {
        for change in event["changes"]?.array ?? [] {
            for (_, file) in Self.localFiles(in: change["add"] ?? change["patch"] ?? .null) + Self.uploadedFiles(in: change["add"] ?? change["patch"] ?? .null) {
                if let path = file["local"]?.string { try? FileManager.default.removeItem(atPath: path) }
            }
        }
    }

    private static func uploadedFiles(in fields: JSONValue) -> [(key: String, file: JSONValue)] {
        (fields.object ?? [:]).compactMap { key, value in value["local"]?.string != nil && value["blobs"] != nil ? (key, value) : nil }
    }

    /// A store as its pages see it: what the plugin last sent, which is its
    /// file on the agent's machine, with your edits the plugin has not
    /// confirmed made to it, in the order you made them; a record's file
    /// described as the phone holds it.
    func showStore(_ id: String) {
        guard let truth = storeTruth[id] else { return show(nil, as: id) }
        let kind = storeKinds[id]
        var data: JSONValue
        if kind == "text" {
            let edits = outgoing.events.filter { $0["kind"]?.string == "file" && $0["store"]?.string == id }.compactMap { $0["edit"] }
            data = fileSync.data(truth, key: id, pending: edits)
        } else if kind == "folder" {
            let events = outgoing.events.filter { $0["kind"]?.string == "file" && $0["store"]?.string == id }
            data = fileSync.records(truth, store: id, pending: events)
        } else {
            let sent = outgoing.events.filter { $0["kind"]?.string == "edits" }.flatMap { $0["changes"]?.array ?? [] }
            let waiting = (sent + pending.changes).filter { $0["store"]?.string == id }
            data = waiting.reduce(truth) { Self.edited($0, by: $1) }
        }
        if let records = data.array {
            data = .array(records.map { record in
                guard let recordID = record["id"]?.string, let path = record["file"]?.string else { return record }
                return record.merging(.object(["file": attachments.describe(path, store: id, record: recordID)]))
            })
        }
        show(data, as: id)
    }

    /// A store with one of your changes made to it: a patch merges into it
    /// (`replace` gives it new data whole), a record's patch merges into that
    /// record, an added record joins the end, a removed one goes.
    static func edited(_ data: JSONValue, by change: JSONValue) -> JSONValue {
        if let added = change["add"] {
            return .array((data.array ?? []) + [added])
        }
        if let removed = change["remove"]?.string {
            return .array((data.array ?? []).filter { $0["id"]?.text != removed })
        }
        guard let patch = change["patch"] else { return data }
        if let record = change["id"]?.string {
            return .array((data.array ?? []).map { $0["id"]?.text == record ? $0.merging(patch) : $0 })
        }
        var fields = patch.object ?? [:]
        let base = fields.removeValue(forKey: "replace") ?? data
        return fields.isEmpty || base.object == nil ? base : base.merging(.object(fields))
    }

    /// Runs a command on the agent's machine: sent now, kept until the plugin
    /// answers, shown as running meanwhile under `$commands.<name>`. The
    /// reason when it cannot start: one run of a command at a time.
    func command(_ name: String, args: JSONValue, from source: String) -> String? {
        guard !name.isEmpty else { return "command needs a name" }
        if commandRuns[name]?["status"]?.string == "running" {
            return "The command \(name) is already running"
        }
        let event = outgoing.add(.object(["kind": "command", "name": .string(name), "args": args, "from": .string(source), "at": JSONValue.iso(.now)]))
        commandRuns[name] = .object(["status": "running", "args": args, "at": JSONValue.iso(.now), "id": event["id"] ?? .null])
        showCommands()
        saveSoon()
        emit(event)
        return nil
    }

    /// What the plugin answered about a command's run: its outcome, shown
    /// under its name from now on.
    func commandRan(_ op: JSONValue) throws {
        guard let name = op["name"]?.string else { throw OperationError(description: "command needs name") }
        var run = commandRuns[name]?.object ?? [:]
        for key in ["status", "result", "error", "at", "duration", "args"] {
            run[key] = op[key]
        }
        run["id"] = nil
        commandRuns[name] = .object(run)
        showCommands()
        saveSoon()
    }

    func showCommands() {
        LiveValues.shared.update(["commands": .object(commandRuns)])
    }

    /// Sends what is pending now: when you stopped, or when the app goes away.
    func flushEdits() {
        Storage.flush()
        guard let event = pending.take() else { return }
        emit(outgoing.add(event))
    }

    /// Sends again what the plugin has not acknowledged: the relay is back.
    /// What the share extension spooled joins the one outbox first.
    func resend() {
        for share in ShareOutbox.waiting() where !outgoing.events.contains(where: { $0["id"] == share["id"] }) {
            _ = outgoing.add(share)
        }
        ShareOutbox.acknowledge(Set(ShareOutbox.waiting().compactMap { $0["id"]?.string }))
        outgoing.waiting().forEach(emit)
    }

    /// The plugin has these events. Their answers were applied just before;
    /// what is left is to drop them from the outbox, show the stores they
    /// touched as the plugin now holds them, and mark what was refused.
    func acknowledged(_ ids: Set<String>, failed: [String: String]) {
        var files: Set<String> = []
        var reasons: [String: String] = [:]
        var stores: Set<String> = []
        for event in outgoing.events where event["id"]?.string.map(ids.contains) == true {
            switch event["kind"]?.string {
            case "file":
                guard let store = event["store"]?.string else { continue }
                let key = FileSync.key(store, event["record"]?.string)
                files.insert(key)
                stores.insert(store)
                if let reason = failed[event["id"]?.string ?? ""] { reasons[key] = reason }
            case "edits":
                for change in event["changes"]?.array ?? [] {
                    if let store = change["store"]?.string { stores.insert(store) }
                }
                forgetUploads(in: event)
            case "fetch":
                guard let store = event["store"]?.string, let record = event["record"]?.string else { continue }
                if let reason = failed[event["id"]?.string ?? ""] { attachments.refused(store, record, reason) }
                stores.insert(store)
            case "command":
                guard let name = event["name"]?.string, let run = commandRuns[name], run["id"] == event["id"], run["status"]?.string == "running" else { continue }
                var ended = run.object ?? [:]
                ended["id"] = nil
                ended["status"] = "failed"
                ended["error"] = .string(failed[event["id"]?.string ?? ""] ?? "The plugin took it and said nothing more")
                commandRuns[name] = .object(ended)
                showCommands()
                saveSoon()
            default:
                break
            }
        }
        outgoing.acknowledge(ids)
        fileSync.acknowledged(files, failed: reasons)
        stores.forEach(showStore)
    }
}

/// The changes waiting for you to stop: the patches to one object merged
/// into one. Kept on disk as they come, so what you did just before the app
/// went away is still told.
@MainActor
final class EditBatch {
    /// What you change goes to the agent once you stop for this long: a burst
    /// of taps is one event.
    static let settling: Duration = .seconds(3)

    /// You stopped: time to `take` what waits.
    var onSettled: (() -> Void)?
    private(set) var changes: [JSONValue]
    private let file: String
    private var settling: Task<Void, Never>?
    /// Uploads under way: what waits is not taken until they are done.
    private var held = 0

    init(file: String = "pending-edits.json") {
        self.file = file
        changes = Storage.load(file)?["changes"]?.array ?? []
        if !isEmpty { settle() }
    }

    var isEmpty: Bool { changes.isEmpty }

    func hold() { held += 1 }

    func release() {
        held = max(0, held - 1)
        if held == 0, !isEmpty { settle() }
    }

    /// One change to a store, merged with what waits for the same object: a
    /// patch into the earlier patch, a record's patch into the record added
    /// before it; a removal drops what waited for that record.
    func change(_ change: JSONValue, from source: String) {
        guard let store = change["store"]?.string else { return }
        var kept = change.merging(.object(["from": .string(source)]))
        if let removed = change["remove"]?.string {
            let wasAdded = changes.contains { $0["store"]?.string == store && $0["add"]?["id"]?.text == removed }
            changes.removeAll { $0["store"]?.string == store && ($0["add"]?["id"]?.text == removed || $0["id"]?.string == removed) }
            if wasAdded {
                save()
                settle()
                return
            }
        } else if let patch = change["patch"], let record = change["id"]?.string {
            if let index = changes.firstIndex(where: { $0["store"]?.string == store && $0["add"]?["id"]?.text == record }) {
                replace(at: index, "add", with: Self.combined(changes[index]["add"] ?? .object([:]), patch), from: source)
                return
            }
            if let index = changes.firstIndex(where: { $0["store"]?.string == store && $0["id"]?.string == record }) {
                replace(at: index, "patch", with: Self.combined(changes[index]["patch"] ?? .object([:]), patch), from: source)
                return
            }
        } else if let patch = change["patch"], let index = changes.firstIndex(where: { $0["store"]?.string == store && $0["patch"] != nil && $0["id"] == nil }) {
            replace(at: index, "patch", with: patch["replace"] != nil ? patch : Self.combined(changes[index]["patch"] ?? .object([:]), patch), from: source)
            return
        }
        changes.append(kept)
        save()
        settle()
    }

    private func replace(at index: Int, _ key: String, with value: JSONValue, from source: String) {
        var entry = changes[index].object ?? [:]
        entry[key] = value
        entry["from"] = .string(source)
        changes[index] = .object(entry)
        save()
        settle()
    }

    /// Two patches to one object as one: what the later one says wins, a
    /// field set to null stays a removal, and a `replace` starts over.
    static func combined(_ earlier: JSONValue, _ later: JSONValue) -> JSONValue {
        guard case .object(var fields) = earlier, case .object(let changes) = later else { return later }
        for (key, value) in changes {
            if let before = fields[key], before.object != nil, value.object != nil {
                fields[key] = combined(before, value)
            } else {
                fields[key] = value
            }
        }
        return .object(fields)
    }

    private func settle() {
        settling?.cancel()
        settling = Task { [weak self] in
            try? await Task.sleep(for: Self.settling)
            guard !Task.isCancelled else { return }
            self?.onSettled?()
        }
    }

    /// The event that tells the agent, with nothing left waiting; nil when nothing was.
    func take() -> JSONValue? {
        guard held == 0 else { return nil }
        settling?.cancel()
        settling = nil
        guard !isEmpty else { return nil }
        let event: JSONValue = .object(["kind": "edits", "changes": .array(changes), "at": JSONValue.iso(.now)])
        changes = []
        save()
        return event
    }

    private func save() {
        Storage.save(.object(["changes": .array(changes)]), to: file)
    }
}
