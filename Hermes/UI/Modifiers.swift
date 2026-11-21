// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import SwiftUI

/// Hermes UI modifiers, applied in a fixed order that reads naturally: text,
/// size, padding, surface, margin, effects, behaviour. `modifiers` then applies an
/// ordered list on top.
enum Modifiers {
    static let frameKeys: Set<String> = ["frame", "width", "height", "minWidth", "maxWidth", "minHeight", "maxHeight"]

    static let order: [String] = [
        "font", "fontWeight", "fontDesign", "bold", "italic", "foregroundStyle", "color", "lineLimit", "truncationMode", "lineSpacing",
        "multilineTextAlignment", "minimumScaleFactor", "monospacedDigit", "monospaced", "textCase", "tracking",
        "contentTransition", "symbolRenderingMode", "symbolVariant", "symbolEffect", "imageScale", "tint",
        "controlSize", "labelStyle", "aspectRatio",
        "frame",
        "fixedSize", "layoutPriority", "padding",
        "background", "glassEffect", "clip", "border", "overlay", "shadow",
        "margin",
        "opacity", "scale", "rotation", "offset", "blur", "saturation", "grayscale", "zIndex",
        "onTap", "disabled", "transition", "accessibilityLabel",
    ]

    static let names: Set<String> = Set(order).union(frameKeys).union(["cornerRadius", "clipShape"])

    /// What a modifier does to a view, given its value as resolved in scope.
    typealias Effect = (_ value: JSONValue, _ view: AnyView, _ scope: Scope, _ facts: Element.Facts) -> AnyView

