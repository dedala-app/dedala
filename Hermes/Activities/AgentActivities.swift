// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import ActivityKit
import CryptoKit
import Foundation
import UIKit

/// Live Activities the agent draws, started here and then driven by push:
/// `{"op": "activity", "id", "views", "components", "assets", "background", "tint", "data", "alert", "end"}`.
/// Views, components and assets go to the app group once; every later op only
/// merges data.
final class AgentActivities {
    var report: ((JSONValue) -> Void)?
    var onStartToken: ((String) -> Void)? {
        didSet { if let startToken { onStartToken?(startToken) } }
    }
    private var data: [String: JSONValue] = [:]
    private var updateTokens: [String: String] = [:]
    private var startToken: String?

    init() {
        Task {
            for await token in Activity<HermesActivityAttributes>.pushToStartTokenUpdates {
                startToken = Self.hex(token)
                onStartToken?(Self.hex(token))
            }
        }
        Task {
            for await activity in Activity<HermesActivityAttributes>.activityUpdates {
                observe(activity)
            }
        }
        for activity in Activity<HermesActivityAttributes>.activities {
            observe(activity)
        }
    }

    /// Draws every activity on the phone again at its real sizes, and tells
    /// the agent once per design when it did not fit, so it improves it.
    func review(record: (JSONValue, [String: Data]) -> Void) {
        var reviewed = Set(UserDefaults.standard.stringArray(forKey: "reviewedActivityDesigns") ?? [])
        for activity in Activity<HermesActivityAttributes>.activities {
            let views = ActivityViews(activity.attributes)
            let design = (try? JSONEncoder().encode(views.file)) ?? Data()
            let key = activity.attributes.id + "-" + SHA256.hash(data: design).map { String(format: "%02x", $0) }.joined().prefix(16)
            guard !reviewed.contains(key) else { continue }
            reviewed.insert(key)
            let data = ActivityViews.data(activity.content.state)
            let (report, captures) = ActivityPreview.run(.object(["id": .string(activity.attributes.id), "design": views.file, "data": data]))
            guard report["shown"]?.string != "lock" || !(report["issues"]?.array ?? []).isEmpty else { continue }
            var object = report.object ?? [:]
            object["kind"] = "activity-report"
            record(.object(object), captures)
        }
        UserDefaults.standard.set(Array(reviewed), forKey: "reviewedActivityDesigns")
    }

    /// Ends the activities a previous pairing started: their channels went
    /// with it, so nothing could update them; the agent starts them again.
    func endAll() {
        for activity in Activity<HermesActivityAttributes>.activities {
            Task { await activity.end(nil, dismissalPolicy: .immediate) }
        }
    }

    /// What a server needs to reach the activities by push.
    var tokens: JSONValue {
        .object([
            "start": startToken.map(JSONValue.string) ?? .null,
            "activities": .object(updateTokens.mapValues(JSONValue.string)),
        ])
    }

    func apply(_ op: JSONValue) {
        guard let id = op["id"]?.string else { return }
        if op["views"] != nil, let url = HermesActivityAttributes.viewsURL(id) {
            var file = op.object ?? [:]
            for key in ["op", "id", "data", "alert", "end", "assets"] { file[key] = nil }
            try? FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
            try? JSONEncoder().encode(JSONValue.object(file)).write(to: url)
        }
        let merged = (data[id] ?? .object([:])).merging(op["data"] ?? .object([:]))
        data[id] = merged
        let encoded = (try? JSONEncoder().encode(merged)).flatMap { String(data: $0, encoding: .utf8) } ?? "{}"
        let content = ActivityContent(state: HermesActivityAttributes.ContentState(data: encoded), staleDate: nil)
        let alert = op["alert"].map { alert in
            AlertConfiguration(title: "\(alert["title"]?.text ?? "")", body: "\(alert["body"]?.text ?? "")", sound: .default)
        }
        let ending = op["end"]?.truthy == true
        let starting = op["views"] != nil
        let assets = op["assets"]?.object ?? [:]
        Assets.shared.awaiting(assets.keys)
        Task {
            for (name, data) in await Self.store(assets) {
                Assets.shared.kept(data, as: name)
            }
            Assets.shared.settled(assets.keys)
            let running = Activity<HermesActivityAttributes>.activities.filter { $0.attributes.id == id && $0.activityState == .active }
            if ending {
                for activity in running {
                    await activity.end(content, dismissalPolicy: .after(.now + 15 * 60))
                }
            } else if starting || running.isEmpty {
                for activity in running {
                    await activity.end(nil, dismissalPolicy: .immediate)
                }
                do {
                    observe(try Activity.request(attributes: HermesActivityAttributes(id: id), content: content, pushType: .token))
                } catch {
                    report?(.object(["kind": "activity", "id": .string(id), "error": .string(error.localizedDescription)]))
                }
            } else {
                for activity in running {
                    await activity.update(content, alertConfiguration: alert)
                }
            }
        }
    }

