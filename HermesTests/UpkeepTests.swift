// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import Foundation
import Testing
@testable import Hermes

/// The line under a page's title says how fresh it is: a watched page names
/// when what it watches last changed, and when it was last checked.
@Suite("Upkeep")
struct UpkeepTests {
    let now = Date(timeIntervalSince1970: 1_792_933_200)

    @Test func aWatchedPageSaysWhenItWasChecked() {
        let state: JSONValue = .object([
            "last": JSONValue.iso(now.addingTimeInterval(-3 * 3600)),
            "checked": JSONValue.iso(now.addingTimeInterval(-120)),
            "next": JSONValue.iso(now.addingTimeInterval(180)),
            "watching": true,
        ])
        let line = Upkeep(state).line(at: now)
        #expect(line.hasPrefix("No changes since \(Upkeep.since(now.addingTimeInterval(-3 * 3600), now: now)) ·"))
        #expect(line.hasSuffix("· checked 2 minutes ago"))
        #expect(Upkeep(state).warning(at: now) == nil)
    }

    @Test func aChangeIsNamedAsAPersonWould() {
        let earlier = now.addingTimeInterval(-3600)
        let calendar = Calendar.current
        #expect(Upkeep.since(earlier, now: now) == (calendar.isDate(earlier, inSameDayAs: now) ? earlier.formatted(date: .omitted, time: .shortened) : "yesterday"))
        let lastWeek = now.addingTimeInterval(-3 * 86400)
        #expect(Upkeep.since(lastWeek, now: now) == lastWeek.formatted(.dateTime.weekday(.wide)))
        let lastMonth = now.addingTimeInterval(-40 * 86400)
        #expect(Upkeep.since(lastMonth, now: now) == lastMonth.formatted(.dateTime.day().month(.abbreviated)))
    }
}
