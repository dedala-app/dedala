// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import SwiftUI

/// The agent's face when he has no picture: no one in particular, a sphere
/// of light in the poster's colors. It breathes at rest, swirls with a ring
/// of light circling it while he thinks, and pulses while he speaks.
struct AgentOrb: View {
    var mood: AgentMood = .idle

    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    private static let palette: [Color] = [
        Color(red: 0.36, green: 0.44, blue: 0.98), Color(red: 0.60, green: 0.46, blue: 0.99), Color(red: 1.00, green: 0.64, blue: 0.56),
        Color(red: 0.38, green: 0.76, blue: 0.99), Color(red: 0.93, green: 0.90, blue: 1.00), Color(red: 0.98, green: 0.55, blue: 0.74),
        Color(red: 0.30, green: 0.36, blue: 0.86), Color(red: 0.50, green: 0.40, blue: 0.94), Color(red: 0.95, green: 0.50, blue: 0.62),
    ]

    var body: some View {
        TimelineView(.animation(paused: reduceMotion)) { context in
            let t = context.date.timeIntervalSinceReferenceDate
            let thinking = mood == .thinking
            let flow = t * (thinking ? 1.6 : 0.45)
            GeometryReader { proxy in
                let size = proxy.size.width
                ZStack {
                    MeshGradient(width: 3, height: 3, points: points(flow, reach: thinking ? 0.24 : 0.16), colors: Self.palette)
                        .hueRotation(.degrees(sin(t * (thinking ? 0.9 : 0.25)) * (thinking ? 28 : 14)))
                    Circle()
                        .fill(RadialGradient(colors: [.white.opacity(0.32), .white.opacity(0)], center: UnitPoint(x: 0.34, y: 0.26),
                                             startRadius: 0, endRadius: size * 0.34))
                        .blendMode(.plusLighter)
                    Circle()
                        .fill(RadialGradient(colors: [.clear, .black.opacity(0.18)], center: .center, startRadius: size * 0.32, endRadius: size * 0.52))
                    if thinking {
                        Circle()
                            .strokeBorder(AngularGradient(colors: [.white.opacity(0), .white.opacity(0.85), .white.opacity(0)], center: .center),
                                          lineWidth: max(1.5, size * 0.045))
                            .rotationEffect(.radians(t * 3.2))
                            .blendMode(.plusLighter)
                            .transition(.opacity)
                    }
                }
                .clipShape(.circle)
                .scaleEffect(scale(t))
            }
            .aspectRatio(1, contentMode: .fit)
        }
        .animation(.easeInOut(duration: 0.6), value: mood)
        .accessibilityHidden(true)
    }

    /// The mesh's inner points wander on slow loops; the corners stay put.
    private func points(_ flow: Double, reach: Double) -> [SIMD2<Float>] {
        func wobble(_ x: Double, _ y: Double, _ phase: Double, _ amount: Double) -> SIMD2<Float> {
            SIMD2(Float(x + cos(flow + phase) * amount), Float(y + sin(flow * 1.3 + phase) * amount))
        }
        return [
            [0, 0], wobble(0.5, 0, 1.0, reach * 0.4), [1, 0],
            wobble(0, 0.5, 2.1, reach * 0.4), wobble(0.5, 0.5, 0, reach), wobble(1, 0.5, 4.2, reach * 0.4),
            [0, 1], wobble(0.5, 1, 3.3, reach * 0.4), [1, 1],
        ].map { point in SIMD2(min(max(point.x, 0), 1), min(max(point.y, 0), 1)) }
    }

    private func scale(_ t: Double) -> CGFloat {
        guard !reduceMotion else { return 1 }
        switch mood {
        case .idle, .glancing, .winking, .surprised: return 1 + 0.02 * sin(t * 1.2)
        case .sleepy: return 1 + 0.015 * sin(t * 0.6)
        case .thinking: return 1 + 0.012 * sin(t * 2.6)
        case .speaking: return 1 + 0.045 * abs(sin(t * 7))
        }
    }
}

#Preview {
    HStack(spacing: 24) {
        AgentOrb(mood: .idle)
        AgentOrb(mood: .thinking)
        AgentOrb(mood: .speaking)
    }
    .frame(height: 96)
    .padding()
}
