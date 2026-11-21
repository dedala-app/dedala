// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import SwiftUI

/// A Hermes UI view as decoded from its JSON, once: every string in it is
/// already read as the text, reference or expression it is, every argument
/// already taken by the view that has it. Drawing walks this, not the JSON.
indirect enum Node {
    case empty
    /// A number or a boolean, drawn as written.
    case verbatim(String)
    /// Text, or a view held by the data it names (`"$content"`).
    case string(Template)
    /// A bare list: a leading VStack of its items.
    case list([Node])
    /// A node that declares state for its subtree, and the node without it.
    case stateful([String: Dynamic], Node)
    case element(Element)
}

/// What a container was given to draw: a list of nodes, one node, or nothing.
struct Children {
    fileprivate enum Form {
        case none
        case list([Node])
        case single(Node)
    }

    fileprivate let form: Form

    init(_ value: JSONValue?) {
        switch value {
        case nil: form = .none
        case .array(let items)?: form = .list(items.map(Tree.decode))
        case let value?: form = .single(Tree.decode(value))
        }
    }

    init(list nodes: [Node]) {
        form = .list(nodes)
    }

    init(single node: Node) {
        form = .single(node)
    }

    /// What is wrong in any of them, in every branch.
    var problems: [String] {
        switch form {
        case .none: []
        case .list(let nodes): nodes.flatMap(Tree.problems)
        case .single(let node): Tree.problems(node)
        }
    }
}

/// How a view is drawn from the arguments it read. One type per view: what it
/// takes is what its `init` reads, and nothing else is accepted on its node.
protocol ViewSpec {
    func view(_ scope: Scope, _ element: Element) -> AnyView
}

/// A node with a view key, a `ForEach` or an `If`, decoded.
final class Element {
    enum Content {
        case loop(Loop)
        case choice(Choice)
        case view(String, any ViewSpec)
        /// A view the app does not draw itself: a component, if one is defined by that name.
        case custom(String, Call)
        case none
    }

    struct Loop {
        fileprivate enum Source {
            case bare(Compiled)
            case value(Dynamic)
        }

        fileprivate let source: Source
        /// The list as it was written, for a reorder to know where it lives.
        let written: JSONValue
        let name: String
        let indexName: String
        let onMove: JSONValue?
        let content: Children

        fileprivate func list(_ scope: Scope) -> JSONValue {
            switch source {
            case .bare(let compiled): compiled.evaluate(scope)
            case .value(let value): value.resolve(scope)
            }
        }
    }

    struct Choice {
        let condition: Condition
        let then: Children
        let otherwise: Children
    }

    /// What a component is called with: named props, a view among them left
    /// for the component to draw, or one value.
    struct Call {
        fileprivate enum Argument {
            case view(JSONValue)
            case value(Dynamic)
        }

        fileprivate enum Form {
            case named([String: Argument])
            case single(Dynamic)
        }

        fileprivate let form: Form
        /// The named props as they were written.
        let written: [String: JSONValue]

        init(_ value: JSONValue) {
            if case .object(let arguments) = value {
                form = .named(arguments.mapValues { Tree.isView($0) ? .view($0) : .value(Dynamic($0)) })
                written = arguments
            } else {
                form = .single(Dynamic(value))
                written = [:]
            }
        }

        fileprivate func resolve(_ scope: Scope) -> JSONValue {
            switch form {
            case .single(let value):
                return value.resolve(scope)
            case .named(let arguments):
                return .object(arguments.mapValues { argument in
                    switch argument {
                    case .view(let view): scope.resolveKnown(view)
                    case .value(let value): value.resolve(scope)
                    }
                })
            }
        }
    }

    /// What a view needs to know of the modifiers on its node.
    struct Facts {
        var view = ""
        var hasWidth = false
        var hasHeight = false
        var limitsLines = false
        var clips = false
        var fillsWidth = false
        var accessibilityLabel: Dynamic?

