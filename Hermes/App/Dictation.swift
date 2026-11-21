// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import Foundation

/// A `Dictate` input listening: the conversation's listener, started for the
/// page, its words handed on as they settle; the closure given back stops it.
@MainActor
enum Dictation {
    static func start(_ heard: @escaping (String, Bool) -> Void) -> () -> Void {
        let listener = Listener()
        var watching = true
        func follow() {
            guard watching else { return }
            let text = withObservationTracking { listener.text } onChange: {
                Task { @MainActor in follow() }
            }
            if !text.isEmpty { heard(text, false) }
        }
        Task { @MainActor in
            await listener.start()
            if case .failed = listener.state {
                watching = false
                heard("", true)
                return
            }
            follow()
        }
        return {
            watching = false
            Task { @MainActor in
                let said = await listener.finish()
                heard(said, true)
            }
        }
    }
}
