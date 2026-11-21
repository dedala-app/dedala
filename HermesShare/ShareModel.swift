// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import Foundation
import Observation
import OSLog
import UIKit
import UniformTypeIdentifiers

/// What you are sharing, read from the other app, and its sending: files and
/// long texts go first as sealed blobs, then the share as one event, kept in
/// the app group until the plugin acknowledges it.
@Observable
final class ShareModel {
    enum Item: Equatable {
        case link(url: URL, title: String?, selection: String?, page: String?)
        case text(String)
        case image(jpeg: Data, thumbnail: Data?)
        case file(name: String, type: String, data: Data)
    }

    enum Phase: Equatable {
        case loading, ready, sending, unpaired
        case failed(String)
    }

    /// The most a shared file may weigh: blobs wait on the relay in a space
    /// of 50MB for everything on its way to the agent.
    static let largestFile = 20 * 1024 * 1024
    /// A text longer than this travels as a blob, not inside the event.
    static let inlineText = 50_000

    var items: [Item] = []
    var phase = Phase.loading
    var note = ""
    var agentName = PairingStore.load()?.agentName ?? "Dedala"

    var canSend: Bool {
        !items.isEmpty && !note.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            && (phase == .ready || { if case .failed = phase { true } else { false } }())
    }

    func load(_ inputs: [NSExtensionItem]) async {
        guard PairingStore.load() != nil else {
            phase = .unpaired
            return
        }
        var found: [Item] = []
        var refused: String?
        for provider in inputs.flatMap({ $0.attachments ?? [] }) {
            switch await Self.item(from: provider) {
            case .success(let item?): found.append(item)
            case .failure(let reason): refused = reason.message
            default: break
            }
        }
        items = Self.merged(found)
        phase = items.isEmpty ? .failed(refused ?? "Nothing here \(agentName) can take.") : .ready
    }

    /// Sends the share; false when it could not go, with the reason in `phase`.
    func send() async -> Bool {
        guard let pairing = PairingStore.load(), let keys = try? pairing.keys() else {
            phase = .unpaired
            return false
        }
        phase = .sending
        let id = UUID().uuidString
        var described: [JSONValue] = []
        for (index, item) in items.enumerated() {
            guard let value = await describe(item, at: index, share: id, pairing: pairing, keys: keys) else {
                phase = .failed("The relay could not be reached. Try again in a moment.")
                return false
            }
            described.append(value)
        }
        let event: JSONValue = .object([
            "kind": "share", "id": .string(id), "conversation": "main", "text": .string(note.trimmingCharacters(in: .whitespacesAndNewlines)),
            "items": .array(described), "at": .iso(.now),
        ])
        ShareOutbox.add(event)
        await RelayPost.send([event], pairing: pairing, keys: keys)
        return true
    }

    private func describe(_ item: Item, at index: Int, share: String, pairing: Pairing, keys: Seal.Keys) async -> JSONValue? {
        func blobs(_ data: Data) async -> JSONValue? {
            await RelayPost.upload(data, pairing: pairing, keys: keys).map { .array($0.map(JSONValue.string)) }
        }
        switch item {
        case .link(let url, let title, let selection, let page):
            var value: [String: JSONValue] = ["type": "link", "url": .string(url.absoluteString)]
            if let title { value["title"] = .string(title) }
            if let selection { value["selection"] = .string(String(selection.prefix(Self.inlineText))) }
            if let page {
                guard let uploaded = await blobs(Data(page.utf8)) else { return nil }
                value["page"] = uploaded
            }
            return .object(value)
        case .text(let text):
            guard text.count > Self.inlineText else { return .object(["type": "text", "text": .string(text)]) }
            return await blobs(Data(text.utf8)).map { .object(["type": "text", "blobs": $0]) }
        case .image(let jpeg, let thumbnail):
            guard let uploaded = await blobs(jpeg) else { return nil }
            if let thumbnail { ShareOutbox.keepThumbnail(thumbnail, share: share, item: index) }
            return .object(["type": "image", "item": .number(Double(index)), "mime": "image/jpeg", "blobs": uploaded])
        case .file(let name, let type, let data):
            guard let uploaded = await blobs(data) else { return nil }
            return .object(["type": "file", "name": .string(name), "mime": .string(type), "size": .number(Double(data.count)), "blobs": uploaded])
        }
    }

