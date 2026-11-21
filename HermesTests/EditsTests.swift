// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import Foundation
import Testing
@testable import Hermes

/// What you change on the phone: applied at once, told to the agent once, as
/// one patch per object.
@MainActor
@Suite("Edits")
struct EditsTests {
    func hub(events: @escaping (JSONValue) -> Void) -> Hub {
        let hub = Hub()
        hub.onEmit = events
        return hub
    }

    @Test func editsToOneRecordMergeIntoOnePatchAndShowAtOnce() throws {
        var events: [JSONValue] = []
        let hub = hub { events.append($0) }
        let id = "tasks-\(UUID().uuidString)"
        _ = try hub.apply(.object(["op": "store", "id": .string(id), "data": .array([.object(["id": "water", "done": false, "room": "kitchen"])])]))
        try hub.edit(.object(["store": .string(id), "id": "water", "done": true]), from: "today")
        try hub.edit(.object(["store": .string(id), "id": "water", "note": "Done this morning"]), from: "today")
        try hub.edit(.object(["store": .string(id), "add": .object(["room": "bath"])]), from: "today")
        #expect(events.isEmpty)
        let shown = try #require(hub.stores[id]?.array)
        #expect(shown.count == 2 && shown[0]["done"] == true && shown[0]["room"] == "kitchen" && shown[0]["note"] == "Done this morning")
        let made = try #require(shown[1]["id"]?.string)
        try hub.edit(.object(["store": .string(id), "id": .string(made), "room": "garden"]), from: "today")
        try hub.edit(.object(["store": .string(id), "remove": "water"]), from: "today")
        #expect(hub.stores[id]?.array?.map { $0["room"] } == ["garden"])
        hub.flushEdits()
        #expect(events.count == 1)
        let changes = try #require(events.first?["changes"]?.array)
        #expect(changes.count == 2)
        #expect(changes[0]["store"]?.string == id && changes[0]["add"]?["room"] == "garden" && changes[0]["add"]?["id"]?.string == made && changes[0]["from"] == "today")
        #expect(changes[1]["remove"] == "water")
        hub.flushEdits()
        #expect(events.count == 1)
    }

    @Test func anEditNamesAStoreThatExists() throws {
        let hub = hub { _ in }
        #expect(throws: Hub.OperationError.self) { try hub.edit(.object(["store": "ghost", "done": true]), from: "today") }
        #expect(throws: Hub.OperationError.self) { try hub.edit(.object(["done": true]), from: "today") }
        #expect(throws: Hub.OperationError.self) { try hub.edit(.object(["item": "a", "done": true]), from: "today") }
    }

    @Test func aTextStoreEditIsSentAtOnceAndShownUntilAcknowledged() throws {
        var events: [JSONValue] = []
        let hub = hub { events.append($0) }
        let id = "daily-\(UUID().uuidString)"
        let file: JSONValue = .object(["path": "/notes/daily.org", "name": "daily.org", "exists": true, "text": "- [ ] Milk\n", "updated": "2026-11-07T10:00:00Z"])
        _ = try hub.apply(.object(["op": "store", "id": .string(id), "kind": "text", "data": file]))
        try hub.edit(.object(["store": .string(id), "append": "Eggs"]), from: "note")
        #expect(events.count == 1 && events[0]["kind"] == "file" && events[0]["store"]?.string == id && events[0]["record"] == nil)
        #expect(events[0]["edit"] == .object(["append": "Eggs"]))
        #expect(hub.stores[id]?["text"] == "- [ ] Milk\n- [ ] Eggs\n" && hub.stores[id]?["sync"] == "pending")
        let sent = try #require(events[0]["id"]?.string)
        hub.acknowledged([sent], failed: [sent: "the file is gone"])
        #expect(hub.stores[id]?["sync"] == "failed" && hub.stores[id]?["error"] == "the file is gone")
        #expect(throws: Hub.OperationError.self) { try hub.edit(.object(["store": .string(id), "id": "x", "append": "Eggs"]), from: "note") }
    }

