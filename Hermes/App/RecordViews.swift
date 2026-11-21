// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import SwiftUI

/// A record of a store opened on its own (protocol.md, Data): the screen its
/// store declares, over the stores as they are; without one, a plain sheet
/// of its fields and its file.
enum Records {
    /// What a store's declaration says of a record, evaluated over it.
    @MainActor
    static func scope(_ record: JSONValue, hub: Hub, store: String) -> Scope {
        var scope = Scope(values: [:], boxes: [], context: CardContext(cardID: "record:\(store)", component: { [weak hub] in hub?.component($0) }, onSend: { _, _ in }),
                          data: record.object ?? [:])
        scope.stores = hub.stores
        scope.probes = false
        return scope
    }

    @MainActor
    static func title(of record: JSONValue, in store: String, hub: Hub) -> String {
        guard let expression = hub.declarations[store]?["title"], expression != .null else {
            return record["title"]?.string ?? record["name"]?.string ?? record["id"]?.text ?? store
        }
        let text = scope(record, hub: hub, store: store).text(expression)
        return text.isEmpty ? record["id"]?.text ?? store : text
    }

    @MainActor
    static func subtitle(of record: JSONValue, in store: String, hub: Hub) -> String? {
        guard let expression = hub.declarations[store]?["subtitle"], expression != .null else { return nil }
        let text = scope(record, hub: hub, store: store).text(expression)
        return text.isEmpty ? nil : text
    }

    /// The screen the store declares for its records, when it is defined.
    @MainActor
    static func screen(for store: String, hub: Hub) -> String? {
        guard let name = hub.declarations[store]?["screen"]?.string, hub.component(name) != nil else { return nil }
        return name
    }

    /// The record a link written in a document points to: by identifier
    /// (`denote:ID`, `id:UUID`), by path (`file:plan.md`, `2026/plan.md`) or
    /// by name (a wikilink, the file's stem or its title); looked for in the
    /// folder store the document is a record of, then in every folder store.
    @MainActor
    static func linked(_ target: String, from document: JSONValue, hub: Hub) -> RecordRef? {
        let (kind, name) = DocumentLink.parse(target)
        guard kind != .heading, !name.isEmpty else { return nil }
        let folders = hub.stores.keys.filter { hub.storeKinds[$0] == "folder" }.sorted()
        let own = folders.first { store in hub.stores[store]?.array?.contains { $0["path"] == document["path"] && document["path"] != nil } == true }
        let base = (document["id"]?.string ?? "").split(separator: "/").dropLast().joined(separator: "/")
        let lowered = name.lowercased()
        for store in ([own].compactMap { $0 } + folders.filter { $0 != own }) {
            guard let records = hub.stores[store]?.array else { continue }
            let found: JSONValue?
            switch kind {
            case .identifier:
                found = records.first { $0["identifier"]?.text == name }
            case .path:
                let relative = base.isEmpty ? name : "\(base)/\(name)"
                let wanted = Self.stem(name)
                found = records.first { $0["id"]?.string == relative || $0["id"]?.string == name } ?? records.first { Self.stem($0["id"]?.string ?? "") == wanted }
            default:
                found = records.first { Self.stem($0["id"]?.string ?? "").lowercased() == lowered } ?? records.first { $0["title"]?.string?.lowercased() == lowered }
            }
            if let id = found?["id"]?.string { return RecordRef(store: store, record: id) }
        }
        return nil
    }

    private static func stem(_ path: String) -> String {
        let name = path.split(separator: "/").last.map(String.init) ?? path
        guard let dot = name.lastIndex(of: "."), dot != name.startIndex else { return name }
        return String(name[..<dot])
    }

    /// Opens a record from where a document is drawn: its declared screen
    /// pushed on the stack the document is on, or the record's sheet.
    @MainActor
    static func open(_ ref: RecordRef, from scope: Scope, hub: Hub) {
        if let navigator = scope.navigator, let screen = screen(for: ref.store, hub: hub) {
            navigator.show(Shown(name: screen, call: Element.Call(.object(["id": .string(ref.record)])), scope: scope), replacing: false)
        } else {
            ActionRunner.openRecord?(ref.store, ref.record)
        }
    }
}

