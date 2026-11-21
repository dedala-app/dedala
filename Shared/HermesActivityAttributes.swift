// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import ActivityKit
import Foundation

/// A Live Activity the agent draws: its design comes with the start (or waits in
/// the app group), and each update carries only the data.
nonisolated struct HermesActivityAttributes: ActivityAttributes {
    nonisolated struct ContentState: Codable, Hashable {
        var data: String
    }

    var id: String
    /// The agent's design for this activity, deflated and base64-encoded, so a
    /// push can start an activity the phone has never seen.
    var design: String?

    static let group = "group.app.dedala"

    static func viewsURL(_ id: String) -> URL? {
        FileManager.default
            .containerURL(forSecurityApplicationGroupIdentifier: group)?
            .appending(path: "Activities")
            .appending(path: "\(id).json")
    }
}
