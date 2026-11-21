// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import CoreSpotlight

/// Called by Spotlight when it has lost what the app gave it: everything, or
/// some items, given again from what the app last kept in the App Group.
final class IndexRequestHandler: CSIndexExtensionRequestHandler {
    override func searchableIndex(_ searchableIndex: CSSearchableIndex, reindexAllSearchableItemsWithAcknowledgementHandler acknowledgementHandler: @escaping () -> Void) {
        let held = SpotlightItems.load()
        searchableIndex.indexSearchableItems(held.searchable(held.items.keys)) { _ in acknowledgementHandler() }
    }

    override func searchableIndex(_ searchableIndex: CSSearchableIndex, reindexSearchableItemsWithIdentifiers identifiers: [String], acknowledgementHandler: @escaping () -> Void) {
        let held = SpotlightItems.load()
        searchableIndex.indexSearchableItems(held.searchable(identifiers)) { _ in acknowledgementHandler() }
    }
}
