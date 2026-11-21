// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import CryptoKit
import Foundation
import Observation
import UIKit

/// The app's end of the relay (docs/relay.md): pairing from the code the
/// plugin prints, a WebSocket while the app is open, sealed ops in and sealed
/// events out, numbered and acknowledged.
@Observable
final class Relay {
    enum State: Equatable {
        case unpaired
        case offline
        case connecting
        case connected
    }

    struct PairingCode: Decodable {
        let v: Int
        let relay: URL
        let pairing: String
        let claim: String
        let proof: String
        let agent_key: String
        let name: String?
    }

    enum PairingError: LocalizedError {
        case unreadable, refused(String)

        var errorDescription: String? {
            switch self {
            case .unreadable: "This is not a Dedala pairing code."
            case .refused(let reason): reason
            }
        }
    }

    /// Whether what the app shows is the agent's: connected, past what waited
    /// on the relay, and brought in sync by the agent since.
    enum Sync: Equatable {
        case offline, connecting, catchingUp, agentAway, upToDate
    }

    private(set) var state: State
    private(set) var caughtUp = false
    private(set) var agentOnline = false
    private(set) var synced = false
    private(set) var agentName: String?
    private(set) var lastError: String?
    /// Ops from the agent, to apply and keep before returning: they are
    /// acknowledged right after.
    @ObservationIgnored var onOps: (([JSONValue]) -> Void)?
    @ObservationIgnored var onPaired: ((String) -> Void)?
    /// What waited on the relay is applied: a moment to send again what the
    /// agent has not acknowledged.
    @ObservationIgnored var onCaughtUp: (() -> Void)?
    @ObservationIgnored var capture: ((String) -> Data?)?
    @ObservationIgnored private var pairing: Pairing?
    @ObservationIgnored private var keys: Seal.Keys?
    @ObservationIgnored private var socket: URLSessionWebSocketTask?
    @ObservationIgnored private var apns = Push()
    @ObservationIgnored private var retry: Task<Void, Never>?
    @ObservationIgnored private var failedConnections = 0
    @ObservationIgnored private var wantsConnection = false
    @ObservationIgnored private var waiting: [Seal.Message] = []
    @ObservationIgnored private let outbound = Outbound()
    @ObservationIgnored private var stored: [Int: CheckedContinuation<Bool, Never>] = [:]
    @ObservationIgnored private var leaving = UIBackgroundTaskIdentifier.invalid

    private struct Push: Equatable {
        var token: String?
        var start: String?
    }

    #if DEBUG
    static let environment = "development"
    #else
    static let environment = "production"
    #endif

    init() {
        pairing = PairingStore.load()
        keys = try? pairing?.keys()
        if let keys { PairingStore.saveActivityKey(keys.toApp) }
        agentName = pairing?.agentName
        state = pairing == nil ? .unpaired : .offline
        outbound.deliver = { [weak self] message in await self?.deliver(message) ?? .failed }
        outbound.onProblem = { [weak self] problem in self?.lastError = problem }
    }

    var isPaired: Bool { pairing != nil }

    var sync: Sync {
        switch state {
        case .unpaired, .offline: .offline
        case .connecting: .connecting
        case .connected where !caughtUp: .catchingUp
        case .connected where !agentOnline: .agentAway
        case .connected: synced ? .upToDate : .catchingUp
        }
    }

    // MARK: - Pairing

    func pair(with code: String) async throws {
        guard let parsed = try? JSONDecoder().decode(PairingCode.self, from: Data(code.utf8)), parsed.v == 1 else {
            throw PairingError.unreadable
        }
        let key = Curve25519.KeyAgreement.PrivateKey()
        let deviceKey = Seal.publicKey(key)
        var apnsBody: [String: JSONValue] = ["environment": .string(Self.environment)]
        if let token = apns.token { apnsBody["token"] = .string(token) }
        if let start = apns.start { apnsBody["start_token"] = .string(start) }
        let body: JSONValue = .object([
            "claim": .string(parsed.claim),
            "device_key": .string(deviceKey),
            "mac": .string(Seal.proofMac(proof: parsed.proof, deviceKey: deviceKey)),
            "name": .string("iPhone"),
            "apns": .object(apnsBody),
        ])
        let (data, status) = try await call(parsed.relay.appending(path: "pairings/\(parsed.pairing)/claim"), method: "POST", body: body, token: nil)
        guard status == 201, let answer = try? JSONValue.parse(data), let token = answer["device_token"]?.string else {
            throw PairingError.refused((try? JSONValue.parse(data))?["error"]?.string ?? "The relay refused the pairing (\(status)).")
        }
        let name = parsed.name ?? answer["agent_name"]?.string ?? "Assistant"
        let saved = Pairing(relay: parsed.relay, agentName: name, agentKey: parsed.agent_key, pairing: parsed.pairing, deviceToken: token, deviceKey: key.rawRepresentation)
        try PairingStore.save(saved)
        PairingStore.counters.set(0, forKey: "relay.lastIn")
        PairingStore.resetOut()
        outbound.clear()
        pairing = saved
        keys = try saved.keys()
        if let keys { PairingStore.saveActivityKey(keys.toApp) }
        agentName = name
        lastError = nil
        state = .offline
        onPaired?(name)
        connect()
    }

