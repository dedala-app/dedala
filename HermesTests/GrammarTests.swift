// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import Foundation
import Testing
@testable import Hermes

/// The plugin checks cards before they reach the phone with
/// plugin/dedala/grammar.json: it must know what the app draws.
@MainActor
@Suite("Grammar")
struct GrammarTests {
    let written: JSONValue = {
        let url = Bundle(for: GrammarMarker.self).url(forResource: "grammar", withExtension: "json")!
        return try! JSONValue.parse(Data(contentsOf: url))
    }()

    /// The file is the interpreter's own tables written out: `./mac grammar` writes it again after a change.
    @Test func thePluginsGrammarIsTheApps() {
        for (key, value) in Views.grammar.object ?? [:] {
            #expect(written[key] == value, "\(key) differs: run ./mac grammar")
        }
        #expect(Set(written.object?.keys.map { $0 } ?? []) == Set(Views.grammar.object?.keys.map { $0 } ?? []))
    }

    @Test func everyModifierInTheOrderHasItsEffect() {
        let special: Set<String> = ["frame", "clip", "border", "overlay", "onTap", "disabled"]
        for name in Modifiers.order where !special.contains(name) {
            #expect(Modifiers.effect(name) != nil, "\(name)")
        }
    }

    @Test func everyListedViewIsDrawn() {
        for name in Views.names {
            let context = CardContext(cardID: name, component: { _ in nil }, onSend: { _, _ in })
            _ = Tree.render(Tree.node(.object([name: .null])), Scope(values: [:], boxes: [], context: context))
            #expect(!context.diagnostics.contains("Unknown view '\(name)'"), "\(name)")
        }
    }

    @Test func aViewTakesWhatItReads() {
        #expect(Views.arguments["VStack"]?.keys.sorted() == ["alignment", "spacing"])
        #expect(Views.arguments["Gauge"]?.keys.sorted() == ["current", "in", "label", "max", "min", "style"])
        #expect(Views.arguments["Toggle"]?["bind"] == .binding && Views.arguments["Button"]?["action"] == .action)
        #expect(Element.flow["ForEach"]?.keys.sorted() == ["as", "content", "index", "onMove"])
        #expect(Views.containers.contains("Card") && !Views.containers.contains("Section") && !Views.names.contains("Masonry"))
    }
}
private final class GrammarMarker {}
