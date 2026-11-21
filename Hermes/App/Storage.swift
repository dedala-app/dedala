// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import Foundation

/// The app's own files, kept in Application Support as JSON. Under test they
/// go to a folder of their own, so a test never reads or changes what the app keeps.
enum Storage {
    static let directory: URL = ProcessInfo.processInfo.environment["XCTestConfigurationFilePath"] == nil
        ? .applicationSupportDirectory
        : .temporaryDirectory.appending(path: "tests-\(UUID().uuidString)")

    static func url(_ name: String) -> URL {
        directory.appending(path: name)
    }

    static func load(_ name: String) -> JSONValue? {
        (try? Data(contentsOf: url(name))).flatMap { try? JSONValue.parse($0) }
    }

    static func save(_ value: JSONValue, to name: String) {
        try? FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        try? value.data().write(to: url(name), options: .atomic)
    }

    private static var waiting: [String: () -> Void] = [:]
    private static var soon: Task<Void, Never>?

    /// Writes a file shortly, as it stands then: a burst of changes (a card's
    /// state at each keystroke, the ops of one batch) is one write.
    static func saveSoon(_ name: String, _ write: @escaping () -> Void) {
        waiting[name] = write
        guard soon == nil else { return }
        soon = Task {
            try? await Task.sleep(for: .milliseconds(400))
            guard !Task.isCancelled else { return }
            flush()
        }
    }

    /// Writes now what `saveSoon` still holds: before what the agent sent is
    /// acknowledged, after what you did, and when the app goes away.
    static func flush() {
        soon?.cancel()
        soon = nil
        let writes = waiting
        waiting = [:]
        for write in writes.values { write() }
    }

    static func load<T: Decodable>(_ type: T.Type, from name: String) -> T? {
        (try? Data(contentsOf: url(name))).flatMap { try? JSONDecoder().decode(type, from: $0) }
    }

    static func save(_ value: some Encodable, to name: String) {
        try? FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        try? JSONEncoder().encode(value).write(to: url(name), options: .atomic)
    }
}