        fileprivate init(_ node: [String: JSONValue], view: String) {
            self.view = view
            hasWidth = node["width"] != nil || node["frame"]?["width"] != nil || node["maxWidth"] != nil || node["frame"]?["maxWidth"] != nil
            hasHeight = node["height"] != nil || node["frame"]?["height"] != nil || node["maxHeight"] != nil
            limitsLines = node["lineLimit"] != nil
            clips = node["cornerRadius"] != nil || node["clipShape"] != nil
            fillsWidth = (node["maxWidth"] ?? node["frame"]?["maxWidth"])?.string == "infinity"
            accessibilityLabel = node["accessibilityLabel"].map(Dynamic.init)
        }
    }

    /// The keys any node takes besides its view's arguments and the modifiers.
    static let own: Set<String> = ["hidden", "visible", "modifiers", "actions", "overlayAlignment"]

    /// What `ForEach` and `If` take, as they read it.
    static let flow: [String: [String: Reader.Kind]] = {
        var each = Reader(view: "ForEach", node: [:])
        _ = loop(&each)
        var condition = Reader(view: "If", node: [:])
        _ = choice(&condition)
        return ["ForEach": each.declared, "If": condition.declared]
    }()

    let content: Content
    let facts: Facts
    let modifiers: ModifierList
    let actions: Interactions.Decoded?
    /// What is wrong with the node as written, known without drawing it.
    let problems: [String]
    /// The views inside it, whichever branch they are in.
    fileprivate let inner: [Children]
    private let hidden: Condition?
    private let visible: Condition?

    /// What a `ForEach` or `List` takes for itself; anything else written on
    /// it applies to each of its rows, as in SwiftUI.
    private static let loopOwn: Set<String> = ["ForEach", "List", "as", "index", "content", "onMove", "hidden", "visible", "state"]

    static func distributing(_ node: [String: JSONValue]) -> [String: JSONValue] {
        guard node["ForEach"] != nil || node["List"] != nil, let content = node["content"] else { return node }
        let pushed = node.filter { !loopOwn.contains($0.key) }
        guard !pushed.isEmpty else { return node }
        var own = node.filter { loopOwn.contains($0.key) }
        own["content"] = push(pushed, into: content)
        return own
    }

    private static func push(_ pushed: [String: JSONValue], into content: JSONValue) -> JSONValue {
        switch content {
        case .array(let children): .array(children.map { push(pushed, into: $0) })
        case .object(let child): .object(pushed.merging(child) { _, own in own })
        case .string(let text): .object(pushed.merging(["Text": .string(text)]) { _, own in own })
        default: content
        }
    }

    fileprivate init(_ written: [String: JSONValue]) {
        let node = Self.distributing(written)
        hidden = node["hidden"].map(Condition.init)
        visible = node["visible"].map(Condition.init)
        var problems = (hidden?.problems ?? []) + (visible?.problems ?? [])
        if node["ForEach"] != nil || node["If"] != nil {
            let flow = node["ForEach"] != nil ? "ForEach" : "If"
            var reader = Reader(view: flow, node: node)
            content = flow == "ForEach" ? .loop(Self.loop(&reader)) : .choice(Self.choice(&reader))
            facts = Facts(node, view: flow)
            modifiers = ModifierList()
            actions = nil
            problems += reader.problems + reader.unread(besides: Modifiers.names.union(Views.argumentNames)).map { "Unknown modifier or argument '\($0)' on \(flow)" }
            self.problems = problems
            inner = reader.inner
            return
        }
        let keys = node.keys.filter { $0.first?.isUppercase == true }.sorted()
        guard let key = keys.first else {
            content = .none
            facts = Facts(node, view: "")
            modifiers = ModifierList()
            actions = nil
            self.problems = problems + ["A node needs one capitalised view key, got \(node.keys.sorted())"]
            inner = []
            return
        }
        if keys.count > 1 {
            problems.append("A node has several view keys \(keys); using \(key)")
        }
        var reader = Reader(view: key, node: node)
        if let make = Views.table[key] {
            content = .view(key, make(&reader))
        } else {
            content = .custom(key, Call(reader.main))
        }
        facts = Facts(node, view: key)
        modifiers = ModifierList(node, view: key)
        actions = node["actions"].map(Interactions.Decoded.init)
        problems += reader.unread(besides: Modifiers.names.union(Views.argumentNames)).map { "Unknown modifier or argument '\($0)' on \(key)" }
        problems += reader.problems + modifiers.problems + (actions?.problems ?? [])
        self.problems = problems
        inner = reader.inner + modifiers.inner
    }

