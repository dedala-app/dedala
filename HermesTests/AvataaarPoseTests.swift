// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import Foundation
import Testing
@testable import Hermes

/// An Avataaars face lives on its own: it blinks, its eyes wander within
/// the face, it looks up while thinking, and its mouth moves while speaking.
@Suite("Avataaars pose")
struct AvataaarPoseTests {
    let minute = stride(from: 1_000.0, to: 1_060.0, by: 0.02).map { $0 }

    @Test func atRestItBlinksAndLooksAroundWithinTheFace() {
        let poses = minute.map { AvataaarPose(at: $0, mood: .idle) }
        let blinks = zip(poses, poses.dropFirst()).filter { $0.eyes != "closed" && $1.eyes == "closed" }.count
        #expect((8...25).contains(blinks))
        #expect(poses.allSatisfy { abs($0.gaze.x) <= 4.01 && abs($0.gaze.y) <= 2.51 })
        #expect(Set(poses.map { Int($0.gaze.x.rounded()) }).count > 3)
    }

    @Test func thinkingItLooksUpWithAnEyebrowRaised() {
        let poses = minute.map { AvataaarPose(at: $0, mood: .thinking) }
        #expect(poses.allSatisfy { $0.gaze.y < -2 && $0.eyebrows == "upDownNatural" && $0.mouth == "serious" })
    }

    @Test func speakingItsMouthOpensAndCloses() {
        let mouths = minute.map { AvataaarPose(at: $0, mood: .speaking).mouth }
        let open = mouths.filter { $0 == "default" }.count
        #expect(open > mouths.count / 4 && open < mouths.count * 3 / 4)
    }

    @Test func stillItDoesNotSway() {
        #expect(minute.allSatisfy { AvataaarPose(at: $0, mood: .idle, still: true).tilt == 0 })
    }
}
