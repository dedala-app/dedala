// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import SwiftUI
import UIKit

/// The SF Symbols the agent's layout twin meets, measured as this phone draws
/// them: Apple's symbol data cannot ship with the agent, so the twin asks for
/// each name at the point sizes it needs. Per size, every weight and scale
/// gives the image's width, height and baseline in pixels and the aspect a
/// resizable one keeps; a picture of each name goes with them for the twin's
/// drawings. A name iOS does not know is null.
enum SymbolMetrics {
    static let weights: [(UIImage.SymbolWeight, Font.Weight)] = [
        (.ultraLight, .ultraLight), (.thin, .thin), (.light, .light), (.regular, .regular), (.medium, .medium),
        (.semibold, .semibold), (.bold, .bold), (.heavy, .heavy), (.black, .black),
    ]
    static let scales: [(UIImage.SymbolScale, Image.Scale)] = [(.small, .small), (.medium, .medium), (.large, .large)]

    static func measured(_ op: JSONValue) async -> JSONValue {
        var symbols: [String: JSONValue] = [:]
        for (name, sizes) in op["symbols"]?.object ?? [:] {
            guard UIImage(systemName: name) != nil else {
                symbols[name] = .null
                continue
            }
            var bySize: [String: JSONValue] = [:]
            for size in sizes.array?.compactMap(\.number) ?? [] {
                bySize[String(size)] = .array(weights.flatMap { weight in scales.map { scale in measured(name, size, weight, scale) } })
                await Task.yield()
            }
            symbols[name] = .object(["sizes": .object(bySize), "images": .object(Dictionary(uniqueKeysWithValues: drawn.map { label, weight in (label, image(name, weight)) }))])
        }
        return .object(["kind": .string("symbols"), "os": .string(UIDevice.current.systemVersion), "symbols": .object(symbols)])
    }

    /// [width, height, baseline] in pixels as UIImage has them, and the aspect
    /// SwiftUI gives the symbol made resizable.
    private static func measured(_ name: String, _ size: Double, _ weight: (UIImage.SymbolWeight, Font.Weight), _ scale: (UIImage.SymbolScale, Image.Scale)) -> JSONValue {
        let configuration = UIImage.SymbolConfiguration(pointSize: size, weight: weight.0, scale: scale.0)
        guard let image = UIImage(systemName: name, withConfiguration: configuration) else { return .null }
        let pixels = [image.size.width, image.size.height, image.baselineOffsetFromBottom ?? 0].map { JSONValue.number(($0 * 3).rounded()) }
        let host = UIHostingController(rootView: Image(systemName: name).resizable().aspectRatio(contentMode: .fit)
            .font(.system(size: size, weight: weight.1)).imageScale(scale.1))
        let fitted = host.sizeThatFits(in: CGSize(width: 300, height: 300))
        return .array(pixels + [fitted.height > 0 ? .number(fitted.width / fitted.height) : .null])
    }

    static let drawn: [(String, UIImage.SymbolWeight)] = [("regular", .regular), ("semibold", .semibold), ("bold", .bold)]

    /// The symbol at 17 points as a PNG mask four times its size, for the
    /// pictures the agent's twin draws of a card, with its size in points.
    private static func image(_ name: String, _ weight: UIImage.SymbolWeight) -> JSONValue {
        guard let symbol = UIImage(systemName: name, withConfiguration: UIImage.SymbolConfiguration(pointSize: 17, weight: weight)) else { return .null }
        let format = UIGraphicsImageRendererFormat()
        format.scale = 4
        let png = UIGraphicsImageRenderer(size: symbol.size, format: format).pngData { _ in
            symbol.withTintColor(.black).draw(at: .zero)
        }
        return .object(["png": .string(png.base64EncodedString()), "size": .array([.number(symbol.size.width), .number(symbol.size.height)])])
    }
}
