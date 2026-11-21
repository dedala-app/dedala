// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import CoreImage.CIFilterBuiltins
import SwiftUI
import UIKit

struct TextSpec: ViewSpec {
    private enum Form {
        case text(Dynamic, source: String?)
        case timer(Dynamic)
        case countdown(Dynamic)
        case date(Dynamic, style: String?)
        case number(Dynamic, format: String?)
        case unreadable
    }

    private let forms: [Form]

    init(_ reader: inout Reader) {
        let value = reader.main
        guard let object = value.object else {
            forms = [.text(reader.mainValue(), source: value.string)]
            return
        }
        var forms: [Form] = []
        if let timer = object["timer"] { forms.append(.timer(Dynamic(timer))) }
        if let end = object["countdown"] { forms.append(.countdown(Dynamic(end))) }
        if let date = object["date"] { forms.append(.date(Dynamic(date), style: object["style"]?.string)) }
        if let number = object["number"] { forms.append(.number(Dynamic(number), format: object["format"]?.string)) }
        self.forms = forms + [.unreadable]
    }

    func view(_ scope: Scope, _ element: Element) -> AnyView {
        for form in forms {
            switch form {
            case .text(let text, let source):
                let string = scope.text(text)
                if scope.probes { scope.context.recordSource(scope.path, source: source, shown: string) }
                return AnyView(TextProbe(text: Tree.markdown(string), path: scope.path, context: scope.probes ? scope.context : nil,
                                         checksWidth: !element.facts.limitsLines, characters: string.count))
            case .timer(let date):
                if let date = scope.value(date)?.date { return AnyView(Text(date, style: .timer)) }
            case .countdown(let end):
                if let end = scope.value(end)?.date { return AnyView(Text(timerInterval: Date.now...max(end, .now), countsDown: true)) }
            case .date(let date, let style):
                guard let date = scope.value(date)?.date else { continue }
                let style: Text.DateStyle = switch style {
                case "time": .time
                case "relative": .relative
                case "offset": .offset
                case "timer": .timer
                default: .date
                }
                return AnyView(Text(date, style: style))
            case .number(let number, let format):
                return AnyView(Text(ExpressionFunctions.format(number.resolve(scope), spec: format ?? "number")))
            case .unreadable:
                scope.context.report("Text needs a string, or one of date, timer, countdown, number")
            }
        }
        return AnyView(EmptyView())
    }
}

struct LabelSpec: ViewSpec {
    let title: Dynamic
    let symbol: Dynamic

    init(_ reader: inout Reader) {
        let value = reader.main
        let parts = value.array ?? [value["title"] ?? .null, value["symbol"] ?? .null]
        title = Dynamic(parts.first ?? .null)
        symbol = Dynamic(parts.count > 1 ? parts[1] : .null)
    }

    func view(_ scope: Scope, _ element: Element) -> AnyView {
        let title = scope.text(title)
        let symbol = scope.text(symbol)
        Views.checkSymbol(symbol, scope)
        return AnyView(Label { Tree.markdown(title) } icon: { Image(systemName: symbol) })
    }
}

struct ImageSpec: ViewSpec {
    let fill: Bool
    let asset: Dynamic?
    let url: Dynamic?
    let symbol: Dynamic?
    let variable: Dynamic?
    let resizable: Condition?
    /// A picture the phone holds (`Photo`): the value, or a reference to it, with a `local` path.
    let local: Dynamic?

    init(_ reader: inout Reader) {
        let value = reader.main
        fill = reader.word("contentMode") == "fill"
        asset = value["asset"].map(Dynamic.init)
        url = value["url"].map(Dynamic.init)
        local = value["local"] != nil || (value.string?.hasPrefix("$") == true) ? Dynamic(value) : nil
        symbol = (value.object == nil ? value : value["symbol"]).map(Dynamic.init)
        variable = value["variable"].map(Dynamic.init)
        resizable = reader.condition("resizable")
    }

