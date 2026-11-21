// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import Observation
import SwiftUI

/// State declared by a node with `state`, owned by the view that declared it.
@Observable
final class StateBox {
    var values: [String: JSONValue]

    init(_ values: [String: JSONValue]) {
        self.values = values
    }
}

/// What you changed on a card or page, kept where it is stored: each state
/// scope's values by its place in the tree, so they come back when the card is
/// drawn again, after scrolling away or a restart.
@MainActor
final class SavedState {
    private var values: [String: [String: JSONValue]]
    private let save: ([String: [String: JSONValue]]) -> Void

    init(_ values: [String: [String: JSONValue]], save: @escaping ([String: [String: JSONValue]]) -> Void) {
        self.values = values
        self.save = save
    }

    func values(at key: String) -> [String: JSONValue] {
        values[key] ?? [:]
    }

    func set(_ new: [String: JSONValue], at key: String) {
        guard values[key] != new else { return }
        values[key] = new
        save(values)
    }
}

/// A component definition: its props with their defaults, its body, and the
/// title it shows under when opened as a screen.
struct ComponentDefinition {
    var props: [String: JSONValue]
    var state: [String: JSONValue]?
    var body: JSONValue
    var title: JSONValue?
    /// Buttons for the bar when the component is a screen: `Button`s and
    /// `Menu`s with a symbol, at most three.
    var toolbar: [JSONValue] = []

    init?(_ value: JSONValue) {
        guard let body = value["body"] else { return nil }
        self.body = body
        self.state = value["state"]?.object
        self.title = value["title"]
        self.toolbar = value["toolbar"]?.array ?? []
        if let names = value["props"]?.array {
            props = Dictionary(names.compactMap { $0.string.map { ($0, JSONValue.null) } }, uniquingKeysWith: { a, _ in a })
        } else {
            props = value["props"]?.object ?? [:]
        }
    }
}

/// Shared by every node of one card: where diagnostics and actions go.
final class CardContext {
    let cardID: String
    let component: (String) -> ComponentDefinition?
    let onSend: (_ payload: JSONValue, _ say: String?) -> Void
    private(set) var diagnostics: [String] = []
    private(set) var structural: [String] = []
    private var told: Set<String> = []
    private(set) var frames: [String: (view: String, frame: CGRect, sideways: Bool)] = [:]
    private(set) var cutText: [String: (shown: CGFloat, needed: CGFloat)] = [:]
    private(set) var squeezedText: [String: (shown: CGFloat, needed: CGFloat)] = [:]
    private(set) var brokenText: [String: Int] = [:]
    private(set) var emptyText: [String: String] = [:]
    /// The paths the card draws right now, gathered as a preference on every
    /// render: what an earlier version measured is not reported.
    var live: Set<String>?
    var size: CGSize = .zero
    /// Each derived value as the script last computed it, for the render report.
    var derived: [String: JSONValue] = [:]

    static let space = "hermes-card"

    init(cardID: String, component: @escaping (String) -> ComponentDefinition?, onSend: @escaping (JSONValue, String?) -> Void) {
        self.cardID = cardID
        self.component = component
        self.onSend = onSend
    }

    func report(_ message: String) {
        guard !diagnostics.contains(message) else { return }
        diagnostics.append(message)
    }

    /// Something an action could not do when it ran: reported like the rest,
    /// and told to the agent, once until the card or page is sent again.
    func fail(_ message: String, tapped: String?) {
        report(message)
        guard told.insert(message).inserted else { return }
        ActionRunner.failed?(message, cardID, tapped)
    }

    func resetDiagnostics() {
        diagnostics = []
        told = []
    }

    /// What the app changed in the view before drawing it, reported as an issue.
    func note(_ message: String) {
        guard !structural.contains(message) else { return }
        structural.append(message)
    }

    func record(_ path: String, view: String, frame: CGRect, sideways: Bool = false) {
        frames[path] = (view, frame, sideways)
    }

    func recordText(_ path: String, shown: CGFloat, needed: CGFloat) {
        cutText[path] = needed > shown + 1 ? (shown, needed) : nil
    }