    // MARK: - Reading what was shared

    struct Refusal: Error {
        let message: String
    }

    /// A page from Safari comes as its link and as what the page script read:
    /// the richer one is kept.
    static func merged(_ items: [Item]) -> [Item] {
        let read = Set(items.compactMap { item -> URL? in
            if case .link(let url, _, _, let page) = item, page != nil { return url }
            return nil
        })
        return items.filter { item in
            if case .link(let url, _, _, nil) = item { return !read.contains(url) }
            return true
        }
    }

    private static func item(from provider: NSItemProvider) async -> Result<Item?, Refusal> {
        if provider.hasItemConformingToTypeIdentifier(UTType.propertyList.identifier),
           let values = try? await provider.loadItem(forTypeIdentifier: UTType.propertyList.identifier) as? [String: Any],
           let page = values[NSExtensionJavaScriptPreprocessingResultsKey] as? [String: Any],
           let url = (page["url"] as? String).flatMap(URL.init(string:)) {
            return .success(.link(url: url, title: filled(page["title"]), selection: filled(page["selection"]), page: filled(page["text"])))
        }
        if provider.hasItemConformingToTypeIdentifier(UTType.image.identifier) {
            guard let data = await imageData(provider) else { return .failure(Refusal(message: "A photo could not be read.")) }
            var drawn = await resized(data)
            if drawn == nil, let unarchived = Self.unarchived(data) { drawn = await resized(unarchived) }
            if drawn == nil, let object = await imageObject(provider) { drawn = await resized(object) }
            guard let image = drawn else {
                note("A photo of \(data.count) bytes starting \(data.prefix(16).map { String(format: "%02x", $0) }.joined()), offered as \(provider.registeredTypeIdentifiers), could not be drawn")
                return .failure(Refusal(message: "A photo could not be read."))
            }
            return .success(.image(jpeg: image.jpeg, thumbnail: image.thumbnail))
        }
        if provider.hasItemConformingToTypeIdentifier(UTType.url.identifier),
           let url = try? await provider.loadItem(forTypeIdentifier: UTType.url.identifier) as? URL, !url.isFileURL {
            return .success(.link(url: url, title: provider.suggestedName, selection: nil, page: nil))
        }
        if provider.hasItemConformingToTypeIdentifier(UTType.plainText.identifier),
           let text = try? await provider.loadItem(forTypeIdentifier: UTType.plainText.identifier) as? String {
            if let url = URL(string: text.trimmingCharacters(in: .whitespacesAndNewlines)), url.scheme?.hasPrefix("http") == true {
                return .success(.link(url: url, title: nil, selection: nil, page: nil))
            }
            return .success(.text(text))
        }
        guard let type = provider.registeredTypeIdentifiers.first(where: { UTType($0)?.conforms(to: .data) == true }) else { return .success(nil) }
        guard let data = await data(provider, type) else { return .failure(Refusal(message: "A file could not be read.")) }
        guard data.count <= largestFile else { return .failure(Refusal(message: "Files up to 20 MB only.")) }
        let kind = UTType(type)
        var name = provider.suggestedName ?? "file"
        if let suffix = kind?.preferredFilenameExtension, !name.lowercased().hasSuffix(".\(suffix)") { name += ".\(suffix)" }
        return .success(.file(name: name, type: kind?.preferredMIMEType ?? "application/octet-stream", data: data))
    }

