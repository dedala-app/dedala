// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import Observation
import SwiftUI

/// Every conversation with the agent: the main one, split by days and nights,
/// and the topics it opens. Filled by `say`, `presence`, `topic` and `receipt`
/// ops; what you write and tap goes back as events.
@Observable
final class Conversations {
    enum Who: String, Codable { case agent, you }

    enum Presence: Equatable {
        case idle
        case working(Activity)
    }

    /// The agent's turn as it happens: the steps done, what it is doing now
    /// when that has a name (a call it writes, a tool it runs, its reply) and
    /// the symbol of the tool at work, the tokens it wrote, since when. Between
    /// two steps the last one stands for what it does: it thinks only before
    /// the first.
    struct Activity: Equatable {
        var steps: [Step] = []
        var doing: String?
        var symbol: String?
        var tokens = 0
        var since: Date?

        /// The step it just took, while nothing newer has a name.
        var last: Step? { doing == nil ? steps.last : nil }
        /// The steps behind what stands for the turn now.
        var trail: ArraySlice<Step> { last == nil ? steps[...] : steps.dropLast() }
        var line: String { doing ?? last?.text ?? "Thinking" }
        var glyph: String { (doing == nil ? last?.symbol : symbol) ?? "ellipsis" }
    }

    struct CardSpec: Codable {
        var view: JSONValue
        var data: JSONValue
        var state: [String: JSONValue]
        var script: String?
        var derive: [String: String]?
        /// What you changed on it, by state scope.
        var saved: [String: [String: JSONValue]]?
        /// Bumped when the agent sends state over yours, to draw it afresh.
        var stateRevision: Int?

        var json: JSONValue {
            var object: [String: JSONValue] = ["view": view, "data": data, "state": .object(state)]
            if let script { object["script"] = .string(script) }
            if let derive { object["derive"] = .object(derive.mapValues(JSONValue.string)) }
            return .object(object)
        }

        var scriptSpec: ScriptSpec? { ScriptSpec(json) }
    }

    struct Night: Codable {
        var remembered: [String]
        var overnight: [String]
    }

    struct Message: Identifiable, Codable {
        let id: String
        var who = Who.agent
        var at: Date
        var text = ""
        var card: CardSpec?
        var topic: String?
        var night: Night?
        var receipt: String?
        var record: RecordRef?
        var page: String?
        var steps: [Step]?
        var note: String?
        var notice: Notice?
        var loved: Bool?
        /// When you answered its card with a button that sends to the agent.
        var answered: Date?
        /// What you shared from another app with this message, and the share's
        /// id (its photos' small images are kept under it).
        var shared: [SharedItem]?
        var share: String?
    }

    /// One thing you shared: a link, a photo, a file or some text.
    struct SharedItem: Codable, Hashable {
        var type: String
        var url: String?
        var title: String?
        var name: String?
        var size: Int?
        var text: String?
        var item: Int?
    }

    /// Hermes speaking for itself (a command's reply, a warning): an event in
    /// the conversation, not the agent talking.
    struct Notice: Codable, Hashable {
        var title: String
        var symbol: String
        var details: [String]
        var warning: Bool
    }

    /// One thing the agent did on the way to a message: what it read, ran, searched.
    struct Step: Codable, Hashable {
        var text: String
        var symbol: String
        var failed: Bool?
    }

    struct Topic: Identifiable, Codable {
        let id: String
        var title: String
        var symbol: String
        var color: String
        var started: Date
        var unread = 0
        var closed: Date?
        var outcome: String?
        var messages: [Message] = []
    }

    private struct Saved: Codable {
        var main: [Message]
        var topics: [Topic]
    }

    private(set) var main: [Message] = []
    private(set) var topics: [Topic] = []
    private(set) var presence: [String: Presence] = [:]
    @ObservationIgnored private var presenceStamps: [String: UUID] = [:]
    @ObservationIgnored var onEvent: ((JSONValue) -> Void)?
    @ObservationIgnored var onShare: ((JSONValue, [Data]) -> Void)?
    @ObservationIgnored var reading: () -> String? = { nil }