    @Test func aFolderStoreEditNamesItsFileAndCanAddOrDeleteOne() throws {
        var events: [JSONValue] = []
        let hub = hub { events.append($0) }
        let id = "notes-\(UUID().uuidString)"
        let note: JSONValue = .object(["id": "a.org", "name": "a.org", "path": "/notes/a.org", "title": "A", "tags": [], "text": "- [ ] One\n", "updated": "2026-11-07T10:00:00Z"])
        _ = try hub.apply(.object(["op": "store", "id": .string(id), "kind": "folder", "data": .array([note])]))
        try hub.edit(.object(["store": .string(id), "id": "a.org", "toggle": "One"]), from: "notes")
        try hub.edit(.object(["store": .string(id), "add": "b.org", "text": "#+title: B\n"]), from: "notes")
        #expect(events.map { $0["kind"] } == ["file", "file"] && events[0]["record"] == "a.org" && events[1]["record"] == nil)
        #expect(events[1]["edit"] == .object(["add": "b.org", "text": "#+title: B\n"]))
        let records = try #require(hub.stores[id]?.array)
        #expect(records.count == 2 && records[0]["text"] == "- [X] One\n" && records[0]["sync"] == "pending")
        #expect(records[1]["id"] == "b.org" && records[1]["text"] == "#+title: B\n" && records[1]["sync"] == "pending")
        try hub.edit(.object(["store": .string(id), "id": "a.org", "delete": true]), from: "notes")
        #expect(hub.stores[id]?.array?.map { $0["id"] } == ["b.org"])
        #expect(throws: Hub.OperationError.self) { try hub.edit(.object(["store": .string(id), "delete": true]), from: "notes") }
        #expect(throws: Hub.OperationError.self) { try hub.edit(.object(["store": .string(id), "toggle": "One"]), from: "notes") }
        _ = try hub.apply(.object(["op": "store", "id": .string(id), "kind": "folder", "record": .object(["id": "c.org", "name": "c.org", "text": ""])]))
        _ = try hub.apply(.object(["op": "store", "id": .string(id), "drop": "a.org"]))
        hub.acknowledged(Set(events.compactMap { $0["id"]?.string }), failed: [:])
        #expect(hub.stores[id]?.array?.map { $0["id"] } == ["c.org"])
    }

    @Test func aRecordsFileIsDescribedAsThePhoneHoldsIt() throws {
        let hub = hub { _ in }
        let id = "docs-\(UUID().uuidString)"
        _ = try hub.apply(.object(["op": "store", "id": .string(id), "data": .array([.object(["id": "lease", "title": "Lease", "file": "/vault/lease.pdf"])]),
                                   "declare": .object(["name": "Documents", "symbol": "doc", "title": "$title"])]))
        var file = try #require(hub.stores[id]?.array?.first?["file"])
        #expect(file["path"] == "/vault/lease.pdf" && file["name"] == "lease.pdf" && file["format"] == "pdf" && file["ready"] == false)
        #expect(file["store"]?.string == id && file["id"] == "lease")
        let local = URL.temporaryDirectory.appending(path: UUID().uuidString)
        try Data("pdf".utf8).write(to: local)
        _ = try hub.apply(.object(["op": "attachment", "store": .string(id), "id": "lease", "name": "Lease v4.pdf", "size": .number(3), "version": "v4"]))
        #expect(hub.stores[id]?.array?.first?["file"]?["ready"] == false)
        _ = try hub.apply(.object(["op": "attachment", "store": .string(id), "id": "lease", "name": "Lease v4.pdf", "size": .number(3), "part": .number(1), "of": .number(1), "local": .string(local.path)]))
        file = try #require(hub.stores[id]?.array?.first?["file"])
        #expect(file["ready"] == true && file["name"] == "Lease v4.pdf" && file["size"] == .number(3))
        #expect(hub.attachments.url(id, "lease")?.lastPathComponent == "Lease v4.pdf")
        #expect(hub.declarations[id]?["name"] == "Documents")
        _ = try hub.apply(.object(["op": "store", "id": .string(id), "data": .array([])]))
        #expect(hub.attachments.url(id, "lease") == nil)
        _ = try hub.apply(.object(["op": "store", "id": .string(id), "data": .null]))
        #expect(hub.declarations[id] == nil && hub.stores[id] == nil)
    }

