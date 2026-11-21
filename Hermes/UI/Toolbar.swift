// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import SwiftUI

/// The buttons a screen or a page puts in its bar, beside the app's own:
/// `Button`s and `Menu`s with a symbol, at most three, drawn by the system
/// as bar items and run in the scope of the body.
struct Toolbar: ViewModifier {
    let items: [Node]
    let scope: Scope

    static let most = 3

    func body(content: Content) -> some View {
        if items.isEmpty {
            content
        } else {
            content.toolbar {
                ToolbarItemGroup(placement: .topBarTrailing) {
                    ForEach(items.indices, id: \.self) { index in
                        TreeView(node: items[index], scope: scope)
                    }
                }
            }
        }
    }

    /// The items as nodes, those that are not a Button or a Menu with a
    /// symbol reported and left out.
    static func nodes(_ items: [JSONValue], _ scope: Scope) -> [Node] {
        var nodes: [Node] = []
        for (index, item) in items.enumerated() {
            guard let object = item.object, let kind = object.keys.first(where: { $0 == "Button" || $0 == "Menu" }) else {
                scope.context.report("toolbar[\(index)] is not a Button or a Menu: the bar takes only those")
                continue
            }
            guard object["symbol"] != nil else {
                scope.context.report("toolbar[\(index)] needs a symbol: the bar shows the \(kind) as its symbol, its title as the label")
                continue
            }
            if object["style"] != nil {
                scope.context.report("toolbar[\(index)]: the bar styles its own buttons; style is ignored")
            }
            if nodes.count == most {
                scope.context.report("toolbar holds at most \(most) items; the rest are left out — put them in a Menu")
                break
            }
            var cleaned = object
            cleaned["style"] = nil
            nodes.append(Tree.node(.object(cleaned)))
        }
        return nodes
    }
}