    static let main = "main"
    static let topicsList = "#topics"
    private static let file = "conversations.json"

    init() {
        if let saved = Storage.load(Saved.self, from: Self.file) {
            main = saved.main
            topics = saved.topics
        }
    }

    // MARK: - Reading

    func messages(in conversation: String) -> [Message] {
        conversation == Self.main ? main : topic(conversation)?.messages ?? []
    }

    func topic(_ id: String) -> Topic? {
        topics.first { $0.id == id }
    }

    /// The conversation a message is in, with the message.
    func holding(_ messageID: String) -> (conversation: String, message: Message)? {
        if let message = main.first(where: { $0.id == messageID }) { return (Self.main, message) }
        for topic in topics {
            if let message = topic.messages.first(where: { $0.id == messageID }) { return (topic.id, message) }
        }
        return nil
    }

    var ongoing: [Topic] {
        topics.filter { $0.closed == nil }.sorted { lastActivity($0) > lastActivity($1) }
    }

    var closedTopics: [Topic] {
        topics.filter { $0.closed != nil }
    }

    func lastActivity(_ topic: Topic) -> Date {
        topic.messages.last?.at ?? topic.started
    }

    var unreadTopics: Int {
        topics.filter { $0.unread > 0 }.count
    }

    func presence(in conversation: String) -> Presence {
        presence[conversation] ?? .idle
    }

    /// Whether the turn shown began after the agent said this: what a turn
    /// before it left late does not end it.
    private func outlasts(_ message: Message, in conversation: String) -> Bool {
        guard case .working(let activity) = presence(in: conversation), let since = activity.since else { return false }
        return since > message.at
    }

    func markRead(_ id: String) {
        guard let index = topics.firstIndex(where: { $0.id == id }), topics[index].unread > 0 else { return }
        topics[index].unread = 0
        save()
    }

    // MARK: - You

    func send(_ text: String, in conversation: String) {
        var message = Message(id: UUID().uuidString, who: .you, at: .now, text: text)
        if case .working = presence(in: conversation) {
            message.note = "Arrives after his current step"
        }
        append(message, to: conversation)
        onEvent?(.object(["kind": "message", "conversation": .string(conversation), "text": .string(text), "yours": .string(message.id), "at": JSONValue.iso(.now)]))
        Storage.flush()
    }

    /// Your words with photos: drawn at once from the photos' small images,
    /// and sent as a share (protocol.md, Events: `share`), the photos as the
    /// JPEGs beside it. The plugin says it back under the same id.
    func send(_ text: String, photos: [ChatPhoto], in conversation: String) {
        let share = UUID().uuidString
        for (index, photo) in photos.enumerated() {
            ShareOutbox.keepThumbnail(photo.thumbnail, share: share, item: index)
        }
        var message = Message(id: "share-\(share)", who: .you, at: .now, text: text)
        message.shared = photos.indices.map { SharedItem(type: "image", size: photos[$0].jpeg.count, item: $0) }
        message.share = share
        if case .working = presence(in: conversation) {
            message.note = "Arrives after his current step"
        }
        append(message, to: conversation)
        let items: [JSONValue] = photos.indices.map { .object(["type": "image", "item": .number(Double($0)), "mime": "image/jpeg"]) }
        onShare?(.object(["kind": "share", "id": .string(share), "conversation": .string(conversation), "text": .string(text), "from": "chat",
                          "items": .array(items), "at": JSONValue.iso(.now)]), photos.map(\.jpeg))
        Storage.flush()
    }

    /// A card action, sent back to the agent with the message it came from.
    func act(_ payload: JSONValue, say: String?, from messageID: String, in conversation: String) {
        let yours = UUID().uuidString
        if let say {
            append(Message(id: yours, who: .you, at: .now, text: say), to: conversation)
        }
        update(messageID, in: conversation) { $0.answered = .now }
        var event: [String: JSONValue] = ["kind": "action", "conversation": .string(conversation), "message": .string(messageID), "payload": payload, "at": JSONValue.iso(.now)]
        if let say {
            event["say"] = .string(say)
            event["yours"] = .string(yours)
        }
        onEvent?(.object(event))
        Storage.flush()
    }

