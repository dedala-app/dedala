// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import SwiftUI
import UIKit

/// Draws a Live Activity design at the sizes iOS gives it, before any push
/// starts it: what overflows, which lock layout would show, and captures for
/// the agent to look at. `{"op": "preview", "id", "design", "data"}`
enum ActivityPreview {
    static let lock = CGSize(width: 374, height: 160)
    static let padding: CGFloat = 16
    static let expanded = CGSize(width: 371, height: 160)
    static let compact = CGSize(width: 52, height: 36.67)
    static let minimal = CGSize(width: 37, height: 37)

    static func run(_ op: JSONValue) -> (report: JSONValue, captures: [String: Data]) {
        let id = op["id"]?.string ?? "preview"
        let data = op["data"] ?? .object([:])
        let views = ActivityViews(id: id, design: op["design"] ?? .null)
        let content = CGSize(width: lock.width - padding * 2, height: lock.height - padding * 2)
        var issues: [String] = []
        var regions: [String: JSONValue] = [:]

        func note(_ slot: String, _ size: CGSize, limit: CGSize) {
            regions[slot] = .object([
                "size": [.number(size.width.rounded()), .number(size.height.rounded())],
                "limit": [.number(limit.width.rounded()), .number(limit.height.rounded())],
            ])
        }

        guard views.has("lock") else {
            return (.object(["kind": "preview", "id": .string(id), "issues": ["The design has no lock region"]]), [:])
        }
        let lockSize = measure(views.render("lock", data: data), width: content.width)
        note("lock", lockSize, limit: content)
        var shown = "lock"
        var shownHeight = lockSize.height
        if lockSize.height > content.height {
            if views.has("lockCompact") {
                let compactSize = measure(views.render("lockCompact", data: data), width: content.width)
                note("lockCompact", compactSize, limit: content)
                shown = compactSize.height > content.height ? "clipped" : "lockCompact"
                shownHeight = compactSize.height
            } else {
                shown = "clipped"
            }
            let fallback = shown == "lockCompact" ? "lockCompact is shown instead" : "nothing fits, so iOS squeezes and cuts it"
            issues.append("lock needs \(Int(lockSize.height))pt of height but the lock screen leaves \(Int(content.height))pt inside its padding; \(fallback)")
        } else if !views.has("lockCompact") {
            issues.append("No lockCompact region: add one so a longer note or a larger text size degrades instead of overflowing")
        }

        for slot in ["compactLeading", "compactTrailing"] where views.has(slot) {
            let size = measure(views.render(slot, data: data), width: nil)
            note(slot, size, limit: compact)
            if size.width > compact.width { issues.append("\(slot) is \(Int(size.width))pt wide; the compact island leaves about \(Int(compact.width))pt per side") }
            if size.height > compact.height { issues.append("\(slot) is \(Int(size.height))pt tall; the compact island is \(Int(compact.height))pt") }
        }
        if views.has("minimal") {
            let size = measure(views.render("minimal", data: data), width: nil)
            note("minimal", size, limit: minimal)
            if size.width > minimal.width || size.height > minimal.height { issues.append("minimal is \(Int(size.width))×\(Int(size.height))pt; it gets about \(Int(minimal.width))×\(Int(minimal.height))pt") }
        } else {
            issues.append("No minimal region: iOS shows it when two activities share the island")
        }
        let top = ["leading", "center", "trailing"].filter(views.has).map { measure(views.render($0, data: data), width: nil) }
        let bottom = views.has("bottom") ? measure(views.render("bottom", data: data), width: expanded.width - 40) : .zero
        let expandedHeight = (top.map(\.height).max() ?? 0) + bottom.height + 36
        note("expanded", CGSize(width: expanded.width, height: expandedHeight), limit: expanded)
        if expandedHeight > expanded.height { issues.append("The expanded island needs about \(Int(expandedHeight))pt; it gets \(Int(expanded.height))pt") }
        if top.map(\.width).reduce(0, +) > expanded.width - 40 { issues.append("leading, center and trailing together are wider than the expanded island") }

        shownHeight = min(max(shownHeight, 32), content.height)
        let lockShot = views.lock(data: data)
            .frame(width: content.width, height: shownHeight, alignment: .top)
            .padding(padding)
            .background(views.color("background") ?? Color(.secondarySystemBackground))
            .clipShape(.rect(cornerRadius: 23.5, style: .continuous))
        let islandShot = VStack(spacing: 18) {
            HStack(spacing: 0) {
                views.render("compactLeading", data: data)
                Spacer(minLength: 126)
                views.render("compactTrailing", data: data)
            }
            .padding(.horizontal, 14)
            .frame(height: compact.height)
            .background(.black, in: .capsule)
            .fixedSize()
            views.render("minimal", data: data)
                .frame(width: minimal.width, height: minimal.height)
                .background(.black, in: .circle)
            VStack(spacing: 8) {
                HStack(alignment: .top) {
                    views.render("leading", data: data)
                    Spacer(minLength: 0)
                    views.render("center", data: data)
                    Spacer(minLength: 0)
                    views.render("trailing", data: data)
                }
                views.render("bottom", data: data)
            }
            .padding(.horizontal, 20)
            .padding(.vertical, 14)
            .frame(width: expanded.width)
            .background(.black, in: .rect(cornerRadius: 44, style: .continuous))
        }
        .padding(12)

        var captures: [String: Data] = [:]
        var shots: [JSONValue] = []
        let stamp = Int(Date.now.timeIntervalSince1970)
        for (name, view) in [("lock", AnyView(lockShot)), ("island", AnyView(islandShot))] {
            let renderer = ImageRenderer(content: view.environment(\.colorScheme, .dark))
            renderer.scale = 3
            guard let png = renderer.uiImage?.pngData() else { continue }
            let key = "preview-\(id)-\(name)-\(stamp).png"
            captures[key] = png
            shots.append(.object(["region": .string(name), "capture": .string(key)]))
        }

        let report: JSONValue = .object([
            "kind": "preview",
            "id": .string(id),
            "shown": .string(shown),
            "issues": .array(issues.map(JSONValue.string)),
            "diagnostics": .array(views.context.diagnostics.map(JSONValue.string)),
            "regions": .object(regions),
            "captures": .array(shots),
        ])
        return (report, captures)
    }

    private static func measure(_ view: some View, width: CGFloat?) -> CGSize {
        let sized: AnyView = if let width {
            AnyView(view.frame(width: width).fixedSize(horizontal: false, vertical: true))
        } else {
            AnyView(view.fixedSize())
        }
        return UIHostingController(rootView: sized).sizeThatFits(in: CGSize(width: width ?? 1000, height: 1000))
    }
}
