// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import SwiftUI

/// Design tokens: how names in a Hermes UI tree become colours, fonts and
/// alignments.
enum Tokens {
    static func color(_ value: JSONValue?) -> Color? {
        guard let name = value?.string else { return nil }
        let parts = name.split(separator: "@", maxSplits: 1).map(String.init)
        guard let base = baseColor(parts[0]) else { return nil }
        if parts.count > 1, let opacity = Double(parts[1]) {
            return base.opacity(opacity)
        }
        return base
    }

    private static func baseColor(_ name: String) -> Color? {
        if name.hasPrefix("#") { return hex(name) }
        switch name {
        case "accent": return .accentColor
        case "primary": return .primary
        case "secondary": return .secondary
        case "tertiary": return Color(.tertiaryLabel)
        case "quaternary": return Color(.quaternaryLabel)
        case "background": return Color(.systemBackground)
        case "card": return Color(.secondarySystemGroupedBackground)
        case "groupedBackground": return Color(.systemGroupedBackground)
        case "fill": return Color(.systemFill)
        case "secondaryFill": return Color(.secondarySystemFill)
        case "separator": return Color(.separator)
        case "red": return .red
        case "orange": return .orange
        case "yellow": return .yellow
        case "green": return .green
        case "mint": return .mint
        case "teal": return .teal
        case "cyan": return .cyan
        case "blue": return .blue
        case "indigo": return .indigo
        case "purple": return .purple
        case "pink": return .pink
        case "brown": return .brown
        case "gray", "grey": return .gray
        case "white": return .white
        case "black": return .black
        case "clear": return .clear
        default: return nil
        }
    }

    private static func hex(_ string: String) -> Color? {
        let digits = string.dropFirst()
        guard digits.count == 6 || digits.count == 8, let value = UInt64(digits, radix: 16) else { return nil }
        let hasAlpha = digits.count == 8
        let red = Double((value >> (hasAlpha ? 24 : 16)) & 0xFF) / 255
        let green = Double((value >> (hasAlpha ? 16 : 8)) & 0xFF) / 255
        let blue = Double((value >> (hasAlpha ? 8 : 0)) & 0xFF) / 255
        let alpha = hasAlpha ? Double(value & 0xFF) / 255 : 1
        return Color(red: red, green: green, blue: blue, opacity: alpha)
    }

    static let palette: [Color] = [.blue, .orange, .green, .purple, .pink, .teal, .indigo, .yellow, .red, .mint]

    /// Colours, hierarchical styles, materials and gradients.
    static func style(_ value: JSONValue?) -> AnyShapeStyle? {
        guard let value else { return nil }
        if let name = value.string {
            switch name {
            case "primary": return AnyShapeStyle(.primary)
            case "secondary": return AnyShapeStyle(.secondary)
            case "tertiary": return AnyShapeStyle(.tertiary)
            case "quaternary": return AnyShapeStyle(.quaternary)
            case "ultraThinMaterial": return AnyShapeStyle(.ultraThinMaterial)
            case "thinMaterial": return AnyShapeStyle(.thinMaterial)
            case "regularMaterial", "material": return AnyShapeStyle(.regularMaterial)
            case "thickMaterial": return AnyShapeStyle(.thickMaterial)
            default: return color(value).map { AnyShapeStyle($0) }
            }
        }
        if let colors = value["gradient"]?.array {
            return gradient(colors.compactMap(color), direction: value["direction"]?.string, kind: value["kind"]?.string)
        }
        return nil
    }

    static func gradient(_ colors: [Color], direction: String?, kind: String?) -> AnyShapeStyle {
        let gradient = Gradient(colors: colors.isEmpty ? [.clear] : colors)
        switch kind {
        case "radial":
            return AnyShapeStyle(RadialGradient(gradient: gradient, center: .center, startRadius: 0, endRadius: 240))
        case "angular":
            return AnyShapeStyle(AngularGradient(gradient: gradient, center: .center))
        default:
            let (start, end): (UnitPoint, UnitPoint) = switch direction {
            case "up": (.bottom, .top)
            case "right": (.leading, .trailing)
            case "left": (.trailing, .leading)
            case "diagonal": (.topLeading, .bottomTrailing)
            default: (.top, .bottom)
            }
            return AnyShapeStyle(LinearGradient(gradient: gradient, startPoint: start, endPoint: end))
        }
    }

