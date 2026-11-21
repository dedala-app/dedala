// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import SwiftUI
import UIKit

/// Draws a view in a window behind the app, at a given width and its full
/// height: measured and captured the same whatever is on the screen (the
/// keyboard, where the conversation is scrolled, a sheet).
enum Offscreen {
    static let maxHeight: CGFloat = 4000

    static func checkingScope(context: CardContext, stores: [String: JSONValue]) -> Scope {
        var scope = Scope(values: [:], boxes: [], context: context, data: [:], stores: stores)
        scope.checking = true
        return scope
    }

    static func draw(_ content: AnyView, width: CGFloat) async -> (fitting: CGSize, png: Data?)? {
        guard let scene = UIApplication.shared.connectedScenes.compactMap({ $0 as? UIWindowScene }).first else { return nil }
        let host = UIHostingController(rootView: content)
        host.safeAreaRegions = []
        let fitting = host.sizeThatFits(in: CGSize(width: width, height: .greatestFiniteMagnitude))
        let window = UIWindow(windowScene: scene)
        window.windowLevel = UIWindow.Level(rawValue: UIWindow.Level.normal.rawValue - 1)
        window.frame = CGRect(x: 0, y: 0, width: width, height: min(max(fitting.height, 60), maxHeight))
        window.rootViewController = host
        window.isHidden = false
        defer {
            window.isHidden = true
            window.rootViewController = nil
        }
        host.view.layoutIfNeeded()
        try? await Task.sleep(for: .milliseconds(1200))
        let format = UIGraphicsImageRendererFormat()
        format.scale = 1.5
        let image = UIGraphicsImageRenderer(bounds: window.bounds, format: format).image { _ in
            window.drawHierarchy(in: window.bounds, afterScreenUpdates: true)
        }
        return (fitting, image.pngData())
    }
}

/// A page the agent just sent, drawn at the phone's width whether or not it is
/// on screen, measured and captured like a card.
enum PageProbe {
    static func report(_ page: Hub.PageSpec, stores: [String: JSONValue], components: [String: JSONValue]) async -> (report: [String: JSONValue], png: Data?)? {
        guard let scene = UIApplication.shared.connectedScenes.compactMap({ $0 as? UIWindowScene }).first else { return nil }
        let width = SharedCards.pageWidth > 0 ? SharedCards.pageWidth : scene.screen.bounds.width
        let context = CardContext(cardID: page.id, component: { components[$0].flatMap(ComponentDefinition.init) }, onSend: { _, _ in })
        Tree.problems(in: page.view, components: components).forEach(context.report)
        let data: JSONValue = .null
        let derived = await CardDrawing.derive(page.script, data: data, state: page.state, stores: stores)
        let content = StateScopeView(
            initial: page.state,
            node: PageColumns.view(page.view, width: width, fold: 0),
            scope: Offscreen.checkingScope(context: context, stores: stores),
            script: page.script,
            data: data,
            derived: derived.values
        )
        .coordinateSpace(.named(CardContext.space))
        .onGeometryChange(for: CGSize.self) { $0.size } action: { context.size = $0 }
        .onPreferenceChange(LivePaths.self) { context.live = Set($0) }
        .padding(.horizontal, 16)
        .padding(.vertical, 20)
        .frame(width: width)
        .background(Color(.systemGroupedBackground))

        guard let drawn = await Offscreen.draw(AnyView(content), width: width) else { return nil }
        var issues = context.layoutIssues()
        if drawn.fitting.height > Offscreen.maxHeight {
            issues.append("The page is \(Int(drawn.fitting.height))pt tall; only the first \(Int(Offscreen.maxHeight))pt were drawn and checked. Make it shorter, move details into DisclosureGroups, or draw a long list with List, which the check draws twelve rows of")
        }
        var report: [String: JSONValue] = [
            "page": .string(page.id),
            "size": [.number(width.rounded()), .number(drawn.fitting.height.rounded())],
            "issues": .array(issues.map(JSONValue.string)),
            "diagnostics": .array(context.diagnostics.map(JSONValue.string)),
        ]
        if !context.derived.isEmpty { report["derived"] = .object(context.derived) }
        return (report, drawn.png)
    }
}

/// A card the agent just sent or changed, drawn alone behind the app.
enum CardProbe {
    static func report(_ id: String, card: JSONValue, components: [String: JSONValue], stores: [String: JSONValue],
                       frames: Bool = false) async -> (report: [String: JSONValue], png: Data?)? {
        let derived = await CardDrawing.derive(card, stores: stores)
        let drawn = CardDrawing.view(id, card: card, components: components, stores: stores, derived: derived.values)
        let framed = AnyView(drawn.view.padding(8).background(Color(.systemBackground)))
        guard let image = await Offscreen.draw(framed, width: SharedCards.width + 16) else { return nil }
        return (CardDrawing.report(id, context: drawn.context, frames: frames), image.png)
    }
}
