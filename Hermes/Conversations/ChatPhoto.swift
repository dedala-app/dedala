// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import SwiftUI

/// A photo you put in a message before sending it: the JPEG the agent gets
/// and the small image your message shows.
nonisolated struct ChatPhoto: Identifiable, Sendable {
    static let most = 10

    let id = UUID()
    let jpeg: Data
    let thumbnail: Data

    /// From the camera or the library (`source`), at most `limit`.
    @MainActor
    static func pick(_ source: String, limit: Int) async -> [ChatPhoto] {
        let pictures = await PhotoPicking.pictures(source, limit: limit)
        return await Task.detached {
            pictures.compactMap { data in ShareOutbox.photo(data).map { ChatPhoto(jpeg: $0.jpeg, thumbnail: $0.thumbnail ?? $0.jpeg) } }
        }.value
    }
}

/// A photo waiting in the message field, with its button to take it out.
struct PickedPhoto: View {
    let photo: ChatPhoto
    let remove: () -> Void

    var body: some View {
        Group {
            if let image = UIImage(data: photo.thumbnail) {
                Image(uiImage: image).resizable().scaledToFill()
            } else {
                Image(systemName: "photo").foregroundStyle(.secondary)
            }
        }
        .frame(width: 56, height: 56)
        .clipShape(.rect(cornerRadius: 12, style: .continuous))
        .overlay(alignment: .topTrailing) {
            Button(action: remove) {
                Label("Remove Photo", systemImage: "xmark.circle.fill")
                    .labelStyle(.iconOnly)
                    .font(.body)
                    .symbolRenderingMode(.palette)
                    .foregroundStyle(.white, .black.opacity(0.6))
                    .padding(2)
                    .contentShape(.circle)
            }
            .buttonStyle(.plain)
        }
    }
}
