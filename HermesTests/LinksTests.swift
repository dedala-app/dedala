// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import Foundation
import Testing
@testable import Hermes

/// Links written in a note: how the reader carries them, and which record
/// each one opens.
@MainActor
@Suite("Links")
struct LinksTests {
    private static func inline(_ text: String, format: String) -> AttributedString {
        let paragraph = OrgTree.select(OrgTree.parse(text, format: format), "paragraph").first ?? .null
        return Inline.attributed(paragraph["children"]?.array ?? [])
    }

    @Test func orgLinksAreCarriedAsURLsTheReaderTellsApart() {
        let text = Self.inline("See [[denote:20251109T181549][the SC]], [[file:plan.md]], [[*Members]] and [[https://nixos.org][NixOS]].", format: "org")
        let links = text.runs.compactMap(\.link)
        #expect(links.count == 4)
        #expect(DocumentLink.target(of: links[0]) == "denote:20251109T181549")
        #expect(DocumentLink.target(of: links[1]) == "file:plan.md" && String(text.characters).contains("plan.md"))
        #expect(DocumentLink.target(of: links[2]) == "*Members")
        #expect(DocumentLink.target(of: links[3]) == nil && links[3].host == "nixos.org")
        let markdown = Self.inline("See [[Committee|the SC]] and [the plan](plan.md).", format: "markdown")
        let found = markdown.runs.compactMap(\.link)
        #expect(found.count == 2 && DocumentLink.target(of: found[0]) == "Committee" && DocumentLink.target(of: found[1]) == "plan.md")
        #expect(String(markdown.characters) == "See the SC and the plan.")
    }

    @Test func aLinkOpensTheRecordItNamesInTheSameFolderFirst() throws {
        let hub = Hub()
        let store = "notes-\(UUID().uuidString.prefix(6))"
        let other = "wiki-\(UUID().uuidString.prefix(6))"
        let report: JSONValue = .object(["id": "2026/report.org", "path": .string("/n/\(store)/2026/report.org"), "title": "Report", "identifier": "20260401T225935"])
        let committee: JSONValue = .object(["id": "20251109T181549--sc.org", "path": .string("/n/\(store)/sc.org"), "title": "Committee", "identifier": "20251109T181549"])
        let plan: JSONValue = .object(["id": "2026/plan.md", "path": .string("/n/\(store)/2026/plan.md"), "title": "The plan"])
        _ = try hub.apply(.object(["op": "store", "id": .string(store), "kind": "folder", "data": .array([report, committee, plan])]))
        _ = try hub.apply(.object(["op": "store", "id": .string(other), "kind": "folder", "data": .array([.object(["id": "Committee.md", "path": "/w/Committee.md", "title": "Committee"])])]))
        defer {
            _ = try? hub.apply(.object(["op": "store", "id": .string(store), "data": .null]))
            _ = try? hub.apply(.object(["op": "store", "id": .string(other), "data": .null]))
        }
        #expect(Records.linked("denote:20251109T181549", from: report, hub: hub) == RecordRef(store: store, record: "20251109T181549--sc.org"))
        #expect(Records.linked("file:plan.md", from: report, hub: hub) == RecordRef(store: store, record: "2026/plan.md"))
        #expect(Records.linked("plan.md", from: report, hub: hub) == RecordRef(store: store, record: "2026/plan.md"))
        #expect(Records.linked("Committee", from: report, hub: hub) == RecordRef(store: store, record: "20251109T181549--sc.org"))
        #expect(Records.linked("Committee", from: .object(["path": "/w/Committee.md"]), hub: hub) == RecordRef(store: other, record: "Committee.md"))
        #expect(Records.linked("*Members", from: report, hub: hub) == nil)
        #expect(Records.linked("denote:00000000T000000", from: report, hub: hub) == nil)
    }
}