    func unpair() {
        disconnect()
        PairingStore.clear()
        PairingStore.clearActivityKey()
        outbound.clear()
        pairing = nil
        keys = nil
        agentName = nil
        state = .unpaired
    }

    // MARK: - Connection

    func connect() {
        wantsConnection = true
        guard let pairing, socket == nil else { return }
        var request = URLRequest(url: pairing.relay.appending(path: "ws"))
        request.setValue("Bearer \(pairing.deviceToken)", forHTTPHeaderField: "Authorization")
        let socket = URLSession.shared.webSocketTask(with: request)
        self.socket = socket
        forget()
        state = .connecting
        socket.resume()
        socket.sendPing { [weak self] error in
            Task { @MainActor [weak self] in
                guard let self, self.socket === socket else { return }
                if error == nil { self.connected() }
            }
        }
        Task { await receive(on: socket) }
    }

    func disconnect() {
        wantsConnection = false
        retry?.cancel()
        socket?.cancel(with: .goingAway, reason: nil)
        socket = nil
        forget()
        if pairing != nil { state = .offline }
    }

    private func forget() {
        waiting = []
        caughtUp = false
        agentOnline = false
        synced = false
        for seq in Array(stored.keys) { settle(seq, false) }
    }

    private func connected() {
        failedConnections = 0
        guard state != .connected else { return }
        state = .connected
        outbound.send()
    }

    private func receive(on socket: URLSessionWebSocketTask) async {
        while self.socket === socket {
            do {
                let frame = try await socket.receive()
                guard case .string(let text) = frame, let value = try? JSONValue.parse(Data(text.utf8)) else { continue }
                connected()
                if let message = value["message"], let sealed = Self.message(message) {
                    if caughtUp { await handle(sealed) } else { waiting.append(sealed) }
                } else if value["caught_up"]?.truthy == true {
                    await catchUp()
                } else if let seq = value["stored"]?.number.flatMap(Int.init(exactly:)) {
                    settle(seq, true)
                } else if let agent = value["agent"]?.string {
                    agentOnline = agent == "online"
                    if !agentOnline { synced = false }
                } else if value["replaced"]?.truthy == true {
                    lastError = "Another device was paired with \(agentName ?? "your agent")."
                    unpair()
                } else if let error = value["error"]?.string {
                    lastError = error
                    if let seq = value["seq"]?.number.flatMap(Int.init(exactly:)) { settle(seq, false) }
                }
            } catch {
                guard self.socket === socket else { return }
                self.socket = nil
                forget()
                state = .offline
                lastError = error.localizedDescription
                scheduleReconnect()
                return
            }
        }
    }

    private func scheduleReconnect() {
        retry?.cancel()
        let wait = Self.reconnects[min(failedConnections, Self.reconnects.count - 1)]
        failedConnections += 1
        retry = Task { [weak self] in
            try? await Task.sleep(for: wait)
            guard let self, !Task.isCancelled, self.wantsConnection else { return }
            self.connect()
        }
    }

    static let reconnects: [Duration] = [.seconds(3), .seconds(3), .seconds(6), .seconds(15), .seconds(30)]

    /// What a message from the agent holds once opened: its ops, and the blobs
    /// its files came in, to delete from the relay once the ops are kept.
    private struct Opened {
        var ops: [JSONValue] = []
        var blobs: [String] = []
    }

    /// Applies a message from the agent once, then acknowledges it.
    private func handle(_ message: Seal.Message) async {
        guard let opened = await open(message) else { return }
        finish([message.seq], opened)
    }

    /// Ops are applied and kept, then acknowledged; what they drew is reported
    /// after, so a card that takes a second to draw holds nothing back.
    private func finish(_ seqs: [Int], _ opened: Opened) {
        apply(opened.ops)
        if let last = seqs.max() { PairingStore.counters.set(last, forKey: "relay.lastIn") }
        seqs.forEach(acknowledge)
        discard(opened.blobs)
    }

