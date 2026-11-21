// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import SwiftUI

/// A component opened on its own, with what it was opened with: pushed over
/// a page, or the root of a sheet. It keeps the scope of the tap that opened
/// it, so it sees the page's store, state and script, and an action it was
/// handed runs where it was written.
struct Shown: Identifiable, Hashable {
    let id = UUID()
    let name: String
    let call: Element.Call
    let scope: Scope

    static func == (lhs: Shown, rhs: Shown) -> Bool { lhs.id == rhs.id }

    func hash(into hasher: inout Hasher) { hasher.combine(id) }
}

/// The screens over one page or in one sheet, in the order they were opened.
@Observable
final class Navigator {
    var path: [Shown] = []
    /// Closes the sheet this stack is in, when it is in one.
    var dismiss: (() -> Void)?

    func show(_ shown: Shown, replacing: Bool) {
        if replacing, !path.isEmpty {
            path[path.count - 1] = shown
        } else {
            path.append(shown)
        }
    }

    /// Back one screen; `all` back to the page, and out of the sheet when it is one.
    func close(all: Bool) {
        if all {
            path = []
            dismiss?()
        } else if path.isEmpty {
            dismiss?()
        } else {
            path.removeLast()
        }
    }
}

/// A screen's body with its bar buttons: the state the component declares
/// is the body's and the buttons', so a button can set it.
private struct ScreenBody: View {
    let body_: JSONValue
    let scope: Scope
    let toolbar: [JSONValue]

    init(body: JSONValue, scope: Scope, toolbar: [JSONValue]) {
        body_ = body
        self.scope = scope
        self.toolbar = toolbar
    }

    var body: some View {
        if case .stateful(let state, let rest) = Tree.node(body_) {
            StateScopeView(initial: state, node: rest, scope: scope, toolbar: toolbar)
        } else {
            NodeView(node: body_, scope: scope)
                .modifier(Toolbar(items: Toolbar.nodes(toolbar, scope), scope: scope))
        }
    }
}

/// A screen as it is drawn: the component's body in a scope of its own,
/// given its props, its state for as long as it is open, the stack it is
/// on, and the stores as they are now, not as they were when it opened.
struct ScreenView: View {
    let shown: Shown
    let navigator: Navigator
    var stores: [String: JSONValue]

    var body: some View {
        if let definition = shown.scope.context.component(shown.name) {
            let drawn = Self.scope(definition, shown, navigator: navigator, stores: stores)
            ScrollView {
                ScreenBody(body: drawn.body, scope: drawn.scope, toolbar: definition.toolbar)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.horizontal, 16)
                    .padding(.bottom, 24)
            }
            .background(Color(.systemGroupedBackground))
            .navigationTitle(definition.title.map { drawn.scope.text($0) } ?? shown.name)
            .toolbarTitleDisplayMode(.inline)
        } else {
            ContentUnavailableView("No screen \(shown.name)", systemImage: "questionmark.square.dashed",
                                   description: Text("Nothing by that name is defined."))
        }
    }

    static func scope(_ definition: ComponentDefinition, _ shown: Shown, navigator: Navigator, stores: [String: JSONValue]) -> (body: JSONValue, scope: Scope) {
        var opener = shown.scope
        opener.stores = stores
        var drawn = Tree.component(definition, shown.call, opener)
        drawn.scope.path = " › \(shown.name)"
        drawn.scope.probes = false
        drawn.scope.saved = nil
        drawn.scope.navigator = navigator
        return drawn
    }
}

/// A sheet with a screen at its root and its own stack over it.
struct ScreenSheet: View {
    let root: Shown
    let stores: [String: JSONValue]
    let close: () -> Void
    @State private var navigator = Navigator()

    var body: some View {
        NavigationStack(path: $navigator.path) {
            ScreenView(shown: root, navigator: navigator, stores: stores)
                .navigationDestination(for: Shown.self) { ScreenView(shown: $0, navigator: navigator, stores: stores) }
                .toolbar {
                    ToolbarItem(placement: .cancellationAction) { Button("Close", action: close) }
                }
        }
        .onAppear { navigator.dismiss = close }
    }
}
