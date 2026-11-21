// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import SwiftUI

extension EnvironmentValues {
    /// Drawn into an image (a thumbnail): no scroll views, which an ImageRenderer cannot draw.
    @Entry var documentSnapshot = false
    @Entry var documentListDepth = 0
}

/// The org-element tree of a note drawn: headlines with their keywords,
/// planning and tags, folding what is under them; lists with their boxes;
/// tables, blocks, and the objects of each paragraph as styled text. The
/// title and the file's keywords lead when `head`, left to the screen
/// otherwise.
struct DocumentView: View {
    let tree: JSONValue
    var head = true

    private static let shownKeywords = ["SUBTITLE", "AUTHOR", "DATE", "EMAIL"]

    var body: some View {
        let keywords = tree["keywords"]?.object ?? [:]
        let shown = Self.shownKeywords.compactMap { key in keywords[key]?.string.map { (key.capitalized, $0) } }
        VStack(alignment: .leading, spacing: 14) {
            if head, let title = tree["title"]?.string {
                Text(title).font(.title.bold())
            }
            if head, !shown.isEmpty {
                Grid(alignment: .leading, horizontalSpacing: 12, verticalSpacing: 4) {
                    ForEach(shown.indices, id: \.self) { index in
                        GridRow {
                            Text(shown[index].0).font(.caption.weight(.semibold)).foregroundStyle(.secondary)
                            Text(shown[index].1).font(.subheadline)
                        }
                    }
                }
            }
            ElementsView(nodes: tree["children"]?.array ?? [])
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

/// Elements one under the other; the ones the reader does not draw
/// (drawers, keywords, comments, clocks) are left out before the stack, so
/// they take no spacing either.
struct ElementsView: View {
    let nodes: [JSONValue]
    var spacing: CGFloat = 14

    static let hidden: Set<String> = ["drawer", "keyword", "comment", "comment-block", "export-block", "clock", "babel-call", "planning", "property-drawer"]

    var body: some View {
        let shown = nodes.filter { !Self.hidden.contains($0["type"]?.string ?? "") }
        VStack(alignment: .leading, spacing: spacing) {
            ForEach(shown.indices, id: \.self) { index in
                ElementView(node: shown[index])
            }
        }
    }
}

struct ElementView: View {
    let node: JSONValue

    var body: some View {
        switch node["type"]?.string ?? "" {
        case "section":
            ElementsView(nodes: node["children"]?.array ?? [])
        case "headline":
            HeadlineView(node: node)
        case "paragraph":
            Text(Inline.attributed(node["children"]?.array ?? []))
                .lineSpacing(3)
                .fixedSize(horizontal: false, vertical: true)
        case "plain-list":
            ListView(list: node)
        case "table":
            TableBlock(table: node)
        case "src-block", "example-block", "fixed-width", "latex-environment":
            CodeBlock(language: node["language"]?.string, text: (node["value"]?.string ?? "").trimmingCharacters(in: .newlines))
        case "quote-block", "center-block", "special-block", "dynamic-block":
            QuoteBlock(nodes: node["children"]?.array ?? [])
        case "verse-block":
            VStack(alignment: .leading, spacing: 10) {
                ForEach(node["children"]?.array?.indices ?? 0..<0, id: \.self) { index in
                    let child = node["children"]?.array?[index] ?? .null
                    Text(Inline.attributed(child["children"]?.array ?? [], keepingNewlines: true))
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
            .padding(.leading, 12)
        case "footnote-definition":
            HStack(alignment: .firstTextBaseline, spacing: 6) {
                Text("[\(node["label"]?.string ?? "")]").foregroundStyle(.secondary)
                if let children = node["children"]?.array, children.contains(where: { $0["type"]?.string == "paragraph" || $0["type"]?.string == "plain-list" }) {
                    ElementsView(nodes: children, spacing: 8)
                } else {
                    Text(node["text"]?.string ?? "")
                }
            }
            .font(.footnote)
        case "horizontal-rule":
            Divider().padding(.vertical, 4)
        default:
            EmptyView()
        }
    }
}

/// A headline: its keyword and priority, its title, its tags, its planning,
/// and what is under it, folded away by a tap.
struct HeadlineView: View {
    let node: JSONValue
    @State private var folded = false

    var body: some View {
        let children = node["children"]?.array ?? []
        let level = node["level"]?.int ?? 1
        let done = node["todoType"]?.string == "done"
        let label = level >= 3
        VStack(alignment: .leading, spacing: 8) {
            VStack(alignment: .leading, spacing: 6) {
                HStack(alignment: .firstTextBaseline, spacing: 8) {
                    if let keyword = node["todoKeyword"]?.string {
                        chip(keyword, color: done ? .green : .orange)
                    }
                    if let priority = node["priority"]?.string {
                        chip(priority, color: priority == "A" ? .red : .secondary)
                    }
                    Text(label ? Self.uppercased(Inline.attributed(node["objects"]?.array ?? [])) : Inline.attributed(node["objects"]?.array ?? []))
                        .font(font(level))
                        .tracking(label ? 0.6 : 0)
                        .foregroundStyle(done || label ? .secondary : .primary)
                    Spacer(minLength: 0)
                    if !children.isEmpty, !label {
                        Image(systemName: "chevron.down")
                            .font(.caption.weight(.semibold))
                            .foregroundStyle(.tertiary)
                            .rotationEffect(.degrees(folded ? -90 : 0))
                    }
                }
                let planning = Self.planning(node)
                let tags = node["tags"]?.array?.compactMap(\.string) ?? []
                if !planning.isEmpty {
                    HStack(spacing: 10) {
                        ForEach(planning.indices, id: \.self) { index in
                            let (key, stamp) = planning[index]
                            Label(Inline.readable(stamp), systemImage: Self.symbol(key))
                                .foregroundStyle(key == "deadline" ? .red : .secondary)
                        }
                    }
                    .font(.caption)
                    .lineLimit(1)
                }
                if !tags.isEmpty {
                    Text(tags.map { "#\($0)" }.joined(separator: " "))
                        .font(.caption)
                        .foregroundStyle(.tint)
                }
            }
            .padding(.top, level == 1 ? 24 : level == 2 ? 16 : 10)
            .contentShape(.rect)
            .onTapGesture {
                guard !children.isEmpty else { return }
                withAnimation(.snappy) { folded.toggle() }
            }
            if !folded {
                ElementsView(nodes: children)
            }
        }
    }

    static func planning(_ node: JSONValue) -> [(String, JSONValue)] {
        ["scheduled", "deadline", "closed"].compactMap { key in node[key].map { (key, $0) } }
    }

    private func font(_ level: Int) -> Font {
        switch level {
        case 1: .title2.bold()
        case 2: .headline
        default: .footnote.weight(.semibold)
        }
    }

    /// A section label's words in capitals, its markup and links kept.
    static func uppercased(_ text: AttributedString) -> AttributedString {
        var text = text
        for range in text.runs.map(\.range).reversed() {
            text.characters.replaceSubrange(range, with: String(text[range].characters).uppercased())
        }
        return text
    }

    private func chip(_ text: String, color: Color) -> some View {
        Text(text)
            .font(.caption.weight(.bold))
            .foregroundStyle(color)
            .padding(.horizontal, 6)
            .padding(.vertical, 2)
            .background(color.opacity(0.15), in: .capsule)
    }

    private static func symbol(_ key: String) -> String {
        switch key {
        case "deadline": "exclamationmark.circle"
        case "closed": "checkmark.circle"
        default: "calendar"
        }
    }
}

struct ListView: View {
    let list: JSONValue
    @Environment(\.documentListDepth) private var depth

    var body: some View {
        let items = list["children"]?.array ?? []
        VStack(alignment: .leading, spacing: 6) {
            ForEach(items.indices, id: \.self) { index in
                let item = items[index]
                let done = item["checkbox"]?.string == "on"
                let (line, rest) = Self.split(item)
                HStack(alignment: .firstTextBaseline, spacing: 8) {
                    marker(item, number: Self.number(item))
                        .frame(minWidth: 16, alignment: .trailing)
                    VStack(alignment: .leading, spacing: 6) {
                        if let line {
                            Text(line)
                                .strikethrough(done)
                                .foregroundStyle(done ? .secondary : .primary)
                                .fixedSize(horizontal: false, vertical: true)
                        }
                        ForEach(rest.indices, id: \.self) { ElementView(node: rest[$0]) }
                    }
                }
            }
        }
        .environment(\.documentListDepth, depth + 1)
    }

    /// The item's first paragraph as its line, with its tag in front, and
    /// the elements that follow.
    static func split(_ item: JSONValue) -> (AttributedString?, [JSONValue]) {
        var children = item["children"]?.array ?? []
        var line: AttributedString?
        if let first = children.first, first["type"]?.string == "paragraph" {
            line = Inline.attributed(first["children"]?.array ?? [])
            children.removeFirst()
        }
        if let tag = item["tag"]?.string, !tag.isEmpty {
            var term = AttributedString(tag)
            term.inlinePresentationIntent = .stronglyEmphasized
            var rest = line ?? AttributedString()
            if String(rest.characters).hasPrefix(tag), let separator = rest.range(of: " :: ") {
                rest.removeSubrange(rest.startIndex..<separator.upperBound)
            }
            line = term + AttributedString(rest.characters.isEmpty ? "" : " — ") + rest
        }
        return (line, children)
    }

    /// "5." for a numbered item: its counter when set, else its bullet.
    static func number(_ item: JSONValue) -> String? {
        if let counter = item["counter"]?.string, !counter.isEmpty { return "\(counter)." }
        let bullet = item["bullet"]?.string ?? ""
        return bullet.first?.isNumber == true ? bullet : nil
    }

    @ViewBuilder
    private func marker(_ item: JSONValue, number: String?) -> some View {
        switch item["checkbox"]?.string {
        case "off": Image(systemName: "circle").foregroundStyle(.secondary)
        case "on": Image(systemName: "checkmark.circle.fill").foregroundStyle(.green)
        case "trans": Image(systemName: "minus.circle.fill").foregroundStyle(.orange)
        default:
            if let number {
                Text(number).monospacedDigit().foregroundStyle(.secondary)
            } else {
                Text(depth.isMultiple(of: 2) ? "•" : "◦").foregroundStyle(.secondary)
            }
        }
    }
}

struct QuoteBlock: View {
    let nodes: [JSONValue]

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            Capsule().fill(.tint.opacity(0.5)).frame(width: 3)
            ElementsView(nodes: nodes, spacing: 10)
                .foregroundStyle(.secondary)
        }
    }
}

struct CodeBlock: View {
    let language: String?
    let text: String
    @Environment(\.documentSnapshot) private var snapshot

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            if let language, !language.isEmpty {
                Text(language).font(.caption2.weight(.semibold)).foregroundStyle(.secondary)
            }
            if snapshot {
                code
            } else {
                ScrollView(.horizontal) { code }.scrollIndicators(.hidden)
            }
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color(.secondarySystemBackground), in: .rect(cornerRadius: 12, style: .continuous))
        .clipped()
    }

    private var code: some View {
        Text(text).font(.system(.footnote, design: .monospaced)).fixedSize()
    }
}

struct TableBlock: View {
    let table: JSONValue
    @Environment(\.documentSnapshot) private var snapshot

