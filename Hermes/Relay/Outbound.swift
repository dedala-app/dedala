// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import Foundation

/// Messages sealed for the agent, kept on disk until the relay holds each:
/// what you wrote offline, or as the connection died, still arrives, and
/// arrives once, since the relay and the plugin know a message by its number.
/// They go in order, one at a time: the next once the relay holds the one
/// before. What the relay cannot take now is tried again, a little later each time.
@MainActor
final class Outbound {
    enum Delivery: Equatable {
        case held, refused(String), failed
    }

    /// How a message goes to the relay now, from whoever holds the connection.
    var deliver: ((Seal.Message) async -> Delivery)?
    /// What went wrong with the last message, to show.
    var onProblem: ((String) -> Void)?
    var retries: [Duration] = [.seconds(2), .seconds(5), .seconds(15), .seconds(30), .seconds(60)]
    private var sending = false
    private var napping: Task<Void, Never>?

    struct Entry: Codable, Equatable {
        let message: Seal.Message
        let at: Date
        /// Only worth sending now: a stop, a refresh.
        let passing: Bool
    }

    /// The relay keeps a message this long; nothing older is worth sending.
    static let kept: TimeInterval = 7 * 24 * 3600
    static let passingKept: TimeInterval = 60

    private(set) var entries: [Entry]
    private let file: String

    init(file: String = "outbound.json") {
        self.file = file
        entries = Storage.load([Entry].self, from: file) ?? []
    }

    func add(_ message: Seal.Message, passing: Bool, at: Date = .now) {
        entries.append(Entry(message: message, at: at, passing: passing))
        save()
    }

    func remove(_ seq: Int) {
        let before = entries.count
        entries.removeAll { $0.message.seq == seq }
        if entries.count != before { save() }
    }

    func clear() {
        guard !entries.isEmpty else { return }
        entries = []
        save()
    }

    /// The next message to send, in the order they were numbered, once what is
    /// no longer worth sending is dropped.
    func next(at now: Date = .now) -> Entry? {
        let fresh = entries.filter { now.timeIntervalSince($0.at) < ($0.passing ? Self.passingKept : Self.kept) }
        if fresh.count != entries.count {
            entries = fresh
            save()
        }
        return entries.min { $0.message.seq < $1.message.seq }
    }

    /// Sends what waits, now: also cuts short the wait after a failure, when
    /// the connection is back.
    func send() {
        napping?.cancel()
        guard !sending, deliver != nil else { return }
        sending = true
        Task { [weak self] in
            await self?.drain()
            self?.sending = false
        }
    }

    private func drain() async {
        var failures = 0
        while let deliver, let entry = next() {
            switch await deliver(entry.message) {
            case .held:
                remove(entry.message.seq)
                failures = 0
            case .refused(let reason):
                remove(entry.message.seq)
                onProblem?("The relay refused a message: \(reason)")
            case .failed:
                onProblem?("A message has not reached the relay yet; it is sent again shortly.")
                let wait = retries[min(failures, retries.count - 1)]
                failures += 1
                let nap = Task { _ = try? await Task.sleep(for: wait) }
                napping = nap
                await nap.value
                napping = nil
            }
        }
    }

    private func save() {
        Storage.save(entries, to: file)
    }
}