    func view(_ scope: Scope, _ element: Element) -> AnyView {
        let fill = fill
        if let local, let path = local.resolve(scope)["local"]?.string, let image = UIImage(contentsOfFile: path) {
            return AnyView(Image(uiImage: image).resizable().aspectRatio(contentMode: fill ? .fill : .fit))
        }
        if let asset = asset.map({ scope.text($0) }) {
            guard let image = Assets.shared.image(asset) else {
                if !Assets.shared.isAwaited(asset) {
                    scope.context.report("No asset named \(asset)")
                }
                return AnyView(Image(systemName: "photo").foregroundStyle(.tertiary))
            }
            return AnyView(Image(uiImage: image).resizable().aspectRatio(contentMode: fill ? .fill : .fit))
        }
        if let url = url.map({ scope.text($0) }).flatMap(URL.init(string:)) {
            return AnyView(AsyncImage(url: url) { phase in
                if let image = phase.image {
                    image.resizable().aspectRatio(contentMode: fill ? .fill : .fit)
                } else if phase.error != nil {
                    Image(systemName: "photo").foregroundStyle(.tertiary)
                } else {
                    Rectangle().fill(.quaternary).overlay { ProgressView() }
                }
            })
        }
        let name = scope.text(symbol)
        Views.checkSymbol(name, scope)
        let image = scope.number(variable).map { Image(systemName: name, variableValue: $0) } ?? Image(systemName: name)
        if resizable?.holds(scope) == true {
            return AnyView(image.resizable().aspectRatio(contentMode: fill ? .fill : .fit))
        }
        return AnyView(image)
    }
}

struct ColorSpec: ViewSpec {
    let color: Dynamic

    init(_ reader: inout Reader) {
        color = reader.mainValue()
    }

    func view(_ scope: Scope, _ element: Element) -> AnyView {
        AnyView(Rectangle().fill(Views.style(color, scope) ?? AnyShapeStyle(.clear)))
    }
}

struct GradientSpec: ViewSpec {
    let colors: Dynamic
    let direction: String?
    let kind: String?

    init(_ reader: inout Reader) {
        colors = reader.mainValue()
        direction = reader.word("direction")
        kind = reader.word("kind")
    }

    func view(_ scope: Scope, _ element: Element) -> AnyView {
        let colors = (colors.resolve(scope).array ?? []).compactMap { Tokens.color($0) }
        return AnyView(Rectangle().fill(Tokens.gradient(colors, direction: direction, kind: kind)))
    }
}

/// `Circle`, `Capsule`, `Rectangle`, `Ellipse`, `RoundedRectangle`, `Path`: a
/// shape filled, stroked or both.
struct ShapeSpec: ViewSpec {
    enum Outline {
        case circle, capsule, rectangle, ellipse, rounded, path
    }

    let outline: Outline
    let value: Dynamic
    let fill: Dynamic?
    let stroke: Dynamic?
    let lineWidth: Dynamic?
    let closed: Condition?
    let smooth: Condition?

    init(_ outline: Outline, _ reader: inout Reader) {
        self.outline = outline
        value = reader.mainValue()
        fill = reader.value("fill")
        stroke = reader.value("stroke")
        lineWidth = reader.value("lineWidth")
        closed = outline == .path ? reader.condition("closed") : nil
        smooth = outline == .path ? reader.condition("smooth") : nil
    }

    func view(_ scope: Scope, _ element: Element) -> AnyView {
        switch outline {
        case .circle: return draw(Circle(), scope)
        case .capsule: return draw(Capsule(), scope)
        case .rectangle: return draw(Rectangle(), scope)
        case .ellipse: return draw(Ellipse(), scope)
        case .rounded: return draw(RoundedRectangle(cornerRadius: scope.number(value) ?? 12, style: .continuous), scope)
        case .path:
            let points = (value.resolve(scope).array ?? []).compactMap { point -> CGPoint? in
                guard let pair = point.array, pair.count == 2, let x = pair[0].number, let y = pair[1].number else { return nil }
                return CGPoint(x: x, y: y)
            }
            return draw(UnitPath(points: points, closed: closed?.holds(scope) == true, smooth: smooth?.holds(scope) == true), scope, defaultStroke: true)
        }
    }

