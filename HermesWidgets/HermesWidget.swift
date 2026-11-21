// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import AppIntents
import SwiftUI
import WidgetKit

/// A Home Screen or Lock Screen widget of the agent's: one of the widgets he
/// declared, drawn from the snapshot the app keeps for it (protocol.md,
/// Widgets), the component over the store's value, `family` in scope.
struct HermesWidget: Widget {
    var body: some WidgetConfiguration {
        AppIntentConfiguration(kind: "hermes", intent: PickWidgetIntent.self, provider: Provider()) { entry in
            WidgetEntryView(entry: entry)
        }
        .configurationDisplayName("Dedala")
        .description("One of the widgets your assistant made.")
        .supportedFamilies([.systemSmall, .systemMedium, .systemLarge, .accessoryRectangular, .accessoryCircular, .accessoryInline])
    }
}

struct Entry: TimelineEntry {
    let date: Date
    let snapshot: JSONValue?
    let wanted: String?
    var agent = "Your assistant"
}

struct Provider: AppIntentTimelineProvider {
    func placeholder(in context: Context) -> Entry {
        Entry(date: .now, snapshot: nil, wanted: nil)
    }

    func snapshot(for configuration: PickWidgetIntent, in context: Context) async -> Entry {
        entry(configuration, at: .now)
    }

    func timeline(for configuration: PickWidgetIntent, in context: Context) async -> Timeline<Entry> {
        let now = Date.now
        let hours = (0..<6).map { Calendar.current.date(byAdding: .hour, value: $0, to: now) ?? now }
        return Timeline(entries: hours.map { entry(configuration, at: $0) }, policy: .atEnd)
    }

    private func entry(_ configuration: PickWidgetIntent, at date: Date) -> Entry {
        let wanted = Snapshots.shown(configuration)
        return Entry(date: date, snapshot: wanted.flatMap(Snapshots.load), wanted: wanted, agent: PairingStore.load()?.agentName ?? "Your assistant")
    }
}

struct WidgetEntryView: View {
    let entry: Entry
    @Environment(\.widgetFamily) private var family

    var body: some View {
        content
            .containerBackground(for: .widget) {
                switch family {
                case .accessoryCircular: AccessoryWidgetBackground()
                case .accessoryRectangular, .accessoryInline: Color.clear
                default: Rectangle().fill(.fill.tertiary)
                }
            }
    }

    @ViewBuilder private var content: some View {
        if let snapshot = entry.snapshot, let name = snapshot["component"]?.string {
            let families = (snapshot["families"]?.array ?? []).compactMap(\.string)
            if families.isEmpty ? !WidgetFamily.lockScreen.contains(family.name) : families.contains(family.name) {
                NodeView(node: .object([name: Self.props(snapshot["data"] ?? .null, family: family.name)]), scope: scope(snapshot))
            } else {
                missing("\(entry.agent) is making this one fit")
            }
        } else {
            missing(entry.wanted.map { "No snapshot for \($0) yet" } ?? "Ask your assistant for a widget")
        }
    }

    @ViewBuilder private func missing(_ text: String) -> some View {
        switch family {
        case .accessoryCircular:
            Image(systemName: "square.grid.2x2").font(.title3)
        case .accessoryInline:
            Text(text)
        case .accessoryRectangular:
            Text(text).font(.footnote)
        default:
            VStack(spacing: 6) {
                Image(systemName: "square.grid.2x2").font(.title2).foregroundStyle(.secondary)
                Text(text).font(.footnote).foregroundStyle(.secondary).multilineTextAlignment(.center)
            }
        }
    }

    /// The component's props: the store's value's fields, the whole value as
    /// `data`, and the widget's `family`.
    static func props(_ data: JSONValue, family: String) -> JSONValue {
        var props = data.object ?? [:]
        props["data"] = data
        props["family"] = .string(family)
        return .object(props)
    }

    private func scope(_ snapshot: JSONValue) -> Scope {
        let components = snapshot["components"]?.object ?? [:]
        let context = CardContext(cardID: "widget:\(snapshot["id"]?.string ?? "")", component: { components[$0].flatMap(ComponentDefinition.init) }, onSend: { _, _ in })
        var scope = Scope(values: ["family": .string(family.name)], boxes: [], context: context, data: snapshot["data"]?.object ?? [:])
        scope.stores = snapshot["stores"]?.object ?? [:]
        scope.probes = false
        return scope
    }
}