    /// The modifiers that only take a value: each by its name.
    static func effect(_ key: String) -> Effect? {
        switch key {
        case "font":
            return { value, view, scope, facts in
                guard let font = Tokens.font(value) else {
                    scope.context.report("Unknown font \(value.text)")
                    return view
                }
                return AnyView(view.font(font))
            }
        case "fontWeight":
            return { value, view, scope, facts in
                return AnyView(view.fontWeight(Tokens.weight(value.string)))
            }
        case "fontDesign":
            return { value, view, scope, facts in
                return AnyView(view.fontDesign(Tokens.design(value.string)))
            }
        case "bold":
            return { value, view, scope, facts in
                return AnyView(view.bold(value.truthy))
            }
        case "italic":
            return { value, view, scope, facts in
                return AnyView(view.italic(value.truthy))
            }
        case "foregroundStyle", "color":
            return { value, view, scope, facts in
                if ["Text", "Label"].contains(facts.view), ["tertiary", "quaternary"].contains(value.string) {
                    return AnyView(view.foregroundStyle(.secondary))
                }
                guard let style = Views.style(value, scope) else { return view }
                return AnyView(view.foregroundStyle(style))
            }
        case "lineLimit":
            return { value, view, scope, facts in
                return AnyView(view.lineLimit(value.int.map { max(1, $0) }))
            }
        case "truncationMode":
            return { value, view, scope, facts in
                let mode: Text.TruncationMode = switch value.string {
                case "head": .head
                case "middle": .middle
                default: .tail
                }
                return AnyView(view.truncationMode(mode))
            }
        case "lineSpacing":
            return { value, view, scope, facts in
                return AnyView(view.lineSpacing(value.number ?? 0))
            }
        case "multilineTextAlignment":
            return { value, view, scope, facts in
                return AnyView(view.multilineTextAlignment(Tokens.textAlignment(value.string)))
            }
        case "minimumScaleFactor":
            return { value, view, scope, facts in
                return AnyView(view.minimumScaleFactor(value.number ?? 1))
            }
        case "monospacedDigit":
            return { value, view, scope, facts in
                return value.truthy ? AnyView(view.monospacedDigit()) : view
            }
        case "monospaced":
            return { value, view, scope, facts in
                return AnyView(view.monospaced(value.truthy))
            }
        case "textCase":
            return { value, view, scope, facts in
                return AnyView(view.textCase(value.string == "lowercase" ? .lowercase : value.string == "uppercase" ? .uppercase : nil))
            }
        case "tracking":
            return { value, view, scope, facts in
                return AnyView(view.tracking(value.number ?? 0))
            }
        case "contentTransition":
            return { value, view, scope, facts in
                switch value.string {
                case "numericText": return AnyView(view.contentTransition(.numericText()))
                case "opacity": return AnyView(view.contentTransition(.opacity))
                case "interpolate": return AnyView(view.contentTransition(.interpolate))
                case "symbol": return AnyView(view.contentTransition(.symbolEffect(.replace)))
                default: return view
                }
            }
        case "symbolRenderingMode":
            return { value, view, scope, facts in
                let mode: SymbolRenderingMode? = switch value.string {
                case "hierarchical": .hierarchical
                case "palette": .palette
                case "multicolor": .multicolor
                case "monochrome": .monochrome
                default: nil
                }
                return AnyView(view.symbolRenderingMode(mode))
            }
        case "symbolVariant":
            return { value, view, scope, facts in
                let variant: SymbolVariants = switch value.string {
                case "fill": .fill
                case "circle": .circle
                case "square": .square
                case "slash": .slash
                case "rectangle": .rectangle
                default: .none
                }
                return AnyView(view.symbolVariant(variant))
            }
        case "symbolEffect":
            return { value, view, scope, facts in
                return symbolEffect(value.string, on: view, scope)
            }
        case "imageScale":
            return { value, view, scope, facts in
                let scale: Image.Scale = value.string == "small" ? .small : value.string == "large" ? .large : .medium
                return AnyView(view.imageScale(scale))
            }
        case "tint":
            return { value, view, scope, facts in
                return AnyView(view.tint(Tokens.style(value)))
            }
        case "controlSize":
            return { value, view, scope, facts in
                let size: ControlSize = switch value.string {
                case "mini": .mini
                case "small": .small
                case "large": .large
                case "extraLarge": .extraLarge
                default: .regular
                }
                return AnyView(view.controlSize(size))
            }
        case "labelStyle":
            return { value, view, scope, facts in
                switch value.string {
                case "iconOnly": return AnyView(view.labelStyle(.iconOnly))
                case "titleOnly": return AnyView(view.labelStyle(.titleOnly))
                default: return AnyView(view.labelStyle(.titleAndIcon))
                }
            }
        case "aspectRatio":
            return { value, view, scope, facts in
                if let ratio = value.number {
                    return AnyView(view.aspectRatio(ratio, contentMode: .fit))
                }
                return AnyView(view.aspectRatio(contentMode: value.string == "fill" ? .fill : .fit))
            }
        case "fixedSize":
            return { value, view, scope, facts in
                switch value.string {
                case "horizontal": return AnyView(view.fixedSize(horizontal: true, vertical: false))
                case "vertical": return AnyView(view.fixedSize(horizontal: false, vertical: true))
                default:
                    if value.object != nil {
                        return AnyView(view.fixedSize(horizontal: value["horizontal"]?.truthy == true, vertical: value["vertical"]?.truthy == true))
                    }
                    return value.truthy ? AnyView(view.fixedSize()) : view
                }
            }
        case "layoutPriority", "zIndex":
            return { value, view, scope, facts in
                return view
            }
        case "padding", "margin":
            return { value, view, scope, facts in
                return padding(scope.resolve(value), on: view)
            }
        case "background":
            return { value, view, scope, facts in
                guard let style = Views.style(value, scope) else { return view }
                return AnyView(view.background(style))
            }
        case "glassEffect":
            return { value, view, scope, facts in
                return glass(value, on: view)
            }
        case "shadow":
            return { value, view, scope, facts in
                if let object = value.object {
                    return AnyView(view.shadow(
                        color: Tokens.color(object["color"]) ?? .black.opacity(0.15),
                        radius: object["radius"]?.number ?? 8,
                        x: object["x"]?.number ?? 0,
                        y: object["y"]?.number ?? 4
                    ))
                }
                return value.truthy ? AnyView(view.shadow(color: .black.opacity(0.08), radius: 12, y: 4)) : view
            }
        case "opacity":
            return { value, view, scope, facts in
                return AnyView(view.opacity(value.number ?? 1))
            }
        case "scale":
            return { value, view, scope, facts in
                return AnyView(view.scaleEffect(value.number ?? 1))
            }
        case "rotation":
            return { value, view, scope, facts in
                return AnyView(view.rotationEffect(.degrees(value.number ?? 0)))
            }
        case "offset":
            return { value, view, scope, facts in
                return AnyView(view.offset(x: value["x"]?.number ?? 0, y: value["y"]?.number ?? 0))
            }
        case "blur":
            return { value, view, scope, facts in
                return AnyView(view.blur(radius: value.number ?? 0))
            }
        case "saturation":
            return { value, view, scope, facts in
                return AnyView(view.saturation(value.number ?? 1))
            }
        case "grayscale":
            return { value, view, scope, facts in
                return AnyView(view.grayscale(value.number ?? (value.truthy ? 1 : 0)))
            }
        case "transition":
            return { value, view, scope, facts in
                return AnyView(view.transition(transition(value.string)))
            }
        case "accessibilityLabel":
            return { value, view, scope, facts in
                return AnyView(view.accessibilityLabel(value.text))
            }
        default:
            return nil
        }
    }

