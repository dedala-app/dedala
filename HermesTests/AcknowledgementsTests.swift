// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import Foundation
import Testing
@testable import Hermes

/// What the app is built with is listed, and every licence it names can be read.
@MainActor
@Suite("Acknowledgements")
struct AcknowledgementsTests {
    @Test func everyComponentIsListedWithItsLicenceText() {
        let components = AcknowledgementsView.components
        #expect(components.count > 20)
        #expect(components.contains { $0.name == "orgize" } && components.contains { $0.name == "SwiftDraw" })
        for license in Set(components.map(\.license)).union(["AGPL-3.0-or-later"]) {
            let text = Bundle.main.url(forResource: license, withExtension: "txt").flatMap { try? String(contentsOf: $0, encoding: .utf8) }
            #expect(text?.isEmpty == false, "no text for \(license)")
        }
    }
}
