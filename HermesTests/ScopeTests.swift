// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import Foundation
import SwiftUI
import Testing
@testable import Hermes

@MainActor
@Suite("Scope")
struct ScopeTests {
    let scope = Scope(
        values: ["sc": .object(["prs": [.object(["number": .number(299)])]]), "title": "PRs"],
        boxes: [],
        context: CardContext(cardID: "test", component: { _ in nil }, onSend: { _, _ in })
    )

    @Test func namesAreWhatAStringReadsNotWhatItCalls() {
        #expect(Scope.names(in: "$item.number") == ["item"])
        #expect(Scope.names(in: "#${item.number} by ${count(sc.prs)}") == ["item", "sc"])
        #expect(Scope.names(in: "${a.b == \"x y\" and not done}") == ["a", "done"])
        #expect(Scope.names(in: "plain") == [])
    }

    /// A view handed to a component keeps what only its own ForEach binds.
    @Test func aViewPassedToAComponentKeepsItsLoopVariables() {
        let view: JSONValue = .object(["VStack": [
            .object(["Text": "$title"]),
            .object(["ForEach": "$sc.prs", "content": .object(["Text": "#${item.number}"])]),
        ]])
        let resolved = scope.resolveKnown(view)
        #expect(resolved["VStack"]?.array?[0]["Text"] == "PRs")
        #expect(resolved["VStack"]?.array?[1]["ForEach"]?.array?.count == 1)
        #expect(resolved["VStack"]?.array?[1]["content"]?["Text"] == "#${item.number}")
    }

    /// A condition is an expression however its names are written.
    @Test func aConditionIsEvaluatedWhateverItStartsWith() {
        let scope = Scope(values: ["a": true, "b": false, "n": .number(3), "items": .array([])], boxes: [],
                          context: CardContext(cardID: "test", component: { _ in nil }, onSend: { _, _ in }))
        #expect(scope.truthy("$a && $b") == false)
        #expect(scope.truthy("$a && !$b") == true)
        #expect(scope.truthy("$n > 5") == false)
        #expect(scope.truthy("!$a && $b") == false)
        #expect(scope.truthy("$a") == true && scope.truthy("$b") == false)
        #expect(scope.truthy("${n > 2}") == true)
        #expect(scope.truthy("count(items) == 0") == true)
    }

    /// Numbers no count, line or index can be never reach the views.
    @Test func numbersBeyondCountingAreNone() {
        #expect(JSONValue.string("infinity").int == nil && JSONValue.string("nan").int == nil)
        #expect(JSONValue.number(1e19).int == nil && JSONValue.number(-1e300).int == nil)
        #expect(JSONValue.number(3.9).int == 3 && JSONValue.string("12").int == 12)
        #expect(JSONValue.number(.infinity).finite == nil && JSONValue.number(2.5).finite == 2.5)
        #expect(scope.step(Dynamic(.number(0))) == nil && scope.step(Dynamic(.number(-1))) == nil && scope.step(Dynamic(.number(0.5))) == 0.5)
        #expect(scope.evaluate("sc.prs[1e19]") == .null)
        #expect(scope.evaluate("sc.prs[0].number") == .number(299))
        for spec in ["bytes", "duration", "percent:-3", "number:999", "currency:EUR:-1", "compact"] {
            #expect(!scope.evaluate("format('infinity', '\(spec)')").text.isEmpty)
            #expect(!scope.evaluate("format(1234.5, '\(spec)')").text.isEmpty)
        }
    }

    /// The verbs of one action run in the same order every time.
    @Test func anActionsVerbsRunInAFixedOrder() {
        #expect(ActionRunner.order(["set", "edit", "say", "haptic"]) == ["edit", "set", "haptic"])
        #expect(ActionRunner.order(["page", "toggle", "send", "require", "command"]) == ["send", "command", "toggle", "page"])
        #expect(ActionRunner.order(["zap", "send", "abc"]) == ["send", "abc", "zap"])
    }

    /// Hostile numbers draw something rather than stopping the app.
    @Test func hostileNumbersStillDraw() {
        let context = CardContext(cardID: "hostile", component: { _ in nil }, onSend: { _, _ in })
        let scope = Scope(values: [:], boxes: [], context: context)
        func draw(_ node: JSONValue, _ scope: Scope) {
            _ = Tree.render(Tree.node(node), scope)
        }
        draw(.object(["Columns": .array(["a", "b"]), "count": .number(1e19)]), scope)
        draw(.object(["Columns": .array(["a", "b"]), "count": "infinity"]), scope)
        draw(.object(["Slider": "Volume", "bind": "$v", "in": .array([.number(0), "infinity"]), "step": .number(0)]), scope.with(["v": .number(1)]))
        draw(.object(["Text": "x", "lineLimit": "infinity"]), scope)
        draw(.object(["Text": "x", "lineLimit": .number(1e300)]), scope)
    }
}
