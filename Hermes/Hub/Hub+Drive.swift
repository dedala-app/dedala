// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

#if DEBUG
import SwiftUI
import UIKit

/// The drive server of debug builds: the Mac sends ops over USB and reads back
/// what they drew, the events and the screen (docs/protocol.md, Transport).
extension Hub {
    func startServer() {
        if server == nil {
            server = DriveServer(port: 7070) { [weak self] request in
                await self?.handle(request) ?? .init(status: 503, body: Data())
            }
        }
        server?.start()
    }

    private func handle(_ request: DriveServer.Request) async -> DriveServer.Response {
        switch (request.method, request.path) {
        case ("POST", "/ops"):
            return await perform(request.body)
        case ("POST", "/lines"):
            return .init(body: TextLines.measure(request.body))
        case ("GET", "/snapshot"):
            let scale = request.query["scale"].flatMap(Double.init) ?? 2
            guard let png = snapshot(scale: scale) else { return .init(status: 500, body: Data("no window".utf8)) }
            return .init(contentType: "image/png", body: png)
        case ("GET", "/events"):
            let events = JSONValue.array(driven)
            driven = []
            return .init(body: events.data())
        case ("GET", "/show"):
            guard request.query["tab"] != nil || request.query["record"] != nil || request.query["message"] != nil else { return .init(status: 400, body: Data("tab, record or message?".utf8)) }
            onShow?(request.query["tab"], request.query["record"], request.query["message"])
            return .init(body: Data("{\"ok\":true}".utf8))
        case ("GET", "/onboarding"):
            let shown = request.query["step"]
            onOnboarding?(shown == "off" ? nil : shown ?? "welcome")
            return .init(body: Data("{\"ok\":true}".utf8))
        case ("POST", "/turn"):
            guard let scene = keyWindow?.windowScene else { return .init(status: 500, body: Data("no window".utf8)) }
            scene.requestGeometryUpdate(.iOS(interfaceOrientations: request.query["to"] == "landscape" ? .landscapeRight : .portrait))
            return .init(body: Data("{\"ok\":true}".utf8))
        case ("POST", "/reset"):
            onReset?()
            return .init(body: Data("{\"ok\":true}".utf8))
        case ("GET", "/tokens"):
            return .init(body: (try? JSONEncoder().encode(pushTokens?() ?? .null)) ?? Data())
        case ("GET", "/grammar"):
            return .init(body: Views.grammar.data())
        case ("GET", "/components"):
            return .init(body: JSONValue.object(components).data())
        case ("GET", let path) where path.hasPrefix("/captures/"):
            guard let png = captures[String(path.dropFirst("/captures/".count))] else {
                return .init(status: 404, body: Data("{\"error\":\"no such capture\"}".utf8))
            }
            return .init(contentType: "image/png", body: png)
        default:
            return .init(status: 404, body: Data("{\"error\":\"not found\"}".utf8))
        }
    }

    private func perform(_ body: Data) async -> DriveServer.Response {
        let ops: [JSONValue]
        do {
            let value = try JSONValue.parse(body)
            ops = value.array ?? [value]
        } catch {
            return .init(status: 400, body: JSONValue.object(["ok": false, "errors": [.string("Body is not JSON: \(error.localizedDescription)")]]).data())
        }
        return .init(body: await run(ops).data())
    }

    /// Applies a batch of ops over USB and answers once what they drew has settled.
    func run(_ ops: [JSONValue]) async -> JSONValue {
        let applied = apply(batch: ops)
        let rendered = await report(applied)
        let clean = (rendered + applied.previews).allSatisfy { ($0["issues"]?.array ?? []).isEmpty && ($0["diagnostics"]?.array ?? []).isEmpty }
        var result: [String: JSONValue] = [
            "ok": .bool(applied.errors.isEmpty && clean),
            "applied": .number(Double(ops.count - applied.errors.count)),
            "errors": .array(applied.errors),
            "rendered": .array(rendered),
        ]
        if !applied.previews.isEmpty {
            result["previews"] = .array(applied.previews)
        }
        return .object(result)
    }

    private func snapshot(scale: Double) -> Data? {
        guard let window = keyWindow else { return nil }
        let format = UIGraphicsImageRendererFormat()
        format.scale = scale
        let image = UIGraphicsImageRenderer(bounds: window.bounds, format: format).image { _ in
            window.drawHierarchy(in: window.bounds, afterScreenUpdates: true)
        }
        return image.pngData()
    }
}
#endif
