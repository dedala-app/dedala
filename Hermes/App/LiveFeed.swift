// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import Foundation
import Observation

/// Computes the live values from the conversations, Activity and the pages,
/// again whenever one of them changes, and each minute for what depends on
/// the day.
@MainActor
final class LiveFeed {
    private let conversations: Conversations
    private let background: Background
    private let hub: Hub

    static let waitingFor: TimeInterval = 7 * 24 * 3600

    init(conversations: Conversations, background: Background, hub: Hub) {
        self.conversations = conversations
        self.background = background
        self.hub = hub
    }

    /// Each group of values follows what it is made from, and is computed
    /// again only when that changes: a turn's progress every other second
    /// does not walk the conversations again.
    func start() {
        follow(asked)
        follow(ran)
        follow(underWay)
        follow(kept)
    }

    private var answered: [JSONValue] = []
    private var written = 0
    private var finished: [JSONValue] = []

    /// Today is made of two things that change apart: what was said and
    /// answered, and the runs that ended.
    private var today: JSONValue {
        .object(["answered": .array(answered), "runs": .array(finished), "messages": .number(Double(written))])
    }

    private func follow(_ part: @escaping () -> [String: JSONValue]) {
        let values = withObservationTracking(part) { [weak self] in
            Task { @MainActor [weak self] in self?.follow(part) }
        }
        LiveValues.shared.update(values)
    }

    private var conversationsByID: [(String, Conversations.Topic?)] {
        [(Conversations.main, nil as Conversations.Topic?)] + conversations.topics.map { ($0.id, $0) }
    }

    /// What waits on you and what you answered today, from the conversations.
    private func asked() -> [String: JSONValue] {
        let now = Clock.shared.minute
        var waiting: [(Date, JSONValue)] = []
        var answered: [(Date, JSONValue)] = []
        var written = 0
        for (id, topic) in conversationsByID {
            for message in conversations.messages(in: id) {
                if message.who == .agent, Calendar.current.isDate(message.at, inSameDayAs: now) { written += 1 }
                guard let card = message.card else { continue }
                if let at = message.answered, Calendar.current.isDate(at, inSameDayAs: now) {
                    answered.append((at, .object(["card": .string(message.id), "said": .string(message.text), "at": JSONValue.iso(at)])))
                }
                guard message.who == .agent, message.receipt == nil, message.answered == nil,
                      now.timeIntervalSince(message.at) < Self.waitingFor,
                      Self.sends(card.view, components: hub.components) else { continue }
                waiting.append((message.at, .object([
                    "card": .string(message.id), "conversation": .string(id),
                    "topic": topic.map { .string($0.title) } ?? .null,
                    "said": .string(message.text), "at": JSONValue.iso(message.at),
                ])))
            }
        }
        self.answered = answered.sorted { $0.0 > $1.0 }.map(\.1)
        self.written = written
        return ["waiting": .array(waiting.sorted { $0.0 > $1.0 }.map(\.1)), "today": today]
    }

    /// The runs that ended today, from Activity.
    private func ran() -> [String: JSONValue] {
        let now = Clock.shared.minute
        finished = background.runs.compactMap { run in
            guard !run.running, let end = run.finished, Calendar.current.isDate(end, inSameDayAs: now) else { return nil }
            return .object(["job": .string(run.job), "name": .string(run.name), "status": .string(run.status), "finished": JSONValue.iso(end)])
        }
        return ["today": today]
    }

    /// The turns and the runs under way.
    private func underWay() -> [String: JSONValue] {
        let turns: [JSONValue] = conversationsByID.compactMap { id, topic in
            guard case .working(let activity) = conversations.presence(in: id) else { return nil }
            return .object([
                "conversation": .string(id), "topic": topic.map { .string($0.title) } ?? .null,
                "doing": .string(activity.line), "since": activity.since.map(JSONValue.iso) ?? .null,
                "tokens": .number(Double(activity.tokens)),
            ])
        }
        let runs: [JSONValue] = background.running.map { run in
            .object(["id": .string(run.id), "job": .string(run.job), "name": .string(run.name),
                     "doing": .string(run.doing ?? run.steps.last?.text ?? "Starting"), "since": run.started.map(JSONValue.iso) ?? .null])
        }
        return ["running": .object(["turns": .array(turns), "runs": .array(runs)])]
    }

    /// The pages.
    private func kept() -> [String: JSONValue] {
        [
            "pages": .array(hub.pages.map { page in
                .object(["id": .string(page.id), "title": .string(page.title), "symbol": .string(page.symbol),
                         "bar": .bool(hub.pinned.contains(page.id)),
                         "updated": hub.updated(page).map(JSONValue.iso) ?? .null])
            }),
        ]
    }

    /// Whether a view, or a component it uses, has a button that answers the agent.
    static func sends(_ view: JSONValue, components: [String: JSONValue], seen: Set<String> = []) -> Bool {
        switch view {
        case .object(let object):
            if object["send"] != nil { return true }
            for (key, value) in object {
                if let first = key.first, first.isUppercase, !seen.contains(key), let body = components[key]?["body"],
                   sends(body, components: components, seen: seen.union([key])) {
                    return true
                }
                if sends(value, components: components, seen: seen) { return true }
            }
            return false
        case .array(let items):
            return items.contains { sends($0, components: components, seen: seen) }
        default:
            return false
        }
    }
}
