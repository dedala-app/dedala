// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import CoreSpotlight
import Foundation
import Observation

/// What the phone's Spotlight finds of the app: pages, the records of the
/// declared stores and the agent's jobs, given again whenever they change,
/// and only what changed. Messages stay out, so the conversation never shows on the home
/// screen. A tap on one opens it where it lives.
@MainActor
final class Spotlight {
    static let kinds: Set<Search.Kind> = [.page, .record, .job]

    private let hub: Hub
    private let conversations: Conversations
    private let background: Background
    private let agent: Agent
    private let index = CSSearchableIndex.default()
    private lazy var held = SpotlightItems.load()
    private var giving = false
    private var waiting: [Search.Entry]?

    init(hub: Hub, conversations: Conversations, background: Background, agent: Agent) {
        self.hub = hub
        self.conversations = conversations
        self.background = background
        self.agent = agent
    }

    /// Follows the entries, waiting a little after a change so a burst of
    /// them is given once.
    func start() {
        let entries = withObservationTracking {
            Search.entries(hub: hub, conversations: conversations, background: background, agent: agent.name, kinds: Self.kinds)
        } onChange: { [weak self] in
            Task { @MainActor in
                try? await Task.sleep(for: .seconds(2))
                self?.start()
            }
        }
        Task { await give(entries) }
    }

    private func give(_ entries: [Search.Entry]) async {
        guard CSSearchableIndex.isIndexingAvailable() else { return }
        guard !giving else {
            waiting = entries
            return
        }
        giving = true
        defer { giving = false }
        var next: [Search.Entry]? = entries
        while let entries = next {
            await update(entries)
            next = waiting
            waiting = nil
        }
    }

    private func update(_ entries: [Search.Entry]) async {
        var now = SpotlightItems()
        for entry in entries {
            now.items[entry.key] = SpotlightItems.Item(kind: entry.kind.rawValue, title: entry.title,
                                                       description: entry.subtitle ?? entry.group ?? entry.texts.first.map { Search.snippet($0, around: "") },
                                                       text: entry.texts.joined(separator: "\n"), at: entry.at)
        }
        let changed = now.items.filter { held.items[$0.key] != $0.value }.map(\.key)
        let gone = held.items.keys.filter { now.items[$0] == nil }
        guard !changed.isEmpty || !gone.isEmpty else { return }
        let items = now.searchable(changed)
        do {
            for start in stride(from: 0, to: items.count, by: 100) {
                try await index.indexSearchableItems(Array(items[start..<min(start + 100, items.count)]))
            }
            if !gone.isEmpty { try await index.deleteSearchableItems(withIdentifiers: gone) }
            held = now
            now.save()
        } catch {
            return
        }
    }
}