    private static func padding(_ value: JSONValue, on view: AnyView) -> AnyView {
        if let amount = value.number, value.bool == nil {
            return AnyView(view.padding(amount))
        }
        guard let object = value.object else {
            return value.truthy ? AnyView(view.padding()) : view
        }
        let horizontal = object["horizontal"]?.number ?? object["h"]?.number
        let vertical = object["vertical"]?.number ?? object["v"]?.number
        let insets = EdgeInsets(
            top: object["top"]?.number ?? vertical ?? 0,
            leading: object["leading"]?.number ?? horizontal ?? 0,
            bottom: object["bottom"]?.number ?? vertical ?? 0,
            trailing: object["trailing"]?.number ?? horizontal ?? 0
        )
        return AnyView(view.padding(insets))
    }

    private static func glass(_ value: JSONValue, on view: AnyView) -> AnyView {
        guard value.truthy else { return view }
        let object = value.object ?? [:]
        let variant = object["variant"]?.string ?? value.string ?? "regular"
        var glass: Glass = variant == "clear" ? .clear : .regular
        if let tint = Tokens.color(object["tint"]) {
            glass = glass.tint(tint)
        }
        if object["interactive"]?.truthy == true {
            glass = glass.interactive()
        }
        return AnyView(view.glassEffect(glass, in: Tokens.shape(object["shape"] ?? .string("capsule"))))
    }

    private static func symbolEffect(_ name: String?, on view: AnyView, _ scope: Scope) -> AnyView {
        switch name {
        case "bounce": return AnyView(view.symbolEffect(.bounce, options: .repeat(.continuous)))
        case "pulse": return AnyView(view.symbolEffect(.pulse, options: .repeat(.continuous)))
        case "variableColor": return AnyView(view.symbolEffect(.variableColor.iterative, options: .repeat(.continuous)))
        case "breathe": return AnyView(view.symbolEffect(.breathe, options: .repeat(.continuous)))
        case "wiggle": return AnyView(view.symbolEffect(.wiggle, options: .repeat(.continuous)))
        case "rotate": return AnyView(view.symbolEffect(.rotate, options: .repeat(.continuous)))
        case nil, "none", "": return view
        default:
            scope.context.report("Unknown symbol effect \(name ?? "")")
            return view
        }
    }

    private static func transition(_ name: String?) -> AnyTransition {
        switch name {
        case "scale": .scale.combined(with: .opacity)
        case "slide": .slide
        case "blur": AnyTransition(.blurReplace)
        case "push": AnyTransition(.push(from: .bottom))
        case "move:top": .move(edge: .top).combined(with: .opacity)
        case "move:bottom": .move(edge: .bottom).combined(with: .opacity)
        case "move:leading": .move(edge: .leading).combined(with: .opacity)
        case "move:trailing": .move(edge: .trailing).combined(with: .opacity)
        default: .opacity
        }
    }
}

/// The modifiers written on one node, read once: the keyed ones in the fixed
/// order, then the `modifiers` list in its own.
struct ModifierList {
    private typealias Step = (_ view: AnyView, _ scope: Scope, _ facts: Element.Facts) -> AnyView

    private var steps: [Step] = []
    private var priority: Dynamic?
    private var z: Dynamic?
    /// What is wrong with them as written.
    private(set) var problems: [String] = []
    /// The views they draw: an overlay, a background.
    private(set) var inner: [Children] = []

    init() {}

    init(_ node: [String: JSONValue], view: String) {
        for key in Modifiers.order {
            switch key {
            case "frame":
                if !Modifiers.frameKeys.isDisjoint(with: node.keys) {
                    var frame = node["frame"]?.object ?? [:]
                    for name in Modifiers.frameKeys where name != "frame" {
                        if let value = node[name] { frame[name] = value }
                    }
                    steps.append(Self.frame(frame))
                }
            case "clip":
                if let shape = node["clipShape"] ?? node["cornerRadius"] {
                    steps.append(Self.clip(shape))
                }
            case "border":
                if let border = node["border"] {
                    steps.append(Self.border(border, shape: node["clipShape"] ?? node["cornerRadius"]))
                }
            default:
                if let value = node[key], let step = one(key, value, node) {
                    steps.append(step)
                }
            }
        }
        for modifier in node["modifiers"]?.array ?? [] {
            let entries = modifier.object ?? [:]
            for key in entries.keys.sorted() {
                let value = entries[key] ?? .null
                if Modifiers.frameKeys.contains(key) {
                    steps.append(Self.frame(key == "frame" ? value.object ?? [:] : [key: value]))
                } else if key == "cornerRadius" || key == "clipShape" {
                    steps.append(Self.clip(value))
                } else if key == "border" {
                    steps.append(Self.border(value, shape: nil))
                } else if let step = one(key, value, node) {
                    steps.append(step)
                } else {
                    problems.append("Unknown modifier '\(key)'")
                }
            }
        }
        priority = Self.trait("layoutPriority", node)
        z = Self.trait("zIndex", node)
    }

