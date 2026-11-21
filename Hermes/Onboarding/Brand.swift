// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import SwiftUI

/// Dedala's own colours, from its icon: a warm white ground, the bronze of the
/// mark, darkened where it carries text, and their dark counterparts.
enum Brand {
    static let ground = dynamic(light: 0xFBF8F3, dark: 0x16120F)
    static let surface = dynamic(light: 0xFFFFFF, dark: 0x231D18)
    static let well = dynamic(light: 0xF1EBE2, dark: 0x2B241E)
    static let line = dynamic(light: 0xF0EAE1, dark: 0x3A312A)
    static let ink = dynamic(light: 0x1F1A16, dark: 0xF6F1EA)
    static let quiet = dynamic(light: 0x6B6157, dark: 0xB7AB9E)
    static let bronze = dynamic(light: 0xA4500F, dark: 0xE38D4B)
    /// Behind white text: deep enough in both appearances.
    static let fill = dynamic(light: 0xA4500F, dark: 0xA9541A)
    static let mark = Color(hex: 0xC8651A)
    static let tint = dynamic(light: 0xF6E9DC, dark: 0x3A2717)

    private static func dynamic(light: UInt32, dark: UInt32) -> Color {
        Color(UIColor { $0.userInterfaceStyle == .dark ? UIColor(hex: dark) : UIColor(hex: light) })
    }
}

extension Color {
    init(hex: UInt32) {
        self.init(UIColor(hex: hex))
    }
}

extension UIColor {
    convenience init(hex: UInt32) {
        self.init(red: CGFloat(hex >> 16 & 0xFF) / 255, green: CGFloat(hex >> 8 & 0xFF) / 255, blue: CGFloat(hex & 0xFF) / 255, alpha: 1)
    }
}

/// The icon's mark: a bronze disc in its ring, with the badge cut out at its corner.
struct DedalaMark: View {
    var size: CGFloat = 96

    var body: some View {
        let unit = size / 96
        ZStack {
            Circle()
                .stroke(Brand.mark.opacity(0.28), lineWidth: 5 * unit)
                .frame(width: 80 * unit, height: 80 * unit)
            Circle()
                .fill(Brand.mark)
                .frame(width: 60 * unit, height: 60 * unit)
            Circle()
                .fill(Brand.mark)
                .frame(width: 24 * unit, height: 24 * unit)
                .padding(5 * unit)
                .background(Circle().fill(Brand.surface))
                .offset(x: 26 * unit, y: -26 * unit)
        }
        .frame(width: size, height: size)
        .accessibilityHidden(true)
    }
}

/// The wide button that moves the flow on.
struct BrandButton: View {
    let title: String
    var busy = false
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            ZStack {
                Text(title).opacity(busy ? 0 : 1)
                if busy { ProgressView().tint(.white) }
            }
            .font(.body.weight(.semibold))
            .foregroundStyle(.white)
            .frame(maxWidth: .infinity, minHeight: 34)
        }
        .buttonStyle(.glassProminent)
        .tint(Brand.fill)
        .controlSize(.large)
        .disabled(busy)
    }
}

/// A quieter way on, under the main button.
struct BrandLink: View {
    let title: String
    let action: () -> Void

    var body: some View {
        Button(title, action: action)
            .font(.body.weight(.medium))
            .foregroundStyle(Brand.bronze)
            .frame(maxWidth: .infinity, minHeight: 44)
    }
}

/// A command to run where the agent lives, set in a well.
struct ShellCommand: View {
    let text: String

    var body: some View {
        Text(text)
            .font(.footnote.monospaced().weight(.medium))
            .foregroundStyle(Brand.ink)
            .padding(.horizontal, 12)
            .padding(.vertical, 9)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(Brand.well, in: .rect(cornerRadius: 10, style: .continuous))
            .textSelection(.enabled)
    }
}

/// A picture drawn at one size, scaled down to the room it is given, never up.
struct Fitted<Content: View>: View {
    let size: CGSize
    @ViewBuilder let content: Content

    var body: some View {
        GeometryReader { proxy in
            let scale = min(1, proxy.size.width / size.width, proxy.size.height / size.height)
            content
                .frame(width: size.width, height: size.height)
                .scaleEffect(scale)
                .frame(width: proxy.size.width, height: proxy.size.height)
        }
    }
}

/// Content that stands as laid out when it fits the screen, and scrolls when
/// it does not: a short screen, or a large text size.
struct Fitting<Content: View>: View {
    @ViewBuilder let content: Content

    var body: some View {
        ViewThatFits(in: .vertical) {
            content
            ScrollView { content }
                .scrollBounceBehavior(.basedOnSize)
        }
    }
}
