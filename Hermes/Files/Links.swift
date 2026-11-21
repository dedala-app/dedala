// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import Foundation

/// A link written in a document that is not a web address: to another file
/// (`denote:ID`, `id:UUID`, `file:plan.md`, `plan.md`, a `[[wikilink]]`) or
/// to a place in this one (`*Heading`). Carried in the text as a `link:` URL
/// so the reader tells it from the addresses the system opens.
nonisolated enum DocumentLink {
    static let scheme = "link"
    private static let system: Set<String> = ["http", "https", "mailto", "tel", "sms", "maps", "shortcuts", "facetime", "x-apple-data-detectors"]

    /// The URL a link target is carried as: the target itself when the
    /// system opens it, `link:` + the target otherwise.
    static func url(_ target: String) -> URL? {
        let trimmed = target.trimmingCharacters(in: .whitespaces)
        guard !trimmed.isEmpty else { return nil }
        if let url = URL(string: trimmed), let scheme = url.scheme, system.contains(scheme.lowercased()) { return url }
        return URL(string: scheme + ":" + (trimmed.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? trimmed))
    }

    /// The target as written, of a URL that is not the system's to open:
    /// nil for a web address.
    static func target(of url: URL) -> String? {
        guard let scheme = url.scheme?.lowercased() else { return url.absoluteString.removingPercentEncoding ?? url.absoluteString }
        if scheme == Self.scheme {
            return String(url.absoluteString.dropFirst(Self.scheme.count + 1)).removingPercentEncoding
        }
        return ["denote", "id", "file"].contains(scheme) ? url.absoluteString.removingPercentEncoding : nil
    }

    /// Where a target points: the kind of name and the name.
    enum Kind { case identifier, path, name, heading }

    static func parse(_ target: String) -> (Kind, String) {
        if target.hasPrefix("denote:") || target.hasPrefix("id:") {
            return (.identifier, String(target[target.index(after: target.firstIndex(of: ":")!)...]))
        }
        if target.hasPrefix("file:") {
            return (.path, String(target.dropFirst(5).split(separator: "::", maxSplits: 1).first ?? ""))
        }
        if target.hasPrefix("*") || target.hasPrefix("#") {
            return (.heading, String(target.dropFirst()))
        }
        let path = target.split(separator: "::", maxSplits: 1).first.map(String.init) ?? target
        return (path.contains(".") && !path.contains(" ") ? .path : .name, path)
    }
}
