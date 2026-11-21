// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import Foundation
import SwiftUI
import Testing
@testable import Hermes

/// A view is decoded once, and what is wrong with it is known without drawing it.
@MainActor
@Suite("Decode")
struct DecodeTests {
    func json(_ text: String) throws -> JSONValue {
        try JSONValue.parse(Data(text.utf8))
    }

    func context(_ sent: @escaping (JSONValue, String?) -> Void = { _, _ in }) -> CardContext {
        CardContext(cardID: "tree", component: { _ in nil }, onSend: sent)
    }

    @Test func mistakesAreFoundInBranchesNotDrawnAndBehindButtonsNotTapped() throws {
        let view = try json(#"""
        {"If": "$paid", "then": "Thanks",
         "else": {"VStack": [
            {"Button": "Pay", "action": {"sned": {"pay": true}}},
            {"Text": "${count(items) ==}"},
            {"Text": "Total", "paddding": 8},
            {"Label": ["Later", "clock"], "onTap": [{"set": {"later": true}}, "nothing"]}
         ]}}
        """#)
        let problems = Tree.problems(in: view)
        #expect(problems.contains("Unknown action 'sned'"))
        #expect(problems.contains("Unknown modifier or argument 'paddding' on Text"))
        #expect(problems.contains("An action must be an object, got nothing"))
        #expect(problems.contains { $0.contains("count(items) ==") || $0.lowercased().contains("expected") || $0.lowercased().contains("unexpected") })
        #expect(problems.count == 4)
    }

    @Test func aSoundViewHasNothingAgainstIt() throws {
        let view = try json(#"""
        {"Card": [
            {"HStack": [{"Text": "$title", "font": "headline"}, {"Spacer": {}}, {"Image": "airplane"}], "spacing": 8},
            {"ForEach": "$rows", "as": "row", "content": {"Toggle": "$row.name", "bind": "$on[row.id]"}},
            {"Button": "Save", "action": {"edit": {"store": "daily", "append": "$text"}, "set": {"text": ""}}, "style": "prominent"},
            {"List": "$notes", "as": "note", "content": {"Text": "$note.title"}},
            {"TextEditor": "Write…", "bind": "$text", "height": 240, "font": "mono"},
            {"File": "$doc.file", "height": 300}
        ], "state": {"on": {}, "text": ""}}
        """#)
        #expect(Tree.problems(in: view) == [])
        #expect(Set(["List", "TextEditor", "File"]).isSubset(of: Views.names) && !Views.names.contains("Item"))
        #expect(Views.arguments["List"]?.keys.sorted() == ["as", "content", "index"])
        #expect(Views.arguments["TextEditor"]?.keys.sorted() == ["bind", "font", "height", "onChange"])
    }

    @Test func whatIsWrittenOnALoopAppliesToEachRow() throws {
        let node = try json(#"{"ForEach": "$notes", "as": "n", "content": {"Text": "$n.title"}, "onTap": {"show": "Note", "with": {"id": "$n.id"}}, "padding": 4}"#)
        let spread = Element.distributing(node.object!)
        #expect(spread.keys.sorted() == ["ForEach", "as", "content"])
        #expect(spread["content"]?["onTap"]?["with"]?["id"] == "$n.id" && spread["content"]?["padding"] == .number(4) && spread["content"]?["Text"] == "$n.title")
        let many = try json(#"{"List": "$notes", "content": [{"Text": "a"}, "b"], "onTap": {"page": "x"}}"#)
        let rows = Element.distributing(many.object!)["content"]?.array
        #expect(rows?.count == 2 && rows?[0]["onTap"]?["page"] == "x" && rows?[1]["Text"] == "b" && rows?[1]["onTap"] != nil)
        let own = try json(#"{"ForEach": "$notes", "content": {"Text": "x", "padding": 8}, "padding": 4}"#)
        #expect(Element.distributing(own.object!)["content"]?["padding"] == .number(8))
        #expect(Tree.problems(in: node) == [])
    }

    @Test func aListDrawsItsRowsInTheirOwnScopeAndAFileShowsItsText() throws {
        let context = context()
        var scope = Scope(values: [:], boxes: [], context: context)
        scope.data = ["notes": .array([.object(["id": "a", "title": "Alpha"]), .object(["id": "b", "title": "Beta"])]), "doc": .object(["text": "# Hi", "name": "hi.md"])]
        _ = Tree.render(Tree.node(try json(#"{"List": "$notes", "as": "note", "content": {"Text": "${index}: ${note.title}", "fnt": 1}}"#)), scope)
        #expect(Tree.problems(in: try json(#"{"List": "$notes", "as": "note", "content": {"Text": "$note.title", "fnt": 1}}"#)) == ["Unknown modifier or argument 'fnt' on Text"])
        _ = Tree.render(Tree.node(try json(#"{"List": "$doc", "content": {"Text": "x"}}"#)), scope)
        #expect(context.diagnostics.contains { $0.hasPrefix("List needs a list") } == false)
        _ = Tree.render(Tree.node(try json(#"{"List": "$doc.name", "content": {"Text": "x"}}"#)), scope)
        #expect(context.diagnostics.contains { $0.hasPrefix("List needs a list, got hi.md") })
        Views.file = nil
        _ = Tree.render(Tree.node(try json(#"{"File": "$doc"}"#)), scope)
        _ = Tree.render(Tree.node(try json(#"{"File": "$doc", "height": 100}"#)), scope)
        #expect(Tree.problems(in: try json(#"{"File": "$doc", "widht": 100}"#)) == ["Unknown modifier or argument 'widht' on File"])
    }

    @Test func anArgumentOfAnotherViewIsLetThroughAsBefore() throws {
        #expect(Tree.problems(in: try json(#"{"Card": ["x"], "alignment": "center"}"#)) == [])
        #expect(Tree.problems(in: try json(#"{"Card": ["x"], "alignement": "center"}"#)) == ["Unknown modifier or argument 'alignement' on Card"])
    }

    @Test func theComponentsAViewDrawsAreCheckedWithIt() throws {
        let components: [String: JSONValue] = ["Row": try json(#"{"props": {"name": ""}, "body": {"Text": "$name", "fnt": "body"}}"#),
                                               "Unused": try json(#"{"body": {"Nope": 1, "zzz": 2}}"#)]
        #expect(Tree.problems(in: try json(#"{"VStack": [{"Row": {"name": "a"}}]}"#), components: components) == ["Unknown modifier or argument 'fnt' on Text"])
    }

    @Test func aViewIsDecodedOnce() throws {
        let view = try json(#"{"VStack": [{"Text": "${a + 1}"}], "spacing": "$gap"}"#)
        guard case .element(let first) = Tree.node(view), case .element(let second) = Tree.node(view) else {
            Issue.record("not an element")
            return
        }
        #expect(first === second)
    }

    @Test func stringsAreReadOnceAsWhatTheyAre() {
        let scope = Scope(values: ["a": .number(2), "who": "Marta", "list": .array([.number(1)])], boxes: [], context: context())
        #expect(Template("plain").resolve(scope) == "plain" && !Template("plain").isComputed)
        #expect(Template("$a").resolve(scope) == .number(2) && Template("$a").isReference)
        #expect(Template("${a + 1}").resolve(scope) == .number(3))
        #expect(Template("Hi $who, ${a * 2} left").resolve(scope) == "Hi Marta, 4 left")
        #expect(Template("costs $5 and $unknown").resolve(scope) == "costs $5 and $unknown")
        #expect(Dynamic(.object(["n": "$a", "fixed": .array(["x"])])).resolve(scope) == .object(["n": .number(2), "fixed": .array(["x"])]))
        #expect(Dynamic(.array(["x", .number(1)])).isConstant)
    }

    @Test func anActionChangesStateAndSendsWhatItResolvesTo() async {
        var sent: [(JSONValue, String?)] = []
        let box = StateBox(["tip": .number(10), "open": false, "text": "eggs"])
        let scope = Scope(values: ["id": "split"], boxes: [box], context: context { sent.append(($0, $1)) })
        ActionRunner.run(.array([
            .object(["set": .object(["tip": "${tip + 5}"]), "toggle": "open"]),
            .object(["send": .object(["card": "$id", "tip": "$tip", "typed": "$text"]), "say": "Tip is ${tip}", "set": .object(["text": ""])]),
        ]), in: scope)
        for _ in 0..<50 where sent.isEmpty { try? await Task.sleep(for: .milliseconds(10)) }
        #expect(box.values["tip"] == .number(15) && box.values["open"] == true && box.values["text"] == "")
        #expect(sent.count == 1)
        #expect(sent.first?.0 == .object(["card": "split", "tip": .number(15), "typed": "eggs"]))
        #expect(sent.first?.1 == "Tip is 15")
    }

    struct NotAComponent: Error {}

    func called(_ view: String, _ definition: String, from scope: Scope) throws -> Scope {
        guard case .element(let element) = Tree.node(try json(view)), case .custom(_, let call) = element.content,
              let definition = ComponentDefinition(try json(definition)) else {
            throw NotAComponent()
        }
        return Tree.component(definition, call, scope).scope
    }

    @Test func anActionHandedToAComponentRunsWhereItWasWritten() async throws {
        var sent: [(JSONValue, String?)] = []
        let box = StateBox(["picked": "", "last": .number(0)])
        let card = Scope(values: ["who": "Marta"], boxes: [box], context: context { sent.append(($0, $1)) })
        let inside = try called(
            #"{"Chip": {"label": "A", "onPick": [{"set": {"picked": "$who", "last": "$value"}}, {"send": {"picked": "$who"}}], "onLeave": "$nothing"}}"#,
            #"{"props": {"label": "", "onPick": null, "onHold": {"send": {"held": "$label"}}}, "body": {"Text": "$label"}}"#, from: card)
        ActionRunner.run("$onPick", title: "A", in: inside.with(["value": .number(3)]))
        for _ in 0..<50 where sent.isEmpty { try? await Task.sleep(for: .milliseconds(10)) }
        #expect(box.values["picked"] == "Marta" && box.values["last"] == .number(3))
        #expect(sent.first?.0 == .object(["picked": "Marta"]) && sent.first?.1 == "A")
        ActionRunner.run("$onHold", in: inside)
        ActionRunner.run("$onLeave", in: inside)
        for _ in 0..<50 where sent.count < 2 { try? await Task.sleep(for: .milliseconds(10)) }
        #expect(sent.count == 2 && sent.last?.0 == .object(["held": "A"]))
        #expect(Action("$onPick").problems.isEmpty && inside.context.diagnostics.isEmpty)
    }

    @Test func aComponentRunsTheScriptOfWhatDrawsItAndKeepsItsState() async throws {
        let context = context()
        let state = StateBox(["tip": .number(10)])
        let spec = ScriptSpec(.object(["script": "function more({state, args}) { return {state: {tip: state.tip + args, asked: true}} }"]))!
        let host = ScriptHost(spec: spec, data: .null, context: context, state: state, derived: StateBox([:]))
        var card = Scope(values: [:], boxes: [state], context: context).with(script: host)
        card.saved = SavedState([:]) { _ in }
        let inside = try called(#"{"Tip": {"step": 5}}"#, #"{"props": {"step": 1}, "body": {"Button": "More", "action": {"run": "more", "args": "$step"}}}"#, from: card)
        #expect(inside.saved != nil && inside.boxes.isEmpty)
        ActionRunner.run(.object(["run": "more", "args": "$step"]), in: inside)
        for _ in 0..<100 where state.values["asked"] == nil { try? await Task.sleep(for: .milliseconds(10)) }
        #expect(state.values["tip"] == .number(15) && state.values["asked"] == true)
    }

    @Test func aShowOpensAComponentAsAScreenOverThePageOrAsASheet() async throws {
        let invoice = try json(#"{"props": ["id"], "title": "Invoice $id", "body": {"Text": "$id"}}"#)
        let context = CardContext(cardID: "invoices", component: { $0 == "Invoice" ? ComponentDefinition(invoice) : nil }, onSend: { _, _ in })
        let navigator = Navigator()
        var page = Scope(values: ["it": .object(["id": "inv-41"])], boxes: [], context: context, data: ["rows": .array([])])
        page.navigator = navigator
        var presented: [Shown] = []
        ActionRunner.present = { presented.append($0) }
        ActionRunner.run(.object(["show": "Invoice", "with": .object(["id": "$it.id"])]), in: page)
        for _ in 0..<50 where navigator.path.isEmpty { try? await Task.sleep(for: .milliseconds(10)) }
        let shown = try #require(navigator.path.first)
        let drawn = ScreenView.scope(ComponentDefinition(invoice)!, shown, navigator: navigator, stores: ["trip": .object([:])])
        #expect(drawn.scope.lookup("id") == "inv-41" && drawn.scope.text(invoice["title"]) == "Invoice inv-41")
        #expect(drawn.scope.lookup("rows") == nil && drawn.scope.lookup("trip") == .object([:]))
        #expect(drawn.scope.saved == nil && drawn.scope.navigator === navigator)
        ActionRunner.run(.object(["show": "Invoice", "with": "inv-42", "replace": true]), in: page)
        for _ in 0..<50 where navigator.path.first?.id == shown.id { try? await Task.sleep(for: .milliseconds(10)) }
        #expect(navigator.path.count == 1 && navigator.path.first?.call.written.isEmpty == true)
        ActionRunner.run(.object(["close": true]), in: drawn.scope)
        for _ in 0..<50 where !navigator.path.isEmpty { try? await Task.sleep(for: .milliseconds(10)) }
        #expect(navigator.path.isEmpty)
        ActionRunner.run(.object(["show": "Invoice", "as": "sheet"]), in: page)
        ActionRunner.run(.object(["show": "Invoice"]), in: Scope(values: [:], boxes: [], context: context))
        ActionRunner.run(.object(["show": "Nothing"]), in: page)
        for _ in 0..<50 where presented.count < 2 { try? await Task.sleep(for: .milliseconds(10)) }
        #expect(presented.count == 2 && navigator.path.isEmpty)
        #expect(context.diagnostics == ["There is no component 'Nothing' to show: define it first"])
        let screen: [String: JSONValue] = ["Invoice": try json(#"{"body": {"Text": "$id", "fnt": "body"}}"#)]
        #expect(Tree.problems(in: try json(#"{"Button": "Go", "action": {"show": "Invoice"}}"#), components: screen) == ["Unknown modifier or argument 'fnt' on Text"])
    }

    @Test func whatATapCouldNotDoIsToldOnceUntilTheCardIsSentAgain() async {
        var told: [(String, String, String?)] = []
        ActionRunner.failed = { told.append(($0, $1, $2)) }
        ActionRunner.openConversation = { _ in false }
        defer { ActionRunner.failed = nil; ActionRunner.openConversation = nil }
        let context = context()
        let scope = Scope(values: [:], boxes: [], context: context)
        ActionRunner.run(.object(["conversation": "gone"]), title: "Open", in: scope)
        ActionRunner.run(.object(["conversation": "gone"]), title: "Open", in: scope)
        ActionRunner.run(.object(["run": "ask"]), in: scope)
        for _ in 0..<50 where told.count < 2 { try? await Task.sleep(for: .milliseconds(10)) }
        #expect(told.map(\.0) == ["There is no conversation 'gone': use main or a topic's id", "run needs a script on the card or page"])
        #expect(told.first?.1 == "tree" && told.first?.2 == "Open" && told.last?.2 == nil)
        #expect(context.diagnostics.count == 2)
        context.resetDiagnostics()
        ActionRunner.run(.object(["conversation": "gone"]), title: "Open", in: scope)
        for _ in 0..<50 where told.count < 3 { try? await Task.sleep(for: .milliseconds(10)) }
        #expect(told.count == 3)
    }

    @Test func aNodeDeclaresStateOnceForItsSubtree() throws {
        let context = context()
        let scope = Scope(values: [:], boxes: [StateBox(["picked": []])], context: context)
        _ = Tree.render(Tree.node(try json(#"{"VStack": [], "state": {"picked": [], "draft": ""}}"#)), scope)
        #expect(context.diagnostics.contains { $0.hasPrefix("state picked is already declared") })
    }
}
