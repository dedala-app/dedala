// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import Foundation
import Observation

/// Where the app is: the tab shown (a page, or Search), the page that took
/// the bar's moving place, and the conversation open over the pages or not,
/// with its path.
@Observable
final class Router {
    enum ActivityRoute: Hashable {
        case list
        case run(String)
        case job(String)
    }

    /// The tab shown: a page's id, or `Router.search`; nil shows the first.
    var tab: String?
    /// The page in the bar's place after the fixed ones: the last one opened
    /// from elsewhere.
    var recent: String?

    static let search = "#search"

    /// Whether the conversation is open over the pages.
    var chatOpen = false
    /// The agent's pill down to his face, while you scroll down a page.
    var pillFolded = false
    var path: [String] = []
    var sheetPage: String?
    /// A record opened over what shows: from Search, a message, or a page
    /// (its declared screen, or a plain sheet of its fields).
    var sheetRecord: RecordRef?
    /// A screen opened as a sheet: from a card, or asked for one.
    var sheetScreen: Shown?
    var activity: ActivityRoute?
    /// A message to bring into view and light up, once its conversation shows.
    var focus: String?
    /// Until when you have read the main conversation: what came after shows
    /// on the agent's pill.
    private(set) var seen: Date

    init() {
        seen = UserDefaults.standard.object(forKey: "conversationSeen") as? Date ?? .now
    }

    /// A page of the bar, the conversation put away.
    func show(page id: String) {
        chatOpen = false
        sheetPage = nil
        tab = id
    }

    /// A page opened from elsewhere: its tab when it is in the bar, else a sheet of its own.
    func show(page id: String, pinned: Bool) {
        if pinned { show(page: id) } else { sheetPage = id }
    }

    /// A page from Activity's sheet: in the bar, or its own sheet once Activity's is gone.
    func openPage(_ id: String, pinned: Bool) {
        guard !pinned else {
            show(page: id)
            return
        }
        Task {
            try? await Task.sleep(for: .milliseconds(450))
            sheetPage = id
        }
    }

    func open(conversation: String) {
        sheetPage = nil
        sheetRecord = nil
        sheetScreen = nil
        activity = nil
        chatOpen = true
        path = conversation == Conversations.main ? [] : [conversation]
    }

    /// A card from a page: its conversation, scrolled to it.
    func show(_ message: String, in conversation: String) {
        open(conversation: conversation)
        focus = message
    }

    /// Something found, opened where it lives: a page in the bar or its own
    /// sheet, a record of a store in its sheet, a topic, a message in its
    /// conversation, a job in Activity.
    func open(_ kind: Search.Kind, _ target: String, conversation: String? = nil, pinned: Bool) {
        switch kind {
        case .page:
            show(page: target, pinned: pinned)
        case .record:
            sheetRecord = RecordRef(target)
        case .topic:
            open(conversation: target)
        case .message:
            show(target, in: conversation ?? Conversations.main)
        case .job:
            activity = .job(target)
        }
    }

    func read() {
        seen = .now
        UserDefaults.standard.set(seen, forKey: "conversationSeen")
    }
}

/// A record of a store, named: `store/id`.
struct RecordRef: Hashable, Identifiable, Codable {
    let store: String
    let record: String

    init(store: String, record: String) {
        self.store = store
        self.record = record
    }

    /// From `store/id`; nil without the slash.
    init?(_ key: String) {
        guard let slash = key.firstIndex(of: "/") else { return nil }
        store = String(key[..<slash])
        record = String(key[key.index(after: slash)...])
    }

    var id: String { "\(store)/\(record)" }
}