    private static func loop(_ reader: inout Reader) -> Loop {
        let written = reader.main
        let source: Loop.Source = if case .string(let expression) = written, !expression.hasPrefix("$") {
            .bare(Compiled(expression))
        } else {
            .value(Dynamic(written))
        }
        if case .bare(let compiled) = source, let problem = compiled.problem { reader.report(problem) }
        return Loop(source: source, written: written, name: reader.word("as") ?? "item", indexName: reader.word("index") ?? "index",
                    onMove: reader.raw("onMove"), content: reader.children("content"))
    }

    private static func choice(_ reader: inout Reader) -> Choice {
        let condition = Condition(reader.main)
        condition.problems.forEach { reader.report($0) }
        return Choice(condition: condition, then: reader.children("then"), otherwise: reader.children("else"))
    }

    func isHidden(_ scope: Scope) -> Bool {
        if let hidden, hidden.holds(scope) { return true }
        if let visible, !visible.holds(scope) { return true }
        return false
    }
}

/// A child of a container once `ForEach` and `If` are expanded.
struct ChildItem: Identifiable {
    let id: String
    let node: Node
    let scope: Scope
}

/// Draws a decoded node.
struct TreeView: View {
    let node: Node
    let scope: Scope

    var body: some View {
        Tree.render(node, scope)
    }
}

enum Tree {
    static let maxDepth = 40

    // MARK: Decoding

    private static var decoded: [JSONValue: Node] = [:]
    private static let kept = 2000

    /// The node a JSON view decodes to, kept: a view is decoded once however
    /// often it is drawn.
    static func node(_ value: JSONValue) -> Node {
        if let known = decoded[value] { return known }
        if decoded.count >= kept { decoded.removeAll() }
        let node = decode(value)
        decoded[value] = node
        return node
    }

    static func decode(_ value: JSONValue) -> Node {
        switch value {
        case .null:
            return .empty
        case .bool, .number:
            return .verbatim(value.text)
        case .string(let string):
            return .string(Template.of(string))
        case .array(let items):
            return .list(items.map(decode))
        case .object(var object):
            if let state = object.removeValue(forKey: "state") {
                return .stateful((state.object ?? [:]).mapValues(Dynamic.init), decode(.object(object)))
            }
            return .element(Element(object))
        }
    }

    /// A value that is a view: a node, or a list holding one.
    static func isView(_ value: JSONValue) -> Bool {
        switch value {
        case .object(let object): object.keys.contains { $0.first?.isUppercase == true }
        case .array(let items): items.contains(where: isView)
        default: false
        }
    }

    /// Everything wrong with a view as written, in every branch and behind
    /// every button, drawn or not.
    static func problems(_ node: Node) -> [String] {
        switch node {
        case .empty, .verbatim:
            return []
        case .string(let template):
            return template.problems
        case .list(let nodes):
            return nodes.flatMap(problems)
        case .stateful(let state, let rest):
            return state.keys.sorted().flatMap { state[$0]?.problems ?? [] } + problems(rest)
        case .element(let element):
            return element.problems + element.inner.flatMap(\.problems)
        }
    }

