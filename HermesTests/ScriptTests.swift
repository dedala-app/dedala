// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import Foundation
import Testing
@testable import Hermes

/// Scripts compute from what is on the phone, with the time they are given,
/// and nothing they do can hang the app.
@MainActor
@Suite("Scripts")
struct ScriptTests {
    let now = "2026-10-25T14:00:00+01:00"

    @Test func aDerivedValueComesFromDataAndState() async throws {
        let source = """
        function shares({data, state}) {
          const who = data.people.filter(p => !state.left_out.includes(p))
          return who.map(p => ({name: p, owes: h.round(data.total / who.length, 2)}))
        }
        """
        let input: JSONValue = .object([
            "data": .object(["total": .number(90), "people": ["Julien", "Manon", "Théo"]]),
            "state": .object(["left_out": ["Théo"]]), "now": .string(now),
        ])
        let result = try await ScriptEngine.shared.call(source, function: "shares", input: input, limit: 1).get()
        #expect(result == [.object(["name": "Julien", "owes": .number(45)]), .object(["name": "Manon", "owes": .number(45)])])
    }

    @Test func theTimeIsTheOneGiven() async throws {
        let source = "function when({now}) { return [new Date().toISOString(), Date.now(), h.until('2026-10-28T14:00:00+01:00', now).text] }"
        let result = try await ScriptEngine.shared.call(source, function: "when", input: .object(["now": .string(now)]), limit: 1).get()
        #expect(result == ["2026-10-25T13:00:00.000Z", .number(1_792_933_200_000), "in 3 days"])
    }

    @Test func theListHelpersSortAndGroup() async throws {
        let source = "function newest({data}) { return h.sortBy(data.docs, 'at', {desc: true}).map(d => d.id) }"
        let docs: JSONValue = [.object(["id": "offer", "at": "2026-10-20"]), .object(["id": "nda", "at": "2026-10-25"])]
        let result = try await ScriptEngine.shared.call(source, function: "newest", input: .object(["now": .string(now), "data": .object(["docs": docs])]), limit: 1).get()
        #expect(result == ["nda", "offer"])
    }

    @Test func sharedModulesAreThereForEveryScript() async throws {
        ScriptEngine.modules["money"] = "function twice(x) { return x * 2 }\nreturn {twice}"
        defer { ScriptEngine.modules["money"] = nil }
        let result = try await ScriptEngine.shared.call("function go() { return money.twice(21) }", function: "go", input: .object(["now": .string(now)]), limit: 1).get()
        #expect(result == .number(42))
    }

    @Test func aScriptThatThrowsSaysWhy() async {
        let result = await ScriptEngine.shared.call("function go() { return nope.x }", function: "go", input: .object(["now": .string(now)]), limit: 1)
        guard case .failure(let failure) = result else { Issue.record("it should fail"); return }
        #expect(failure.message.contains("nope"))
    }

    @Test func anEndlessScriptIsAbandonedThenSwitchedOff() async {
        let source = "function spin() { while (true) {} }"
        let input: JSONValue = .object(["now": .string(now)])
        for _ in 0..<2 {
            let result = await ScriptEngine.shared.call(source, function: "spin", input: input, limit: 0.05)
            guard case .failure(let failure) = result else { Issue.record("it should time out"); return }
            #expect(failure.timedOut)
        }
        let third = await ScriptEngine.shared.call(source, function: "spin", input: input, limit: 0.05)
        guard case .failure(let failure) = third else { Issue.record("it should be off"); return }
        #expect(failure.message.contains("switched off"))
        let other = await ScriptEngine.shared.call("function ok() { return 1 }", function: "ok", input: input, limit: 1)
        #expect((try? other.get()) == .number(1))
    }

    @Test func aHandlerTurnsIntoActions() async {
        let context = CardContext(cardID: "split", component: { _ in nil }, onSend: { _, _ in })
        let spec = ScriptSpec(.object(["script": "function ask({state}) { return {state: {asked: true}, send: {tip: state.tip}, say: 'Ask them'} }"]))!
        let host = ScriptHost(spec: spec, data: .object([:]), context: context, state: StateBox(["tip": .number(10)]), derived: StateBox([:]))
        let outcome = await host.handle("ask", args: nil)
        #expect(outcome?.state == ["asked": .bool(true)])
        #expect(outcome?.then == [.object(["send": .object(["tip": .number(10)]), "say": "Ask them"])])
    }

    @Test func aHandlerGetsTheSecondOfTheTap() {
        let context = CardContext(cardID: "watch", component: { _ in nil }, onSend: { _, _ in })
        let host = ScriptHost(spec: ScriptSpec(.object(["script": "function f() {}"]))!, data: .object([:]), context: context, state: StateBox([:]), derived: StateBox([:]))
        let tapped = host.input(exact: true)["now"]?.date ?? .distantPast
        #expect(abs(tapped.timeIntervalSinceNow) < 2)
    }

    @Test func stateYouChangedIsKeptAndWins() {
        var stored: [String: [String: JSONValue]] = [:]
        let saved = SavedState(["card": ["taps": .number(5)]]) { stored = $0 }
        #expect(saved.values(at: "card") == ["taps": .number(5)])
        saved.set(["taps": .number(6), "running": .bool(true)], at: "card")
        #expect(stored["card"] == ["taps": .number(6), "running": .bool(true)])
        saved.set(["taps": .number(6), "running": .bool(true)], at: "card")
        #expect(saved.values(at: "node › 1.") == [:])
    }

    @Test func stateDeclaredAgainInsideAPageIsTheSameState() {
        let context = CardContext(cardID: "note", component: { _ in nil }, onSend: { _, _ in })
        let page = StateBox(["picked": []])
        let scope = Scope(values: [:], boxes: [page], context: context)
        _ = Tree.render(Tree.node(.object(["VStack": [], "state": .object(["picked": [], "draft": ""])])), scope)
        #expect(context.diagnostics.contains { $0.hasPrefix("state picked is already declared") })
    }

    @Test func aWaitingCardHasAButtonThatAnswers() {
        let components: [String: JSONValue] = ["Ask": .object(["body": .object(["Button": "Yes", "action": .object(["send": "yes"])])])]
        #expect(LiveFeed.sends(.object(["VStack": [.object(["Ask": .object([:])])]]), components: components))
        #expect(!LiveFeed.sends(.object(["Toggle": "Done", "bind": "$done"]), components: components))
    }
}
