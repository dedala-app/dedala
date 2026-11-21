// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import Foundation
import Testing
@testable import Hermes

@MainActor
private func scope(_ values: [String: JSONValue] = [:]) -> Scope {
    Scope(values: values, boxes: [], context: CardContext(cardID: "test", component: { _ in nil }, onSend: { _, _ in }))
}

private func json(_ text: String) throws -> JSONValue {
    try JSONValue.parse(Data(text.utf8))
}

@Suite("Dedala UI expressions")
@MainActor
struct ExpressionTests {
    @Test("References keep their type")
    func references() throws {
        let scope = scope(["flight": try json(#"{"gate": "B32", "seat": 14}"#)])
        #expect(scope.resolve("$flight.gate") == .string("B32"))
        #expect(scope.resolve("$flight.seat") == .number(14))
        #expect(scope.resolve("${flight.seat + 1}") == .number(15))
    }

    @Test("Interpolation handles $name, ${expr}, and leaves unknown names and prices alone")
    func interpolation() {
        let scope = scope(["trade": "Plumber", "price": .number(85)])
        #expect(scope.resolve("A $trade at ${format(price, 'number')}").text == "A Plumber at 85")
        #expect(scope.resolve("Costs $5, paid in $USD").text == "Costs $5, paid in $USD")
    }

    @Test("Operators, ternaries and functions")
    func evaluation() throws {
        let scope = scope(["items": try json(#"[{"kwh": 2}, {"kwh": 4}]"#), "tone": "warm"])
        #expect(scope.evaluate("sum(items, 'kwh') / count(items)") == .number(3))
        #expect(scope.evaluate("tone == 'warm' ? 'accent' : 'fill'") == .string("accent"))
        #expect(scope.evaluate("!(1 < 2) || items[1].kwh >= 4") == .bool(true))
    }

    @Test("Bad expressions report instead of throwing")
    func badExpression() {
        let scope = scope()
        #expect(scope.evaluate("1 +") == .null)
        #expect(scope.evaluate("nope(1)") == .null)
        #expect(scope.context.diagnostics.count == 2)
    }
}

@Suite("Dedala UI trees")
@MainActor
struct TreeTests {
    @Test("Children expanded from ForEach and If never share an identity")
    func uniqueIdentities() throws {
        let tree = try json(#"""
        [
          {"Text": "Header"},
          {"ForEach": "$days", "as": "d", "content": [
            {"Text": "$d.name"},
            {"ForEach": "$d.plan", "as": "p", "content": {"Text": "$p"}}
          ]},
          {"If": "true", "then": [{"Text": "a"}, {"Text": "b"}]}
        ]
        """#)
        let days = try json(#"[{"name": "Fri", "plan": ["x", "y"]}, {"name": "Sat", "plan": ["z"]}]"#)
        let items = Tree.items(Children(tree), scope(["days": days]))
        let ids = items.map(\.id)
        #expect(Set(ids).count == ids.count)
        #expect(items.count == 1 + 3 + 2 + 2)
    }

    @Test("Patches merge objects, replace arrays and drop nulls")
    func merging() throws {
        let data = try json(#"{"flight": {"gate": null, "seat": "14A"}, "bars": [1, 2]}"#)
        let merged = data.merging(try json(#"{"flight": {"gate": "B32"}, "bars": [3], "seat": null}"#))
        #expect(merged == (try json(#"{"flight": {"gate": "B32", "seat": "14A"}, "bars": [3]}"#)))
    }
}

@Suite("Card surfaces")
@MainActor
struct CardSurfaceTests {
    private func context() -> CardContext {
        CardContext(cardID: "test", component: { _ in nil }, onSend: { _, _ in })
    }

    @Test("A bare view goes inside a Card, one that draws a surface stays")
    func wraps() throws {
        let bare = try json(#"{"VStack": [{"Text": "Hi"}], "padding": 8}"#)
        let wrapped = CardSurfaces.surfaced(bare, components: [])
        #expect(wrapped["Card"] != nil)
        #expect(wrapped["Card"]?.array?[0]["padding"] == nil)
        let card = try json(#"{"Card": [{"Text": "Hi"}]}"#)
        #expect(CardSurfaces.surfaced(card, components: []) == card)
        let sideways = try json(#"{"ScrollView": [{"Card": [{"Text": "A"}]}], "axis": "horizontal"}"#)
        #expect(CardSurfaces.surfaced(sideways, components: []) == sideways)
    }

    @Test("Loose lines around a Card go on a surface too, a list of cards stays as it is")
    func mixed() throws {
        let mixed = try json(#"{"VStack": [{"Text": "Proxmox backup mail"}, {"Card": [{"Text": "03:30 sync failed"}]}, {"Text": "What we do"}]}"#)
        #expect(CardSurfaces.surfaced(mixed, components: [])["Card"] != nil)
        let list = try json(#"{"VStack": [{"Card": [{"Text": "A"}]}, {"Flight": {}}, {"ForEach": "$legs", "content": {"Card": ["$leg"]}}]}"#)
        #expect(CardSurfaces.surfaced(list, components: ["Flight"]) == list)
        let header = try json(#"{"VStack": [{"Text": "Flights"}, {"Flight": {}}]}"#)
        #expect(CardSurfaces.surfaced(header, components: ["Flight"])["Card"] != nil)
    }

    @Test("A vertical ScrollView at the root becomes a VStack on a Card and is reported")
    func unscrolls() throws {
        let context = context()
        let view = try json(#"{"ScrollView": [{"Text": "A"}, {"Text": "B"}], "spacing": 4}"#)
        let drawn = CardSurfaces.surfaced(view, components: [], context: context)
        #expect(drawn["Card"] != nil)
        let inner = try #require(drawn["Card"]?.array?[0])
        #expect(inner["ScrollView"] == nil)
        #expect(inner["VStack"]?.array?.count == 2)
        #expect(inner["spacing"] == .number(4))
        #expect(inner["alignment"] == .string("leading"))
        #expect(context.layoutIssues().count == 1)
        #expect(context.layoutIssues()[0].hasPrefix("ScrollView at the root of a card"))
    }
}