    /// Everything wrong with a view as written and with the components it
    /// draws: what a report says of a card or page beyond what was drawn.
    static func problems(in view: JSONValue, components: [String: JSONValue] = [:]) -> [String] {
        var used: [String] = []
        func find(_ value: JSONValue) {
            switch value {
            case .array(let items):
                items.forEach(find)
            case .object(let object):
                for (key, inner) in object {
                    let drawn = key == "show" ? inner.string ?? "" : key
                    if let body = components[drawn]?["body"], !used.contains(drawn) {
                        used.append(drawn)
                        find(body)
                    }
                    find(inner)
                }
            default:
                break
            }
        }
        find(view)
        let found = problems(node(view)) + used.sorted().flatMap { problems(node(components[$0]?["body"] ?? .null)) }
        var seen = Set<String>()
        return found.filter { seen.insert($0).inserted }
    }

    // MARK: Drawing

    static func render(_ node: Node, _ scope: Scope) -> AnyView {
        guard scope.depth < maxDepth else {
            scope.context.report("The tree is nested deeper than \(maxDepth) levels")
            return AnyView(EmptyView())
        }
        var scope = scope
        scope.depth += 1
        switch node {
        case .empty:
            return AnyView(EmptyView())
        case .verbatim(let text):
            return AnyView(Text(text))
        case .string(let template):
            let value = template.resolve(scope)
            if value.object != nil || value.array != nil, template.source.hasPrefix("$") {
                return render(Tree.node(value), scope)
            }
            scope.path += "Text"
            if scope.probes { scope.context.recordSource(scope.path, source: template.source, shown: value.text) }
            return probe(AnyView(TextProbe(text: markdown(value.text), path: scope.path, context: scope.probes ? scope.context : nil)), view: "Text", scope)
        case .list(let nodes):
            return AnyView(VStack(alignment: .leading, spacing: 12) { children(Children(list: nodes), scope) })
        case .stateful(let declared, let rest):
            let again = declared.keys.filter { name in scope.boxes.contains { $0.values[name] != nil } }.sorted()
            if !again.isEmpty {
                scope.context.report("state \(again.joined(separator: ", ")) is already declared around this view, by its page or card: declare it once, or taps and the script see different copies")
            }
            let new = declared.filter { !again.contains($0.key) }
            return new.isEmpty ? render(rest, scope) : AnyView(StateScopeView(initial: new, node: rest, scope: scope))
        case .element(let element):
            if element.isHidden(scope) {
                return AnyView(EmptyView())
            }
            element.problems.forEach(scope.context.report)
            switch element.content {
            case .loop, .choice:
                return AnyView(Group { children(Children(single: node), scope) })
            case .none:
                return AnyView(EmptyView())
            case .view(let key, _), .custom(let key, _):
                scope.path += key
                let place = (row: scope.row, move: scope.move)
                scope.row = false
                scope.move = nil
                let view = draw(element, scope)
                let modified = element.modifiers.apply(to: view, scope, element.facts)
                let wrapped = probe(Interactions.apply(element.actions, to: modified, scope, row: place.row, move: place.move), view: key, scope)
                return element.modifiers.traits(on: wrapped, scope)
            }
        }
    }

    private static func draw(_ element: Element, _ scope: Scope) -> AnyView {
        switch element.content {
        case .view(_, let spec):
            return spec.view(scope, element)
        case .custom(let key, let call):
            if let definition = scope.context.component(key) {
                let inside = component(definition, call, scope)
                return AnyView(NodeView(node: inside.body, scope: inside.scope))
            }
            scope.context.report("Unknown view '\(key)'")
            return AnyView(Label("Unknown view \(key)", systemImage: "questionmark.square.dashed")
                .font(.caption.weight(.medium))
                .foregroundStyle(.red))
        case .loop, .choice, .none:
            return AnyView(EmptyView())
        }
    }