    /// What waited on the relay while the app was away is applied as one batch,
    /// so each card and page is drawn and reported once, not once per message.
    private func catchUp() async {
        let messages = waiting.sorted { $0.seq < $1.seq }
        waiting = []
        var all = Opened()
        var seqs: [Int] = []
        for message in messages {
            guard let found = await open(message) else { continue }
            all.ops += found.ops
            all.blobs += found.blobs
            seqs.append(message.seq)
        }
        finish(seqs, all)
        caughtUp = true
        onCaughtUp?()
    }

    /// A message's ops, or nil when it was applied already or cannot be opened.
    private func open(_ message: Seal.Message) async -> Opened? {
        guard let keys else { return nil }
        if message.seq <= PairingStore.counters.integer(forKey: "relay.lastIn") {
            acknowledge(message.seq)
            return nil
        }
        guard let plain = try? Seal.open(message, key: keys.toApp), let ops = try? JSONValue.parse(plain) else {
            lastError = "A message from the agent could not be opened."
            return nil
        }
        return await withFiles(ops.array ?? [ops])
    }

    private func apply(_ ops: [JSONValue]) {
        let drawn = ops.filter { $0["op"]?.string != "synced" }
        if !drawn.isEmpty { onOps?(drawn) }
        if drawn.count < ops.count { synced = true }
    }

    /// Attachments and assets arrive as sealed blobs: each is fetched, opened
    /// and joined into a local file before the op is applied.
    private func withFiles(_ ops: [JSONValue]) async -> Opened {
        var carried: [JSONValue] = []
        var fetched: [String] = []
        for op in ops {
            if op["op"]?.string == "assets", let assets = op["assets"]?.object {
                var local: [String: JSONValue] = [:]
                for (name, source) in assets {
                    guard let blobs = source["blobs"]?.array?.compactMap(\.string), !blobs.isEmpty else {
                        local[name] = source
                        continue
                    }
                    if let file = await download(blobs) {
                        local[name] = .object(["local": .string(file.path)])
                        fetched += blobs
                    }
                }
                carried.append(op.merging(.object(["assets": .object(local)])))
                continue
            }
            guard op["op"]?.string == "attachment", let blobs = op["blobs"]?.array?.compactMap(\.string), !blobs.isEmpty else {
                carried.append(op)
                continue
            }
            var local = op
            if let file = await download(blobs) {
                local = op.merging(.object(["local": .string(file.path)]))
                fetched += blobs
            } else {
                local = op.merging(.object(["missing": true]))
            }
            carried.append(local)
        }
        return Opened(ops: carried, blobs: fetched)
    }

    private func download(_ blobs: [String]) async -> URL? {
        guard let pairing, let keys else { return nil }
        var body = Data()
        for blob in blobs {
            guard let (data, status) = try? await call(pairing.relay.appending(path: "blobs/\(blob)"), method: "GET", body: nil, token: pairing.deviceToken),
                  status == 200, let sealed = try? JSONDecoder().decode(Seal.Message.self, from: data),
                  let plain = try? Seal.open(sealed, key: keys.toApp) else { return nil }
            body.append(plain)
        }
        let url = URL.temporaryDirectory.appending(path: UUID().uuidString)
        guard (try? body.write(to: url)) != nil else { return nil }
        return url
    }

    private func discard(_ blobs: [String]) {
        guard let pairing, !blobs.isEmpty else { return }
        Task {
            for blob in blobs {
                _ = try? await call(pairing.relay.appending(path: "blobs/\(blob)"), method: "DELETE", body: nil, token: pairing.deviceToken)
            }
        }
    }

