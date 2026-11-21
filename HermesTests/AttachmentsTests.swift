// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import Foundation
import Testing
@testable import Hermes

/// A record's file: described first, fetched in parts when asked for, kept
/// within the budget.
@MainActor
@Suite("Attachments", .serialized)
struct AttachmentsTests {
    private func part(_ bytes: [UInt8]) -> String {
        let url = URL.temporaryDirectory.appending(path: UUID().uuidString)
        try! Data(bytes).write(to: url)
        return url.path
    }

    @Test func aDescribedFileIsFetchedInPartsAndKeptUntilItsVersionChanges() throws {
        let attachments = Attachments()
        let store = "docs-\(UUID().uuidString.prefix(6))"
        defer { attachments.forget(store: store) }
        var asked: [String] = []
        attachments.fetch = { _, record in asked.append(record) }
        try attachments.apply(.object(["op": "attachment", "store": .string(store), "id": "lease", "name": "lease.pdf", "size": .number(6), "version": "v1"]))
        let described = attachments.describe("/x/lease.pdf", store: store, record: "lease")
        #expect(described["ready"] == false && described["size"] == .number(6) && described["format"] == "pdf" && attachments.url(store, "lease") == nil)
        attachments.request(store, "lease")
        attachments.request(store, "lease")
        #expect(asked == ["lease"] && attachments.describe("/x/lease.pdf", store: store, record: "lease")["fetching"] == true)
        try attachments.apply(.object(["op": "attachment", "store": .string(store), "id": "lease", "name": "lease.pdf", "size": .number(6), "part": .number(1), "of": .number(2), "local": .string(part([1, 2, 3]))]))
        #expect(attachments.describe("/x/lease.pdf", store: store, record: "lease")["received"] == .number(3) && attachments.url(store, "lease") == nil)
        try attachments.apply(.object(["op": "attachment", "store": .string(store), "id": "lease", "name": "lease.pdf", "size": .number(6), "part": .number(2), "of": .number(2), "local": .string(part([4, 5, 6]))]))
        let url = try #require(attachments.url(store, "lease"))
        #expect(try Data(contentsOf: url) == Data([1, 2, 3, 4, 5, 6]))
        try attachments.apply(.object(["op": "attachment", "store": .string(store), "id": "lease", "name": "lease.pdf", "size": .number(6), "version": "v1"]))
        #expect(attachments.url(store, "lease") != nil)
        try attachments.apply(.object(["op": "attachment", "store": .string(store), "id": "lease", "name": "lease.pdf", "size": .number(7), "version": "v2"]))
        #expect(attachments.url(store, "lease") == nil && attachments.describe("/x/lease.pdf", store: store, record: "lease")["size"] == .number(7))
        attachments.refused(store, "lease", "No file to fetch")
        #expect(attachments.describe("/x/lease.pdf", store: store, record: "lease")["error"] == "No file to fetch")
        try attachments.apply(.object(["op": "attachment", "store": .string(store), "id": "lease", "name": "lease.pdf", "missing": true]))
        #expect(attachments.describe("/x/lease.pdf", store: store, record: "lease")["missing"] == true)
    }

    @Test func theLeastRecentlyOpenedFilesGoWhenTheBudgetIsFull() throws {
        let attachments = Attachments()
        let store = "docs-\(UUID().uuidString.prefix(6))"
        defer { attachments.forget(store: store); Attachments.budget = 2 * 1024 * 1024 * 1024 }
        Attachments.budget = 5
        for (record, bytes) in [("a", [UInt8](repeating: 1, count: 3)), ("b", [UInt8](repeating: 2, count: 3))] {
            try attachments.apply(.object(["op": "attachment", "store": .string(store), "id": .string(record), "name": .string("\(record).bin"), "size": .number(3), "version": "v"]))
            try attachments.apply(.object(["op": "attachment", "store": .string(store), "id": .string(record), "name": .string("\(record).bin"), "size": .number(3), "part": .number(1), "of": .number(1), "local": .string(part(bytes))]))
        }
        #expect(attachments.url(store, "a") == nil && attachments.url(store, "b") != nil)
        #expect(attachments.describe("/x/a.bin", store: store, record: "a")["ready"] == false)
    }
}
