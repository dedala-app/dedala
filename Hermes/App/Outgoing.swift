// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import Foundation

/// What the agent must get of what you did, kept on disk until the plugin
/// says it has it: sent again each time the relay is back, so an edit made
/// offline, or lost on the way, still arrives, and arrives once (the plugin
/// knows each by its id).
@MainActor
final class Outgoing {
    private(set) var events: [JSONValue]

    /// Undelivered messages wait on the relay this long; nothing older is sent again.
    static let kept: TimeInterval = 7 * 24 * 3600

    init() {
        events = Storage.load("outgoing.json")?.array ?? []
    }

    /// The event, with an id to acknowledge it by.
    func add(_ event: JSONValue) -> JSONValue {
        let kept = event["id"]?.string == nil ? event.merging(.object(["id": .string(UUID().uuidString)])) : event
        events.append(kept)
        save()
        return kept
    }

    func acknowledge(_ ids: Set<String>) {
        let before = events.count
        events.removeAll { $0["id"]?.string.map(ids.contains) ?? true }
        if events.count != before { save() }
    }

    /// What is still waiting, the too old dropped.
    func waiting(at now: Date = .now) -> [JSONValue] {
        let fresh = events.filter { ($0["at"]?.date).map { now.timeIntervalSince($0) < Self.kept } ?? true }
        if fresh.count != events.count {
            events = fresh
            save()
        }
        return events
    }

    private func save() {
        Storage.save(.array(events), to: "outgoing.json")
    }
}