    private static func filled(_ value: Any?) -> String? {
        guard let text = (value as? String)?.trimmingCharacters(in: .whitespacesAndNewlines), !text.isEmpty else { return nil }
        return text
    }

    private static func data(_ provider: NSItemProvider, _ type: String) async -> Data? {
        await withCheckedContinuation { done in
            _ = provider.loadDataRepresentation(forTypeIdentifier: type) { data, error in
                if let error { note("\(type) as data: \(error)") }
                done.resume(returning: data)
            }
        }
    }

    /// Photos hands a photo over in its own format (HEIC, JPEG), not as any
    /// image: each image type it offers is asked for, as data, as a file, then
    /// as the object it holds.
    private static func imageData(_ provider: NSItemProvider) async -> Data? {
        let offered = provider.registeredTypeIdentifiers.filter { UTType($0)?.conforms(to: .image) == true }
        for type in offered + [UTType.image.identifier] {
            if let data = await data(provider, type) { return data }
            if let data = await file(provider, type) { return data }
            if let data = await object(provider, type) { return data }
            note("\(type): no data, no file, no object")
        }
        note("No photo among \(provider.registeredTypeIdentifiers)")
        return nil
    }

    private static func resized(_ data: Data) async -> (jpeg: Data, thumbnail: Data?)? {
        await Task.detached { ShareOutbox.photo(data) }.value
    }

    /// Signal hands over the image it holds archived, a property list of a
    /// UIImage rather than the picture's bytes.
    private static func unarchived(_ data: Data) -> Data? {
        guard data.starts(with: Data("bplist".utf8)),
              let image = try? NSKeyedUnarchiver.unarchivedObject(ofClass: UIImage.self, from: data) else { return nil }
        return image.jpegData(compressionQuality: 0.9)
    }

    /// An app may hand over the image it holds, whose bytes as a generic
    /// image are no picture ImageIO reads.
    private static func imageObject(_ provider: NSItemProvider) async -> Data? {
        guard provider.canLoadObject(ofClass: UIImage.self) else { return nil }
        return await withCheckedContinuation { done in
            _ = provider.loadObject(ofClass: UIImage.self) { image, error in
                if let error { note("As an image object: \(error)") }
                done.resume(returning: (image as? UIImage)?.jpegData(compressionQuality: 0.9))
            }
        }
    }

    private static func file(_ provider: NSItemProvider, _ type: String) async -> Data? {
        await withCheckedContinuation { done in
            _ = provider.loadFileRepresentation(forTypeIdentifier: type) { url, error in
                if let error { note("\(type) as file: \(error)") }
                done.resume(returning: url.flatMap { try? Data(contentsOf: $0) })
            }
        }
    }

    private static func object(_ provider: NSItemProvider, _ type: String) async -> Data? {
        switch try? await provider.loadItem(forTypeIdentifier: type) {
        case let url as URL: try? Data(contentsOf: url)
        case let image as UIImage: image.jpegData(compressionQuality: 0.9)
        case let data as Data: data
        default: nil
        }
    }

    nonisolated private static let log = Logger(subsystem: "app.dedala.share", category: "share")

    /// Logged, and in a debug build also kept in the app group, where
    /// `devicectl device copy from` reads it: the extension's log does not
    /// reach the Mac.
    nonisolated private static func note(_ line: String) {
        log.error("\(line, privacy: .public)")
        #if DEBUG
        guard let url = FileManager.default.containerURL(forSecurityApplicationGroupIdentifier: HermesActivityAttributes.group)?
            .appending(path: "Library/Caches/share-diagnostics.log") else { return }
        try? FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
        let entry = Data("\(Date.now.ISO8601Format()) \(line)\n".utf8)
        if let handle = try? FileHandle(forWritingTo: url) {
            handle.seekToEndOfFile()
            handle.write(entry)
            try? handle.close()
        } else {
            try? entry.write(to: url)
        }
        #endif
    }
}
