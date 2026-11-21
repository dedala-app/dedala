// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import SwiftUI
import WidgetKit

@main
struct HermesWidgetsBundle: WidgetBundle {
    init() {
        Views.widgetLink = { action in
            let steps = action.array ?? [action]
            guard steps.contains(where: { step in ["page", "show", "conversation", "open"].contains { step[$0] != nil } }),
                  let json = String(data: action.data(), encoding: .utf8),
                  let encoded = json.addingPercentEncoding(withAllowedCharacters: .alphanumerics) else { return nil }
            return URL(string: "hermes://open?action=\(encoded)")
        }
    }

    var body: some Widget {
        HermesWidget()
        HermesLiveActivity()
    }
}