    func stop(_ conversation: String) {
        withAnimation(.spring(duration: 0.4)) { presence[conversation] = .idle }
        onEvent?(.object(["kind": "stop", "conversation": .string(conversation), "at": JSONValue.iso(.now)]))
    }

    /// Empties every conversation. Development only: the agent has no op for it.
    func reset() {
        withAnimation(.spring(duration: 0.4)) {
            main = []
            topics = []
            presence = [:]
        }
        save()
    }

    // MARK: - The agent

    /// `say`, `patch`, `presence`, `topic`, `receipt` and `history` ops.
    func receive(_ op: JSONValue) {
        let conversation = op["conversation"]?.string ?? Self.main
        switch op["op"]?.string {
        case "presence":
            let presence: Presence = if op["typing"]?.truthy == true || op["doing"] != nil {
                .working(Activity(
                    steps: Self.steps(op["steps"]) ?? [],
                    doing: op["doing"]?.string,
                    symbol: op["symbol"]?.string,
                    tokens: op["tokens"]?.int ?? 0,
                    since: op["since"]?.date
                ))
            } else {
                .idle
            }
            if case .working(let old) = self.presence(in: conversation), case .working(let new) = presence, old.steps == new.steps {
                self.presence[conversation] = presence
            } else {
                withAnimation(.spring(duration: 0.4)) { self.presence[conversation] = presence }
            }
            expire(conversation)
        case "topic":
            topic(op)
        case "history":
            restore(op)
        case "receipt":
            guard let messageID = op["message"]?.string else { return }
            update(messageID, in: conversation) { $0.receipt = op["text"]?.text ?? "Done" }
        case "patch":
            guard let messageID = op["id"]?.string, let conversation = place(of: messageID) else { return }
            let retold = op["say"] != nil && answered(since: messageID, in: conversation)
            update(messageID, in: conversation) { message in
                if let text = op["say"]?.text { message.text = text }
                guard var card = message.card else { return }
                if let data = op["data"] { card.data = card.data.merging(data) }
                if let view = op["view"] { card.view = view }
                if let script = op["script"]?.string {
                    card.script = script
                    ScriptEngine.shared.pardon(script)
                }
                if let derive = op["derive"]?.object { card.derive = derive.compactMapValues(\.string) }
                if let state = op["state"]?.object {
                    card.state.merge(state) { $1 }
                    for key in state.keys { card.saved?["card"]?[key] = nil }
                    card.stateRevision = (card.stateRevision ?? 0) + 1
                }
                message.card = card
            }
            if retold, var message = messages(in: conversation).first(where: { $0.id == messageID }) {
                message.at = .now
                remove(messageID, from: conversation)
                append(message, to: conversation)
            }
        default:
            var message = Self.message(op)
            if message.who == .agent, !outlasts(message, in: conversation) {
                withAnimation(.spring(duration: 0.4)) { presence[conversation] = .idle }
            }
            if let known = place(of: message.id), known == conversation, !answered(since: message.id, in: known) {
                update(message.id, in: known) { old in
                    if message.steps == nil { message.steps = old.steps }
                    old = message
                }
            } else {
                if let known = place(of: message.id) { remove(message.id, from: known) }
                append(message, to: conversation)
            }
        }
    }