    @Test func aStoreEditMergesOrReplaces() throws {
        var events: [JSONValue] = []
        let hub = hub { events.append($0) }
        let id = "groceries-\(UUID().uuidString)"
        _ = try hub.apply(.object(["op": "store", "id": .string(id), "data": .object(["list": .array(["milk", "eggs"]), "shop": "Biocoop"])]))
        try hub.edit(.object(["store": .string(id), "list": .array(["eggs", "milk"])]), from: "groceries")
        #expect(hub.stores[id] == .object(["list": .array(["eggs", "milk"]), "shop": "Biocoop"]))
        try hub.edit(.object(["store": .string(id), "replace": .object(["list": .array(["bread"])])]), from: "groceries")
        try hub.edit(.object(["store": .string(id), "shop": "Naturalia"]), from: "groceries")
        #expect(hub.stores[id] == .object(["list": .array(["bread"]), "shop": "Naturalia"]))
        hub.flushEdits()
        let change = events.last?["changes"]?.array?.first { $0["store"]?.string == id }
        #expect(change?["patch"] == .object(["replace": .object(["list": .array(["bread"])]), "shop": "Naturalia"]))
        #expect(EditBatch.combined(.object(["a": .number(1), "in": .object(["x": .number(1)])]), .object(["b": .null, "in": .object(["y": .null])]))
            == .object(["a": .number(1), "b": .null, "in": .object(["x": .number(1), "y": .null])]))
    }

    @Test func aStoreIsWhatTheAgentHoldsWithYourEditsItHasNotConfirmed() throws {
        var events: [JSONValue] = []
        let hub = hub { events.append($0) }
        let id = "shopping-\(UUID().uuidString)"
        func arrives(_ data: [String: JSONValue]) {
            _ = hub.apply(batch: [.object(["op": "store", "id": .string(id), "data": .object(data)])])
        }
        arrives(["list": .array(["milk"]), "shop": "Biocoop"])
        try hub.edit(.object(["store": .string(id), "list": .array(["milk", "eggs"])]), from: "shopping")
        arrives(["list": .array(["milk"]), "shop": "Naturalia"])
        let yours: JSONValue = .object(["list": .array(["milk", "eggs"]), "shop": "Naturalia"])
        #expect(hub.stores[id] == yours)
        hub.flushEdits()
        let sent = try #require(events.last { $0["kind"] == "edits" }?["id"]?.string)
        #expect(hub.stores[id] == yours && Hub().stores[id] == yours)
        arrives(["list": .array(["milk", "eggs"]), "shop": "Naturalia", "aisle": .number(3)])
        hub.acknowledged([sent], failed: [:])
        let held: JSONValue = .object(["list": .array(["milk", "eggs"]), "shop": "Naturalia", "aisle": .number(3)])
        #expect(hub.stores[id] == held && Hub().stores[id] == held)
        _ = hub.apply(batch: [.object(["op": "store", "id": .string(id), "data": .null])])
        #expect(hub.stores[id] == nil)
    }

    @Test func actionsAreTitledHandlers() {
        let context = CardContext(cardID: "c", component: { _ in nil }, onSend: { _, _ in })
        let scope = Scope(values: ["item": .object(["id": "water"])], boxes: [], context: context)
        let actions = Interactions.parse(.array([
            .object(["title": "Done", "symbol": "checkmark", "edit": .object(["store": "tasks", "id": "$item.id", "done": true])]),
            .object(["title": "Delete", "role": "destructive", "edge": "leading", "send": .object(["forget": "$item.id"])]),
            .object(["symbol": "star"]),
            .object(["title": "Nothing"]),
        ]), scope)
        #expect(actions.map(\.title) == ["Done", "Delete"])
        #expect(actions[0].action.steps.first?.verbs.map(\.name) == ["edit"])
        #expect(actions[0].action.steps.first?.verbs.first?.raw == .object(["store": "tasks", "id": "$item.id", "done": true]))
        #expect(actions[1].leading && actions[1].destructive)
        #expect(context.diagnostics.count == 2)
    }

    @Test func aHandlerMayEditAndRunACommand() async {
        let context = CardContext(cardID: "c", component: { _ in nil }, onSend: { _, _ in })
        let host = ScriptHost(spec: ScriptSpec(.object(["script": "function done() { return {edit: {item: 'water', done: true}, command: 'water', args: {room: 'kitchen'}} }"]))!,
                              data: .null, context: context, state: StateBox([:]), derived: StateBox([:]))
        let outcome = await host.handle("done", args: nil)
        #expect(outcome?.then.array?.map { $0.object?.keys.sorted() } == [["args", "command"], ["edit"]])
        #expect(outcome?.then.array?.first?["args"] == .object(["room": "kitchen"]))
    }

    @Test func aCommandIsSentAtOnceAndShownRunningUntilThePluginAnswers() throws {
        var events: [JSONValue] = []
        let hub = hub { events.append($0) }
        #expect(hub.command("pr_review", args: .object(["pr": .number(312)]), from: "prs") == nil)
        #expect(events.count == 1 && events[0]["kind"] == "command" && events[0]["name"] == "pr_review" && events[0]["args"]?["pr"] == .number(312))
        let id = try #require(events[0]["id"]?.string)
        #expect(LiveValues.shared.value("commands")?["pr_review"]?["status"] == "running")
        #expect(hub.command("pr_review", args: .null, from: "prs") == "The command pr_review is already running")
        #expect(events.count == 1)
        _ = try hub.apply(.object(["op": "acked", "ids": .array([.string(id)]), "answers": .object([id: .array([
            .object(["op": "command", "name": "pr_review", "status": "done", "result": .object(["verdict": "ok"]), "duration": .number(40), "at": "now", "args": .object(["pr": .number(312)])]),
        ])])]))
        #expect(hub.outgoing.events.contains { $0["id"]?.string == id } == false)
        let run = try #require(LiveValues.shared.value("commands")?["pr_review"])
        #expect(run["status"] == "done" && run["result"]?["verdict"] == "ok" && run["duration"] == .number(40) && run["id"] == nil)
        #expect(hub.command("pr_review", args: .null, from: "prs") == nil && events.count == 2)
        let second = try #require(events[1]["id"]?.string)
        hub.acknowledged([second], failed: [second: "Already running"])
        #expect(LiveValues.shared.value("commands")?["pr_review"]?["status"] == "failed")
        #expect(LiveValues.shared.value("commands")?["pr_review"]?["error"] == "Already running")
        hub.outgoing.acknowledge([id, second])
    }
}

