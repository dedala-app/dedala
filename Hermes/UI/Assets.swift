// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import Observation
import UIKit

/// The images the agent sent, by name, as cards and pages draw them. Those the
/// app keeps while it runs are held here, so what was drawn before one arrived
/// is drawn again with it; the others are read from the app group, where they
/// stay across launches and for the extensions.
@Observable
final class Assets {
    static let shared = Assets()

    private var received: [String: UIImage] = [:]
    @ObservationIgnored private var loaded: [String: UIImage] = [:]
    /// Names announced and still being fetched: not missing yet.
    @ObservationIgnored private var awaited: Set<String> = []

    func image(_ name: String) -> UIImage? {
        if let image = received[name] ?? loaded[name] { return image }
        guard let file = HermesAssets.url(name), let image = UIImage(contentsOfFile: file.path) else { return nil }
        loaded[name] = image
        return image
    }

    /// An asset the app just kept in the app group.
    func kept(_ data: Data, as name: String) {
        received[name] = UIImage(data: data)
        awaited.remove(name)
    }

    /// Assets an op announced, until they are kept or could not be.
    func awaiting(_ names: some Sequence<String>) {
        awaited.formUnion(names)
    }

    func settled(_ names: some Sequence<String>) {
        awaited.subtract(names)
    }

    func isAwaited(_ name: String) -> Bool {
        awaited.contains(name)
    }
}
