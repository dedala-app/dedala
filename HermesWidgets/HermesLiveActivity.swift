// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import ActivityKit
import SwiftUI
import WidgetKit

/// Every region of an agent's activity is one Dedala UI node from its design:
/// `lock` (with `lockCompact` when it does not fit the lock screen), `leading`,
/// `trailing`, `center`, `bottom`, `compactLeading`, `compactTrailing` and
/// `minimal`, drawn over the latest data.
struct HermesLiveActivity: Widget {
    var body: some WidgetConfiguration {
        ActivityConfiguration(for: HermesActivityAttributes.self) { context in
            let views = ActivityViews(context.attributes)
            views.lock(data: ActivityViews.data(context.state))
                .padding(16)
                .activityBackgroundTint(views.color("background"))
                .activitySystemActionForegroundColor(views.color("tint") ?? .primary)
        } dynamicIsland: { context in
            let views = ActivityViews(context.attributes)
            return DynamicIsland {
                DynamicIslandExpandedRegion(.leading) { views.render("leading", context.state) }
                DynamicIslandExpandedRegion(.trailing) { views.render("trailing", context.state) }
                DynamicIslandExpandedRegion(.center) { views.render("center", context.state) }
                DynamicIslandExpandedRegion(.bottom) { views.render("bottom", context.state) }
            } compactLeading: {
                views.render("compactLeading", context.state)
            } compactTrailing: {
                views.render("compactTrailing", context.state)
            } minimal: {
                views.render("minimal", context.state)
            }
            .keylineTint(views.color("tint"))
        }
    }
}