/// What waits to be told survives the app going away.
@MainActor
@Suite("Edit batch")
struct EditBatchTests {
    @Test func whatWaitsIsStillThereAfterARestart() throws {
        let file = "pending-\(UUID().uuidString).json"
        let batch = EditBatch(file: file)
        batch.change(.object(["store": "groceries", "patch": .object(["list": .array(["milk"])])]), from: "shopping")
        batch.change(.object(["store": "groceries", "patch": .object(["shop": "Biocoop"])]), from: "today")
        let again = EditBatch(file: file)
        let event = try #require(again.take())
        let changes = try #require(event["changes"]?.array)
        #expect(changes.count == 1 && changes[0]["store"] == "groceries" && changes[0]["from"] == "today")
        #expect(changes[0]["patch"] == .object(["list": .array(["milk"]), "shop": "Biocoop"]))
        #expect(again.take() == nil && EditBatch(file: file).isEmpty)
    }

    @Test func aStoreYouEditedIsKept() async throws {
        let id = "edited-\(UUID().uuidString)"
        let hub = Hub()
        _ = hub.apply(batch: [.object(["op": "store", "id": .string(id), "data": .object(["list": .array(["milk"])])])])
        try hub.edit(.object(["store": .string(id), "list": .array(["milk", "eggs"])]), from: "shopping")
        hub.flushEdits()
        #expect(Hub().stores[id] == .object(["list": .array(["milk", "eggs"])]))
    }

    @Test func onlyTheLastCapturesAreKept() {
        let captures = Captures()
        let first = captures.keep(Data([1]), as: "card")
        for _ in 0..<Captures.kept { _ = captures.keep(Data([2]), as: "card") }
        captures.hold(["preview.png": Data([3])])
        #expect(captures[first] == nil && captures["preview.png"] == Data([3]))
    }
}
