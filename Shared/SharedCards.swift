// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import Foundation

/// What the notification extension needs to draw a card as the app would: the
/// components the agent defined, the width cards get in a conversation and how
/// much of the conversation shows. Written by the app into the App Group.
enum SharedCards {
    private static var componentsURL: URL? {
        FileManager.default.containerURL(forSecurityApplicationGroupIdentifier: HermesActivityAttributes.group)?
            .appending(path: "components.json")
    }

    static func saveComponents(_ components: [String: JSONValue]) {
        guard let url = componentsURL else { return }
        try? JSONValue.object(components).data().write(to: url, options: .atomic)
    }

    static func components() -> [String: JSONValue] {
        guard let url = componentsURL, let data = try? Data(contentsOf: url) else { return [:] }
        return (try? JSONValue.parse(data))?.object ?? [:]
    }

    // Read once, written only on a change: the app sets them from layout
    // callbacks, which run on every frame while cards move.
    private nonisolated(unsafe) static var known: (width: Double, dark: Bool, viewport: Double, page: Double)?

    private static var current: (width: Double, dark: Bool, viewport: Double, page: Double) {
        if let known { return known }
        let counters = PairingStore.counters
        let read = (counters.double(forKey: "cards.width").nonZero ?? 354, counters.bool(forKey: "cards.dark"),
                    counters.double(forKey: "cards.viewport"), counters.double(forKey: "pages.width"))
        known = read
        return read
    }

    /// The width a card gets in a conversation on a narrow display: a wide one
    /// only gives it more room.
    static var width: Double {
        get { current.width }
        set {
            guard abs(newValue - current.width) > 0.5 else { return }
            known?.width = newValue
            PairingStore.counters.set(newValue, forKey: "cards.width")
        }
    }

    /// The width a page gets on a narrow display, its margins included: a wide
    /// one only gives widgets more room. Zero until a page has been shown.
    static var pageWidth: Double {
        get { current.page }
        set {
            guard abs(newValue - current.page) > 0.5 else { return }
            known?.page = newValue
            PairingStore.counters.set(newValue, forKey: "pages.width")
        }
    }

    /// Whether the app is drawn dark, so cards are captured as he sees them.
    static var dark: Bool {
        get { current.dark }
        set {
            guard newValue != current.dark else { return }
            known?.dark = newValue
            PairingStore.counters.set(newValue, forKey: "cards.dark")
        }
    }

    /// The height of conversation that shows between its header and the message
    /// field, keyboard down: the largest seen, since the keyboard takes some.
    static var viewport: Double {
        get { current.viewport.nonZero ?? 520 }
        set {
            guard newValue > current.viewport + 0.5 else { return }
            known?.viewport = newValue
            PairingStore.counters.set(newValue, forKey: "cards.viewport")
        }
    }
}

private extension Double {
    var nonZero: Double? { self == 0 ? nil : self }
}
