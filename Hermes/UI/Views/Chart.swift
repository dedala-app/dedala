// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import Charts
import SwiftUI

struct ChartSpec: ViewSpec {
    /// The marks as written: each reads its data and its options when drawn.
    let marks: [JSONValue]
    let xAxis: Condition?
    let yAxis: Condition?
    let yDomain: Dynamic?
    let legend: Condition?

    init(_ reader: inout Reader) {
        let value = reader.main
        marks = value.array ?? [value]
        xAxis = reader.condition("xAxis")
        yAxis = reader.condition("yAxis")
        yDomain = reader.value("yDomain")
        legend = reader.condition("legend")
    }

    func view(_ scope: Scope, _ element: Element) -> AnyView {
        let marks = marks.enumerated().compactMap { index, mark in
            ChartMarkSpec(mark, index: index, scope: scope)
        }
        let domain = scope.value(yDomain)?.array.flatMap { bounds -> ClosedRange<Double>? in
            guard bounds.count == 2, let low = bounds[0].finite, let high = bounds[1].finite, low < high else { return nil }
            return low...high
        }
        let view = ChartNodeView(
            marks: marks,
            xAxis: xAxis?.holds(scope) ?? true,
            yAxis: yAxis?.holds(scope) ?? true,
            yDomain: domain,
            legend: legend?.holds(scope) ?? true
        )
        return AnyView(view.frame(height: element.facts.hasHeight ? nil : 160))
    }
}

struct ChartPoint: Identifiable {
    let id: Int
    let x: String
    let xNumber: Double?
    let y: Double
    let series: String
    let style: AnyShapeStyle
    var label: String? = nil
    var axisLabel: String? = nil
}

struct ChartMarkSpec: Identifiable {
    let id: Int
    let type: String
    let points: [ChartPoint]
    let smooth: Bool
    let innerRadius: Double
    let grouped: Bool
    let legend: [(String, Color)]

    init?(_ mark: JSONValue, index: Int, scope: Scope) {
        guard let type = mark["type"]?.string else {
            scope.context.report("A chart mark needs a type")
            return nil
        }
        guard ["line", "area", "bar", "point", "rule", "sector"].contains(type) else {
            scope.context.report("Unknown chart mark '\(type)'")
            return nil
        }
        id = index
        self.type = type
        smooth = scope.truthy(mark["smooth"])
        innerRadius = scope.number(mark["innerRadius"]) ?? 0
        grouped = scope.truthy(mark["grouped"])
        let base = Tokens.color(scope.resolve(mark["color"] ?? .null)) ?? (index == 0 ? .accentColor : Tokens.palette[index % Tokens.palette.count])
        let gradient = scope.truthy(mark["gradient"])

        if type == "rule" {
            let value = scope.number(mark["value"]) ?? 0
            points = [ChartPoint(id: 0, x: "", xNumber: nil, y: value, series: "rule", style: AnyShapeStyle(base))]
            legend = []
            return
        }

        let data = scope.resolve(mark["data"] ?? .null).array ?? []
        if data.isEmpty {
            scope.context.report("Chart mark \(type) has no data")
        }
        let xKey = mark["x"]?.string ?? "x"
        let yKey = mark["y"]?.string ?? "y"
        let seriesKey = mark["series"]?.string ?? (type == "sector" ? xKey : nil)
        let labelKey = mark["label"]?.string
        let axisKey = mark["xLabel"]?.string
        let named = scope.resolve(mark["colors"] ?? .null).object ?? [:]
        var seriesColors: [String: Color] = [:]
        var order: [String] = []
        for element in data {
            let name = seriesKey.flatMap { element[$0]?.text } ?? "\(index)"
            if seriesColors[name] == nil {
                seriesColors[name] = Tokens.color(named[name]) ?? (seriesKey == nil ? base : Tokens.palette[order.count % Tokens.palette.count])
                order.append(name)
            }
        }
        legend = seriesKey == nil ? [] : order.map { ($0, seriesColors[$0] ?? base) }
        let allNumeric = data.allSatisfy { element in
            guard let x = element[xKey] else { return false }
            if case .number = x { return true }
            return false
        }
        points = data.enumerated().map { position, element in
            let name = seriesKey.flatMap { element[$0]?.text } ?? "\(index)"
            let x = element[xKey] ?? .number(Double(position))
            let color = seriesColors[name] ?? base
            let style: AnyShapeStyle = if type == "area" && gradient {
                AnyShapeStyle(LinearGradient(colors: [color.opacity(0.4), color.opacity(0.02)], startPoint: .top, endPoint: .bottom))
            } else {
                AnyShapeStyle(color)
            }
            return ChartPoint(
                id: position,
                x: x.date.map { $0.formatted(.dateTime.weekday(.abbreviated)) } ?? x.text,
                xNumber: allNumeric ? x.number : nil,
                y: element[yKey]?.number ?? 0,
                series: name,
                style: style,
                label: labelKey.flatMap { element[$0]?.text },
                axisLabel: axisKey.flatMap { element[$0]?.text }
            )
        }
    }
}

