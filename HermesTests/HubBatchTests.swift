// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import Foundation
import Testing
@testable import Hermes

/// A batch of ops is applied and kept at once; its errors go back at once.
@MainActor
@Suite("Hub batches")
struct HubBatchTests {
    @Test func aBatchIsAppliedAndItsErrorsSentAtOnce() {
        let hub = Hub()
        var events: [JSONValue] = []
        hub.onEmit = { events.append($0) }
        let id = "batch-\(UUID().uuidString)"
        let applied = hub.apply(batch: [
            .object(["op": "store", "id": .string(id), "data": .object(["score": "2-1"])]),
            .object(["op": "store", "id": "nothing"]),
            .object(["op": "nonsense"]),
        ])
        #expect(hub.stores[id] == .object(["score": "2-1"]))
        #expect(applied.errors.count == 2 && applied.touched.isEmpty)
        #expect(events.count == 1 && events[0]["kind"] == "errors")
        #expect(events[0]["errors"]?.array?.count == 2)
    }

    @Test func whatABatchChangedIsThereAfterARestart() {
        let id = "kept-\(UUID().uuidString)"
        _ = Hub().apply(batch: [.object(["op": "store", "id": .string(id), "data": .object(["rent": .number(1480)])])])
        #expect(Hub().stores[id] == .object(["rent": .number(1480)]))
    }

    @Test func aBatchThatAsksIsAnsweredCleanOrNot() {
        let hub = Hub()
        var events: [JSONValue] = []
        hub.onEmit = { events.append($0) }
        _ = hub.apply(batch: [.object(["op": "store", "id": "asked", "data": .object([:])]), .object(["op": "check", "id": "a1"])])
        _ = hub.apply(batch: [.object(["op": "store", "id": "nothing"]), .object(["op": "check", "id": "a2"])])
        #expect(events.map { $0["kind"] } == ["checked", "checked"])
        #expect(events[0]["id"] == "a1" && events[0]["errors"] == [])
        #expect(events[1]["id"] == "a2" && events[1]["errors"]?.array?.count == 1)
    }

    @Test func aCleanBatchSendsNoErrors() {
        let hub = Hub()
        var events: [JSONValue] = []
        hub.onEmit = { events.append($0) }
        let applied = hub.apply(batch: [.object(["op": "store", "id": "clean", "data": .object([:])])])
        #expect(applied.errors.isEmpty && events.isEmpty)
    }
}
