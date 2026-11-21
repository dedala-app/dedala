// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import Foundation
import Testing
@testable import Hermes

/// Search finds a thing by any of its words, wherever they are, and says
/// where it found them.
@Suite("Search")
struct SearchTests {
    let page = Search.Entry(kind: .page, id: "day", title: "Today", symbol: "sun.max",
                            texts: ["Nothing on the calendar; the day is yours.", "PBS backups failing, Deel card declined"])
    let lease = Search.Entry(kind: .record, id: "documents/lease", title: "Lease · 12 rue des Lilas", symbol: "doc",
                             subtitle: "Contract · Marta Ribeiro", texts: ["Marta Ribeiro", "notice period of three months"], at: .now, group: "Documents")
    let old = Search.Entry(kind: .message, id: "m1", title: "Jacques", symbol: "bubble.left", texts: ["Marseille 4–3 Le Havre at the Vélodrome"],
                           conversation: "main", at: Date(timeIntervalSinceNow: -3600))
    let new = Search.Entry(kind: .message, id: "m2", title: "Jacques", symbol: "bubble.left", texts: ["The Vélodrome was full"],
                           conversation: "main", at: .now)

    @Test func aWordOnAPageFindsThePageAndSaysWhere() {
        let hits = Search.hits(for: "deel", in: [page, lease])
        #expect(hits.map(\.target) == ["day"])
        #expect(hits[0].line == "PBS backups failing, Deel card declined")
    }

    @Test func accentsAndCaseDoNotMatter() {
        let hits = Search.hits(for: "velodrome", in: [old, new])
        #expect(hits.count == 2)
        #expect(hits[0].target == "m2")
    }

    @Test func everyWordMustBeFoundSomewhere() {
        #expect(Search.hits(for: "marta three", in: [lease, page]).map(\.target) == ["documents/lease"])
        #expect(Search.hits(for: "marta deel", in: [lease, page]).isEmpty)
    }

    @Test func kindsComeInOrderAndTitlesFirst() {
        let byTitle = Search.Entry(kind: .page, id: "lease-page", title: "Lease", symbol: "doc")
        let hits = Search.hits(for: "lease", in: [lease, page, byTitle])
        #expect(hits.map(\.target) == ["lease-page", "documents/lease"])
        #expect(hits[1].line == "Contract · Marta Ribeiro")
    }

    @Test func aLongTextIsCutAroundTheWord() {
        let long = String(repeating: "before ", count: 30) + "needle" + String(repeating: " after", count: 30)
        let line = Search.snippet(long, around: "needle")
        #expect(line.count < 100)
        #expect(line.contains("needle"))
        #expect(line.hasPrefix("…") && line.hasSuffix("…"))
    }

    @Test func aViewsWordsComeFromWhatItShowsAndItsComponents() throws {
        let components: [String: JSONValue] = ["Tile": .object(["body": .object(["VStack": [.object(["Text": "Read at 18:00"]), .object(["Label": ["Weather", "cloud"]])]])])]
        let view: JSONValue = .object(["VStack": [.object(["Text": "$day.sentence", "font": "title"]), .object(["Tile": .object([:])]), .object(["Button": "Save", "action": .object(["send": "x"])])]])
        #expect(Set(Search.texts(in: view, components: components)) == ["Read at 18:00", "Weather", "Save"])
        #expect(Search.strings(in: .object(["a": .object(["b": "deep", "c": .number(3)]), "d": ["x", "y"]])) == ["deep", "x", "y"])
    }

    @Test func historyKeepsTheLatestFirstWithoutRepeats() {
        var history = Search.History()
        for words in ["lease", "deel", "Lease", "a", "b", "c", "d"] { history.searched(words) }
        #expect(history.searches == ["d", "c", "b", "a", "Lease"])
        let lease = Search.History.Opened(kind: .record, target: "documents/lease", title: "Lease", symbol: "doc")
        let day = Search.History.Opened(kind: .page, target: "day", title: "Today", symbol: "sun.max")
        history.opened(lease)
        history.opened(day)
        history.opened(lease)
        #expect(history.opened.map(\.target) == ["documents/lease", "day"])
    }

    @MainActor
    @Test func aDeclaredStoresRecordsAreFoundByWhatItsDeclarationSays() throws {
        let hub = Hub()
        let id = "people-\(UUID().uuidString)"
        _ = hub.apply(batch: [.object(["op": "store", "id": .string(id),
                                       "data": .array([.object(["id": "theo", "name": "Théo Lefèvre", "role": "Botany", "email": "theo@example.org", "updated": "2026-11-01T10:00:00Z"]),
                                                       .object(["id": "ryan", "name": "Ryan Lahfa", "role": "NixOS", "updated": "2026-11-05T10:00:00Z"])]),
                                       "declare": .object(["name": "People", "symbol": "person", "title": "$name", "subtitle": "${role} · ${email}", "words": ["$email"]])])])
        let entries = Search.records(hub: hub)
        #expect(entries.map(\.id) == ["\(id)/theo", "\(id)/ryan"])
        #expect(entries[0].title == "Théo Lefèvre" && entries[0].subtitle == "Botany · theo@example.org" && entries[0].texts == ["theo@example.org"])
        #expect(entries[0].group == "People" && entries[0].symbol == "person" && entries[1].subtitle == "NixOS · ")
        #expect(Search.hits(for: "example", in: entries).map(\.target) == ["\(id)/theo"])
        #expect(Search.latest(hub: hub).map(\.id) == ["\(id)/ryan", "\(id)/theo"])
        #expect(RecordRef("\(id)/theo")?.record == "theo" && RecordRef("notes/2026/a.org")?.record == "2026/a.org" && RecordRef("plain") == nil)
        _ = hub.apply(batch: [.object(["op": "store", "id": .string(id), "declare": .null])])
        #expect(Search.records(hub: hub).isEmpty)
    }
}