    private func draw<S: Shape>(_ shape: S, _ scope: Scope, defaultStroke: Bool = false) -> AnyView {
        let fill = Views.style(fill, scope)
        let stroke = Views.style(stroke, scope)
        let width = scope.number(lineWidth) ?? (defaultStroke ? 3 : 1)
        let strokeStyle = StrokeStyle(lineWidth: width, lineCap: .round, lineJoin: .round)
        switch (fill, stroke) {
        case (let fill?, let stroke?):
            return AnyView(shape.fill(fill).overlay(shape.stroke(stroke, style: strokeStyle)))
        case (nil, let stroke?):
            return AnyView(shape.stroke(stroke, style: strokeStyle))
        case (let fill?, nil):
            return AnyView(shape.fill(fill))
        case (nil, nil):
            return defaultStroke ? AnyView(shape.stroke(.tint, style: strokeStyle)) : AnyView(shape.fill(.tint))
        }
    }
}

struct UnitPath: Shape {
    let points: [CGPoint]
    let closed: Bool
    let smooth: Bool

    func path(in rect: CGRect) -> Path {
        let mapped = points.map { CGPoint(x: rect.minX + $0.x * rect.width, y: rect.minY + $0.y * rect.height) }
        var path = Path()
        guard let first = mapped.first else { return path }
        path.move(to: first)
        if smooth, mapped.count > 2 {
            for index in 1..<mapped.count {
                let previous = mapped[index - 1]
                let point = mapped[index]
                let middle = CGPoint(x: (previous.x + point.x) / 2, y: (previous.y + point.y) / 2)
                path.addQuadCurve(to: middle, control: previous)
                if index == mapped.count - 1 {
                    path.addQuadCurve(to: point, control: middle)
                }
            }
        } else {
            for point in mapped.dropFirst() {
                path.addLine(to: point)
            }
        }
        if closed {
            path.closeSubpath()
        }
        return path
    }
}

struct GaugeSpec: ViewSpec {
    let value: Dynamic
    let range: Dynamic?
    let label: Dynamic?
    let current: Dynamic?
    let low: Dynamic?
    let high: Dynamic?
    let style: Dynamic?

    init(_ reader: inout Reader) {
        value = reader.mainValue()
        range = reader.value("in")
        label = reader.value("label")
        current = reader.value("current")
        low = reader.value("min")
        high = reader.value("max")
        style = reader.value("style")
    }

    func view(_ scope: Scope, _ element: Element) -> AnyView {
        let range = Views.range(range, scope)
        let current = min(max(scope.number(value) ?? 0, range.lowerBound), range.upperBound)
        let label = label.map { scope.text($0) }
        let currentLabel = self.current.map { scope.text($0) }
        let gauge = Gauge(value: current, in: range) {
            if let label { Text(label) }
        } currentValueLabel: {
            if let currentLabel { Text(currentLabel) }
        } minimumValueLabel: {
            if let low { Text(scope.text(low)) }
        } maximumValueLabel: {
            if let high { Text(scope.text(high)) }
        }
        switch scope.string(style) {
        case "circular": return AnyView(gauge.gaugeStyle(.accessoryCircular))
        case "capacity": return AnyView(gauge.gaugeStyle(.accessoryCircularCapacity))
        case "bar": return AnyView(gauge.gaugeStyle(.accessoryLinearCapacity))
        default: return AnyView(gauge.gaugeStyle(.linearCapacity))
        }
    }
}

struct ProgressViewSpec: ViewSpec {
    let value: Dynamic
    let label: Dynamic?
    let total: Dynamic?