    /// A text that reads values and shows nothing: the collapse it causes is
    /// reported with what it read.
    func recordSource(_ path: String, source: String?, shown: String) {
        emptyText[path] = shown.isEmpty && source?.contains("$") == true ? source : nil
    }

    func recordBreak(_ path: String, characters: Int?, shown: CGSize, line: CGSize) {
        guard let characters, line.height > 0 else { return }
        let lines = Int((shown.height / line.height).rounded())
        brokenText[path] = characters <= 12 && lines > 1 ? lines : nil
    }

    /// A text narrower than its one line needs, that did not wrap onto another
    /// line, is truncated or clipped: a digit squeezed between two flexible
    /// names loses half of itself without any "…".
    func recordWidth(_ path: String, shown: CGSize, line: CGSize) {
        guard shown.width > 0, line.width > 0 else { return }
        let squeezed = shown.width + 1 < line.width && shown.height < line.height * 1.5
        squeezedText[path] = squeezed ? (shown.width, line.width) : nil
    }

    private static let contentViews: Set<String> = ["Text", "Image", "Label", "Chart", "Map", "Gauge", "Circle", "Capsule", "Rectangle", "RoundedRectangle", "Ellipse", "Path", "Button"]

    /// What can be measured about the layout: elements outside the card, text
    /// cut short, collapsed views, tap targets too small to hit.
    func layoutIssues() -> [String] {
        var issues = structural
        guard size.width > 0 else { return issues }
        let current = { (path: String) in self.live?.contains(path) ?? true }
        for (path, entry) in frames.sorted(by: { $0.key < $1.key }) where current(path) {
            let frame = entry.frame
            var outside: [String] = []
            if frame.minX < -1, !entry.sideways { outside.append("\(Int(-frame.minX))pt past the left edge") }
            if frame.maxX > size.width + 1, !entry.sideways { outside.append("\(Int(frame.maxX - size.width))pt past the right edge") }
            if frame.minY < -1 { outside.append("\(Int(-frame.minY))pt above the top") }
            if frame.maxY > size.height + 1 { outside.append("\(Int(frame.maxY - size.height))pt below the bottom") }
            if !outside.isEmpty {
                issues.append("\(path) sticks out of the card: \(outside.joined(separator: ", "))")
            }
            if Self.contentViews.contains(entry.view), frame.width < 0.5 || frame.height < 0.5 {
                let empty = emptyText[path].map { ": \($0) is empty" } ?? ""
                issues.append("\(path) collapsed to \(Int(frame.width))×\(Int(frame.height))\(empty)")
            }
            if entry.view == "Button", frame.width >= 0.5, frame.width < 28 || frame.height < 28 {
                issues.append("\(path) is a small tap target: \(Int(frame.width))×\(Int(frame.height))pt")
            }
        }
        for (path, cut) in cutText.sorted(by: { $0.key < $1.key }) where current(path) {
            issues.append("\(path) is cut: shows \(Int(cut.shown))pt of the \(Int(cut.needed))pt it needs")
        }
        for (path, lines) in brokenText.sorted(by: { $0.key < $1.key }) where current(path) {
            issues.append("\(path) is a few characters broken across \(lines) lines; keep it on one (fixedSize, layoutPriority, a smaller font, or less beside it)")
        }
        for (path, squeeze) in squeezedText.sorted(by: { $0.key < $1.key }) where current(path) {
            issues.append("\(path) is squeezed: \(Int(squeeze.shown))pt wide where its line needs \(Int(squeeze.needed))pt, so it is truncated or clipped; give it room (fixedSize, layoutPriority) or shorten what is beside it")
        }
        return issues
    }
}

/// Where a component was called and what it was called with, as written: an
/// action it was handed runs there.
final class Caller {
    let scope: Scope
    let arguments: [String: JSONValue]

    init(scope: Scope, arguments: [String: JSONValue]) {
        self.scope = scope
        self.arguments = arguments
    }
}

