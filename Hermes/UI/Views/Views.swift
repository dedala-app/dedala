// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import SwiftUI

/// Every view Hermes UI has, by its name: what reads its arguments from a
/// node. This table is the list of views; what each reads is its arguments.
enum Views {
    typealias Make = (inout Reader) -> any ViewSpec

    static let table: [String: Make] = [
        "VStack": { StackSpec(.vertical, &$0) },
        "HStack": { StackSpec(.horizontal, &$0) },
        "ZStack": { StackSpec(.depth, &$0) },
        "Group": { GroupSpec(&$0) },
        "Card": { CardSpec(&$0) },
        "Section": { SectionSpec(&$0) },
        "Masonry": { MasonrySpec(&$0) },
        "Columns": { ColumnsSpec(&$0) },
        "Grid": { GridSpec(&$0) },
        "ScrollView": { ScrollViewSpec(&$0) },
        "Carousel": { CarouselSpec(&$0) },
        "Pages": { PagesSpec(&$0) },
        "DisclosureGroup": { DisclosureGroupSpec(&$0) },
        "GlassGroup": { GlassGroupSpec(&$0) },
        "Spacer": { SpacerSpec(&$0) },
        "Divider": { DividerSpec(&$0) },
        "Text": { TextSpec(&$0) },
        "Label": { LabelSpec(&$0) },
        "Image": { ImageSpec(&$0) },
        "Color": { ColorSpec(&$0) },
        "Gradient": { GradientSpec(&$0) },
        "Circle": { ShapeSpec(.circle, &$0) },
        "Capsule": { ShapeSpec(.capsule, &$0) },
        "Rectangle": { ShapeSpec(.rectangle, &$0) },
        "Ellipse": { ShapeSpec(.ellipse, &$0) },
        "RoundedRectangle": { ShapeSpec(.rounded, &$0) },
        "Path": { ShapeSpec(.path, &$0) },
        "Chart": { ChartSpec(&$0) },
        "Map": { MapSpec(&$0) },
        "Gauge": { GaugeSpec(&$0) },
        "ProgressView": { ProgressViewSpec(&$0) },
        "Link": { LinkSpec(&$0) },
        "Button": { ButtonSpec(&$0) },
        "Menu": { MenuSpec(&$0) },
        "QRCode": { QRCodeSpec(&$0) },
        "Toggle": { ToggleSpec(&$0) },
        "Picker": { PickerSpec(&$0) },
        "Slider": { SliderSpec(&$0) },
        "Stepper": { StepperSpec(&$0) },
        "TextField": { TextFieldSpec(&$0) },
        "DatePicker": { DatePickerSpec(&$0) },
        "TextEditor": { TextEditorSpec(&$0) },
        "Photo": { PhotoSpec(&$0) },
        "Dictate": { DictateSpec(&$0) },
        "List": { ListSpec(&$0) },
        "File": { FileSpec(&$0) },
        "Face": { AppViewSpec("Face", &$0) },
        "Said": { AppViewSpec("Said", &$0) },
    ]

    /// The views the app draws for its own layouts, which the agent does not write.
    static let internalNames: Set<String> = ["Masonry"]

    /// Every view the agent can write; the plugin checks cards against the same list (plugin/dedala/grammar.json).
    static let names: [String] = table.keys.filter { !internalNames.contains($0) }.sorted()

    /// The views that hold other views as their main argument.
    static let containers: [String] = names.filter { name in
        var reader = Reader(view: name, node: [:])
        _ = table[name]?(&reader)
        return reader.holdsChildren
    }

    /// What each view takes besides its main argument, as its spec reads it.
    static let arguments: [String: [String: Reader.Kind]] = Dictionary(uniqueKeysWithValues: names.map { name in
        var reader = Reader(view: name, node: [:])
        _ = table[name]?(&reader)
        return (name, reader.declared)
    })

    /// Accepted on any node though no view reads them there: the keys of a
    /// chart's marks, and the ids and lines agents give nodes.
    static let tolerated: Set<String> = ["id", "say", "colors", "grouped", "xLabel"]

    /// Every argument some view takes. A node is told of a key that is none of
    /// these nor a modifier; one that belongs to another view is let through,
    /// as it always was (`arguments` says which view takes which).
    static let argumentNames: Set<String> = Set(arguments.values.flatMap(\.keys))
        .union(Element.flow.values.flatMap(\.keys)).union(Element.own).union(tolerated)

    /// The grammar the plugin checks cards with before they leave, as these
    /// tables have it: plugin/dedala/grammar.json is this, written out
    /// (`./mac grammar`), and a test holds the two equal.
    static var grammar: JSONValue {
        let takes = arguments.merging(Element.flow) { view, _ in view }
        return .object([
            "views": .array(names.map(JSONValue.string)),
            "containers": .array(containers.map(JSONValue.string)),
            "modifiers": .array(Modifiers.names.sorted().map(JSONValue.string)),
            "arguments": .array(argumentNames.sorted().map(JSONValue.string)),
            "takes": .object(takes.mapValues { .array($0.keys.sorted().map(JSONValue.string)) }),
            "actions": .array(ActionRunner.verbs.map(JSONValue.string)),
            "anywhere": .array(Element.own.union(tolerated).sorted().map(JSONValue.string)),
            "live": .array(LiveValues.names.sorted().map(JSONValue.string)),
        ])
    }

    /// The views only the app can draw, from what it holds: the agent's face,
    /// a card he said. A notification or a widget draws nothing for them.
    static var app: [String: (JSONValue, Scope) -> AnyView] = [:]
    /// How the app draws a file (`File`), from the attachments it holds.
    static var file: ((JSONValue, CGFloat?, Scope) -> AnyView)?
    /// In a widget, a button is a link into the app: the URL for an action, nil when it cannot open anything.
    static var widgetLink: ((JSONValue) -> URL?)?
    /// Takes or picks a photo (`Photo`): the app sets it; an extension has no camera.
    static var pickPhoto: ((String) async -> JSONValue?)?
    /// Listens and writes what is said (`Dictate`): the app sets it; `true` means it listens now.
    static var dictate: ((@escaping (String, Bool) -> Void) -> (() -> Void))?

    static func style(_ value: JSONValue?, _ scope: Scope) -> AnyShapeStyle? {
        guard let value else { return nil }
        let resolved = scope.resolve(value)
        guard resolved != .null else { return nil }
        let style = Tokens.style(resolved)
        if style == nil {
            scope.context.report("Unknown colour or style \(resolved.text)")
        }
        return style
    }

    static func style(_ value: Dynamic?, _ scope: Scope) -> AnyShapeStyle? {
        style(value?.resolve(scope), scope)
    }

    static func checkSymbol(_ name: String, _ scope: Scope) {
        if !name.isEmpty, UIImage(systemName: name) == nil {
            scope.context.report("Unknown SF Symbol '\(name)'")
        }
    }

    /// The bounds of a slider, a stepper or a gauge: two finite numbers, the first below the second.
    static func range(_ value: Dynamic?, _ scope: Scope, default fallback: ClosedRange<Double> = 0...1) -> ClosedRange<Double> {
        guard let bounds = scope.value(value)?.array, bounds.count == 2,
              let low = bounds[0].finite, let high = bounds[1].finite, low < high else { return fallback }
        return low...high
    }
}
