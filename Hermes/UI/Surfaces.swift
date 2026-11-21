// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import SwiftUI

/// A card in a conversation always sits on a surface; shared by the app and the
/// notification extension, which draws cards the same way.
enum CardSurfaces {
    private static let ownSurfaces: Set<String> = ["Card", "Carousel", "ScrollView", "Pages"]
    private static let surfaceModifiers: Set<String> = ["background", "glassEffect"]

    /// A card in a conversation always sits on a surface: unless the agent's view
    /// is one (a Card, a background, a component that might draw one) or a stack
    /// of nothing but those (a list of cards), it goes inside a Card, whose
    /// padding replaces the root's own; a Card within is drawn a shade up.
    /// A vertical ScrollView at the root draws nothing and scrolls inside the
    /// conversation's own scroll, so it becomes a VStack first, and the
    /// context's report says so.
    static func surfaced(_ view: JSONValue, components: Set<String>, context: CardContext? = nil) -> JSONValue {
        guard let root = view.object else { return view }
        let kind = root.keys.first { $0.first?.isUppercase == true } ?? ""
        if kind == "ScrollView", root["axis"]?.string != "horizontal", let children = root["ScrollView"] {
            var inner = root
            inner["ScrollView"] = nil
            inner["axis"] = nil
            inner["paging"] = nil
            inner["VStack"] = children
            inner["alignment"] = inner["alignment"] ?? .string("leading")
            context?.note("ScrollView at the root of a card was drawn as a VStack: the conversation already scrolls, and a ScrollView draws no surface. Start a card with a Card or a VStack")
            return surfaced(.object(inner), components: components, context: context)
        }
        let items = children(root[kind])
        if isSurface(view, components) || stacks.contains(kind) && !items.isEmpty && items.allSatisfy({ isSurface($0, components) }) {
            return view
        }
        var inner = root
        inner["padding"] = nil
        return .object(["Card": .array([.object(inner)])])
    }

    private static let stacks: Set<String> = ["VStack", "HStack", "Group"]

    private static func isSurface(_ node: JSONValue, _ components: Set<String>) -> Bool {
        guard let object = node.object else { return false }
        if object["ForEach"] != nil, let content = object["content"] {
            return isSurface(content, components)
        }
        if object["If"] != nil {
            return [object["then"], object["else"]].compactMap { $0 }.allSatisfy { isSurface($0, components) }
        }
        return object.keys.contains { ownSurfaces.contains($0) || components.contains($0) || surfaceModifiers.contains($0) }
    }

    private static func children(_ value: JSONValue?) -> [JSONValue] {
        guard let value else { return [] }
        return value.array ?? [value]
    }
}
