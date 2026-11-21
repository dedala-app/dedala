// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import Foundation

/// Finding anything on the phone: pages by name and by what is on them, the
/// records of the stores the agent declared (protocol.md, Data) by what their
/// declaration says of them, messages, topics and his jobs. It searches what
/// it is given, so a test can give it less.
enum Search {
    enum Kind: String, CaseIterable, Identifiable, Codable {
        case page, record, topic, message, job

        var id: String { rawValue }

        var title: String {
            switch self {
            case .page: "Pages"
            case .record: "Records"
            case .topic: "Topics"
            case .message: "Messages"
            case .job: "Jobs"
            }
        }

        /// Where a kind's group comes among the others; a declared store's
        /// group sits between pages and topics, in the agent's order.
        var order: Int { (Kind.allCases.firstIndex(of: self) ?? 0) * 100 }

        /// How many of a kind a search shows at most.
        var room: Int { self == .message ? 20 : 30 }
    }

    /// Something searchable: what it is called, and every text it holds.
    struct Entry {
        let kind: Kind
        let id: String
        let title: String
        let symbol: String
        var subtitle: String?
        var texts: [String] = []
        var conversation: String?
        var at: Date?
        /// The group it is listed under, its kind's unless said: a declared store has its own.
        var group: String?
        var order: Int?

        var key: String { "\(kind.rawValue):\(id)" }
    }

    /// Something found: the entry, with the text the query was found in.
    struct Hit: Identifiable, Hashable {
        let kind: Kind
        let target: String
        let title: String
        let symbol: String
        let line: String?
        let conversation: String?
        let at: Date?
        let group: String

        var id: String { "\(kind.rawValue):\(target)" }
    }

    static let options: String.CompareOptions = [.caseInsensitive, .diacriticInsensitive]

    /// Every entry holding all the words of the query, by kind, the ones found
    /// by their title first, then the newest first.
    static func hits(for query: String, in entries: [Entry]) -> [Hit] {
        let words = query.split(whereSeparator: \.isWhitespace).map(String.init)
        guard !words.isEmpty else { return [] }
        var found: [(hit: Hit, rank: Int, order: Int)] = []
        for entry in entries {
            let fields = [entry.title] + (entry.subtitle.map { [$0] } ?? []) + entry.texts
            guard words.allSatisfy({ word in fields.contains { $0.range(of: word, options: options) != nil } }) else { continue }
            let inTitle = entry.title.range(of: words[0], options: options) != nil
            let line = inTitle
                ? entry.subtitle
                : fields.dropFirst().first { $0.range(of: words[0], options: options) != nil }.map { snippet($0, around: words[0]) }
            found.append((Hit(kind: entry.kind, target: entry.id, title: entry.title, symbol: entry.symbol,
                              line: line ?? entry.subtitle, conversation: entry.conversation, at: entry.at,
                              group: entry.group ?? entry.kind.title), inTitle ? 0 : 1, entry.order ?? entry.kind.order))
        }
        found.sort {
            if $0.order != $1.order { return $0.order < $1.order }
            if $0.rank != $1.rank { return $0.rank < $1.rank }
            return ($0.hit.at ?? .distantPast) > ($1.hit.at ?? .distantPast)
        }
        var kept: [String: Int] = [:]
        return found.compactMap { candidate in
            let count = kept[candidate.hit.group, default: 0]
            guard count < candidate.hit.kind.room else { return nil }
            kept[candidate.hit.group] = count + 1
            return candidate.hit
        }
    }

    /// One line of a text around the word found in it.
    static func snippet(_ text: String, around word: String, width: Int = 90) -> String {
        let flat = text.split(whereSeparator: \.isWhitespace).joined(separator: " ")
        guard flat.count > width, let range = flat.range(of: word, options: options) else { return String(flat.prefix(width)) }
        let start = flat.index(range.lowerBound, offsetBy: -30, limitedBy: flat.startIndex) ?? flat.startIndex
        let end = flat.index(start, offsetBy: width, limitedBy: flat.endIndex) ?? flat.endIndex
        var line = String(flat[start..<end])
        if start > flat.startIndex { line = "…" + line }
        if end < flat.endIndex { line += "…" }
        return line
    }

    private static let spoken: Set<String> = ["Text", "Label", "Button", "Section", "DisclosureGroup", "TextField"]

    /// The words a view shows as they are written in it, through the
    /// components it draws; what it reads from data is found in the data.
    static func texts(in view: JSONValue, components: [String: JSONValue], seen: Set<String> = []) -> [String] {
        switch view {
        case .string(let string):
            return string.contains("$") || string.isEmpty ? [] : [string]
        case .array(let items):
            return items.flatMap { texts(in: $0, components: components, seen: seen) }
        case .object(let object):
            var found: [String] = []
            for (key, value) in object {
                if spoken.contains(key) {
                    found += texts(in: key == "Label" ? value.array?.first ?? .null : value, components: components, seen: seen)
                } else if let first = key.first, first.isUppercase, !seen.contains(key), let body = components[key]?["body"] {
                    found += texts(in: body, components: components, seen: seen.union([key]))
                    found += texts(in: value, components: components, seen: seen)
                } else if value.object != nil || value.array != nil {
                    found += texts(in: value, components: components, seen: seen)
                }
            }
            return found
        default:
            return []
        }
    }

