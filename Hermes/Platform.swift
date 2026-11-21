// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import SwiftUI

/// What the bars do from iOS 27 on; iOS 26 keeps its own defaults.
extension View {
    /// The title at the bar's leading edge, as in Messages; centred before iOS 27.2.
    @ViewBuilder func titleAtLeadingEdge() -> some View {
        if #available(iOS 27.2, *) {
            toolbarTitleAlignment(.leading)
        } else {
            self
        }
    }

    /// The navigation bar stays as you scroll; iOS 26 never folds it away.
    @ViewBuilder func barStaysOnScroll() -> some View {
        if #available(iOS 27.0, *) {
            toolbarMinimizationBehavior(.never, for: .navigationBar)
        } else {
            self
        }
    }

    /// Actions in the system's overflow menu; before iOS 27, a menu at the bar's trailing edge.
    @ViewBuilder func overflowMenu<Actions: View>(@ViewBuilder _ actions: () -> Actions) -> some View {
        let content = actions()
        if #available(iOS 27.0, *) {
            toolbarOverflowMenu { content }
        } else {
            toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Menu("More", systemImage: "ellipsis") { content }
                }
            }
        }
    }
}

/// Whether iPhone Duo has moved the bar's items to a side bar, which only
/// iOS 27.1 and later can do.
struct SideBarReader<Content: View>: View {
    @ViewBuilder let content: (Bool) -> Content

    var body: some View {
        if #available(iOS 27.1, *) {
            Reading(content: content)
        } else {
            content(false)
        }
    }

    @available(iOS 27.1, *)
    private struct Reading: View {
        @Environment(\.toolbarVerticalEdge) private var edge
        let content: (Bool) -> Content

        var body: some View {
            content(edge != nil)
        }
    }
}