    /// A component's body and what it sees: its props, its own state, kept
    /// where its card's or page's is, the script of the card or page that
    /// draws it, and who called it.
    static func component(_ definition: ComponentDefinition, _ call: Element.Call, _ scope: Scope) -> (body: JSONValue, scope: Scope) {
        var props = definition.props
        let resolved = call.resolve(scope)
        if let arguments = resolved.object {
            props.merge(arguments) { _, new in new }
        } else if resolved != .null {
            props["value"] = resolved
        }
        var body = definition.body
        if let state = definition.state, case .object(var object) = body {
            object["state"] = .object((object["state"]?.object ?? [:]).merging(state) { own, _ in own })
            body = .object(object)
        }
        var inner = Scope(values: props, boxes: [], context: scope.context, stores: scope.stores, depth: scope.depth + 1)
        inner.path = scope.path + " › "
        inner.probes = scope.probes
        inner.checking = scope.checking
        inner.script = scope.script
        inner.saved = scope.saved
        inner.caller = Caller(scope: scope, arguments: call.written)
        inner.navigator = scope.navigator
        return (body, inner)
    }

    private static func probe(_ view: AnyView, view key: String, _ scope: Scope) -> AnyView {
        guard scope.probes, key != "Spacer" else { return view }
        let context = scope.context
        let path = scope.path
        let sideways = scope.sideways
        return AnyView(view.onGeometryChange(for: CGRect.self) { $0.frame(in: .named(CardContext.space)) } action: { frame in
            context.record(path, view: key, frame: frame, sideways: sideways)
        }
        .transformPreference(LivePaths.self) { $0.append(path) })
    }

    static func markdown(_ string: String) -> Text {
        if let attributed = try? AttributedString(markdown: string, options: .init(interpretedSyntax: .inlineOnlyPreservingWhitespace)) {
            return Text(attributed)
        }
        return Text(verbatim: string)
    }

    // MARK: Children

    @ViewBuilder
    static func children(_ children: Children, _ scope: Scope) -> some View {
        ForEach(items(children, scope)) { item in
            TreeView(node: item.node, scope: item.scope)
        }
    }

    static func items(_ children: Children, _ scope: Scope, prefix: String = "") -> [ChildItem] {
        switch children.form {
        case .none:
            return []
        case .list(let nodes):
            return nodes.enumerated().flatMap { index, child in expand(child, id: "\(prefix)\(index)", scope.child("\(index + 1)")) }
        case .single(let node):
            return expand(node, id: prefix.isEmpty ? "0" : prefix, scope.child("1"))
        }
    }

    private static func expand(_ node: Node, id: String, _ scope: Scope) -> [ChildItem] {
        guard case .element(let element) = node else {
            return [ChildItem(id: id, node: node, scope: scope)]
        }
        if element.isHidden(scope) {
            return []
        }
        switch element.content {
        case .loop(let loop):
            element.problems.forEach(scope.context.report)
            let resolved = loop.list(scope)
            let elements = resolved.array ?? resolved.object.map { $0.sorted { $0.key < $1.key }.map { JSONValue.object(["key": .string($0.key), "value": $0.value]) } } ?? []
            if resolved != .null, resolved.array == nil, resolved.object == nil {
                scope.context.report("ForEach needs a list, got \(resolved.text)")
            }
            let moves = loop.onMove.map { Reorder.list(at: scope.path, source: loop.written, elements: elements, handler: $0, scope) }
            return elements.enumerated().flatMap { index, element in
                let elementID = element["id"]?.text ?? "\(index)"
                var inner = scope.with([loop.name: element, loop.indexName: .number(Double(index))])
                inner.path += "ForEach[\(index)]"
                inner.row = true
                inner.move = moves.map { ($0, index) }
                return items(loop.content, inner, prefix: "\(id)-\(elementID)-")
            }
        case .choice(let choice):
            element.problems.forEach(scope.context.report)
            let holds = choice.condition.holds(scope)
            var inner = scope
            inner.path += holds ? "If(then)" : "If(else)"
            return items(holds ? choice.then : choice.otherwise, inner, prefix: "\(id)-\(holds ? "t" : "f")-")
        case .view, .custom, .none:
            return [ChildItem(id: id, node: node, scope: scope)]
        }
    }
}
