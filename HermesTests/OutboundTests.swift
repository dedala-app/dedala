// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import Foundation
import Testing
@testable import Hermes

/// Messages for the agent wait on disk until the relay holds them.
@MainActor
@Suite("Outbound")
struct OutboundTests {
    func message(_ seq: Int) -> Seal.Message {
        Seal.Message(seq: seq, nonce: "n\(seq)", box: "b\(seq)")
    }

    func fresh() -> (Outbound, String) {
        let file = "outbound-\(UUID().uuidString).json"
        return (Outbound(file: file), file)
    }

    @Test func messagesGoInTheOrderTheyWereNumbered() {
        let (outbound, _) = fresh()
        outbound.add(message(7), passing: false)
        outbound.add(message(5), passing: false)
        outbound.add(message(6), passing: false)
        #expect(outbound.next()?.message.seq == 5)
        outbound.remove(5)
        #expect(outbound.next()?.message.seq == 6)
        outbound.remove(6)
        outbound.remove(7)
        #expect(outbound.next() == nil)
    }

    @Test func whatWaitsSurvivesARestart() {
        let (outbound, file) = fresh()
        outbound.add(message(1), passing: false)
        outbound.add(message(2), passing: false)
        outbound.remove(1)
        let again = Outbound(file: file)
        #expect(again.entries.map(\.message) == [message(2)])
        again.clear()
        #expect(Outbound(file: file).entries.isEmpty)
    }

    @Test func aStopIsNotSentLate() {
        let (outbound, _) = fresh()
        let then = Date.now.addingTimeInterval(-120)
        outbound.add(message(1), passing: true, at: then)
        outbound.add(message(2), passing: false, at: then)
        #expect(outbound.next()?.message.seq == 2)
        #expect(outbound.entries.count == 1)
    }

    @Test func aMessageOlderThanTheRelayKeepsIsDropped() {
        let (outbound, _) = fresh()
        outbound.add(message(1), passing: false, at: Date.now.addingTimeInterval(-Outbound.kept - 60))
        #expect(outbound.next() == nil)
    }

    func until(_ condition: @escaping () -> Bool) async {
        for _ in 0..<200 where !condition() {
            try? await Task.sleep(for: .milliseconds(10))
        }
    }

    @Test func aMessageIsSentAgainUntilTheRelayHoldsItThenTheNext() async {
        let (outbound, _) = fresh()
        outbound.retries = [.milliseconds(10)]
        var tried: [Int] = []
        var problems: [String] = []
        outbound.onProblem = { problems.append($0) }
        outbound.deliver = { message in
            tried.append(message.seq)
            return tried.count < 3 ? .failed : .held
        }
        outbound.add(message(1), passing: false)
        outbound.add(message(2), passing: false)
        outbound.send()
        await until { outbound.entries.isEmpty }
        #expect(tried == [1, 1, 1, 2])
        #expect(problems.count == 2)
    }

    @Test func aMessageTheRelayRefusesDoesNotBlockTheOthers() async {
        let (outbound, _) = fresh()
        var held: [Int] = []
        var problems: [String] = []
        outbound.onProblem = { problems.append($0) }
        outbound.deliver = { message in
            if message.seq == 1 { return .refused("A message is at most 512KB") }
            held.append(message.seq)
            return .held
        }
        outbound.add(message(1), passing: false)
        outbound.add(message(2), passing: false)
        outbound.send()
        await until { outbound.entries.isEmpty }
        #expect(held == [2] && problems == ["The relay refused a message: A message is at most 512KB"])
    }

    @Test func comingBackOnlineSendsAtOnce() async {
        let (outbound, _) = fresh()
        outbound.retries = [.seconds(60)]
        var online = false
        var held: [Int] = []
        outbound.deliver = { message in
            guard online else { return .failed }
            held.append(message.seq)
            return .held
        }
        outbound.add(message(1), passing: false)
        outbound.send()
        await until { false == outbound.entries.isEmpty && held.isEmpty }
        try? await Task.sleep(for: .milliseconds(50))
        online = true
        outbound.send()
        await until { outbound.entries.isEmpty }
        #expect(held == [1])
    }
}

