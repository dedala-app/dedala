// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import Foundation

/// What a conversation shows, in order, worked out apart from how it is drawn:
/// the day and time separators, each message with its place in its group, and
/// repeated notices folded into one.
enum ConversationRows {
    /// A message's place among the bubbles of one sender that follow each
    /// other closely: the bubbles of a group sit close, with tighter corners
    /// on the side they join.
    enum Position: Equatable {
        case alone, first, middle, last

        var opensGroup: Bool { self == .alone || self == .first }
        var closesGroup: Bool { self == .alone || self == .last }

        init(joinsPrevious: Bool, joinsNext: Bool) {
            switch (joinsPrevious, joinsNext) {
            case (false, false): self = .alone
            case (false, true): self = .first
            case (true, true): self = .middle
            case (true, false): self = .last
            }
        }
    }

    struct Row: Identifiable, Equatable {
        enum Kind: Equatable {
            case day(Date)
            case time(Date)
            /// The message at this index of the conversation.
            case message(Int, Position)
            /// The first of `count` notices alike, at this index.
            case notice(Int, count: Int)
        }

        let id: String
        let kind: Kind
        /// The space above it.
        let gap: CGFloat
    }

    static let grouped: TimeInterval = 5 * 60
    static let timeGap: TimeInterval = 60 * 60

    static func rows(_ messages: [Conversations.Message], calendar: Calendar = .current) -> [Row] {
        var rows: [Row] = []
        var index = 0
        while index < messages.count {
            let message = messages[index]
            let previous = index > 0 ? messages[index - 1] : nil
            var separated = false
            if message.night == nil, previous.map({ !calendar.isDate($0.at, inSameDayAs: message.at) }) ?? true {
                rows.append(Row(id: "day-\(message.id)", kind: .day(message.at), gap: rows.isEmpty ? 0 : 8))
                separated = true
            } else if let previous, message.night == nil, message.at.timeIntervalSince(previous.at) > timeGap {
                rows.append(Row(id: "time-\(message.id)", kind: .time(message.at), gap: 8))
                separated = true
            }
            if let notice = message.notice {
                var count = 1
                while index + count < messages.count, messages[index + count].notice == notice {
                    count += 1
                }
                rows.append(Row(id: message.id, kind: .notice(index, count: count), gap: separated ? 0 : 10))
                index += count
                continue
            }
            let joinsPrevious = !separated && previous.map { joins(message, after: $0) } ?? false
            let next = index + 1 < messages.count ? messages[index + 1] : nil
            let joinsNext = next.map { following in
                joins(following, after: message) && calendar.isDate(following.at, inSameDayAs: message.at)
                    && following.at.timeIntervalSince(message.at) <= timeGap
            } ?? false
            let gap: CGFloat = if separated || rows.isEmpty {
                0
            } else if joinsPrevious {
                2
            } else if let previous, previous.who == message.who, isBubble(previous), isBubble(message) {
                8
            } else {
                14
            }
            rows.append(Row(id: message.id, kind: .message(index, Position(joinsPrevious: joinsPrevious, joinsNext: joinsNext)), gap: gap))
            index += 1
        }
        return rows
    }

    /// A message drawn as text from you or the agent, not as an event.
    static func isBubble(_ message: Conversations.Message) -> Bool {
        message.night == nil && message.notice == nil && message.page == nil && message.topic == nil
            && !(message.who == .you && message.text.hasPrefix("/"))
    }

    /// Whether a message's bubble continues the group of the one before it:
    /// the same sender, soon after, with nothing drawn between the two bubbles.
    static func joins(_ message: Conversations.Message, after previous: Conversations.Message) -> Bool {
        isBubble(message) && isBubble(previous) && message.who == previous.who
            && !message.text.isEmpty && !previous.text.isEmpty
            && (message.steps ?? []).isEmpty
            && previous.card == nil && previous.record == nil && previous.receipt == nil
            && message.at.timeIntervalSince(previous.at) <= grouped
    }
}
