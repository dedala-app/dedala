// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import SwiftUI
import Testing
@testable import Hermes

/// The notification extension draws cards with an ImageRenderer, with no window:
/// the layout checks must still measure there.
@MainActor
@Suite("Offscreen")
struct OffscreenProbeTests {
    @Test func cutTextIsFoundWithoutAWindow() {
        let context = CardContext(cardID: "probe", component: { _ in nil }, onSend: { _, _ in })
        let view: JSONValue = .object(["Card": .array([
            .object(["Text": .string(String(repeating: "A long line that cannot fit in twenty points of height. ", count: 6)), "frame": .object(["height": .number(20)])]),
        ])])
        let content = StateScopeView(initial: [:], node: view, scope: Scope(values: [:], boxes: [], context: context))
            .coordinateSpace(.named(CardContext.space))
            .onGeometryChange(for: CGSize.self) { $0.size } action: { context.size = $0 }
            .frame(width: 354)
            .fixedSize(horizontal: false, vertical: true)
        let renderer = ImageRenderer(content: content)
        _ = renderer.uiImage
        #expect(!context.layoutIssues().isEmpty)
    }
}
