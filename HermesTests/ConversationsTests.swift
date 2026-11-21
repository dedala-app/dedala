// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import Foundation
import Testing
@testable import Hermes

/// A card the agent says again reaches you where you are: in place while you
/// have not written since, at the end once you have.
@MainActor
@Suite("Conversations")
struct ConversationsTests {
    func say(_ id: String, _ text: String) -> JSONValue {
        .object(["op": "say", "id": .string(id), "conversation": "main", "text": .string(text),
                 "card": .object(["view": .object(["Text": "x"])])])
    }

    @Test func aCardSaidAgainInTheSameTurnStaysInPlace() {
        let conversations = Conversations()
        let id = "same-turn-\(UUID().uuidString)"
        conversations.receive(say(id, "First"))
        conversations.receive(say("after-\(UUID().uuidString)", "Then"))
        conversations.receive(say(id, "Redrawn"))
        let main = conversations.messages(in: Conversations.main)
        #expect(main.firstIndex { $0.id == id } == main.count - 2)
        #expect(main.first { $0.id == id }?.text == "Redrawn")
    }

    @Test func photosYouSendAreDrawnAtOnceAndSaidBackInPlace() {
        let conversations = Conversations()
        var sent: [(JSONValue, [Data])] = []
        conversations.onShare = { sent.append(($0, $1)) }
        let photos = [ChatPhoto(jpeg: Data([1]), thumbnail: Data([2])), ChatPhoto(jpeg: Data([3, 4]), thumbnail: Data([5]))]
        conversations.send("Which one?", photos: photos, in: Conversations.main)
        let event = sent.first?.0
        let share = event?["id"]?.string ?? ""
        #expect(event?["kind"] == "share" && event?["from"] == "chat" && event?["items"]?.array?.count == 2)
        #expect(sent.first?.1 == [Data([1]), Data([3, 4])])
        #expect(conversations.messages(in: Conversations.main).last?.shared?.map(\.item) == [0, 1])
        conversations.receive(.object(["op": "say", "id": .string("share-\(share)"), "conversation": "main", "from": "you", "text": "Which one?",
                                       "share": .string(share), "shared": [.object(["type": "image", "item": .number(0)]), .object(["type": "image", "item": .number(1)])]]))
        #expect(conversations.messages(in: Conversations.main).filter { $0.share == share }.count == 1)
    }

    @Test func aCardSaidAgainAfterYouWroteComesBackAtTheEnd() {
        let conversations = Conversations()
        let id = "chronometer-\(UUID().uuidString)"
        conversations.receive(say(id, "Yesterday's"))
        conversations.send("I need a chronometer", in: Conversations.main)
        conversations.receive(say(id, "Today's"))
        let main = conversations.messages(in: Conversations.main)
        #expect(main.last?.id == id && main.last?.text == "Today's")
        #expect(main.filter { $0.id == id }.count == 1)
    }

    @Test func aPatchThatRetellsACardAfterYouWroteMovesItToTheEnd() {
        let conversations = Conversations()
        let id = "rsvp-\(UUID().uuidString)"
        conversations.receive(say(id, "Nothing is applied until you tap"))
        conversations.send("Tentative for all but the 18th", in: Conversations.main)
        conversations.receive(.object(["op": "patch", "id": .string(id), "say": "Done"]))
        let main = conversations.messages(in: Conversations.main)
        #expect(main.last?.id == id && main.last?.text == "Done")
        #expect(main.filter { $0.id == id }.count == 1)
    }

    @Test func aPatchOfItsDataAloneKeepsTheCardInPlace() {
        let conversations = Conversations()
        let id = "score-\(UUID().uuidString)"
        conversations.receive(say(id, "OM 1–0"))
        conversations.send("Nice", in: Conversations.main)
        conversations.receive(.object(["op": "patch", "id": .string(id), "data": .object(["home": .number(2)])]))
        let main = conversations.messages(in: Conversations.main)
        #expect(main.last?.id != id)
        #expect(main.first { $0.id == id }?.card?.data["home"] == .number(2))
    }

    @Test func wordsOfYoursThatCameAnotherWayAreDrawnAsYours() {
        let conversations = Conversations()
        let id = "in-tp7-\(UUID().uuidString)"
        conversations.receive(.object(["op": "say", "id": .string(id), "conversation": "main", "from": "you", "text": "Buy oat milk"]))
        let main = conversations.messages(in: Conversations.main)
        #expect(main.last?.id == id && main.last?.who == .you)
    }

    @Test func whatYouSharedComesWithYourNote() {
        let conversations = Conversations()
        let id = "share-\(UUID().uuidString)"
        conversations.receive(.object(["op": "say", "id": .string(id), "conversation": "main", "from": "you", "text": "Read this later",
                                       "share": "S-1", "shared": [.object(["type": "link", "url": "https://example.com/a", "title": "An article"]),
                                                                  .object(["type": "image", "item": .number(1)])]]))
        let message = conversations.messages(in: Conversations.main).last
        #expect(message?.share == "S-1")
        #expect(message?.shared?.map(\.type) == ["link", "image"] && message?.shared?.last?.item == 1)
    }
}