    init(_ reader: inout Reader) {
        value = reader.mainValue()
        label = reader.value("label")
        total = reader.value("total")
    }

    func view(_ scope: Scope, _ element: Element) -> AnyView {
        let label = label.map { scope.text($0) }
        if let progress = value.resolve(scope).number {
            let total = scope.number(total) ?? 1
            return AnyView(ProgressBar(fraction: total > 0 ? min(max(progress, 0), total) / total : 0, label: label))
        }
        return AnyView(ProgressView { if let label { Text(label) } })
    }
}

/// A linear progress bar drawn in SwiftUI alone, so it looks the same on
/// screen, in Live Activities and in offscreen captures.
struct ProgressBar: View {
    let fraction: Double
    let label: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            if let label { Text(label) }
            Capsule()
                .fill(.tint.opacity(0.25))
                .frame(height: 4)
                .overlay(alignment: .leading) {
                    GeometryReader { proxy in
                        Capsule()
                            .fill(.tint)
                            .frame(width: proxy.size.width * fraction)
                    }
                }
                .accessibilityElement()
                .accessibilityValue(Text(fraction, format: .percent.precision(.fractionLength(0))))
        }
    }
}

struct LinkSpec: ViewSpec {
    let title: Dynamic
    let url: Dynamic?

    init(_ reader: inout Reader) {
        title = reader.mainValue()
        url = reader.value("url")
    }

    func view(_ scope: Scope, _ element: Element) -> AnyView {
        guard let url = URL(string: scope.text(url)) else {
            scope.context.report("Link needs a valid url")
            return AnyView(Text(scope.text(title)))
        }
        return AnyView(Link(scope.text(title), destination: url))
    }
}

struct QRCodeSpec: ViewSpec {
    let payload: Dynamic

    init(_ reader: inout Reader) {
        payload = reader.mainValue()
    }

    func view(_ scope: Scope, _ element: Element) -> AnyView {
        let payload = scope.text(payload)
        let filter = CIFilter.qrCodeGenerator()
        filter.message = Data(payload.utf8)
        filter.correctionLevel = "M"
        guard let output = filter.outputImage, let image = CIContext().createCGImage(output, from: output.extent) else {
            scope.context.report("QRCode could not encode '\(payload)'")
            return AnyView(EmptyView())
        }
        let code = Image(decorative: image, scale: 1)
            .interpolation(.none)
            .resizable()
            .aspectRatio(1, contentMode: .fit)
            .padding(8)
            .background(.white, in: RoundedRectangle(cornerRadius: 8, style: .continuous))
            .accessibilityLabel("QR code")
        return AnyView(code.frame(width: element.facts.hasWidth ? nil : 160, height: element.facts.hasHeight ? nil : 160))
    }
}

/// `Face`, `Said`, `Item`: the views only the app can draw, from what it
/// holds. A notification or a widget draws nothing for them.
/// `{"File": file, "height"}`: a record's file, a text store or a folder's
/// file, or a text, drawn natively by its format. The app draws it; a
/// notification or a widget shows its text.
struct FileSpec: ViewSpec {
    let value: Dynamic
    let height: Dynamic?

    init(_ reader: inout Reader) {
        value = reader.mainValue()
        height = reader.value("height")
    }

    func view(_ scope: Scope, _ element: Element) -> AnyView {
        let resolved = value.resolve(scope)
        if let draw = Views.file {
            return draw(resolved, scope.length(height), scope)
        }
        return AnyView(Text(resolved["text"]?.string ?? resolved["name"]?.string ?? resolved.text).font(.body))
    }
}

struct AppViewSpec: ViewSpec {
    let name: String
    let value: JSONValue

    init(_ name: String, _ reader: inout Reader) {
        self.name = name
        value = reader.main
    }

    func view(_ scope: Scope, _ element: Element) -> AnyView {
        Views.app[name]?(value, scope) ?? AnyView(EmptyView())
    }
}
