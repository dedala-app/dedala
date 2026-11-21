// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import SwiftUI

/// What you shared from another app, above the note you wrote with it: photos
/// as small squares, a link, a file or a quote as a row like a vault chip.
struct SharedItems: View {
    let items: [Conversations.SharedItem]
    let share: String?

    private var photos: [Conversations.SharedItem] { items.filter { $0.type == "image" } }

    var body: some View {
        VStack(alignment: .trailing, spacing: 6) {
            if !photos.isEmpty {
                HStack(spacing: 6) {
                    ForEach(photos.prefix(4), id: \.self) { photo in
                        SharedPhoto(url: share.flatMap { share in photo.item.flatMap { ShareOutbox.thumbnail(share: share, item: $0) } })
                    }
                    if photos.count > 4 {
                        Text("+\(photos.count - 4)")
                            .font(.subheadline.weight(.semibold))
                            .foregroundStyle(.secondary)
                            .frame(width: 44, height: 72)
                    }
                }
            }
            ForEach(items.filter { $0.type != "image" }, id: \.self) { item in
                SharedRow(item: item)
            }
        }
    }
}

private struct SharedPhoto: View {
    let url: URL?

    var body: some View {
        Group {
            if let url, let image = UIImage(contentsOfFile: url.path) {
                Image(uiImage: image).resizable().scaledToFill()
            } else {
                Image(systemName: "photo").foregroundStyle(.secondary)
            }
        }
        .frame(width: 72, height: 72)
        .background(Color(.secondarySystemBackground))
        .clipShape(.rect(cornerRadius: 14, style: .continuous))
    }
}

private struct SharedRow: View {
    @Environment(\.openURL) private var openURL
    let item: Conversations.SharedItem

    private var link: URL? { item.type == "link" ? item.url.flatMap(URL.init(string:)) : nil }

    var body: some View {
        Button {
            if let link { openURL(link) }
        } label: {
            HStack(spacing: 12) {
                Image(systemName: symbol)
                    .font(.body.weight(.medium))
                    .foregroundStyle(.secondary)
                    .frame(width: 34, height: 34)
                    .background(Color(.tertiarySystemBackground), in: .rect(cornerRadius: 9, style: .continuous))
                VStack(alignment: .leading, spacing: 2) {
                    Text(title).font(.subheadline.weight(.semibold)).lineLimit(2)
                    if let detail {
                        Text(detail).font(.caption).foregroundStyle(.secondary).lineLimit(item.type == "text" ? 4 : 1)
                    }
                }
                Spacer(minLength: 0)
            }
            .padding(10)
            .background(Color(.secondarySystemBackground), in: .rect(cornerRadius: 16, style: .continuous))
            .contentShape(.rect)
        }
        .buttonStyle(.plain)
        .disabled(link == nil)
    }

    private var symbol: String {
        switch item.type {
        case "link": "safari"
        case "text": "text.quote"
        default: "doc"
        }
    }

    private var title: String {
        switch item.type {
        case "link": item.title?.isEmpty == false ? item.title! : (link?.host() ?? item.url ?? "Link")
        case "text": "Text"
        default: item.name ?? "File"
        }
    }

    private var detail: String? {
        switch item.type {
        case "link": link?.host()
        case "text": item.text
        default: item.size.map { ByteCountFormatter.string(fromByteCount: Int64($0), countStyle: .file) }
        }
    }
}
