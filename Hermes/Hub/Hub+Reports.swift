// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import SwiftUI
import UIKit

/// What the phone tells the agent about what it drew: each card and page a
/// batch touched, drawn off screen and measured, and the cards you flag or love,
/// as they look on screen.
extension Hub {
    /// Draws the cards and pages a batch touched off screen, once they have
    /// settled, and sends each one's report.
    func report(_ applied: Applied) async -> [JSONValue] {
        var rendered: [JSONValue] = []
        var seen = Set<String>()
        let frames = applied.ops.contains { $0["frames"]?.truthy == true }
        for id in applied.touched where seen.insert(id).inserted {
            guard let card = cardSpec?(id), let made = await CardProbe.report(id, card: card, components: components, stores: stores, frames: frames) else { continue }
            var report = made.report
            report["kind"] = "rendered"
            if let png = made.png {
                report["capture"] = .string(captures.keep(png, as: id))
            }
            emit(.object(report))
            rendered.append(.object(report))
        }
        let drawnPages = applied.ops.compactMap { op in op["op"]?.string == "page" && op["remove"]?.truthy != true ? op["id"]?.string : nil }
        for id in Array(Set(drawnPages)).sorted() {
            guard let page = page(id), let made = await PageProbe.report(page, stores: stores, components: components) else { continue }
            var report = made.report
            report["kind"] = "rendered"
            if let png = made.png {
                report["capture"] = .string(captures.keep(png, as: "page-\(id)"))
            }
            emit(.object(report))
            rendered.append(.object(report))
        }
        return rendered
    }

    /// A capture named in a report, for the relay to carry.
    func captureData(_ key: String) -> Data? {
        captures[key]
    }

    /// Sends a report made elsewhere in the app, keeping its captures for the relay.
    func record(_ report: JSONValue, captures shots: [String: Data]) {
        captures.hold(shots)
        emit(report)
    }

    /// An action that could not do what it says, told to the agent: where,
    /// what you tapped when that is known, and why nothing happened.
    func failed(_ problem: String, on id: String, tapped: String?) {
        let place = page(id) != nil ? "page" : "card"
        var event: [String: JSONValue] = ["kind": "failed", place: .string(id), "problem": .string(problem), "at": JSONValue.iso(.now)]
        if let tapped { event["tapped"] = .string(tapped) }
        emit(.object(event))
    }

    /// Flags a card that looks wrong to you, with a capture of the screen as you
    /// see it and its layout, for the agent to fix and learn from.
    func flag(_ id: String, conversation: String, yours: String) {
        Task {
            try? await Task.sleep(for: .milliseconds(800))
            guard var report = seen(id) else { return }
            report["kind"] = "flag"
            report["conversation"] = .string(conversation)
            report["yours"] = .string(yours)
            emit(.object(report))
        }
    }

    /// A card you loved goes to the agent's card bank, as it stands and as it
    /// looks, for it to draw from next time.
    func love(_ id: String, conversation: String, card: JSONValue) {
        Task {
            try? await Task.sleep(for: .milliseconds(800))
            var event = seen(id) ?? ["card": .string(id)]
            event["kind"] = "loved"
            event["conversation"] = .string(conversation)
            event.merge(card.object ?? [:]) { $1 }
            emit(.object(event))
        }
    }

    /// What the card looks like on screen and what its layout measured.
    private func seen(_ id: String) -> [String: JSONValue]? {
        guard let context = contexts[id] else { return nil }
        let size = context.size
        var issues = context.layoutIssues()
        var notes: [String] = []
        var visible: Double?
        if let frame = cardFrames[id], let window = keyWindow {
            let overflow = max(0, -frame.minX) + max(0, frame.maxX - window.bounds.width)
            if overflow > 1 {
                issues.insert("The card is \(Int(frame.width))pt wide and runs \(Int(overflow))pt off the screen; something inside it has a fixed width that is too large", at: 0)
            }
            let area = viewport.map { $0.intersection(window.bounds) } ?? window.bounds
            if frame.height > 0 {
                visible = max(0, frame.intersection(area).height) / frame.height
            }
            if frame.height > area.height + 1 {
                notes.append(CardDrawing.tallNote(frame.height, area.height))
            }
        }
        var report: [String: JSONValue] = [
            "card": .string(id),
            "size": [.number(size.width.rounded()), .number(size.height.rounded())],
            "issues": .array(issues.map(JSONValue.string)),
            "diagnostics": .array(context.diagnostics.map(JSONValue.string)),
        ]
        if let shot = capture(id) {
            report["capture"] = .string(captures.keep(shot.png, as: id))
        }
        if let visible {
            report["visible"] = .number((visible * 100).rounded() / 100)
        }
        if !notes.isEmpty {
            report["notes"] = .array(notes.map(JSONValue.string))
        }

        return report
    }

    private func capture(_ id: String) -> (png: Data, visible: Double)? {
        guard let frame = cardFrames[id], frame.height > 0, let window = keyWindow else { return nil }
        let visible = frame.insetBy(dx: -8, dy: -8).intersection(window.bounds)
        guard !visible.isNull, visible.height > 1 else { return nil }
        let format = UIGraphicsImageRendererFormat()
        format.scale = 2
        let image = UIGraphicsImageRenderer(bounds: visible, format: format).image { _ in
            window.drawHierarchy(in: window.bounds, afterScreenUpdates: true)
        }
        guard let png = image.pngData() else { return nil }
        return (png, min(1, frame.intersection(window.bounds).height / frame.height))
    }

    var keyWindow: UIWindow? {
        UIApplication.shared.connectedScenes
            .compactMap { $0 as? UIWindowScene }
            .flatMap(\.windows)
            .first(where: \.isKeyWindow)
    }
}

/// The pictures named in reports, kept until the relay carries them: the last few.
@MainActor
final class Captures {
    static let kept = 40

    private var images: [String: Data] = [:]
    private var keys: [String] = []
    private var count = 0

    subscript(key: String) -> Data? {
        images[key]
    }

    /// Keeps a capture under a new name, which the report gives.
    func keep(_ png: Data, as name: String) -> String {
        count += 1
        let key = "\(name)-\(count).png"
        hold([key: png])
        return key
    }

    /// Keeps captures under the names their maker gave them.
    func hold(_ shots: [String: Data]) {
        for (key, png) in shots {
            if images[key] == nil { keys.append(key) }
            images[key] = png
        }
        while keys.count > Self.kept {
            images[keys.removeFirst()] = nil
        }
    }
}
