// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import UIKit
import UserNotifications

/// Asks for the device's push token at launch and hands it on once someone
/// listens. While the app is open, what the agent says shows in the
/// conversation, so its notifications stay quiet; a `notify` op rings anyway.
/// A tap on one opens what it names; a button under one runs its action with
/// the app in the background; a silent push wakes the app to read its mail.
final class AppDelegate: NSObject, UIApplicationDelegate, UNUserNotificationCenterDelegate {
    private var token: String?
    var onToken: ((String) -> Void)? {
        didSet { if let token { onToken?(token) } }
    }
    /// Runs an action a notification asked for: what a tap opens, what a button does.
    var onAction: ((JSONValue) -> Void)? {
        didSet { if let onAction, !pendingActions.isEmpty { pendingActions.forEach(onAction); pendingActions = [] } }
    }
    /// Waits until what the action sent has left the phone.
    var onFlush: (() async -> Void)?
    /// A silent push: the app reads what waited for it; true when something new came.
    var onWake: (() async -> Bool)?
    private var pendingActions: [JSONValue] = []

    func application(_ application: UIApplication, didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]? = nil) -> Bool {
        application.registerForRemoteNotifications()
        UNUserNotificationCenter.current().delegate = self
        return true
    }

    func userNotificationCenter(_ center: UNUserNotificationCenter, willPresent notification: UNNotification) async -> UNNotificationPresentationOptions {
        notification.request.content.userInfo["ring"] != nil ? [.banner, .sound] : []
    }

    func userNotificationCenter(_ center: UNUserNotificationCenter, didReceive response: UNNotificationResponse) async {
        let info = response.notification.request.content.userInfo
        let action: JSONValue?
        if response.actionIdentifier == UNNotificationDefaultActionIdentifier {
            action = (info["open"] as? String).flatMap { try? JSONValue.parse(Data($0.utf8)) }
        } else if response.actionIdentifier == UNNotificationDismissActionIdentifier {
            action = nil
        } else {
            let actions = (info["actions"] as? String).flatMap { try? JSONValue.parse(Data($0.utf8)) }
            action = actions?[response.actionIdentifier]
        }
        guard let action else { return }
        if let onAction {
            onAction(action)
            await onFlush?()
        } else if !(await NotificationActions.performDirectly(action)) {
            pendingActions.append(action)
        }
    }

    func application(_ application: UIApplication, didReceiveRemoteNotification userInfo: [AnyHashable: Any]) async -> UIBackgroundFetchResult {
        guard userInfo["wake"] != nil, let onWake else { return .noData }
        return await onWake() ? .newData : .noData
    }

    func application(_ application: UIApplication, didRegisterForRemoteNotificationsWithDeviceToken deviceToken: Data) {
        let hex = deviceToken.map { String(format: "%02x", $0) }.joined()
        token = hex
        onToken?(hex)
    }
}

/// Notification buttons when the app was not running: a `command` or an
/// `edit` goes straight to the mailbox, sealed; anything that opens
/// something waits for the app to come up.
enum NotificationActions {
    /// The categories iOS shows buttons from, one per declared kind.
    static func register(_ kinds: [String: JSONValue]) {
        let categories = kinds.map { kind, buttons in
            UNNotificationCategory(identifier: kind, actions: (buttons.array ?? []).compactMap { button in
                guard let id = button["id"]?.string, let title = button["title"]?.string else { return nil }
                return UNNotificationAction(identifier: id, title: title, options: button["destructive"]?.truthy == true ? [.destructive] : [])
            }, intentIdentifiers: [])
        }
        UNUserNotificationCenter.current().setNotificationCategories(Set(categories))
    }

    /// Sent without the app's state: true when it was, false when the action
    /// needs the app (it opens something, or could not be sent).
    static func performDirectly(_ action: JSONValue) async -> Bool {
        guard let pairing = PairingStore.load(), let keys = try? pairing.keys() else { return false }
        var events: [JSONValue] = []
        for step in action.array ?? [action] {
            guard let object = step.object else { continue }
            if let command = object["command"]?.string {
                events.append(.object(["kind": "command", "id": .string(UUID().uuidString), "name": .string(command), "args": object["args"] ?? .null,
                                       "from": "notification", "at": JSONValue.iso(.now)]))
            } else if var edit = object["edit"]?.object, let store = edit.removeValue(forKey: "store")?.string {
                var change: [String: JSONValue] = ["store": .string(store), "from": "notification"]
                if let added = edit["add"] {
                    change["add"] = added["id"] == nil ? added.merging(.object(["id": .string(UUID().uuidString.lowercased())])) : added
                } else if let removed = edit["remove"] {
                    change["remove"] = .string(removed.text)
                } else {
                    if let record = edit.removeValue(forKey: "id") { change["id"] = .string(record.text) }
                    change["patch"] = .object(edit)
                }
                events.append(.object(["kind": "edits", "id": .string(UUID().uuidString), "changes": .array([.object(change)]), "at": JSONValue.iso(.now)]))
            } else {
                return false
            }
        }
        guard !events.isEmpty else { return false }
        return await RelayPost.send(events, pairing: pairing, keys: keys)
    }
}

