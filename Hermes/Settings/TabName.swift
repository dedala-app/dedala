// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import SwiftUI

/// Naming a page's tab: a short name for the tab bar, which stays on the
/// phone; an empty one gives the tab back the page's title.
private struct TabNameAlert: ViewModifier {
    @Environment(Hub.self) private var hub
    @Binding var pageID: String?
    @State private var name = ""

    func body(content: Content) -> some View {
        content
            .alert("Tab name", isPresented: Binding(get: { pageID != nil }, set: { if !$0 { pageID = nil } })) {
                TextField(pageID.flatMap { hub.page($0)?.title } ?? "", text: $name)
                Button("Cancel", role: .cancel) {}
                Button("Save") {
                    if let pageID { hub.nameTab(pageID, name) }
                }
            } message: {
                Text("A short name for the tab bar. Leave it empty to use the page's title.")
            }
            .onChange(of: pageID) {
                name = pageID.map(hub.tabName) ?? ""
            }
    }
}

extension View {
    func namingTab(_ pageID: Binding<String?>) -> some View {
        modifier(TabNameAlert(pageID: pageID))
    }
}
