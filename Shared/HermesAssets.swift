// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import Foundation

/// Images the agent sends ahead of time, kept in the app group so the widget
/// extension, which cannot download anything, can draw them too.
nonisolated enum HermesAssets {
    static func url(_ name: String) -> URL? {
        let safe = name.filter { $0.isLetter || $0.isNumber || $0 == "-" || $0 == "_" }
        return FileManager.default
            .containerURL(forSecurityApplicationGroupIdentifier: HermesActivityAttributes.group)?
            .appending(path: "Assets")
            .appending(path: "\(safe).png")
    }
}
