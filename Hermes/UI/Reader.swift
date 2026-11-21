// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import Foundation

/// Reads a node's arguments as its view declares them. What a view reads is
/// what it takes: an argument left unread is one the view does not have, and
/// is reported; the arguments each view reads make the grammar the plugin
/// checks cards with before they leave (plugin/dedala/grammar.json).
struct Reader {
    /// How an argument is written and read.
    enum Kind: String {
        /// Any value, resolved in scope: a number, a text, a list, an object.
        case value
        /// A word written as it is, never computed: an axis, a role.
        case word
        /// True or false, by value or by an expression written bare.
        case condition
        /// A view, or a list of views.
        case view
        /// An action, or a list of them.
        case action
        /// A reference to the state an input changes.
        case binding
    }

    let view: String
    private let node: [String: JSONValue]
    private(set) var declared: [String: Kind] = [:]
    private(set) var problems: [String] = []
    /// The views read so far, for what is wrong inside them to be found without drawing.
    private(set) var inner: [Children] = []
    /// Whether the view takes views as its main argument: a container.
    private(set) var holdsChildren = false

    init(view: String, node: [String: JSONValue]) {
        self.view = view
        self.node = node
    }

    /// The view's main argument, the value of its own key.
    var main: JSONValue { node[view] ?? .null }

    /// Whether the node has the argument, without taking it as the view's own.
    func has(_ name: String) -> Bool {
        node[name] != nil
    }

    private mutating func take(_ name: String, _ kind: Kind) -> JSONValue? {
        declared[name] = kind
        return node[name]
    }

    mutating func value(_ name: String) -> Dynamic? {
        guard let dynamic = take(name, .value).map(Dynamic.init) else { return nil }
        problems += dynamic.problems
        return dynamic
    }

    mutating func word(_ name: String) -> String? {
        take(name, .word)?.string
    }

    mutating func condition(_ name: String) -> Condition? {
        guard let condition = take(name, .condition).map(Condition.init) else { return nil }
        problems += condition.problems
        return condition
    }

    mutating func children(_ name: String) -> Children {
        let children = Children(take(name, .view))
        inner.append(children)
        return children
    }

    /// The main argument as the views the container holds.
    mutating func mainChildren() -> Children {
        let children = Children(main)
        holdsChildren = true
        inner.append(children)
        return children
    }

    /// The main argument as one view, when it is one: a button's label drawn by the agent.
    mutating func mainNode() -> Node? {
        guard main.object != nil || main.array != nil else { return nil }
        let node = Tree.decode(main)
        inner.append(Children(single: node))
        return node
    }

    /// An argument as it was written, for what reads it its own way.
    mutating func raw(_ name: String) -> JSONValue? {
        take(name, .value)
    }

    mutating func action(_ name: String) -> Action? {
        guard let action = take(name, .action).map(Action.init) else { return nil }
        problems += action.problems
        return action
    }

    /// The reference an input binds to and what runs when it changes, as
    /// written: a scope makes the binding when the input is drawn.
    mutating func binding() -> (reference: JSONValue?, onChange: JSONValue?) {
        let reference = take("bind", .binding)
        let onChange = take("onChange", .action)
        if let onChange { problems += Action(onChange).problems }
        return (reference, onChange)
    }

    /// The main argument as a value resolved in scope.
    mutating func mainValue() -> Dynamic {
        let dynamic = Dynamic(main)
        problems += dynamic.problems
        return dynamic
    }

    mutating func report(_ problem: String) {
        problems.append(problem)
    }

    /// What the node holds that neither its view nor any node takes.
    func unread(besides known: Set<String>) -> [String] {
        node.keys.filter { $0 != view && declared[$0] == nil && !known.contains($0) }.sorted()
    }
}
