// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import SwiftUI

/// A card drawn as the conversation draws it, and what it measures: the app
/// draws it in a window behind its own, the notification extension renders it
/// to an image, and both report it the same way, whatever is on the screen.
enum CardDrawing {
    @MainActor
    static func view(_ id: String, card: JSONValue, components: [String: JSONValue], stores: [String: JSONValue] = [:],
                     derived: [String: JSONValue] = [:]) -> (view: AnyView, context: CardContext) {
        let context = CardContext(cardID: id, component: { components[$0].flatMap(ComponentDefinition.init) }, onSend: { _, _ in })
        Tree.problems(in: card["view"] ?? .null, components: components).forEach(context.report)
        let content = StateScopeView(
            initial: card["state"]?.object ?? [:],
            node: CardSurfaces.surfaced(card["view"] ?? .null, components: Set(components.keys), context: context),
            scope: Scope(values: [:], boxes: [], context: context, data: card["data"]?.object ?? [:], stores: stores),
            script: ScriptSpec(card),
            data: card["data"] ?? .object([:]),
            derived: derived
        )
        .coordinateSpace(.named(CardContext.space))
        .onGeometryChange(for: CGSize.self) { $0.size } action: { context.size = $0 }
        .onPreferenceChange(LivePaths.self) { context.live = Set($0) }
        .frame(width: SharedCards.width)
        .fixedSize(horizontal: false, vertical: true)
        .environment(\.cardSurface, [Color(.secondarySystemBackground), Color(.tertiarySystemBackground)])
        return (AnyView(content), context)
    }

    /// Derived values computed before a card or page is drawn to be measured or
    /// captured: drawn first without them, it would be measured a line short.
    @MainActor
    static func derive(_ card: JSONValue, stores: [String: JSONValue] = [:]) async -> (values: [String: JSONValue], problems: [String]) {
        await derive(ScriptSpec(card), data: card["data"] ?? .object([:]), state: card["state"]?.object ?? [:], stores: stores)
    }

    @MainActor
    static func derive(_ spec: ScriptSpec?, data: JSONValue, state: [String: JSONValue], stores: [String: JSONValue] = [:]) async -> (values: [String: JSONValue], problems: [String]) {
        guard let spec else { return ([:], []) }
        let context = CardContext(cardID: "", component: { _ in nil }, onSend: { _, _ in })
        let host = ScriptHost(spec: spec, data: data, context: context, state: StateBox(state), derived: StateBox([:]), stores: stores)
        await host.derive()
        return (context.derived, context.diagnostics)
    }

    static func tallNote(_ height: Double, _ shown: Double) -> String {
        "The card is \(Int(height))pt tall and \(Int(shown))pt of the conversation show at once, so he scrolls through it. Fine for something read top to bottom; keep the call and the buttons near the top"
    }

    @MainActor
    static func report(_ id: String, context: CardContext, frames: Bool = false) -> [String: JSONValue] {
        let height = context.size.height
        var report: [String: JSONValue] = [
            "card": .string(id),
            "size": [.number(SharedCards.width.rounded()), .number(height.rounded())],
            "issues": .array(context.layoutIssues().map(JSONValue.string)),
            "diagnostics": .array(context.diagnostics.map(JSONValue.string)),
            "at": .string(ISO8601DateFormatter().string(from: Date())),
        ]
        if height > SharedCards.viewport + 1 {
            report["notes"] = [.string(tallNote(height, SharedCards.viewport))]
        }
        if !context.derived.isEmpty { report["derived"] = .object(context.derived) }
        if frames {
            let live = context.live
            report["frames"] = .array(context.frames.sorted { $0.key < $1.key }.compactMap { path, entry in
                guard live?.contains(path) ?? true else { return nil }
                let frame = entry.frame
                return .object(["path": .string(path), "view": .string(entry.view), "x": .number(frame.minX), "y": .number(frame.minY), "w": .number(frame.width), "h": .number(frame.height)])
            })
        }
        return report
    }
}