    func apply(to view: AnyView, _ scope: Scope, _ facts: Element.Facts) -> AnyView {
        steps.reduce(view) { view, step in step(view, scope, facts) }
    }

    /// Layout traits (`layoutPriority`, `zIndex`) go on last, outside every other
    /// wrapper: a modifier applied on top of an `AnyView` that ends in a trait
    /// drops the trait, so a stack never saw the priority when it sat inside.
    func traits(on view: AnyView, _ scope: Scope) -> AnyView {
        let priority = scope.number(priority)
        let z = scope.number(z)
        guard priority != nil || z != nil else { return view }
        return AnyView(view.layoutPriority(priority ?? 0).zIndex(z ?? 0))
    }

    private static func trait(_ name: String, _ node: [String: JSONValue]) -> Dynamic? {
        if let value = node[name] { return Dynamic(value) }
        for modifier in node["modifiers"]?.array ?? [] {
            if let value = modifier.object?[name] { return Dynamic(value) }
        }
        return nil
    }

    private mutating func one(_ key: String, _ raw: JSONValue, _ node: [String: JSONValue]) -> Step? {
        if key == "onTap" {
            let action = Action(raw)
            problems += action.problems
            return { view, scope, _ in AnyView(view.contentShape(.rect).onTapGesture { ActionRunner.run(action, in: scope) }) }
        }
        if key == "overlay" || key == "background", raw.object?.keys.contains(where: { $0.first?.isUppercase == true }) == true || raw.array != nil {
            let alignment = Tokens.alignment(node["overlayAlignment"]?.string)
            let layer = Tree.decode(raw)
            inner.append(Children(single: layer))
            return { view, scope, _ in
                let layer = TreeView(node: layer, scope: scope.child(key))
                return key == "overlay"
                    ? AnyView(view.overlay(alignment: alignment) { layer })
                    : AnyView(view.background(alignment: alignment) { layer })
            }
        }
        if key == "disabled" {
            let condition = Condition(raw)
            problems += condition.problems
            return { view, scope, _ in AnyView(view.disabled(condition.holds(scope))) }
        }
        guard let effect = Modifiers.effect(key) else { return nil }
        let value = Dynamic(raw)
        problems += value.problems
        return { view, scope, facts in effect(value.resolve(scope), view, scope, facts) }
    }

    private static func frame(_ frame: [String: JSONValue]) -> Step {
        let lengths = frame.mapValues(Dynamic.init)
        let alignment = Tokens.alignment(frame["alignment"]?.string)
        let bounded = ["minWidth", "maxWidth", "minHeight", "maxHeight"].contains { frame[$0] != nil }
        return { view, scope, _ in
            func length(_ key: String) -> CGFloat? {
                guard let value = lengths[key]?.resolve(scope) else { return nil }
                if value.string == "infinity" { return .infinity }
                return value.number.map { CGFloat($0) }
            }
            var view = view
            if length("width") != nil || length("height") != nil {
                view = AnyView(view.frame(width: length("width"), height: length("height"), alignment: alignment))
            }
            if bounded {
                view = AnyView(view.frame(
                    minWidth: length("minWidth"),
                    maxWidth: length("maxWidth"),
                    minHeight: length("minHeight"),
                    maxHeight: length("maxHeight"),
                    alignment: alignment
                ))
            }
            return view
        }
    }

    private static func clip(_ shape: JSONValue) -> Step {
        let shape = Dynamic(shape)
        return { view, scope, _ in AnyView(view.clipShape(Tokens.shape(shape.resolve(scope)))) }
    }

    private static func border(_ border: JSONValue, shape: JSONValue?) -> Step {
        let border = Dynamic(border)
        let shape = shape.map(Dynamic.init)
        return { view, scope, _ in
            let value = border.resolve(scope)
            let color = Tokens.style(value["color"] ?? value) ?? AnyShapeStyle(Color(.separator))
            let width = value["width"]?.number ?? 1
            let dash = value["dash"]?.array?.compactMap(\.number).map { CGFloat($0) } ?? (value["dash"]?.truthy == true ? [4, 3] : [])
            let outline = shape.map { Tokens.shape($0.resolve(scope)) } ?? AnyShape(Rectangle())
            return AnyView(view.overlay { outline.stroke(color, style: StrokeStyle(lineWidth: width, dash: dash)) })
        }
    }
}
