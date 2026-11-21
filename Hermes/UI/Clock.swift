// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import Foundation
import Observation

/// The time cards and pages read, moving: a view that reads `minute` is drawn
/// again each minute, one that reads `second` each second. Until the app
/// starts it (an extension never does), it is simply the time of the reading.
@Observable
final class Clock {
    static let shared = Clock()

    private var minuteTick = Date.now
    private var secondTick = Date.now
    @ObservationIgnored private var started = false
    @ObservationIgnored private var timer: Timer?

    var minute: Date { started ? minuteTick : .now }
    var second: Date { started ? secondTick : .now }

    func start() {
        guard !started else { return }
        started = true
        minuteTick = .now
        secondTick = .now
        timer = Timer.scheduledTimer(withTimeInterval: 1, repeats: true) { [weak self] _ in
            MainActor.assumeIsolated { self?.tick() }
        }
    }

    private func tick() {
        let now = Date.now
        secondTick = now
        if Calendar.current.component(.minute, from: now) != Calendar.current.component(.minute, from: minuteTick) || now.timeIntervalSince(minuteTick) >= 60 {
            minuteTick = now
        }
    }
}
