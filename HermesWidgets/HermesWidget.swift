// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import AppIntents
import SwiftUI
import WidgetKit

/// A Home Screen widget of the agent's: one of the widgets he declared,
/// drawn from the snapshot the app keeps for it (protocol.md, Widgets), the
/// component over the store's value, `family` in scope.
struct HermesWidget: Widget {
    var body: some WidgetConfiguration {
        AppIntentConfiguration(kind: "hermes", intent: PickWidgetIntent.self, provider: Provider()) { entry in
            WidgetEntryView(entry: entry)
                .containerBackground(.fill.tertiary, for: .widget)
        }
        .configurationDisplayName("Dedala")
        .description("One of the widgets your assistant made.")
        .supportedFamilies([.systemSmall, .systemMedium, .systemLarge])
    }
}

struct WidgetChoice: AppEntity {
    static let typeDisplayRepresentation: TypeDisplayRepresentation = "Widget"
    static let defaultQuery = WidgetQuery()

    let id: String
    var displayRepresentation: DisplayRepresentation { DisplayRepresentation(title: "\(id)") }
}

struct WidgetQuery: EntityQuery {
    func entities(for identifiers: [String]) async throws -> [WidgetChoice] {
        identifiers.map(WidgetChoice.init)
    }

    func suggestedEntities() async throws -> [WidgetChoice] {
        Snapshots.ids().map(WidgetChoice.init)
    }

    func defaultResult() async -> WidgetChoice? {
        Snapshots.ids().first.map(WidgetChoice.init)
    }
}

struct PickWidgetIntent: WidgetConfigurationIntent {
    static let title: LocalizedStringResource = "Widget"
    static let description = IntentDescription("Which of the agent's widgets to show.")

    @Parameter(title: "Widget")
    var widget: WidgetChoice?
}

struct Entry: TimelineEntry {
    let date: Date
    let snapshot: JSONValue?
    let wanted: String?
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
        let wanted = configuration.widget?.id ?? Snapshots.ids().first
        return Entry(date: date, snapshot: wanted.flatMap(Snapshots.load), wanted: wanted)
    }
}

/// The snapshot files the app writes in the App Group.
nonisolated enum Snapshots {
    static var folder: URL? {
        FileManager.default.containerURL(forSecurityApplicationGroupIdentifier: HermesActivityAttributes.group)?
            .appending(path: "widgets", directoryHint: .isDirectory)
    }

    static func ids() -> [String] {
        guard let folder, let names = try? FileManager.default.contentsOfDirectory(atPath: folder.path) else { return [] }
        return names.filter { $0.hasSuffix(".json") }.map { String($0.dropLast(5)) }.sorted()
    }

    static func load(_ id: String) -> JSONValue? {
        guard let folder, let data = try? Data(contentsOf: folder.appending(path: "\(id).json")) else { return nil }
        return try? JSONValue.parse(data)
    }
}

struct WidgetEntryView: View {
    let entry: Entry
    @Environment(\.widgetFamily) private var family

    var body: some View {
        if let snapshot = entry.snapshot, let name = snapshot["component"]?.string {
            let families = (snapshot["families"]?.array ?? []).compactMap(\.string)
            if families.isEmpty || families.contains(familyName) {
                NodeView(node: .object([name: Self.props(snapshot["data"] ?? .null, family: familyName)]), scope: scope(snapshot))
            } else {
                Text("Not drawn at this size").font(.footnote).foregroundStyle(.secondary)
            }
        } else {
            VStack(spacing: 6) {
                Image(systemName: "square.grid.2x2").font(.title2).foregroundStyle(.secondary)
                Text(entry.wanted.map { "No snapshot for \($0) yet" } ?? "Ask your assistant for a widget").font(.footnote).foregroundStyle(.secondary).multilineTextAlignment(.center)
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
        var scope = Scope(values: ["family": .string(familyName)], boxes: [], context: context, data: snapshot["data"]?.object ?? [:])
        scope.stores = snapshot["stores"]?.object ?? [:]
        scope.probes = false
        return scope
    }

    private var familyName: String {
        switch family {
        case .systemSmall: "small"
        case .systemLarge, .systemExtraLarge: "large"
        default: "medium"
        }
    }
}
