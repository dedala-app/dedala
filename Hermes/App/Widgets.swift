// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import Foundation
import WidgetKit

/// What the widget extension draws from: one snapshot per widget the agent
/// declared, in the App Group, written by the app each time the widget's
/// store or component changes (protocol.md, Widgets).
final class WidgetSnapshots {
    static let kind = "hermes"

    static var folder: URL? {
        FileManager.default.containerURL(forSecurityApplicationGroupIdentifier: HermesActivityAttributes.group)?
            .appending(path: "widgets", directoryHint: .isDirectory)
    }

    static func url(_ id: String) -> URL? {
        folder?.appending(path: "\(id.replacing("/", with: "_")).json")
    }

    /// The snapshot files, the widgets the extension offers.
    static func ids() -> [String] {
        guard let folder, let names = try? FileManager.default.contentsOfDirectory(atPath: folder.path) else { return [] }
        return names.filter { $0.hasSuffix(".json") }.map { String($0.dropLast(5)) }.sorted()
    }

    static func load(_ id: String) -> JSONValue? {
        guard let url = url(id), let data = try? Data(contentsOf: url) else { return nil }
        return try? JSONValue.parse(data)
    }

    func write(_ snapshot: JSONValue, as id: String) {
        guard let folder = Self.folder, let url = Self.url(id) else { return }
        try? FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        try? snapshot.data().write(to: url, options: .atomic)
        reload()
    }

    func remove(_ id: String) {
        if let url = Self.url(id) { try? FileManager.default.removeItem(at: url) }
        reload()
    }

    private func reload() {
        WidgetCenter.shared.reloadTimelines(ofKind: Self.kind)
    }

    /// The names a component body mentions, among the stores: what the
    /// snapshot carries besides the widget's own store.
    static func storesRead(by body: JSONValue, among names: [String]) -> [String] {
        let text = String(decoding: body.data(), as: UTF8.self)
        return names.filter { text.contains("$\($0)") || text.contains("\($0).") }.sorted()
    }
}

extension Hub {
    /// Writes a widget's snapshot: its component with the components it uses,
    /// its store's value as `data`, and the other stores it reads.
    func snapshot(_ id: String) {
        guard let widget = widgets[id], let name = widget["component"]?.string, let store = widget["store"]?.string else { return }
        var used: [String: JSONValue] = [:]
        var queue = [name]
        while let next = queue.popLast() {
            guard used[next] == nil, let definition = components[next] else { continue }
            used[next] = definition
            let text = String(decoding: definition.data(), as: UTF8.self)
            queue += components.keys.filter { $0 != next && text.contains("\"\($0)\"") }
        }
        let read = WidgetSnapshots.storesRead(by: .object(used), among: Array(stores.keys))
        let snapshot: JSONValue = .object([
            "id": .string(id), "component": .string(name), "families": widget["families"] ?? .array([]),
            "components": .object(used), "data": stores[store] ?? .null,
            "stores": .object(stores.filter { read.contains($0.key) || $0.key == store }),
            "at": JSONValue.iso(.now),
        ])
        snapshots.write(snapshot, as: id)
    }

    /// The widgets whose picture a store changing may change.
    func snapshotWidgets(reading store: String) {
        for (id, widget) in widgets where widget["store"]?.string == store || (WidgetSnapshots.load(id)?["stores"]?[store]) != nil {
            snapshot(id)
        }
    }

    func snapshotAllWidgets() {
        widgets.keys.forEach(snapshot)
    }

    /// Tells the agent where his widgets are placed and at which sizes, from
    /// iOS's own list of the Dedala widgets on the Home Screen and the Lock
    /// Screen, each time that list changed.
    func reportPlacements() async {
        guard let placed = try? await WidgetCenter.shared.currentConfigurations() else { return }
        let order = ["small", "medium", "large", "rectangular", "circular", "inline"]
        var sizes: [String: Set<String>] = [:]
        for info in placed where info.kind == WidgetSnapshots.kind {
            guard let file = Snapshots.shown(info.widgetConfigurationIntent(of: PickWidgetIntent.self)) else { continue }
            let id = widgets.keys.first { WidgetSnapshots.url($0)?.lastPathComponent == "\(file).json" } ?? file
            sizes[id, default: []].insert(info.family.name)
        }
        let report = JSONValue.object(sizes.mapValues { found in .array(order.filter(found.contains).map(JSONValue.string)) })
        let encoder = JSONEncoder()
        encoder.outputFormatting = .sortedKeys
        let written = String(decoding: (try? encoder.encode(report)) ?? Data(), as: UTF8.self)
        guard written != UserDefaults.standard.string(forKey: "placedWidgets") else { return }
        UserDefaults.standard.set(written, forKey: "placedWidgets")
        enqueue(.object(["kind": "widgets", "placed": report]))
    }
}