struct ChartNodeView: View {
    let marks: [ChartMarkSpec]
    let xAxis: Bool
    let yAxis: Bool
    let yDomain: ClosedRange<Double>?
    let legend: Bool

    private var axisLabels: [String: String] {
        var labels: [String: String] = [:]
        for point in marks.flatMap(\.points) {
            if let label = point.axisLabel { labels[point.x] = label }
        }
        return labels
    }

    private var legendItems: [(String, Color)] {
        var seen = Set<String>()
        return marks.flatMap(\.legend).filter { seen.insert($0.0).inserted }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            chart
            if legend, legendItems.count > 1 {
                HStack(spacing: 12) {
                    ForEach(legendItems, id: \.0) { name, color in
                        Label {
                            Text(name)
                        } icon: {
                            Circle().fill(color).frame(width: 8, height: 8)
                        }
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    }
                }
            }
        }
    }

    @ViewBuilder
    private var chart: some View {
        let base = Chart {
            ForEach(marks) { mark in
                ForEach(mark.points) { point in
                    MarkContent(mark: mark, point: point)
                }
            }
        }
        .chartYAxis(yAxis ? .automatic : .hidden)
        .chartLegend(.hidden)
        let labels = axisLabels
        let axed = Group {
            if !xAxis {
                base.chartXAxis(.hidden)
            } else if labels.isEmpty {
                base
            } else {
                base.chartXAxis {
                    AxisMarks { value in
                        AxisValueLabel {
                            Text(value.as(String.self).flatMap { labels[$0] } ?? value.as(String.self) ?? "")
                        }
                    }
                }
            }
        }
        if let yDomain {
            axed.chartYScale(domain: yDomain)
        } else {
            axed
        }
    }
}

struct MarkContent: ChartContent {
    let mark: ChartMarkSpec
    let point: ChartPoint

    @ViewBuilder private var annotation: some View {
        if let label = point.label {
            Text(label).font(.caption2.weight(.medium)).foregroundStyle(.secondary)
        }
    }

    var body: some ChartContent {
        if mark.type == "sector" {
            SectorMark(angle: .value("Value", point.y), innerRadius: .ratio(mark.innerRadius), angularInset: 1.5)
                .cornerRadius(4)
                .foregroundStyle(point.style)
        } else if mark.type == "rule" {
            RuleMark(y: .value("Value", point.y))
                .lineStyle(StrokeStyle(lineWidth: 1, dash: [4, 3]))
                .foregroundStyle(point.style)
        } else if let x = point.xNumber {
            if mark.type == "bar" {
                BarMark(x: .value("X", x), y: .value("Y", point.y))
                    .cornerRadius(4)
                    .foregroundStyle(point.style)
                    .annotation(position: .top) { annotation }
            } else if mark.type == "area" {
                AreaMark(x: .value("X", x), y: .value("Y", point.y))
                    .interpolationMethod(mark.smooth ? .catmullRom : .linear)
                    .foregroundStyle(point.style)
            } else if mark.type == "point" {
                PointMark(x: .value("X", x), y: .value("Y", point.y))
                    .foregroundStyle(point.style)
                    .annotation(position: .top) { annotation }
            } else {
                LineMark(x: .value("X", x), y: .value("Y", point.y), series: .value("Series", point.series))
                    .interpolationMethod(mark.smooth ? .catmullRom : .linear)
                    .lineStyle(StrokeStyle(lineWidth: 2.5, lineCap: .round))
                    .foregroundStyle(point.style)
            }
        } else {
            if mark.type == "bar" && mark.grouped {
                BarMark(x: .value("X", point.x), y: .value("Y", point.y))
                    .position(by: .value("Series", point.series))
                    .cornerRadius(4)
                    .foregroundStyle(point.style)
                    .annotation(position: .top) { annotation }
            } else if mark.type == "bar" {
                BarMark(x: .value("X", point.x), y: .value("Y", point.y))
                    .cornerRadius(4)
                    .foregroundStyle(point.style)
                    .annotation(position: .top) { annotation }
            } else if mark.type == "area" {
                AreaMark(x: .value("X", point.x), y: .value("Y", point.y))
                    .interpolationMethod(mark.smooth ? .catmullRom : .linear)
                    .foregroundStyle(point.style)
            } else if mark.type == "point" {
                PointMark(x: .value("X", point.x), y: .value("Y", point.y))
                    .foregroundStyle(point.style)
                    .annotation(position: .top) { annotation }
            } else {
                LineMark(x: .value("X", point.x), y: .value("Y", point.y), series: .value("Series", point.series))
                    .interpolationMethod(mark.smooth ? .catmullRom : .linear)
                    .lineStyle(StrokeStyle(lineWidth: 2.5, lineCap: .round))
                    .foregroundStyle(point.style)
            }
        }
    }
}