    private func acknowledge(_ seq: Int) {
        socket?.send(.string(#"{"ack":\#(seq)}"#)) { _ in }
    }

    // MARK: - Events

    @ObservationIgnored private var queued: [JSONValue] = []
    @ObservationIgnored private var debounce: Task<Void, Never>?
    @ObservationIgnored private var carrying: Task<Void, Never>?

    /// Collects events for a moment so a burst (an action, then the report of
    /// the card it changed) travels as one message.
    func queue(_ event: JSONValue) {
        guard pairing != nil else { return }
        queued.append(event)
        debounce?.cancel()
        debounce = Task { [weak self] in
            try? await Task.sleep(for: .milliseconds(300))
            guard !Task.isCancelled else { return }
            self?.sendQueued()
        }
    }

    /// Seals what is queued now, after what was queued before it: a capture
    /// still being uploaded holds the next events back, never the other way.
    private func sendQueued() {
        debounce?.cancel()
        debounce = nil
        guard !queued.isEmpty else { return }
        let events = queued
        queued = []
        let previous = carrying
        carrying = Task { [weak self] in
            await previous?.value
            guard let self else { return }
            self.send(await self.withCaptures(events))
        }
    }

    /// Reports name captures kept on the phone, and `files` local files; the
    /// agent gets each capture as a sealed JPEG blob on the relay instead, and
    /// each file as sealed blobs of a megabyte, which the file then leaves.
    private func withCaptures(_ events: [JSONValue]) async -> [JSONValue] {
        var carried: [JSONValue] = []
        for var event in events {
            if let key = event["capture"]?.string, let jpeg = capture?(key).flatMap({ UIImage(data: $0)?.jpegData(compressionQuality: 0.8) }),
               let blob = await upload(jpeg) {
                event = event.merging(.object(["capture": .object(["blob": .string(blob), "type": "image/jpeg"])]))
            }
            if let files = event["files"]?.object {
                var uploaded: [String: JSONValue] = [:]
                for (name, path) in files {
                    guard let path = path.string, let data = FileManager.default.contents(atPath: path) else { continue }
                    try? FileManager.default.removeItem(atPath: path)
                    var blobs: [JSONValue] = []
                    for start in stride(from: 0, to: max(data.count, 1), by: Self.blobChunk) {
                        guard let blob = await upload(data.subdata(in: start..<min(start + Self.blobChunk, data.count))) else { break }
                        blobs.append(.string(blob))
                    }
                    if blobs.count == (data.count + Self.blobChunk - 1) / Self.blobChunk {
                        uploaded[name] = .object(["blobs": .array(blobs), "size": .number(Double(data.count))])
                    }
                }
                event = event.merging(.object(["files": .null])).merging(.object(["files": .object(uploaded)]))
            }
            carried.append(event)
        }
        return carried
    }

    static let blobChunk = 1024 * 1024

    private func upload(_ plain: Data) async -> String? {
        guard let pairing, let keys,
              let sealed = try? Seal.seal(plain, seq: 0, key: keys.toAgent),
              let body = try? JSONEncoder().encode(sealed),
              let (data, status) = try? await call(pairing.relay.appending(path: "blobs"), method: "POST", body: nil, raw: body, token: pairing.deviceToken),
              status == 201 else { return nil }
        return (try? JSONValue.parse(data))?["blob"]?.string
    }

    /// What is only worth hearing now: sent late, a stop would end another turn.
    static let passing: Set<String> = ["stop", "refresh", "display"]

    /// Seals events for the agent and keeps them until the relay holds them.
    func send(_ events: [JSONValue]) {
        guard pairing != nil, let keys else { return }
        let passes = events.filter { Self.passing.contains($0["kind"]?.string ?? "") }
        let lasts = events.filter { !Self.passing.contains($0["kind"]?.string ?? "") }
        for (group, passing) in [(lasts, false), (passes, true)] where !group.isEmpty {
            for batch in Self.batches(group) {
                guard let message = try? Seal.seal(JSONValue.array(batch).data(), seq: PairingStore.nextOut(), key: keys.toAgent) else { continue }
                outbound.add(message, passing: passing)
            }
        }
        outbound.send()
    }

    /// The JSON a message carries at most, so that sealed it stays under the
    /// relay's 512 KB.
    static let messageBudget = 360 * 1024

    /// Events in order, as few messages as fit the budget; an event larger
    /// than it travels alone.
    static func batches(_ events: [JSONValue]) -> [[JSONValue]] {
        var batches: [[JSONValue]] = []
        var current: [JSONValue] = []
        var size = 0
        for event in events {
            let length = event.data().count + 1
            if !current.isEmpty, size + length > messageBudget {
                batches.append(current)
                current = []
                size = 0
            }
            current.append(event)
            size += length
        }
        return current.isEmpty ? batches : batches + [current]
    }

    private typealias Delivery = Outbound.Delivery

    private func deliver(_ message: Seal.Message) async -> Delivery {
        guard let pairing else { return .failed }
        guard let encoded = try? JSONEncoder().encode(message) else { return .refused("it could not be encoded") }
        if let socket, state == .connected, await send(encoded, seq: message.seq, on: socket) { return .held }
        return await post(encoded, to: pairing)
    }

    /// Whether the relay said it holds the message, over the WebSocket.
    private func send(_ encoded: Data, seq: Int, on socket: URLSessionWebSocketTask) async -> Bool {
        await withCheckedContinuation { continuation in
            stored[seq] = continuation
            socket.send(.string(#"{"send":\#(String(decoding: encoded, as: UTF8.self))}"#)) { [weak self] error in
                guard error != nil else { return }
                Task { @MainActor [weak self] in self?.settle(seq, false) }
            }
            Task { [weak self] in
                try? await Task.sleep(for: .seconds(5))
                self?.settle(seq, false)
            }
        }
    }

    private func settle(_ seq: Int, _ held: Bool) {
        stored.removeValue(forKey: seq)?.resume(returning: held)
    }

    private func post(_ message: Data, to pairing: Pairing) async -> Delivery {
        var request = URLRequest(url: pairing.relay.appending(path: "mailbox"))
        request.httpMethod = "POST"
        request.httpBody = message
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("Bearer \(pairing.deviceToken)", forHTTPHeaderField: "Authorization")
        guard let (data, response) = try? await URLSession.shared.data(for: request), let status = (response as? HTTPURLResponse)?.statusCode else { return .failed }
        switch status {
        case 200: return .held
        case 400, 413: return .refused((try? JSONValue.parse(data))?["error"]?.string ?? "status \(status)")
        default: return .failed
        }
    }

    /// What is queued leaves now, and this returns once the relay holds it, or
    /// after a few seconds: for an action run with the app in the background.
    func flush() async {
        sendQueued()
        await carrying?.value
        for _ in 0..<80 where !outbound.entries.isEmpty {
            try? await Task.sleep(for: .milliseconds(100))
        }
    }

    /// Reads the mailbox without the WebSocket, applies what waited and
    /// acknowledges it: for a silent push waking the app in the background.
    /// Whether anything new was applied.
    func fetchMailbox() async -> Bool {
        guard let pairing else { return false }
        let after = PairingStore.counters.integer(forKey: "relay.lastIn")
        guard let (data, status) = try? await call(pairing.relay.appending(path: "mailbox").appending(queryItems: [URLQueryItem(name: "after", value: String(after))]),
                                                   method: "GET", body: nil, token: pairing.deviceToken),
              status == 200, let value = try? JSONValue.parse(data), let messages = value["messages"]?.array else { return false }
        let sealed = messages.compactMap(Self.message)
        guard !sealed.isEmpty else { return false }
        waiting += sealed
        await catchUp()
        return true
    }

    /// The app is leaving: what is queued is sealed now, and what waits gets
    /// a moment to reach the relay before the connection goes.
    func leave() {
        sendQueued()
        if leaving == .invalid {
            leaving = UIApplication.shared.beginBackgroundTask(withName: "relay") { [weak self] in self?.left() }
            Task { [weak self] in
                await self?.carrying?.value
                for _ in 0..<80 where self?.outbound.entries.isEmpty == false {
                    try? await Task.sleep(for: .milliseconds(100))
                }
                self?.left()
            }
        }
        disconnect()
    }

    private func left() {
        guard leaving != .invalid else { return }
        UIApplication.shared.endBackgroundTask(leaving)
        leaving = .invalid
    }

    // MARK: - Push tokens

    /// The tokens the relay pushes to: notifications, and starting Live Activities.
    func updatePush(token: String? = nil, start: String? = nil) {
        var next = apns
        if let token { next.token = token }
        if let start { next.start = start }
        guard next != apns else { return }
        apns = next
        guard let pairing else { return }
        var body: [String: JSONValue] = ["environment": .string(Self.environment)]
        if let token = next.token { body["token"] = .string(token) }
        if let start = next.start { body["start_token"] = .string(start) }
        Task { _ = try? await call(pairing.relay.appending(path: "device/apns"), method: "POST", body: .object(body), token: pairing.deviceToken) }
    }

    // MARK: - HTTP

    private func call(_ url: URL, method: String, body: JSONValue?, raw: Data? = nil, token: String?) async throws -> (Data, Int) {
        var request = URLRequest(url: url)
        request.httpMethod = method
        if let payload = raw ?? body?.data() {
            request.httpBody = payload
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        }
        if let token { request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization") }
        let (data, response) = try await URLSession.shared.data(for: request)
        return (data, (response as? HTTPURLResponse)?.statusCode ?? 0)
    }

    private static func message(_ value: JSONValue) -> Seal.Message? {
        guard let seq = value["seq"]?.number.flatMap(Int.init(exactly:)), let nonce = value["nonce"]?.string, let box = value["box"]?.string else { return nil }
        return Seal.Message(seq: seq, nonce: nonce, box: box)
    }
}
