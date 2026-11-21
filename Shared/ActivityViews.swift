// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import CryptoKit
import SwiftUI

/// An agent's activity design, drawn region by region over the latest data,
/// by the widget extension and by the app's preview alike.
struct ActivityViews {
    let id: String
    let file: JSONValue
    let context: CardContext

    init(_ attributes: HermesActivityAttributes) {
        let packed = attributes.design.flatMap { design in
            Self.opened(design).map { Data($0) } ?? Data(base64Encoded: design)
        }
        let inline = packed.flatMap { try? ($0 as NSData).decompressed(using: .zlib) as Data }
        let stored = HermesActivityAttributes.viewsURL(attributes.id).flatMap { try? Data(contentsOf: $0) }
        self.init(id: attributes.id, design: (inline ?? stored).flatMap { try? JSONValue.parse($0) } ?? .null)
    }

    init(id: String, design: JSONValue) {
        self.id = id
        file = design
        let components = design["components"]?.object ?? [:]
        context = CardContext(cardID: id, component: { components[$0].flatMap(ComponentDefinition.init) }, onSend: { _, _ in })
    }

    func has(_ slot: String) -> Bool {
        file["views"]?[slot] != nil
    }

    func color(_ key: String) -> Color? {
        Tokens.color(file[key])
    }

    func render(_ slot: String, _ state: HermesActivityAttributes.ContentState) -> some View {
        render(slot, data: Self.data(state))
    }

    /// An activity's data: sealed when it came through the relay, plain when
    /// the app started the activity itself.
    static func data(_ state: HermesActivityAttributes.ContentState) -> JSONValue {
        let plain = opened(state.data) ?? Data(state.data.utf8)
        return (try? JSONValue.parse(plain)) ?? .object([:])
    }

    /// Opens a sealed box written as a JSON string, with the paired device's key.
    private static func opened(_ text: String) -> Data? {
        guard text.hasPrefix("{"), let message = try? JSONDecoder().decode(Seal.Message.self, from: Data(text.utf8)),
              let key = PairingKeys.toApp else { return nil }
        return try? Seal.open(message, key: key)
    }

    @ViewBuilder
    func render(_ slot: String, data: JSONValue) -> some View {
        if let node = file["views"]?[slot] {
            NodeView(node: node, scope: Scope(values: [:], boxes: [], context: context, data: data.object ?? [:]))
        }
    }

    /// The lock screen region, falling back to `lockCompact` when it does not
    /// fit in the height the lock screen leaves inside its padding.
    func lock(data: JSONValue, maxHeight: CGFloat = 128) -> some View {
        FirstFitting(maxHeight: maxHeight) {
            render("lock", data: data)
            if has("lockCompact") {
                render("lockCompact", data: data)
            }
        }
        .clipped()
    }
}

/// Shows the first child whose ideal height fits and takes that child's
/// height, so the container shrinks to what it shows; ViewThatFits keeps the
/// height of the first child when a Live Activity is sized.
struct FirstFitting: Layout {
    let maxHeight: CGFloat

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        guard let index = choice(proposal.width, subviews) else { return .zero }
        let size = subviews[index].sizeThatFits(ProposedViewSize(width: proposal.width, height: nil))
        return CGSize(width: proposal.width ?? size.width, height: min(size.height, maxHeight))
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        let chosen = choice(bounds.width, subviews)
        for index in subviews.indices {
            if index == chosen {
                subviews[index].place(at: bounds.origin, proposal: ProposedViewSize(width: bounds.width, height: bounds.height))
            } else {
                subviews[index].place(at: CGPoint(x: bounds.minX, y: bounds.minY - 10_000), proposal: .zero)
            }
        }
    }

    private func choice(_ width: CGFloat?, _ subviews: Subviews) -> Int? {
        subviews.indices.first { subviews[$0].sizeThatFits(ProposedViewSize(width: width, height: nil)).height <= maxHeight }
            ?? subviews.indices.last
    }
}

/// The key that opens what the agent seals for the app, as pairing last left it.
nonisolated enum PairingKeys {
    static var toApp: SymmetricKey? { PairingStore.activityKey() }
}
