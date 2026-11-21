// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import Testing
@testable import Hermes

/// Events leave in messages the relay accepts: a burst too large for one is
/// split, in order.
@MainActor
@Suite("Relay batches")
struct RelayBatchesTests {
    @Test func aBurstLargerThanAMessageIsSplitInOrder() {
        let big = String(repeating: "x", count: 150 * 1024)
        let events: [JSONValue] = (0..<5).map { .object(["kind": .string("symbols"), "n": .number(Double($0)), "data": .string(big)]) }
        let batches = Relay.batches(events)
        #expect(batches.count == 3)
        #expect(batches.flatMap { $0 }.compactMap { $0["n"]?.number } == [0, 1, 2, 3, 4])
        #expect(batches.allSatisfy { JSONValue.array($0).data().count <= Relay.messageBudget })
    }

    @Test func smallEventsShareOneMessage() {
        let events: [JSONValue] = (0..<20).map { .object(["kind": .string("rendered"), "n": .number(Double($0))]) }
        #expect(Relay.batches(events).count == 1)
    }
}
