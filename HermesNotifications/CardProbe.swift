// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import SwiftUI
import UIKit

/// Draws a card that came in a notification the way the app would, and sends
/// its report and capture back to the agent: the app is not open to do it.
enum CardProbe {
    @MainActor
    static func report(_ op: JSONValue) async -> (report: [String: JSONValue], jpeg: Data?)? {
        guard let id = op["id"]?.string, let card = op["card"] else { return nil }
        let components = SharedCards.components().merging(op["components"]?.object ?? [:]) { $1 }
        ScriptEngine.modules = (op["scripts"]?.object ?? [:]).compactMapValues(\.string)
        let derived = await CardDrawing.derive(card)
        let drawn = CardDrawing.view(id, card: card, components: components, derived: derived.values)
        drawn.context.derived = derived.values
        for problem in derived.problems { drawn.context.report(problem) }
        let renderer = ImageRenderer(content: drawn.view.environment(\.colorScheme, SharedCards.dark ? .dark : .light))
        renderer.scale = 2
        guard let image = renderer.uiImage else { return nil }
        return (CardDrawing.report(id, context: drawn.context), image.jpegData(compressionQuality: 0.8))
    }

    /// The report as the app would send it: the capture as a sealed blob, the
    /// event sealed with the next number in the app's own sequence.
    static func send(_ report: [String: JSONValue], jpeg: Data?, pairing: Pairing, keys: Seal.Keys) async {
        var event = report
        event["kind"] = "rendered"
        if let jpeg, let blob = await RelayPost.upload(jpeg, pairing: pairing, keys: keys)?.first {
            event["capture"] = .object(["blob": .string(blob), "type": "image/jpeg"])
        }
        await RelayPost.send([.object(event)], pairing: pairing, keys: keys)
    }
}
