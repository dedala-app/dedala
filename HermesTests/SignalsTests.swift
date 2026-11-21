// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import Foundation
import Testing
@testable import Hermes

/// Notification buttons, widgets and what a page sends up: photos and dictation.
@MainActor
@Suite("Signals")
struct SignalsTests {
    @Test func notificationButtonsAreDeclaredKeptAndRegistered() throws {
        let hub = Hub()
        var registered: [[String: JSONValue]] = []
        hub.onButtons = { registered.append($0) }
        let kind = "bill-\(UUID().uuidString.prefix(6))"
        _ = try hub.apply(.object(["op": "buttons", "kinds": .object([kind: .array([.object(["id": "paid", "title": "Mark paid"]), .object(["id": "later", "title": "Snooze", "destructive": true])])])]))
        #expect(hub.buttonKinds[kind]?.array?.count == 2 && registered.count == 1 && registered[0][kind] != nil)
        #expect(throws: Hub.OperationError.self) {
            try hub.apply(.object(["op": "buttons", "kinds": .object(["bad": .array([.object(["id": "x"])])])]))
        }
        #expect(throws: Hub.OperationError.self) {
            try hub.apply(.object(["op": "buttons", "kinds": .object(["many": .array(Array(repeating: .object(["id": "a", "title": "A"]), count: 5))])]))
        }
        hub.save()
        #expect(Hub().buttonKinds[kind]?.array?.first?["title"] == "Mark paid")
        _ = try hub.apply(.object(["op": "buttons", "kinds": .object([kind: .null])]))
        #expect(hub.buttonKinds[kind] == nil && registered.count == 2)
        hub.save()
    }

    @Test func anActionCarriedByANotificationRoundTripsAsText() throws {
        let actions: JSONValue = .object(["paid": .object(["command": "pay", "args": .object(["bill": "b-1"])]), "later": .object(["edit": .object(["store": "bills", "id": "b-1", "due": "tomorrow"])])])
        let written = String(decoding: actions.data(), as: UTF8.self)
        let back = try JSONValue.parse(Data(written.utf8))
        #expect(back["paid"]?["command"] == "pay" && back["later"]?["edit"]?["store"] == "bills")
    }

    @Test func aWidgetIsDeclaredSnapshottedAndRemoved() throws {
        let hub = Hub()
        let id = "glance-\(UUID().uuidString.prefix(6))"
        let store = "day-\(UUID().uuidString.prefix(6))"
        _ = try hub.apply(.object(["op": "define", "components": .object([
            "DayGlance": .object(["props": .array(["weather", "family"]), "body": .object(["VStack": .array([.object(["Text": "${weather} · ${family}"]), .object(["Tile": .object([:])])])])]),
            "Tile": .object(["body": .object(["Text": "${trip.days} days"])]),
        ])]))
        _ = try hub.apply(.object(["op": "store", "id": .string(store), "data": .object(["weather": "Sunny"])]))
        _ = try hub.apply(.object(["op": "store", "id": "trip", "data": .object(["days": .number(3)])]))
        #expect(throws: Hub.OperationError.self) {
            try hub.apply(.object(["op": "widget", "id": .string(id), "store": .string(store), "component": "Ghost"]))
        }
        _ = try hub.apply(.object(["op": "widget", "id": .string(id), "store": .string(store), "component": "DayGlance", "families": .array(["small", "medium"])]))
        let snapshot = try #require(WidgetSnapshots.load(id))
        #expect(snapshot["component"] == "DayGlance" && snapshot["data"]?["weather"] == "Sunny")
        #expect(snapshot["components"]?["DayGlance"] != nil && snapshot["components"]?["Tile"] != nil)
        #expect(snapshot["stores"]?["trip"]?["days"] == .number(3) && snapshot["families"]?.array?.count == 2)
        _ = try hub.apply(.object(["op": "store", "id": .string(store), "patch": .object(["weather": "Rain"])]))
        #expect(WidgetSnapshots.load(id)?["data"]?["weather"] == "Rain")
        #expect(WidgetSnapshots.ids().contains(id) && hub.widgets[id] != nil)
        _ = try hub.apply(.object(["op": "widget", "id": .string(id), "remove": true]))
        #expect(WidgetSnapshots.load(id) == nil && hub.widgets[id] == nil)
        _ = try hub.apply(.object(["op": "store", "id": .string(store), "data": .null]))
        _ = try hub.apply(.object(["op": "store", "id": "trip", "data": .null]))
    }

    @Test func aPhotoInAnEditIsUploadedBeforeTheEditLeavesAndForgottenOnceAcked() async throws {
        let hub = Hub()
        var events: [JSONValue] = []
        hub.onEmit = { events.append($0) }
        var uploaded: [Int] = []
        hub.uploader = { data in
            uploaded.append(data.count)
            return ["b-1", "b-2"]
        }
        let store = "receipts-\(UUID().uuidString.prefix(6))"
        _ = try hub.apply(.object(["op": "store", "id": .string(store), "data": .array([])]))
        let folder = PhotoPicking.folder
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        let file = folder.appending(path: "test-\(UUID().uuidString).jpg")
        try Data(repeating: 7, count: 1234).write(to: file)
        let photo: JSONValue = .object(["local": .string(file.path), "name": "photo.jpg", "size": .number(1234), "type": "image/jpeg"])
        try hub.edit(.object(["store": .string(store), "add": .object(["id": "r1", "amount": .number(12), "photo": photo])]), from: "receipts")
        #expect(hub.stores[store]?.array?.first?["photo"]?["local"] != nil)
        #expect(hub.pending.take() == nil)
        for _ in 0..<50 where uploaded.isEmpty { try await Task.sleep(for: .milliseconds(20)) }
        for _ in 0..<50 where hub.pending.changes.first?["add"]?["photo"]?["blobs"] == nil { try await Task.sleep(for: .milliseconds(20)) }
        #expect(uploaded == [1234])
        let event = try #require(hub.pending.take())
        let added = try #require(event["changes"]?.array?.first?["add"])
        #expect(added["photo"]?["blobs"] == .array(["b-1", "b-2"]) && added["photo"]?["name"] == "photo.jpg" && added["amount"] == .number(12))
        let kept = hub.outgoing.add(event)
        hub.emit(kept)
        #expect(FileManager.default.fileExists(atPath: file.path))
        hub.acknowledged([try #require(kept["id"]?.string)], failed: [:])
        #expect(!FileManager.default.fileExists(atPath: file.path))
        _ = try hub.apply(.object(["op": "store", "id": .string(store), "data": .null]))
    }

    @Test func photoAndDictateAreInputsThatBind() {
        #expect(Tree.problems(in: .object(["Photo": "Receipt", "bind": "$photo", "source": "camera"])) == [])
        #expect(Tree.problems(in: .object(["Dictate": "Say it", "bind": "$text", "append": true])) == [])
        #expect(Views.names.contains("Photo") && Views.names.contains("Dictate"))
        #expect(Hub.localFiles(in: .object(["photo": .object(["local": "/p", "name": "a.jpg"]), "note": "x", "sent": .object(["local": "/q", "blobs": .array([])])])).map(\.key) == ["photo"])
    }

    @Test func aWidgetLinkCarriesOnlyActionsThatOpen() {
        HermesWidgetsLinks.install()
        defer { Views.widgetLink = nil }
        #expect(Views.widgetLink?(.object(["page": "day"]))?.absoluteString.hasPrefix("hermes://open?action=") == true)
        #expect(Views.widgetLink?(.object(["command": "deploy"])) == nil)
    }
}

/// The widget bundle's link, as the app side can test it.
enum HermesWidgetsLinks {
    static func install() {
        Views.widgetLink = { action in
            let steps = action.array ?? [action]
            guard steps.contains(where: { step in ["page", "show", "conversation", "open"].contains { step[$0] != nil } }),
                  let json = String(data: action.data(), encoding: .utf8),
                  let encoded = json.addingPercentEncoding(withAllowedCharacters: .alphanumerics) else { return nil }
            return URL(string: "hermes://open?action=\(encoded)")
        }
    }
}