/// A record's file that is not on the phone: fetched when shown, with its
/// progress; asked for with a tap when it is big; said missing or refused
/// when the agent's machine cannot give it.
private struct AttachmentState: View {
    @Environment(Hub.self) private var hub
    @Environment(Agent.self) private var agent
    let value: JSONValue
    let store: String
    let record: String

    var body: some View {
        let name = value["name"]?.string ?? ""
        let size = value["size"]?.int ?? 0
        let big = size > Attachments.askFirst
        Group {
            if value["missing"]?.truthy == true {
                Label("\(name) is missing on \(agent.name)'s machine", systemImage: "exclamationmark.icloud")
            } else if let error = value["error"]?.string {
                Button {
                    hub.attachments.request(store, record)
                } label: {
                    Label("\(error) — try again", systemImage: "arrow.clockwise.icloud")
                }
            } else if value["fetching"]?.truthy == true {
                VStack(alignment: .leading, spacing: 6) {
                    Label("Fetching \(name)…", systemImage: "icloud.and.arrow.down")
                    if size > 0 {
                        ProgressView(value: Double(value["received"]?.int ?? 0), total: Double(size))
                        Text("\(Self.megabytes(value["received"]?.int ?? 0)) of \(Self.megabytes(size))")
                    }
                }
            } else if big {
                Button {
                    hub.attachments.request(store, record)
                } label: {
                    Label("Download \(name) (\(Self.megabytes(size)))", systemImage: "icloud.and.arrow.down")
                }
            } else {
                Label("Fetching \(name)…", systemImage: "icloud.and.arrow.down")
                    .task(id: record) { hub.attachments.request(store, record) }
            }
        }
        .font(.footnote)
        .foregroundStyle(.secondary)
    }

    private static func megabytes(_ bytes: Int) -> String {
        Int64(bytes).formatted(.byteCount(style: .file))
    }
}

/// A record over what opened it: its declared screen with its own stack, or
/// the plain sheet.
struct RecordSheet: View {
    @Environment(Hub.self) private var hub
    let ref: RecordRef
    let close: () -> Void

    var body: some View {
        if let screen = Records.screen(for: ref.store, hub: hub) {
            ScreenSheet(root: Shown(name: screen, call: Element.Call(.object(["id": .string(ref.record)])),
                                    scope: Records.scope(.object([:]), hub: hub, store: ref.store)),
                        stores: hub.stores, close: close)
        } else {
            NavigationStack {
                PlainRecord(ref: ref)
                    .toolbar {
                        ToolbarItem(placement: .cancellationAction) { Button("Close", action: close) }
                    }
            }
        }
    }
}

/// A record as it is, when its store declares no screen: its fields as
/// facts, its file read below them.
struct PlainRecord: View {
    @Environment(Hub.self) private var hub
    let ref: RecordRef

    var body: some View {
        let record = hub.record(ref.store, ref.record)
        let declaration = hub.declarations[ref.store]
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                if let record {
                    let shown = (record.object ?? [:]).filter { !["id", "file", "text", "title", "path"].contains($0.key) }
                    if !shown.isEmpty {
                        GroupedRows {
                            ForEach(shown.keys.sorted(), id: \.self) { key in
                                HStack(alignment: .firstTextBaseline) {
                                    Text(key).font(.subheadline).foregroundStyle(.secondary)
                                    Spacer()
                                    Text(shown[key]?.text ?? "").font(.subheadline).multilineTextAlignment(.trailing)
                                }
                            }
                        }
                    }
                    if record["file"] != nil || record["text"] != nil {
                        FileView(value: record["file"] ?? record, height: nil)
                            .padding(16)
                            .background(Color(.secondarySystemGroupedBackground), in: .rect(cornerRadius: 22, style: .continuous))
                    }
                } else {
                    ContentUnavailableView("Nothing here", systemImage: "questionmark.square.dashed",
                                           description: Text("No record \(ref.record) in \(ref.store)."))
                }
            }
            .padding(.horizontal, 16)
            .padding(.bottom, 24)
        }
        .background(Color(.systemGroupedBackground))
        .navigationTitle(record.map { Records.title(of: $0, in: ref.store, hub: hub) } ?? declaration?["name"]?.string ?? ref.store)
        .navigationBarTitleDisplayMode(.inline)
    }
}