    /// Every string in a value, however deep: what a store says.
    static func strings(in value: JSONValue) -> [String] {
        switch value {
        case .string(let string): string.isEmpty ? [] : [string]
        case .array(let items): items.flatMap(strings)
        case .object(let object): object.sorted { $0.key < $1.key }.flatMap { strings(in: $0.value) }
        default: []
        }
    }
}

extension Search {
    /// Everything on the phone of the kinds asked for, ready to search.
    @MainActor
    static func entries(hub: Hub, conversations: Conversations, background: Background, agent: String,
                        kinds: Set<Kind> = Set(Kind.allCases)) -> [Entry] {
        var entries: [Entry] = []
        for page in hub.pages where kinds.contains(.page) {
            let name = hub.tabName(page.id)
            entries.append(Entry(kind: .page, id: page.id, title: page.title, symbol: page.symbol,
                                 subtitle: name == page.title ? nil : name,
                                 texts: texts(in: page.view, components: hub.components)))
        }
        if kinds.contains(.record) {
            entries += records(hub: hub)
        }
        for topic in conversations.topics where kinds.contains(.topic) {
            entries.append(Entry(kind: .topic, id: topic.id, title: topic.title, symbol: topic.symbol,
                                 subtitle: topic.outcome ?? (topic.closed == nil ? nil : "Closed"), at: topic.started))
        }
        let conversationsByID = [(Conversations.main, nil as Conversations.Topic?)] + conversations.topics.map { ($0.id, $0) }
        for (id, topic) in conversationsByID where kinds.contains(.message) {
            for message in conversations.messages(in: id) where ConversationRows.isBubble(message) && !message.text.isEmpty {
                entries.append(Entry(kind: .message, id: message.id, title: message.who == .you ? "You" : agent, symbol: "bubble.left",
                                     subtitle: topic?.title, texts: [message.text] + (message.card.map { strings(in: $0.data) } ?? []),
                                     conversation: id, at: message.at))
            }
        }
        for job in background.jobs where kinds.contains(.job) {
            entries.append(Entry(kind: .job, id: job.id, title: job.name, symbol: "gearshape.2",
                                 subtitle: job.schedule, texts: job.error.map { [$0] } ?? [], at: job.last))
        }
        return entries
    }

    /// The records of every declared store, as its declaration says them: the
    /// title and subtitle shown, the words they are found by, grouped under
    /// the store's name in the order the stores were declared.
    @MainActor
    static func records(hub: Hub) -> [Entry] {
        var entries: [Entry] = []
        for (place, store) in hub.declarations.keys.sorted().enumerated() {
            guard let declaration = hub.declarations[store], let records = hub.stores[store]?.array else { continue }
            let name = declaration["name"]?.string ?? store
            let symbol = declaration["symbol"]?.string ?? "doc.fill"
            let words = declaration["words"]?.array ?? []
            for record in records {
                guard let id = record["id"]?.text else { continue }
                let scope = Records.scope(record, hub: hub, store: store)
                entries.append(Entry(kind: .record, id: "\(store)/\(id)", title: Records.title(of: record, in: store, hub: hub), symbol: symbol,
                                     subtitle: Records.subtitle(of: record, in: store, hub: hub),
                                     texts: words.map { scope.text($0) }.filter { !$0.isEmpty },
                                     at: record["updated"]?.date, group: name, order: Kind.record.order + place))
            }
        }
        return entries
    }

    /// The newest records of the declared stores, by their `updated` field.
    @MainActor
    static func latest(hub: Hub, count: Int = 5) -> [Entry] {
        Array(records(hub: hub).filter { $0.at != nil }.sorted { ($0.at ?? .distantPast) > ($1.at ?? .distantPast) }.prefix(count))
    }

    /// What you looked for lately, newest first: the words you searched, and
    /// what you opened from Search. Kept on the phone.
    struct History: Codable, Equatable {
        struct Opened: Codable, Equatable, Identifiable {
            let kind: Kind
            let target: String
            let title: String
            let symbol: String
            var conversation: String?

            var id: String { "\(kind.rawValue):\(target)" }
        }

        var searches: [String] = []
        var opened: [Opened] = []

        static let room = 5
        private static let key = "searchHistory"

        mutating func searched(_ words: String) {
            let words = words.trimmingCharacters(in: .whitespaces)
            guard !words.isEmpty else { return }
            searches = Array(([words] + searches.filter { $0.caseInsensitiveCompare(words) != .orderedSame }).prefix(Self.room))
        }

        mutating func opened(_ thing: Opened) {
            opened = Array(([thing] + opened.filter { $0.id != thing.id }).prefix(Self.room))
        }

        static func load(_ defaults: UserDefaults = .standard) -> History {
            defaults.data(forKey: key).flatMap { try? JSONDecoder().decode(History.self, from: $0) } ?? History()
        }

        func save(_ defaults: UserDefaults = .standard) {
            defaults.set(try? JSONEncoder().encode(self), forKey: Self.key)
        }
    }
}
