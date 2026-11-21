// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import Foundation
import Observation

/// What the app keeps up to date from what it holds, read by any card or page
/// by name: `$waiting`, `$running`, `$today`, `$pages`, `$commands`.
/// The app fills it; an extension, which holds none of it, reads them empty.
@Observable
final class LiveValues {
    static let shared = LiveValues()
    static let names: Set<String> = ["waiting", "running", "today", "pages", "commands"]

    private(set) var values: [String: JSONValue] = [:]
    /// Bumped on every change, for what recomputes when they change.
    private(set) var version = 0

    /// Takes the values given, keeping the others as they are.
    func update(_ part: [String: JSONValue]) {
        guard part.contains(where: { values[$0.key] != $0.value }) else { return }
        values.merge(part) { $1 }
        version += 1
    }

    func value(_ name: String) -> JSONValue? {
        guard Self.names.contains(name) else { return nil }
        return values[name] ?? Self.empty(name)
    }

    static func empty(_ name: String) -> JSONValue {
        switch name {
        case "running": .object(["turns": [], "runs": []])
        case "today": .object(["answered": [], "runs": [], "messages": .number(0)])
        case "commands": .object([:])
        default: []
        }
    }
}
