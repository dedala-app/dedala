// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import SwiftUI

/// The app's own licence and what it is built with, each with its copyright
/// and the full text of its licence (Acknowledgements.json, written by
/// tools/acknowledgements.py; the texts are the repository's LICENSES/).
struct AcknowledgementsView: View {
    struct Component: Decodable, Identifiable {
        let name: String
        let url: URL
        let copyright: String
        let license: String
        var id: String { name }
    }

    static let components: [Component] = {
        guard let url = Bundle.main.url(forResource: "Acknowledgements", withExtension: "json"),
              let data = try? Data(contentsOf: url) else { return [] }
        return (try? JSONDecoder().decode([Component].self, from: data)) ?? []
    }()

    var body: some View {
        List {
            Section {
                NavigationLink {
                    LicenseText(title: "Dedala", copyright: "Copyright (c) 2026 Julien Malka", url: SettingsView.source, license: "AGPL-3.0-or-later")
                } label: {
                    LabeledContent("Dedala", value: Self.shortName("AGPL-3.0-or-later"))
                }
            } footer: {
                Text("Dedala is free software: you may share and change it under the GNU Affero General Public License, version 3 or later. The Dedala name and icon are reserved.")
            }
            Section("Built with") {
                ForEach(Self.components) { component in
                    NavigationLink {
                        LicenseText(title: component.name, copyright: component.copyright, url: component.url, license: component.license)
                    } label: {
                        LabeledContent(component.name, value: Self.shortName(component.license))
                    }
                }
            }
        }
        .navigationTitle("Acknowledgements")
        .navigationBarTitleDisplayMode(.inline)
    }

    static func shortName(_ license: String) -> String {
        switch license {
        case "AGPL-3.0-or-later": "AGPL-3.0"
        case "Zlib": "zlib"
        case "LicenseRef-Avataaars": "Free to use"
        default: license
        }
    }
}

/// One component's copyright, where it comes from, and its licence's text.
struct LicenseText: View {
    let title: String
    let copyright: String
    let url: URL
    let license: String

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 12) {
                Text(copyright)
                    .font(.subheadline.weight(.semibold))
                Link(url.absoluteString, destination: url)
                    .font(.subheadline)
                Text(text)
                    .font(.footnote)
                    .foregroundStyle(.secondary)
                    .textSelection(.enabled)
            }
            .padding()
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .navigationTitle(title)
        .navigationBarTitleDisplayMode(.inline)
    }

    private var text: String {
        Bundle.main.url(forResource: license, withExtension: "txt").flatMap { try? String(contentsOf: $0, encoding: .utf8) } ?? ""
    }
}