/// What a node can see: its lexical values (data, props, loop variables) and the
/// state boxes above it, innermost last.
struct Scope {
    /// What is bound here: a component's props, a ForEach's element.
    var values: [String: JSONValue]
    var boxes: [StateBox]
    let context: CardContext
    /// The card's or page's own data: a card's as it was sent, a page's store.
    var data: [String: JSONValue] = [:]
    /// Every store on the phone, by name.
    var stores: [String: JSONValue] = [:]
    var depth = 0
    var path = ""
    var probes = true
    /// Drawn off screen for a check, not for him: a List shows its first rows only.
    var checking = false
    /// Inside a carousel: its pages run past the card's edges on purpose.
    var sideways = false
    /// The script of the card or page this node is in, for its handlers.
    var script: ScriptHost?
    /// Where the card's or page's state is kept, if anywhere.
    var saved: SavedState?
    /// In a component's body: who called it.
    var caller: Caller?
    /// The stack of screens over the page or sheet this node is in; none on a
    /// card in the conversation, where a screen opens as a sheet.
    var navigator: Navigator?
    /// Set on the root node of each ForEach element: a row, which swipes.
    var row = false
    /// Set on each element of a ForEach with `onMove`: the list it can be dragged in, and its place.
    var move: (list: Reorder.List, index: Int)?

    func child(_ label: String) -> Scope {
        var scope = self
        scope.path += " › \(label)."
        return scope
    }

    /// One rule for cards and pages: what is bound here, then state and
    /// derived values, then the view's own data, then a store of that name,
    /// then a live value.
    func lookup(_ name: String) -> JSONValue? {
        if let value = values[name] { return value }
        for box in boxes.reversed() {
            if let value = box.values[name] { return value }
        }
        return data[name] ?? stores[name] ?? LiveValues.shared.value(name)
    }

    func with(_ extra: [String: JSONValue]) -> Scope {
        var scope = self
        scope.values.merge(extra) { _, new in new }
        return scope
    }

    func with(script: ScriptHost) -> Scope {
        var scope = self
        scope.script = script
        return scope
    }

    func with(box: StateBox) -> Scope {
        var scope = self
        scope.boxes.append(box)
        return scope
    }

    func evaluate(_ source: String) -> JSONValue {
        Compiled(source).evaluate(self)
    }

    /// Resolves references and interpolation in a value, deeply.
    func resolve(_ value: JSONValue) -> JSONValue {
        switch value {
        case .string(let string):
            return resolve(string)
        case .array(let items):
            return .array(items.map(resolve))
        case .object(let object):
            return .object(object.mapValues(resolve))
        default:
            return value
        }
    }

    /// Resolves what this scope knows in a view handed to a component, and
    /// leaves the rest for where the view is drawn: `$item` stays for the
    /// ForEach inside it to bind.
    func resolveKnown(_ value: JSONValue) -> JSONValue {
        switch value {
        case .string(let string):
            return Self.names(in: string).allSatisfy { lookup($0) != nil } ? resolve(string) : value
        case .array(let items):
            return .array(items.map(resolveKnown))
        case .object(let object):
            return .object(object.mapValues(resolveKnown))
        default:
            return value
        }
    }

    /// The names a string refers to: after `$`, and inside `${…}` except functions.
    static func names(in string: String) -> [String] {
        guard string.contains("$") else { return [] }
        var names: [String] = []
        var index = string.startIndex
        while let dollar = string[index...].firstIndex(of: "$") {
            let after = string.index(after: dollar)
            if after < string.endIndex, string[after] == "{", let close = string[after...].firstIndex(of: "}") {
                names += identifiers(in: string[string.index(after: after)..<close])
                index = string.index(after: close)
            } else {
                let name = string[after...].prefix { $0.isLetter || $0.isNumber || $0 == "_" }
                if !name.isEmpty { names.append(String(name)) }
                index = after
            }
        }
        return names
    }

    private static func identifiers(in source: Substring) -> [String] {
        var found: [String] = []
        var index = source.startIndex
        while index < source.endIndex {
            let character = source[index]
            guard character.isLetter || character == "_" else {
                if character == "\"" || character == "'" {
                    index = source[source.index(after: index)...].firstIndex(of: character).map { source.index(after: $0) } ?? source.endIndex
                } else {
                    index = source.index(after: index)
                }
                continue
            }
            let name = source[index...].prefix { $0.isLetter || $0.isNumber || $0 == "_" }
            let end = source.index(index, offsetBy: name.count)
            let afterName = source[end...].drop { $0 == " " }.first
            let previous = index > source.startIndex ? source[source.index(before: index)] : nil
            if afterName != "(", previous != ".", !["true", "false", "null", "and", "or", "not"].contains(name) {
                found.append(String(name))
            }
            index = end
        }
        return found
    }