    /// A message as a `say` op gives it.
    private static func message(_ op: JSONValue) -> Message {
        let yours = op["from"]?.string == Who.you.rawValue
        var message = Message(id: op["id"]?.string ?? UUID().uuidString, who: yours ? .you : .agent, at: op["at"]?.date ?? .now, text: op["text"]?.text ?? "")
        message.topic = op["topic"]?.string
        message.record = op["record"].flatMap { ref in
            guard let store = ref["store"]?.string, let id = ref["id"]?.string else { return nil }
            return RecordRef(store: store, record: id)
        }
        message.steps = Self.steps(op["steps"])
        if let shared = op["shared"]?.array {
            message.shared = shared.compactMap { try? JSONDecoder().decode(SharedItem.self, from: $0.data()) }
            message.share = op["share"]?.string
        }
        if let notice = op["notice"], let title = notice["title"]?.string {
            message.notice = Notice(title: title, symbol: notice["symbol"]?.string ?? "info.circle",
                                    details: (notice["details"]?.array ?? []).map(\.text), warning: notice["warning"]?.truthy == true)
        }
        if let card = op["card"], let view = card["view"] {
            message.card = CardSpec(view: view, data: card["data"] ?? .object([:]), state: card["state"]?.object ?? [:],
                                    script: card["script"]?.string, derive: card["derive"]?.object?.compactMapValues(\.string))
            if let script = card["script"]?.string { ScriptEngine.shared.pardon(script) }
        }
        if let night = op["night"] {
            message.night = Night(remembered: (night["remembered"]?.array ?? []).map(\.text), overnight: (night["overnight"]?.array ?? []).map(\.text))
        }
        return message
    }

    /// The conversations given back to a newly paired phone: the topics it
    /// does not have, then the messages it does not have, each in its place
    /// by date, as they stood with what you did on them.
    private func restore(_ op: JSONValue) {
        for topic in op["topics"]?.array ?? [] {
            guard let id = topic["id"]?.string, self.topic(id) == nil else { continue }
            topics.append(Topic(id: id, title: topic["title"]?.text ?? id,
                                symbol: topic["symbol"]?.string ?? "bubble.left.and.text.bubble.right.fill",
                                color: topic["color"]?.string ?? "accent", started: topic["started"]?.date ?? .now,
                                closed: topic["closed"]?.date, outcome: topic["outcome"]?.string))
        }
        for entry in op["messages"]?.array ?? [] {
            guard entry["id"]?.string != nil else { continue }
            var message = Self.message(entry)
            guard place(of: message.id) == nil else { continue }
            message.receipt = entry["receipt"]?.string
            message.answered = entry["answered"]?.date
            message.loved = entry["loved"]?.truthy == true ? true : nil
            let conversation = entry["conversation"]?.string ?? Self.main
            if conversation == Self.main {
                Self.insert(message, into: &main)
            } else if let index = topics.firstIndex(where: { $0.id == conversation }) {
                Self.insert(message, into: &topics[index].messages)
            }
        }
        save()
    }

    private static func insert(_ message: Message, into messages: inout [Message]) {
        messages.insert(message, at: messages.lastIndex { $0.at <= message.at }.map { $0 + 1 } ?? 0)
    }

    /// A turn is refreshed every 10 seconds while it lasts; one silent for 30
    /// ended without saying so (the agent restarted or crashed).
    private func expire(_ conversation: String) {
        let stamp = UUID()
        presenceStamps[conversation] = stamp
        guard presence(in: conversation) != .idle else { return }
        Task { [weak self] in
            try? await Task.sleep(for: .seconds(30))
            guard let self, self.presenceStamps[conversation] == stamp else { return }
            withAnimation(.spring(duration: 0.4)) { self.presence[conversation] = .idle }
        }
    }

    private static func steps(_ value: JSONValue?) -> [Step]? {
        value?.array?.compactMap { step in
            step["text"]?.string.map { Step(text: $0, symbol: step["symbol"]?.string ?? "circle", failed: step["failed"]?.bool) }
        }
    }

    /// The card of a message, in any conversation, as it stands.
    func card(_ messageID: String) -> JSONValue? {
        let all = main + topics.flatMap(\.messages)
        guard let card = all.first(where: { $0.id == messageID })?.card else { return nil }
        return card.json
    }

    /// Marks a card you loved and returns it as it stands, for the agent's bank.
    func loved(_ messageID: String, in conversation: String) -> JSONValue? {
        guard let message = messages(in: conversation).first(where: { $0.id == messageID }), let card = message.card else { return nil }
        update(messageID, in: conversation) { $0.loved = true }
        return card.json.merging(.object(["text": .string(message.text)]))
    }

