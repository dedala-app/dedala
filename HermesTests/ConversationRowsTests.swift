// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import Foundation
import Testing
@testable import Hermes

/// A conversation reads as groups: bubbles of one sender that follow closely
/// join, days and long silences are marked, and repeated notices fold.
@Suite("Conversation rows")
struct ConversationRowsTests {
    let start = Date(timeIntervalSince1970: 1_792_929_600)

    func message(_ id: String, _ who: Conversations.Who, after minutes: Double, _ text: String = "Hi") -> Conversations.Message {
        Conversations.Message(id: id, who: who, at: start.addingTimeInterval(minutes * 60), text: text)
    }

    func kinds(_ messages: [Conversations.Message]) -> [ConversationRows.Row.Kind] {
        ConversationRows.rows(messages).map(\.kind)
    }

    @Test func bubblesOfOneSenderJoinUntilTheOtherSpeaks() {
        let rows = ConversationRows.rows([
            message("a", .you, after: 0), message("b", .you, after: 1), message("c", .you, after: 2),
            message("d", .agent, after: 3), message("e", .you, after: 4),
        ])
        #expect(rows.map(\.kind) == [
            .day(start), .message(0, .first), .message(1, .middle), .message(2, .last), .message(3, .alone), .message(4, .alone),
        ])
        #expect(rows.map(\.gap) == [0, 0, 2, 2, 14, 14])
    }

    @Test func aLongPauseOrACardEndsAGroup() {
        var carded = message("b", .agent, after: 1)
        carded.card = Conversations.CardSpec(view: .object(["Text": "x"]), data: .object([:]), state: [:])
        #expect(kinds([message("a", .agent, after: 0), carded, message("c", .agent, after: 2)]) == [
            .day(start), .message(0, .first), .message(1, .last), .message(2, .alone),
        ])
        #expect(kinds([message("a", .you, after: 0), message("b", .you, after: 30)]) == [
            .day(start), .message(0, .alone), .message(1, .alone),
        ])
    }

    @Test func daysAndLongSilencesAreMarked() {
        let rows = kinds([message("a", .you, after: 0), message("b", .agent, after: 90), message("c", .you, after: 24 * 60)])
        #expect(rows == [
            .day(start), .message(0, .alone), .time(start.addingTimeInterval(90 * 60)), .message(1, .alone),
            .day(start.addingTimeInterval(24 * 3600)), .message(2, .alone),
        ])
    }

    @Test func noticesAlikeFoldIntoOne() {
        let notice = Conversations.Notice(title: "Hermes is shutting down", symbol: "power", details: [], warning: true)
        var shutdowns = (0..<3).map { message("n\($0)", .agent, after: Double($0)) }
        for index in shutdowns.indices { shutdowns[index].notice = notice }
        let rows = kinds([message("a", .you, after: 0)] + shutdowns + [message("b", .agent, after: 5)])
        #expect(rows == [.day(start), .message(0, .alone), .notice(1, count: 3), .message(4, .alone)])
    }
}
