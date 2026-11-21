// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import AppIntents
import Foundation
import WidgetKit

/// Which of the agent's widgets a placed widget shows: picked when you add it,
/// read by the extension to draw it and by the app to tell the agent where
/// each of his widgets is placed.
struct PickWidgetIntent: WidgetConfigurationIntent {
    static let title: LocalizedStringResource = "Widget"
    static let description = IntentDescription("Which of the agent's widgets to show.")

    @Parameter(title: "Widget")
    var widget: WidgetChoice?
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

/// The snapshot files the app writes in the App Group, one per widget, named
/// by its id.
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

    /// The widget a placed widget shows: the one picked, else the first.
    static func shown(_ intent: PickWidgetIntent?) -> String? {
        intent?.widget?.id ?? ids().first
    }
}

extension WidgetFamily {
    /// The size's name in the protocol: `small`, `medium`, `large` on the
    /// Home Screen, `rectangular`, `circular`, `inline` on the Lock Screen.
    var name: String {
        switch self {
        case .systemSmall: "small"
        case .systemLarge, .systemExtraLarge: "large"
        case .accessoryRectangular: "rectangular"
        case .accessoryCircular: "circular"
        case .accessoryInline: "inline"
        default: "medium"
        }
    }

    static let lockScreen: Set<String> = ["rectangular", "circular", "inline"]
}