/// A record handed to you in a message: its title and its store's symbol;
/// a tap opens it.
struct RecordChip: View {
    @Environment(Hub.self) private var hub
    @Environment(Router.self) private var router
    let ref: RecordRef

    var body: some View {
        let record = hub.record(ref.store, ref.record)
        let declaration = hub.declarations[ref.store]
        Button { router.sheetRecord = ref } label: {
            HStack(spacing: 12) {
                Image(systemName: declaration?["symbol"]?.string ?? "doc.fill")
                    .font(.title3)
                    .foregroundStyle(.secondary)
                    .frame(width: 34, height: 34)
                    .background(Color(.tertiarySystemFill), in: .rect(cornerRadius: 9, style: .continuous))
                VStack(alignment: .leading, spacing: 2) {
                    Text(record.map { Records.title(of: $0, in: ref.store, hub: hub) } ?? ref.record)
                        .font(.subheadline.weight(.semibold))
                        .lineLimit(1)
                    Text(record.flatMap { Records.subtitle(of: $0, in: ref.store, hub: hub) } ?? declaration?["name"]?.string ?? ref.store)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                }
                Spacer(minLength: 0)
                Image(systemName: "chevron.right").font(.footnote.weight(.semibold)).foregroundStyle(.tertiary)
            }
            .padding(10)
            .background(Color(.secondarySystemBackground), in: .rect(cornerRadius: 16, style: .continuous))
            .contentShape(.rect)
        }
        .buttonStyle(.plain)
    }
}

/// `{"File": …}` drawn by the app: a record's attachment as the phone holds
/// it, a text store or a folder record by its text, or a string.
struct FileView: View {
    @Environment(Hub.self) private var hub
    @Environment(Agent.self) private var agent
    let value: JSONValue
    let height: CGFloat?
    var scope: Scope?

    var body: some View {
        Group {
            if let local = value["local"]?.string, value["blobs"] == nil || hub.attachments.url(value["store"]?.string ?? "", value["id"]?.string ?? "") == nil {
                reader(FileReader(url: URL(fileURLWithPath: local), format: FileFormat.of(value["name"]?.string ?? local)))
            } else if let store = value["store"]?.string, let record = value["id"]?.string, value["path"] != nil {
                if let url = hub.attachments.url(store, record) {
                    reader(FileReader(url: url, format: FileFormat.of(value["name"]?.string ?? "")))
                } else {
                    AttachmentState(value: value, store: store, record: record)
                }
            } else if let file = value["file"], file["store"] != nil || file["local"] != nil {
                FileView(value: file, height: height, scope: scope)
            } else if let text = value["text"]?.string {
                let format = FileFormat.of(value["name"]?.string ?? "")
                reader(FileReader(url: URL(filePath: "/"), format: ["org", "markdown"].contains(format) ? format : "text", text: text, head: value["title"] == nil))
            } else {
                reader(FileReader(url: URL(filePath: "/"), format: "text", text: value.text))
            }
        }
        .environment(\.openURL, OpenURLAction { url in
            guard let target = DocumentLink.target(of: url) else { return .systemAction }
            guard let ref = Records.linked(target, from: value, hub: hub) else { return .discarded }
            Records.open(ref, from: scope ?? Records.scope(value, hub: hub, store: ref.store), hub: hub)
            return .handled
        })
    }

    @ViewBuilder
    private func reader(_ content: FileReader) -> some View {
        if content.format == "pdf" || content.format == "document" {
            content.frame(height: height ?? 600)
        } else if let height {
            ScrollView { content }
                .frame(height: height)
        } else {
            content
        }
    }
}