    @discardableResult
    func flagged(in conversation: String) -> String {
        let message = Message(id: UUID().uuidString, who: .you, at: .now, text: "This one looks off.")
        append(message, to: conversation)
        return message.id
    }

    /// A new page from the agent, offered for the tab bar from the main conversation.
    func proposePage(_ id: String, title: String) {
        var message = Message(id: UUID().uuidString, at: .now, text: title)
        message.page = id
        append(message, to: Self.main)
    }

    private func topic(_ op: JSONValue) {
        guard let id = op["id"]?.string else { return }
        withAnimation(.spring(duration: 0.45)) {
            if let index = topics.firstIndex(where: { $0.id == id }) {
                if let title = op["title"]?.string { topics[index].title = title }
                if let symbol = op["symbol"]?.string { topics[index].symbol = symbol }
                if let color = op["color"]?.string { topics[index].color = color }
                if let outcome = op["outcome"]?.string { topics[index].outcome = outcome }
                if let closed = op["closed"] { topics[index].closed = closed.truthy ? .now : nil }
            } else {
                topics.append(Topic(
                    id: id,
                    title: op["title"]?.text ?? id,
                    symbol: op["symbol"]?.string ?? "bubble.left.and.text.bubble.right.fill",
                    color: op["color"]?.string ?? "accent",
                    started: .now
                ))
            }
        }
        save()
    }

    private func append(_ message: Message, to conversation: String) {
        withAnimation(.spring(duration: 0.45)) {
            if conversation == Self.main {
                main.append(message)
            } else if let index = topics.firstIndex(where: { $0.id == conversation }) {
                topics[index].messages.append(message)
                if message.who == .agent, reading() != conversation {
                    topics[index].unread += 1
                }
            }
        }
        save()
    }

    /// Whether you wrote after a message: said again, it then comes back at
    /// the end, where you are, instead of changing out of sight above.
    private func answered(since messageID: String, in conversation: String) -> Bool {
        let list = messages(in: conversation)
        guard let index = list.firstIndex(where: { $0.id == messageID }) else { return false }
        return list[(index + 1)...].contains { $0.who == .you }
    }

    private func remove(_ messageID: String, from conversation: String) {
        withAnimation(.spring(duration: 0.4)) {
            if conversation == Self.main {
                main.removeAll { $0.id == messageID }
            } else if let index = topics.firstIndex(where: { $0.id == conversation }) {
                topics[index].messages.removeAll { $0.id == messageID }
            }
        }
    }

    private func place(of messageID: String) -> String? {
        if main.contains(where: { $0.id == messageID }) { return Self.main }
        return topics.first { $0.messages.contains { $0.id == messageID } }?.id
    }

    /// What you changed on a card, kept as you change it.
    func saveState(_ messageID: String, _ saved: [String: [String: JSONValue]]) {
        guard let conversation = place(of: messageID) else { return }
        if conversation == Self.main, let index = main.firstIndex(where: { $0.id == messageID }) {
            main[index].card?.saved = saved
        } else if let topic = topics.firstIndex(where: { $0.id == conversation }),
                  let index = topics[topic].messages.firstIndex(where: { $0.id == messageID }) {
            topics[topic].messages[index].card?.saved = saved
        }
        save()
    }

    private func update(_ messageID: String, in conversation: String, _ change: (inout Message) -> Void) {
        withAnimation(.spring(duration: 0.4)) {
            if conversation == Self.main, let index = main.firstIndex(where: { $0.id == messageID }) {
                change(&main[index])
            } else if let topic = topics.firstIndex(where: { $0.id == conversation }),
                      let index = topics[topic].messages.firstIndex(where: { $0.id == messageID }) {
                change(&topics[topic].messages[index])
            }
        }
        save()
    }

    private func save() {
        Storage.saveSoon(Self.file) { [weak self] in
            guard let self else { return }
            Storage.save(Saved(main: self.main, topics: self.topics), to: Self.file)
        }
    }
}