    var body: some View {
        Group {
            if snapshot {
                grid
            } else {
                ScrollView(.horizontal) { grid }.scrollIndicators(.hidden)
            }
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color(.secondarySystemBackground), in: .rect(cornerRadius: 12, style: .continuous))
        .clipped()
    }

    /// The standard rows as cells of styled text; the first is the header
    /// when the table has one.
    static func rows(_ table: JSONValue) -> (header: [AttributedString]?, rows: [[AttributedString]]) {
        var rows = (table["children"]?.array ?? [])
            .filter { $0["rowType"]?.string == "standard" }
            .map { row in (row["children"]?.array ?? []).map { Inline.attributed($0["children"]?.array ?? []) } }
        var header: [AttributedString]?
        if table["hasHeader"]?.truthy == true, !rows.isEmpty {
            header = rows.removeFirst()
        }
        return (header, rows)
    }

    private var grid: some View {
        let (header, rows) = Self.rows(table)
        return Grid(alignment: .leading, horizontalSpacing: 16, verticalSpacing: 8) {
            if let header {
                GridRow {
                    ForEach(header.indices, id: \.self) { Text(header[$0]).font(.subheadline.weight(.semibold)) }
                }
                Divider()
            }
            ForEach(rows.indices, id: \.self) { row in
                GridRow {
                    ForEach(rows[row].indices, id: \.self) { Text(rows[row][$0]).font(.subheadline) }
                }
            }
        }
    }
}

/// The objects of a paragraph as styled text: emphasis as presentation
/// intents, links as links the reader tells apart (Links.swift), timestamps
/// readable and dimmed, entities as their character.
nonisolated enum Inline {
    static func attributed(_ objects: [JSONValue], keepingNewlines: Bool = false) -> AttributedString {
        var result = AttributedString()
        for object in objects {
            result += render(object, keepingNewlines: keepingNewlines)
        }
        return result
    }

    private static func render(_ node: JSONValue, keepingNewlines: Bool) -> AttributedString {
        let children = node["children"]?.array ?? []
        let value = node["value"]?.string ?? ""
        switch node["type"]?.string ?? "" {
        case "plain-text":
            return AttributedString(keepingNewlines ? value : value.replacingOccurrences(of: "\\s*\n\\s*", with: " ", options: .regularExpression))
        case "bold":
            return styled(attributed(children, keepingNewlines: keepingNewlines), .stronglyEmphasized)
        case "italic":
            return styled(attributed(children, keepingNewlines: keepingNewlines), .emphasized)
        case "underline":
            var text = attributed(children, keepingNewlines: keepingNewlines)
            text.underlineStyle = Text.LineStyle.single
            return text
        case "strike-through":
            var text = attributed(children, keepingNewlines: keepingNewlines)
            text.strikethroughStyle = Text.LineStyle.single
            return text
        case "code", "verbatim", "inline-src-block":
            var text = AttributedString(value)
            text.inlinePresentationIntent = .code
            return text
        case "link":
            let raw = node["rawLink"]?.string ?? ""
            var text = children.isEmpty ? AttributedString(description(node)) : attributed(children, keepingNewlines: keepingNewlines)
            if let url = DocumentLink.url(raw) {
                text.link = url
            }
            return text
        case "timestamp":
            var text = AttributedString(readable(node))
            text.foregroundColor = Color.secondary
            return text
        case "statistics-cookie":
            var text = AttributedString(value)
            text.foregroundColor = Color.secondary
            return text
        case "footnote-reference":
            var text = AttributedString("[\(node["label"]?.string ?? "")]")
            text.foregroundColor = Color.secondary
            return text
        case "entity":
            return AttributedString(node["utf8"]?.string ?? "")
        case "line-break":
            return AttributedString("\n")
        case "latex-fragment":
            var text = AttributedString(value)
            text.inlinePresentationIntent = .code
            return text
        case "target":
            return AttributedString(value)
        case "radio-target", "superscript", "subscript":
            return attributed(children, keepingNewlines: keepingNewlines)
        default:
            return AttributedString()
        }
    }

    /// A link with no description shows its path: the address whole, a
    /// note's identifier or file without the scheme.
    static func description(_ link: JSONValue) -> String {
        switch link["linkType"]?.string ?? "" {
        case "denote", "id", "file", "fuzzy": link["path"]?.string ?? ""
        default: link["rawLink"]?.string ?? ""
        }
    }

    /// "Tue 12 May, 09:30–10:30" for a timestamp node.
    static func readable(_ stamp: JSONValue) -> String {
        let raw = stamp["rawValue"]?.string ?? ""
        guard let start = stamp["start"]?.string else { return raw.trimmingCharacters(in: CharacterSet(charactersIn: "<>[]")) }
        let parts = start.split(separator: "T").map(String.init)
        guard let day = parts.first, let date = try? Date.ISO8601FormatStyle(timeZone: .current).year().month().day().parse(day) else { return raw }
        var text = date.formatted(.dateTime.weekday(.abbreviated).day().month(.abbreviated))
        if parts.count > 1 {
            text += ", \(parts[1])"
        }
        if let end = stamp["end"]?.string {
            let ending = end.split(separator: "T").map(String.init)
            if ending.first == day, ending.count > 1 {
                text += "–\(ending[1])"
            } else if let endDay = ending.first, let endDate = try? Date.ISO8601FormatStyle(timeZone: .current).year().month().day().parse(endDay) {
                text += " – " + endDate.formatted(.dateTime.weekday(.abbreviated).day().month(.abbreviated))
            }
        }
        return text
    }

    private static func styled(_ text: AttributedString, _ intent: InlinePresentationIntent) -> AttributedString {
        var text = text
        let runs = text.runs.map { ($0.range, $0.inlinePresentationIntent ?? []) }
        for (range, existing) in runs {
            text[range].inlinePresentationIntent = existing.union(intent)
        }
        return text
    }
}