    private func observe(_ activity: Activity<HermesActivityAttributes>) {
        let id = activity.attributes.id
        Task {
            for await token in activity.pushTokenUpdates {
                updateTokens[id] = Self.hex(token)
                report?(.object(["kind": "activity-token", "id": .string(id), "token": .string(Self.hex(token))]))
            }
        }
    }

    private static func hex(_ token: Data) -> String {
        token.map { String(format: "%02x", $0) }.joined()
    }

    /// `{"op": "assets", "assets": {name: url}}`: fetched, shrunk and kept for
    /// `{"Image": {"asset": name}}`. A picture from the agent's machine comes
    /// through the relay instead (`{"local": file}` once fetched), kept large
    /// enough for a page and replaced each time it is sent.
    func storeAssets(_ op: JSONValue) {
        let assets = op["assets"]?.object ?? [:]
        Assets.shared.awaiting(assets.keys)
        Task {
            for (name, data) in await Self.store(assets) {
                Assets.shared.kept(data, as: name)
            }
            Assets.shared.settled(assets.keys)
        }
    }

    /// What was kept, by name.
    private static func store(_ assets: [String: JSONValue]) async -> [String: Data] {
        await withTaskGroup(of: (String, Data)?.self) { group in
            for (name, source) in assets {
                group.addTask {
                    guard let local = HermesAssets.url(name) else { return nil }
                    if let file = source["local"]?.string {
                        defer { try? FileManager.default.removeItem(atPath: file) }
                        guard let image = UIImage(contentsOfFile: file), let shrunk = shrunk(image, side: 1600, jpeg: true) else { return nil }
                        save(shrunk, to: local)
                        return (name, shrunk)
                    }
                    guard let remote = source.string.flatMap(URL.init(string:)),
                          !FileManager.default.fileExists(atPath: local.path),
                          let (data, _) = try? await URLSession.shared.data(from: remote),
                          let image = UIImage(data: data), let shrunk = shrunk(image, side: 160, jpeg: false) else { return nil }
                    save(shrunk, to: local)
                    return (name, shrunk)
                }
            }
            var kept: [String: Data] = [:]
            for await case let (name, data)? in group { kept[name] = data }
            return kept
        }
    }

    nonisolated private static func shrunk(_ image: UIImage, side: CGFloat, jpeg: Bool) -> Data? {
        let scale = min(1, side / max(image.size.width, image.size.height))
        let size = CGSize(width: image.size.width * scale, height: image.size.height * scale)
        let format = UIGraphicsImageRendererFormat()
        format.scale = 1
        let renderer = UIGraphicsImageRenderer(size: size, format: format)
        let draw: (UIGraphicsImageRendererContext) -> Void = { _ in image.draw(in: CGRect(origin: .zero, size: size)) }
        return jpeg ? renderer.jpegData(withCompressionQuality: 0.85, actions: draw) : renderer.pngData(actions: draw)
    }

    nonisolated private static func save(_ data: Data, to url: URL) {
        try? FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
        try? data.write(to: url, options: .atomic)
    }
}
