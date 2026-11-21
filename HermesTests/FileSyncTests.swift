// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import Foundation
import Testing
@testable import Hermes

/// A file a page works on shows your edits at once, before the plugin has
/// made them to the file, and says whether it is in sync.
@Suite("File sync", .serialized)
@MainActor
struct FileSyncTests {
    let groceries: JSONValue = .object(["name": "groceries.md", "text": "- [ ] Milk\n- [x] Bread\n"])

    func sync() -> FileSync { FileSync() }

    func edit(_ sync: FileSync, _ fields: [String: JSONValue], record: String? = nil, folder: Bool = false) throws -> JSONValue {
        try sync.edit("groceries", record: record, folder: folder, fields, current: groceries)
    }

    func texts(_ data: JSONValue?) -> [String] {
        OrgTree.select(OrgTree.parse(data?["text"]?.string ?? "", format: "markdown"), "item").compactMap { $0["text"]?.string }
    }

    @Test func pendingEditsShowOverTheFile() throws {
        let sync = sync()
        let edits = try [
            edit(sync, ["append": "Eggs"]),
            edit(sync, ["toggle": "Milk"]),
            edit(sync, ["change": "Bread", "to": "Rye bread"]),
        ]
        let data = sync.data(groceries, key: "groceries", pending: edits)
        #expect(texts(data) == ["Milk", "Rye bread", "Eggs"])
        #expect(data["text"] == "- [x] Milk\n- [x] Rye bread\n- [ ] Eggs\n")
        #expect(data["sync"] == "pending")
        #expect(texts(sync.data(groceries, key: "groceries", pending: [try edit(sync, ["remove": "Milk"])])) == ["Bread"])
    }

    @Test func anEditTheFileRefusedSaysWhyUntilTheNextOne() throws {
        let sync = sync()
        sync.acknowledged(["groceries"], failed: ["groceries": "“Milk” is no longer in the file"])
        #expect(sync.data(groceries, key: "groceries", pending: [])["sync"] == "failed")
        #expect(sync.data(groceries, key: "groceries", pending: [])["error"] == "“Milk” is no longer in the file")
        _ = try edit(sync, ["append": "Eggs"])
        #expect(sync.data(groceries, key: "groceries", pending: [])["sync"] == "synced")
    }

    @Test func aWholeTextEditCarriesTheTextItWasMadeOver() throws {
        let edit = try edit(sync(), ["text": "- [ ] Milk\n"])
        #expect(edit["base"] == "- [ ] Milk\n- [x] Bread\n")
    }

    @Test func anEditIsOneOfTheKnownOnes() throws {
        #expect(throws: Hub.OperationError.self) { try edit(sync(), ["rename": "x"]) }
        #expect(throws: Hub.OperationError.self) { try edit(sync(), ["change": "Milk"]) }
        #expect(throws: Hub.OperationError.self) { try edit(sync(), ["add": "b.org"]) }
        #expect(throws: Hub.OperationError.self) { try edit(sync(), ["append": "x"], folder: true) }
        #expect(throws: Hub.OperationError.self) { try edit(sync(), ["delete": true], folder: true) }
        let added = try edit(sync(), ["add": "b.org", "text": "B"], folder: true)
        #expect(added == .object(["add": "b.org", "text": "B"]))
        let deleted = try edit(sync(), ["delete": true], record: "a.org", folder: true)
        #expect(deleted == .object(["delete": true]))
    }

    @Test func aFolderShowsItsFilesWithTheirPendingEditsAddedAndDeleted() throws {
        let sync = sync()
        let a: JSONValue = .object(["id": "a.org", "name": "a.org", "text": "- [ ] One\n"])
        let b: JSONValue = .object(["id": "b.org", "name": "b.org", "text": ""])
        let pending: [JSONValue] = [
            .object(["kind": "file", "store": "notes", "record": "a.org", "edit": .object(["toggle": "One"])]),
            .object(["kind": "file", "store": "notes", "edit": .object(["add": "c.org", "text": "#+title: C\n"]), "at": "now"]),
            .object(["kind": "file", "store": "notes", "record": "b.org", "edit": .object(["delete": true])]),
        ]
        sync.acknowledged(["notes/b.org"], failed: ["notes/b.org": "“One” is no longer in the file"])
        let records = try #require(sync.records(.array([a, b]), store: "notes", pending: pending).array)
        #expect(records.map { $0["id"] } == ["a.org", "c.org"])
        #expect(records[0]["text"] == "- [X] One\n" && records[0]["sync"] == "pending")
        #expect(records[1]["text"] == "#+title: C\n" && records[1]["added"] == true && records[1]["sync"] == "pending")
        #expect(sync.records(.array([a, b]), store: "notes", pending: []).array?.map { $0["sync"] } == ["synced", "failed"])
    }
}

/// A script is given the stores it names, and only those.
@Suite("Script stores")
struct ScriptStoresTests {
    @Test func aScriptNamesTheStoresItReads() throws {
        let spec = try #require(ScriptSpec(.object(["script": "function a({stores}) { return stores.daily.lines.length + stores['sc_recap'].n }"])))
        #expect(spec.stores == ["daily", "sc_recap"])
        #expect(spec.stores(from: ["daily": .object([:]), "other": .object([:])]).keys.sorted() == ["daily"])
    }
}
