// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import Testing
import UIKit
@testable import Hermes

/// An asset kept while the app runs is what cards and pages draw by its name.
@MainActor
@Suite("Assets")
struct AssetsTests {
    @Test func anAssetKeptIsDrawnByItsName() throws {
        let name = "test-\(UUID().uuidString)"
        #expect(Assets.shared.image(name) == nil)
        let format = UIGraphicsImageRendererFormat()
        format.scale = 1
        let png = try #require(UIGraphicsImageRenderer(size: CGSize(width: 4, height: 3), format: format).pngData { _ in })
        Assets.shared.kept(png, as: name)
        #expect(Assets.shared.image(name)?.size == CGSize(width: 4, height: 3))
    }
}
