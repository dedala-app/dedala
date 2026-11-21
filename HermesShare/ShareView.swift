// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import SwiftUI

/// The sheet: what you are sharing, the note that tells the agent what to do
/// with it, and Send. It lands in the main conversation as your message.
struct ShareView: View {
    @Bindable var model: ShareModel
    let close: () -> Void
    let cancel: () -> Void
    @FocusState private var writing: Bool

    var body: some View {
        NavigationStack {
            content
                .navigationTitle(model.agentName)
                .navigationBarTitleDisplayMode(.inline)
                .toolbar {
                    ToolbarItem(placement: .cancellationAction) {
                        Button(role: .cancel, action: cancel)
                    }
                    ToolbarItem(placement: .confirmationAction) {
                        Button(role: .confirm) {
                            Task { if await model.send() { close() } }
                        } label: {
                            Label("Send", systemImage: "arrow.up")
                        }
                        .disabled(!model.canSend)
                    }
                }
        }
    }

    @ViewBuilder private var content: some View {
        switch model.phase {
        case .unpaired:
            ContentUnavailableView("Not paired", systemImage: "link",
                                   description: Text("Open Dedala and pair it with your agent first."))
        case .loading:
            ProgressView()
        default:
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    ForEach(model.items.indices, id: \.self) { index in
                        SharingRow(item: model.items[index])
                    }
                    TextField("What should \(model.agentName) do with it?", text: $model.note, axis: .vertical)
                        .lineLimit(3...10)
                        .focused($writing)
                        .padding(12)
                        .background(Color(.secondarySystemBackground), in: .rect(cornerRadius: 16, style: .continuous))
                    if case .failed(let reason) = model.phase {
                        Text(reason).font(.footnote).foregroundStyle(.red)
                    }
                }
                .padding(16)
            }
            .disabled(model.phase == .sending)
            .overlay {
                if model.phase == .sending { ProgressView() }
            }
            .onAppear { writing = true }
        }
    }
}

private struct SharingRow: View {
    let item: ShareModel.Item

    var body: some View {
        HStack(spacing: 12) {
            preview
                .frame(width: 44, height: 44)
                .background(Color(.tertiarySystemBackground))
                .clipShape(.rect(cornerRadius: 10, style: .continuous))
            VStack(alignment: .leading, spacing: 2) {
                Text(title).font(.subheadline.weight(.semibold)).lineLimit(2)
                if let detail {
                    Text(detail).font(.caption).foregroundStyle(.secondary).lineLimit(3)
                }
            }
            Spacer(minLength: 0)
        }
        .padding(10)
        .background(Color(.secondarySystemBackground), in: .rect(cornerRadius: 16, style: .continuous))
    }

    @ViewBuilder private var preview: some View {
        switch item {
        case .image(_, let thumbnail):
            if let thumbnail, let image = UIImage(data: thumbnail) {
                Image(uiImage: image).resizable().scaledToFill()
            } else {
                Image(systemName: "photo").foregroundStyle(.secondary)
            }
        case .link:
            Image(systemName: "safari").foregroundStyle(.secondary)
        case .text:
            Image(systemName: "text.quote").foregroundStyle(.secondary)
        case .file:
            Image(systemName: "doc").foregroundStyle(.secondary)
        }
    }

    private var title: String {
        switch item {
        case .link(let url, let title, _, _): title ?? url.host() ?? url.absoluteString
        case .text: "Text"
        case .image: "Photo"
        case .file(let name, _, _): name
        }
    }

    private var detail: String? {
        switch item {
        case .link(let url, _, let selection, let page):
            selection.map { "“\($0)”" } ?? (page != nil ? "\(url.host() ?? "") · page text included" : url.host())
        case .text(let text): text
        case .image: nil
        case .file(_, _, let data): ByteCountFormatter.string(fromByteCount: Int64(data.count), countStyle: .file)
        }
    }
}