    func resolve(_ string: String) -> JSONValue {
        Template.of(string).resolve(self)
    }

    func text(_ value: JSONValue?) -> String {
        value.map { resolve($0).text } ?? ""
    }

    func number(_ value: JSONValue?) -> Double? {
        value.flatMap { resolve($0).number }
    }

    /// A condition: an expression written bare (`count(items) == 0`, `$a && !$b`),
    /// a reference or a `${…}`.
    func truthy(_ value: JSONValue?) -> Bool {
        value.map { Condition($0).holds(self) } ?? false
    }

    /// The state box that owns `name`, or the innermost one.
    func box(for name: String) -> StateBox? {
        box(declaring: name) ?? boxes.last
    }

    func box(declaring name: String) -> StateBox? {
        boxes.last { $0.values[name] != nil }
    }

    /// A binding to a state name; or, for a field of something in scope
    /// (`$item.done`, or `$done` in a kind's view when `onChange` is given),
    /// one that reads the field and writes nothing itself: the input's
    /// `onChange` says what the change does, an `edit` usually.
    func binding(_ reference: JSONValue?, onChange: JSONValue? = nil) -> Binding<JSONValue>? {
        guard let reference = reference?.string else { return nil }
        let name = reference.hasPrefix("$") ? String(reference.dropFirst()) : reference
        let scope = self
        if let keyed = keyedBinding(name, onChange: onChange) {
            return keyed
        }
        let field = name.contains(".") || name.contains("[") || (onChange != nil && (values[name] ?? data[name]) != nil && !boxes.contains { $0.values[name] != nil })
        if field {
            guard onChange != nil else {
                context.report("bind: \"\(reference)\" reads a field: say what changes it with onChange, an edit of the item or store it belongs to")
                return nil
            }
            return Binding(get: { scope.resolve("$" + name) }, set: { new in ActionRunner.run(onChange, in: scope.with(["value": new])) })
        }
        guard let box = box(for: name) else { return nil }
        if box.values[name] == nil {
            box.values[name] = values[name] ?? data[name] ?? .null
        }
        return Binding(get: { box.values[name] ?? .null }, set: { new in
            box.values[name] = new
            if let onChange { ActionRunner.run(onChange, in: scope.with(["value": new])) }
        })
    }

    /// `$on[row.id]`: one entry of a state object (or array), keyed by an expression, so each row of a list
    /// keeps its own value; the object is created on the first write.
    private func keyedBinding(_ name: String, onChange: JSONValue?) -> Binding<JSONValue>? {
        guard let match = name.wholeMatch(of: /([A-Za-z_][A-Za-z0-9_]*)\[(.+)\]/) else { return nil }
        let root = String(match.output.1)
        let undeclared = (values[root] ?? data[root]) == nil ? boxes.last : nil
        guard let box = boxes.last(where: { $0.values[root] != nil }) ?? undeclared else { return nil }
        let key = evaluate(String(match.output.2))
        let scope = self
        return Binding(get: {
            let container = box.values[root] ?? .null
            if let i = key.int, let array = container.array {
                return array.indices.contains(i) ? array[i] : .null
            }
            return container[key.text] ?? .null
        }, set: { new in
            let container = box.values[root] ?? .null
            if let i = key.int, var array = container.array {
                if array.indices.contains(i) { array[i] = new }
                box.values[root] = .array(array)
            } else {
                var object = container.object ?? [:]
                object[key.text] = new
                box.values[root] = .object(object)
            }
            if let onChange { ActionRunner.run(onChange, in: scope.with(["value": new])) }
        })
    }
}

/// Every measured path a card draws, collected from its whole tree on each render.
struct LivePaths: PreferenceKey {
    static let defaultValue: [String] = []

    static func reduce(value: inout [String], nextValue: () -> [String]) {
        value.append(contentsOf: nextValue())
    }
}