    static func font(_ value: JSONValue?) -> Font? {
        guard let value else { return nil }
        if let size = value.number, value.string == nil {
            return .system(size: size)
        }
        if let object = value.object {
            let size = object["size"]?.number ?? 17
            return .system(size: size, weight: weight(object["weight"]?.string) ?? .regular, design: design(object["design"]?.string) ?? .default)
        }
        guard let name = value.string else { return nil }
        let parts = name.split(separator: ".").map(String.init)
        guard let first = parts.first else { return nil }
        let style: Font.TextStyle? = switch first {
        case "largeTitle": .largeTitle
        case "title": .title
        case "title2": .title2
        case "title3": .title3
        case "headline": .headline
        case "subheadline": .subheadline
        case "body": .body
        case "callout": .callout
        case "footnote": .footnote
        case "caption": .caption
        case "caption2": .caption2
        default: nil
        }
        guard let style else { return nil }
        let fontDesign = parts.dropFirst().compactMap(design).first
        var font = Font.system(style, design: fontDesign)
        if let fontWeight = parts.dropFirst().compactMap(weight).first {
            font = font.weight(fontWeight)
        }
        if parts.contains("italic") {
            font = font.italic()
        }
        return font
    }

    static func weight(_ name: String?) -> Font.Weight? {
        switch name {
        case "ultraLight": .ultraLight
        case "thin": .thin
        case "light": .light
        case "regular": .regular
        case "medium": .medium
        case "semibold": .semibold
        case "bold": .bold
        case "heavy": .heavy
        case "black": .black
        default: nil
        }
    }

    static func design(_ name: String?) -> Font.Design? {
        switch name {
        case "rounded": .rounded
        case "serif": .serif
        case "monospaced": .monospaced
        case "default": .default
        default: nil
        }
    }

    static func alignment(_ name: String?) -> Alignment {
        switch name {
        case "leading": .leading
        case "trailing": .trailing
        case "top": .top
        case "bottom": .bottom
        case "topLeading": .topLeading
        case "topTrailing": .topTrailing
        case "bottomLeading": .bottomLeading
        case "bottomTrailing": .bottomTrailing
        default: .center
        }
    }

    static func horizontal(_ name: String?, default fallback: HorizontalAlignment = .leading) -> HorizontalAlignment {
        switch name {
        case "leading": .leading
        case "center": .center
        case "trailing": .trailing
        default: fallback
        }
    }

    static func vertical(_ name: String?) -> VerticalAlignment {
        switch name {
        case "top": .top
        case "bottom": .bottom
        case "firstTextBaseline": .firstTextBaseline
        case "lastTextBaseline": .lastTextBaseline
        default: .center
        }
    }

    static func textAlignment(_ name: String?) -> TextAlignment {
        switch name {
        case "center": .center
        case "trailing": .trailing
        default: .leading
        }
    }

    static func shape(_ value: JSONValue?) -> AnyShape {
        if let radius = value?.number {
            return AnyShape(RoundedRectangle(cornerRadius: radius, style: .continuous))
        }
        switch value?.string {
        case "circle": return AnyShape(Circle())
        case "capsule": return AnyShape(Capsule())
        case "rect", "rectangle": return AnyShape(Rectangle())
        default:
            if let string = value?.string, string.hasPrefix("rect:"), let radius = Double(string.dropFirst(5)) {
                return AnyShape(RoundedRectangle(cornerRadius: radius, style: .continuous))
            }
            return AnyShape(Capsule())
        }
    }
}
