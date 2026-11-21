// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import UIKit

/// How the phone draws cards and pages: the text size and Bold Text, the width
/// a card and a page get, how much of a conversation shows, the language, the
/// time zone and the iOS version, so the agent's layout twin can lay them out
/// as this phone will.
enum Display {
    @MainActor static var event: JSONValue {
        .object([
            "kind": .string("display"),
            "textSize": .string(textSize),
            "boldText": .bool(UIAccessibility.isBoldTextEnabled),
            "cardWidth": .number(SharedCards.width),
            "pageWidth": .number(PageColumns.narrow(SharedCards.pageWidth) ? SharedCards.pageWidth : 0),
            "viewport": .number(SharedCards.viewport),
            "language": .string(Locale.preferredLanguages.first ?? "en"),
            "os": .string(UIDevice.current.systemVersion),
            "timeZone": .string(TimeZone.current.identifier),
            "utcOffset": .number(Double(TimeZone.current.secondsFromGMT())),
        ])
    }

    @MainActor static var textSize: String {
        switch UIApplication.shared.preferredContentSizeCategory {
        case .extraSmall: "xSmall"
        case .small: "small"
        case .medium: "medium"
        case .extraLarge: "xLarge"
        case .extraExtraLarge: "xxLarge"
        case .extraExtraExtraLarge: "xxxLarge"
        case .accessibilityMedium: "accessibility1"
        case .accessibilityLarge: "accessibility2"
        case .accessibilityExtraLarge: "accessibility3"
        case .accessibilityExtraExtraLarge: "accessibility4"
        case .accessibilityExtraExtraExtraLarge: "accessibility5"
        default: "large"
        }
    }
}
