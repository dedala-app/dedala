// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import CoreSpotlight
import Foundation

/// What the phone's Spotlight holds of the app, kept in the App Group: the app
/// gives Spotlight what changed against it, and the index extension gives it
/// all again when Spotlight has lost its index.
nonisolated struct SpotlightItems: Codable {
    nonisolated struct Item: Codable, Equatable {
        var kind: String
        var title: String
        var description: String?
        var text: String
        var at: Date?
    }

    var items: [String: Item] = [:]

    private static var url: URL? {
        FileManager.default.containerURL(forSecurityApplicationGroupIdentifier: HermesActivityAttributes.group)?
            .appending(path: "spotlight.json")
    }

    static func load() -> SpotlightItems {
        guard let url, let data = try? Data(contentsOf: url) else { return SpotlightItems() }
        return (try? JSONDecoder().decode(SpotlightItems.self, from: data)) ?? SpotlightItems()
    }

    func save() {
        guard let url = Self.url else { return }
        try? JSONEncoder().encode(self).write(to: url, options: .atomic)
    }

    /// Spotlight's items for the keys held among those asked for.
    func searchable(_ keys: some Sequence<String>) -> [CSSearchableItem] {
        keys.compactMap { key in
            items[key].map { item in
                let attributes = CSSearchableItemAttributeSet(contentType: .text)
                attributes.title = item.title
                attributes.contentDescription = item.description
                attributes.textContent = item.text
                attributes.contentModificationDate = item.at
                return CSSearchableItem(uniqueIdentifier: key, domainIdentifier: item.kind, attributeSet: attributes)
            }
        }
    }
}
