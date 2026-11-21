// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import SwiftUI

/// Draws a Hermes UI view given as JSON: decoded once (see Tree), drawn from
/// what it decodes to.
struct NodeView: View {
    let node: JSONValue
    let scope: Scope

    var body: some View {
        Tree.render(Tree.node(node), scope)
    }
}

/// Gives a subtree the state declared with `state`, kept for the life of the view.
struct StateScopeView: View {
    let node: Node
    let scope: Scope
    let script: ScriptSpec?
    let data: JSONValue
    let key: String
    /// Buttons for the bar of the screen or page this is the body of, drawn
    /// in the same scope as the body: its state, script and stores.
    var toolbar: [Node] = []
    @State private var box: StateBox
    @State private var derived = StateBox([:])

    /// `script` and `data` are a card's or page's: the script derives its values
    /// from the data, this state, the time and the live values. What you change
    /// is kept in `scope.saved` under `key` and wins over `initial`.
    init(initial: [String: JSONValue], node: JSONValue, scope: Scope, script: ScriptSpec? = nil, data: JSONValue = .null,
         derived: [String: JSONValue] = [:], key: String? = nil, toolbar: [JSONValue] = []) {
        self.init(values: initial.mapValues { scope.resolve($0) }, node: Tree.node(node), scope: scope, script: script, data: data, derived: derived, key: key)
        self.toolbar = Toolbar.nodes(toolbar, scope)
    }

    /// The state a node declares for its subtree, already decoded.
    init(initial: [String: Dynamic], node: Node, scope: Scope, toolbar: [JSONValue] = []) {
        self.init(values: initial.mapValues { $0.resolve(scope) }, node: node, scope: scope, script: nil, data: .null, derived: [:], key: nil)
        self.toolbar = Toolbar.nodes(toolbar, scope)
    }

    private init(values: [String: JSONValue], node: Node, scope: Scope, script: ScriptSpec?, data: JSONValue, derived: [String: JSONValue], key: String?) {
        self.node = node
        self.scope = scope
        self.script = script
        self.data = data
        let key = key ?? "node\(scope.path)"
        self.key = key
        _box = State(initialValue: StateBox(values.merging(scope.saved?.values(at: key) ?? [:]) { $1 }))
        let known = derived.isEmpty ? DerivedCache.values[scope.context.cardID] ?? [:] : derived
        _derived = State(initialValue: StateBox(known))
    }

    var body: some View {
        content
            .onChange(of: box.values) { _, values in
                scope.saved?.set(values, at: key)
            }
    }

    @ViewBuilder private var content: some View {
        if let script {
            let host = ScriptHost(spec: script, data: data, context: scope.context, state: box, derived: derived, stores: scope.stores)
            let inner = scope.with(box: derived).with(box: box).with(script: host)
            TreeView(node: node, scope: inner)
                .modifier(Toolbar(items: toolbar, scope: inner))
                .task(id: Inputs(script: script, data: data, state: box.values, stores: script.stores(from: scope.stores), live: LiveValues.shared.version, minute: Clock.shared.minute)) {
                    await host.derive()
                    DerivedCache.values[scope.context.cardID] = derived.values
                }
        } else {
            TreeView(node: node, scope: scope.with(box: box))
                .modifier(Toolbar(items: toolbar, scope: scope.with(box: box)))
        }
    }

    private struct Inputs: Hashable {
        let script: ScriptSpec
        let data: JSONValue
        let state: [String: JSONValue]
        let stores: [String: JSONValue]
        let live: Int
        let minute: Date
    }
}

/// The derived values a card or page last computed, by its id: a page drawn
/// again (a swipe's preview, a tab shown anew) starts from them instead of
/// flashing empty until its script has run.
@MainActor
enum DerivedCache {
    static var values: [String: [String: JSONValue]] = [:]
}

/// A text that reports when it is cut short: a hidden copy measures the height
/// it would need at the same width.
struct TextProbe: View {
    let text: Text
    let path: String
    let context: CardContext?
    /// Off for a text given a `lineLimit`: it accepts being truncated.
    var checksWidth = true
    /// How many characters it shows, when known: a few of them broken across
    /// lines (a score, a time) is a defect even though nothing is cut.
    var characters: Int?
    @State private var shown: CGSize = .zero
    @State private var needed: CGFloat = 0
    @State private var line: CGSize = .zero

    var body: some View {
        text
            .background {
                text.fixedSize(horizontal: false, vertical: true)
                    .hidden()
                    .onGeometryChange(for: CGFloat.self) { $0.size.height } action: { height in
                        needed = height
                        context?.recordText(path, shown: shown.height, needed: height)
                    }
            }
            .background {
                text.fixedSize()
                    .hidden()
                    .onGeometryChange(for: CGSize.self) { $0.size } action: { size in
                        line = size
                        if checksWidth { context?.recordWidth(path, shown: shown, line: size) }
                    }
            }
            .onGeometryChange(for: CGSize.self) { $0.size } action: { size in
                shown = size
                context?.recordText(path, shown: size.height, needed: needed)
                if checksWidth { context?.recordWidth(path, shown: size, line: line) }
                context?.recordBreak(path, characters: characters, shown: size, line: line)
            }
            .transformPreference(LivePaths.self) { $0.append(path) }
    }
}

extension EnvironmentValues {
    /// What a `Card` sits on, then what a `Card` inside it sits on: the grouped
    /// card colours on grouped pages, the bubble grey inside a conversation.
    @Entry var cardSurface = [Color(.secondarySystemGroupedBackground), Color(.tertiarySystemGroupedBackground)]
}

struct CardSurface: ViewModifier {
    @Environment(\.cardSurface) private var surfaces

    func body(content: Content) -> some View {
        content
            .environment(\.cardSurface, surfaces.count > 1 ? Array(surfaces.dropFirst()) : surfaces)
            .background(surfaces[0], in: .rect(cornerRadius: 22, style: .continuous))
    }
}
