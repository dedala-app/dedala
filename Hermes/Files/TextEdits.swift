// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import Foundation

/// Your line edits made to a text on the phone, the way the plugin makes
/// them to the file (plugin/dedala/files.py): an item found by its
/// words in the tree, its box, its text or itself replaced at its place.
nonisolated enum TextEdits {
    struct Refused: Error, CustomStringConvertible {
        let description: String
    }

    static func apply(_ text: String, _ edit: JSONValue, format: String) throws -> String {
        if let whole = edit["text"]?.string { return whole }
        let kind = format == "markdown" ? "markdown" : "org"
        let tree = OrgTree.parse(text, format: kind)
        let items = OrgTree.select(tree, "item")
        var bytes = Array(text.utf8)
        if let added = edit["append"] {
            let top = items.filter { ($0["indent"]?.int ?? 0) == 0 }
            let style = top.last
            let bullet = style?["bullet"]?.string.flatMap { $0.first?.isNumber == true ? nil : $0 } ?? "-"
            let ticked = edit["done"]
            let boxed = ticked != nil && ticked != .null || style?["checkbox"] != nil
            let mark = (ticked?.truthy ?? false) ? (kind == "org" ? "X" : "x") : " "
            let lines = (added.array ?? [added]).map { $0.text.trimmingCharacters(in: .whitespaces) }.filter { !$0.isEmpty }
            guard !lines.isEmpty else { throw Refused(description: "Nothing to add") }
            let new = lines.map { "\(bullet) \(boxed ? "[\(mark)] " : "")\($0)" }
            if let last = top.last {
                var at = min(last["end"]?.int ?? bytes.count, bytes.count)
                if at > 0, bytes[at - 1] != UInt8(ascii: "\n") {
                    bytes.insert(UInt8(ascii: "\n"), at: at)
                    at += 1
                }
                bytes.insert(contentsOf: Array((new.joined(separator: "\n") + "\n").utf8), at: at)
                return String(decoding: bytes, as: UTF8.self)
            }
            let body = text.replacingOccurrences(of: "\\n+$", with: "", options: .regularExpression)
            return (body.isEmpty ? "" : body + "\n\n") + new.joined(separator: "\n") + "\n"
        }
        guard let target = ["change", "remove", "toggle"].first(where: { edit[$0] != nil }) else {
            throw Refused(description: "An edit of a file is one of append, change, remove, toggle, text")
        }
        let named = edit[target]!.text.trimmingCharacters(in: .whitespaces)
        guard let item = items.first(where: { $0["text"]?.string == named }) else {
            throw Refused(description: "“\(named)” is no longer in the file")
        }
        func replace(_ begin: Int, _ end: Int, with replacement: String) {
            let begin = min(max(begin, 0), bytes.count)
            let end = min(max(end, begin), bytes.count)
            bytes.replaceSubrange(begin..<end, with: Array(replacement.utf8))
        }
        switch target {
        case "remove":
            var end = item["end"]?.int ?? bytes.count
            if end < bytes.count, bytes[end] == UInt8(ascii: "\n"), end > 0, bytes[end - 1] != UInt8(ascii: "\n") {
                end += 1
            }
            replace(item["begin"]?.int ?? 0, end, with: "")
        case "change":
            let replacement = (edit["to"]?.text ?? "").trimmingCharacters(in: .whitespaces)
            guard !replacement.isEmpty else { throw Refused(description: "A changed line needs its new text in to") }
            replace(item["contentBegin"]?.int ?? 0, item["contentEnd"]?.int ?? 0, with: replacement)
        default:
            let wasDone = item["checkbox"]?.string == "on"
            let done = edit["done"].map { $0 == .null ? !wasDone : $0.truthy } ?? !wasDone
            let mark = done ? (kind == "org" ? "X" : "x") : " "
            if let begin = item["checkboxBegin"]?.int, let end = item["checkboxEnd"]?.int {
                replace(begin, end, with: "[\(mark)]")
            } else {
                let at = item["contentBegin"]?.int ?? 0
                replace(at, at, with: "[\(mark)] ")
            }
        }
        return String(decoding: bytes, as: UTF8.self)
    }
}
