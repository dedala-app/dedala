// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import JavaScriptCore
import SwiftDraw
import SwiftUI

/// A face drawn with DiceBear's Avataaars (design by Pablo Stanley), made on
/// the phone: DiceBear writes the SVG in JavaScriptCore, SwiftDraw draws it.
/// To come alive, a face is drawn in layers stacked in DiceBear's own order:
/// what lies under (skin, clothes, nose), the mouth, the eyes, the eyebrows,
/// and what lies over them (hair, beard, glasses); the parts that move come
/// in a few variants each.
enum Avataaar {
    static let variants = [
        "mouth": ["twinkle", "default", "serious", "smile"],
        "eyes": ["default", "closed", "happy", "squint", "wink", "surprised"],
        "eyebrows": ["defaultNatural", "upDownNatural", "raisedExcitedNatural", "flatNatural", "raisedExcited"],
    ]
    nonisolated static let rest: [String: Any] = ["eyes": ["default"], "eyebrows": ["defaultNatural"], "mouth": ["twinkle"]]

    private static let queue = DispatchQueue(label: "avataaars", qos: .userInitiated)
    nonisolated(unsafe) private static var context: JSContext?
    nonisolated(unsafe) private static let cache = NSCache<NSString, UIImage>()

    /// A look's layers by name ("under", "over", "eyes.closed"…), drawn at a
    /// size in points.
    static func layers(_ look: AvatarLook, size: CGFloat, scale: CGFloat) async -> [String: UIImage] {
        let options = look.options
        let variants = Self.variants
        return await withCheckedContinuation { continuation in
            queue.async {
                let sources = call("avataaarLayers", options, variants)?.toDictionary() as? [String: String] ?? [:]
                var layers: [String: UIImage] = [:]
                for (name, svg) in sources {
                    if let image = draw(svg, size: size, scale: scale) { layers[name] = image }
                }
                continuation.resume(returning: layers)
            }
        }
    }

    /// A look whole and at rest, drawn at a size in points.
    static func face(_ look: AvatarLook, size: CGFloat, scale: CGFloat) async -> UIImage? {
        let options = look.options.merging(rest) { _, new in new }
        return await withCheckedContinuation { continuation in
            queue.async {
                continuation.resume(returning: call("avataaar", options)?.toString().flatMap { draw($0, size: size, scale: scale) })
            }
        }
    }

    nonisolated private static func draw(_ svg: String, size: CGFloat, scale: CGFloat) -> UIImage? {
        let key = "\(svg.hashValue)-\(svg.count)-\(size)-\(scale)" as NSString
        if let cached = cache.object(forKey: key) { return cached }
        guard let drawing = SVG(xml: svg) else { return nil }
        let image = drawing.rasterize(size: CGSize(width: size, height: size), scale: scale)
        cache.setObject(image, forKey: key)
        return image
    }

    nonisolated private static func call(_ function: String, _ arguments: Any...) -> JSValue? {
        if context == nil {
            guard let url = Bundle.main.url(forResource: "avataaars", withExtension: "js"),
                  let source = try? String(contentsOf: url, encoding: .utf8),
                  let made = JSContext() else { return nil }
            made.evaluateScript(source)
            context = made
        }
        guard let make = context?.objectForKeyedSubscript(function), !make.isUndefined else { return nil }
        return make.call(withArguments: arguments)
    }
}

/// How an Avataaars face holds itself at a moment: which mouth, eyes and
/// eyebrows show, where the eyes look and how high the eyebrows sit (in the
/// face's 280-unit drawing), and the head's sway. Worked out from the time
/// alone, with chance drawn from it, so every face lives on its own rhythm.
struct AvataaarPose: Equatable {
    var mouth = "twinkle"
    var eyes = "default"
    var eyebrows = "defaultNatural"
    var gaze = CGPoint.zero
    var lift: CGFloat = 0
    var bob: CGFloat = 0
    var tilt: Double = 0

    init(at t: TimeInterval, mood: AgentMood, still: Bool = false) {
        switch mood {
        case .idle:
            gaze = Self.saccade(at: t, every: 1.7, reach: CGSize(width: 4, height: 2.5), center: .zero, stay: 0.45)
            lift = gaze.y < -1 ? -1.5 : 0
            if let smiling = Self.moment(at: t, every: 23, chance: 0.4, lasting: 1.6, salt: 7) {
                mouth = "smile"
                eyes = "happy"
                eyebrows = "raisedExcitedNatural"
                lift = smiling < 0.2 ? -2 * smiling / 0.2 : -2
            } else if Self.moment(at: t, every: 9, chance: 0.35, lasting: 0.9, salt: 3) != nil {
                lift = -2.5
            }
        case .thinking:
            gaze = Self.saccade(at: t, every: 0.9, reach: CGSize(width: 1.2, height: 0.8), center: CGPoint(x: 4, y: -3.5), stay: 0)
            eyebrows = "upDownNatural"
            mouth = "serious"
            lift = -1
        case .speaking:
            gaze = Self.saccade(at: t, every: 1.3, reach: CGSize(width: 2.5, height: 1.5), center: .zero, stay: 0.5)
            mouth = Self.syllable(at: t) ? "default" : "twinkle"
            lift = Self.moment(at: t, every: 2.4, chance: 0.4, lasting: 0.5, salt: 11) != nil ? -2 : 0
        case .glancing:
            gaze = CGPoint(x: 3, y: -4)
            eyebrows = "raisedExcitedNatural"
            lift = -2
        case .sleepy:
            gaze = CGPoint(x: 0, y: 1.5)
            eyes = Self.moment(at: t, every: 6, chance: 0.6, lasting: 1.4, salt: 13) != nil ? "closed" : "squint"
            eyebrows = "flatNatural"
            mouth = "serious"
            lift = 1
        case .winking:
            eyes = "wink"
            mouth = "smile"
            eyebrows = "raisedExcitedNatural"
            lift = -2
        case .surprised:
            eyes = "surprised"
            eyebrows = "raisedExcited"
            lift = -3
        }
        if Self.blinking(at: t), eyes == "default" || eyes == "squint" {
            eyes = "closed"
        }
        if !still {
            let nodding = mood == .sleepy
            bob = nodding ? sin(t * 0.6) * 1.5 : sin(t * 1.3) * 0.8
            tilt = nodding ? sin(t * 0.35) * 3 : sin(t * 0.7) * (mood == .speaking ? 2.5 : 1.5) + Double(gaze.x) * 0.3
        }
    }

    /// A number in 0..<1 drawn from a slot of time and a salt.
    private static func chance(_ slot: Int, _ salt: Int) -> Double {
        var x = UInt64(bitPattern: Int64(slot)) &* 0x9E3779B97F4A7C15 &+ UInt64(salt) &* 0xBF58476D1CE4E5B9
        x ^= x >> 31
        x = x &* 0x94D049BB133111EB
        x ^= x >> 29
        return Double(x % 10_000) / 10_000
    }

    /// Quick jumps of the eyes to points around a center, held a while: a
    /// new point each slot, often the center itself.
    private static func saccade(at t: TimeInterval, every period: Double, reach: CGSize, center: CGPoint, stay: Double) -> CGPoint {
        func target(_ slot: Int) -> CGPoint {
            guard chance(slot, 1) >= stay else { return center }
            return CGPoint(x: center.x + (chance(slot, 2) * 2 - 1) * reach.width, y: center.y + (chance(slot, 3) * 2 - 1) * reach.height)
        }
        let slot = Int(floor(t / period))
        let shift = chance(slot, 4) * period * 0.6
        let current = t - shift < Double(slot) * period ? slot - 1 : slot
        let since = t - (Double(current) * period + chance(current, 4) * period * 0.6)
        let from = target(current - 1), to = target(current)
        let progress = min(1, max(0, since / 0.12))
        let eased = 1 - pow(1 - progress, 3)
        return CGPoint(x: from.x + (to.x - from.x) * eased, y: from.y + (to.y - from.y) * eased)
    }

    /// Whether the eyes are shut: a blink every 3 to 6 seconds, now and then two.
    private static func blinking(at t: TimeInterval) -> Bool {
        let slot = Int(floor(t / 4.5))
        let start = Double(slot) * 4.5 + chance(slot, 5) * 1.5
        let since = t - start
        if since >= 0, since < 0.13 { return true }
        return chance(slot, 6) < 0.15 && since >= 0.28 && since < 0.4
    }

    /// How far into a moment that comes now and then (0..<1), or nil.
    private static func moment(at t: TimeInterval, every period: Double, chance odds: Double, lasting duration: Double, salt: Int) -> Double? {
        let slot = Int(floor(t / period))
        guard chance(slot, salt) < odds else { return nil }
        let start = Double(slot) * period + chance(slot, salt + 1) * (period - duration)
        let since = t - start
        return since >= 0 && since < duration ? since / duration : nil
    }

    /// Whether the mouth is open while he speaks: syllables of irregular length.
    private static func syllable(at t: TimeInterval) -> Bool {
        let slot = Int(floor(t / 0.16))
        return chance(slot, 9) < 0.6
    }
}

/// The agent as an Avataaars face, alive: its eyes move around and blink,
/// its eyebrows rise, it smiles now and then, looks up with a raised eyebrow
/// while he thinks, and moves its mouth while he speaks; the head sways. It
/// glances up at the page, nods off when he is away or it is late, winks
/// when you send him a word, and raises its brows when you pull a page.
struct AvataaarFace: View {
    var mood: AgentMood = .idle
    let look: AvatarLook

    @Environment(\.displayScale) private var scale
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var layers: [String: UIImage] = [:]

    var body: some View {
        GeometryReader { proxy in
            let size = proxy.size.width
            let unit = size / 280
            TimelineView(.animation) { context in
                let pose = AvataaarPose(at: context.date.timeIntervalSinceReferenceDate, mood: mood, still: reduceMotion)
                if layers["under"] != nil {
                    ZStack {
                        layer("under")
                        layer("mouth.\(pose.mouth)")
                        layer("eyes.\(pose.eyes)")
                            .offset(x: pose.gaze.x * unit, y: pose.gaze.y * unit)
                        layer("eyebrows.\(pose.eyebrows)")
                            .offset(y: pose.lift * unit)
                        layer("over")
                    }
                    .offset(y: pose.bob * unit)
                    .rotationEffect(.degrees(pose.tilt), anchor: .bottom)
                } else {
                    AgentOrb(mood: mood)
                }
            }
            .task(id: Drawing(look: look, size: size)) {
                guard size > 0 else { return }
                layers = await Avataaar.layers(look, size: size, scale: scale)
            }
        }
        .aspectRatio(1, contentMode: .fit)
        .accessibilityHidden(true)
    }

    @ViewBuilder private func layer(_ name: String) -> some View {
        if let image = layers[name] {
            Image(uiImage: image)
                .resizable()
                .scaledToFit()
        }
    }

    private struct Drawing: Equatable {
        let look: AvatarLook
        let size: CGFloat
    }
}

/// A face as you make it in the editor: each part one of Avataaars' choices,
/// or none for the hair, the beard and the glasses.
struct AvatarLook: Codable, Equatable, Hashable {
    var skin: String
    var top: String?
    var hairColor: String
    var hatColor: String
    var facialHair: String?
    var facialHairColor: String
    var accessories: String?
    var accessoriesColor: String
    var clothing: String
    var clothesColor: String
    var clothingGraphic: String

    static let skins = ["ffdbb4", "edb98a", "d08b5b", "ae5d29", "614335"]
    static let hairs = ["shortFlat", "shortWaved", "shortCurly", "shortRound", "theCaesar", "theCaesarAndSidePart", "sides", "shavedSides",
                        "frizzle", "shaggy", "shaggyMullet", "dreads01", "dreads02", "fro", "froBand", "bob", "bun", "curly", "curvy",
                        "dreads", "frida", "bigHair", "longButNotTooLong", "miaWallace", "straight01", "straight02", "straightAndStrand",
                        "hat", "winterHat1", "winterHat02", "winterHat03", "winterHat04", "hijab", "turban"]
    static let headwear: Set = ["hat", "winterHat1", "winterHat02", "winterHat03", "winterHat04", "hijab", "turban"]
    static let hairColors = ["2c1b18", "4a312c", "724133", "a55728", "b58143", "d6b370", "ecdcbf", "e8e1e1", "c93305", "f59797"]
    static let beards = ["beardLight", "beardMedium", "beardMajestic", "moustacheFancy", "moustacheMagnum"]
    static let glasses = ["prescription01", "prescription02", "round", "wayfarers", "kurt", "sunglasses", "eyepatch"]
    static let clothes = ["shirtCrewNeck", "shirtScoopNeck", "shirtVNeck", "collarAndSweater", "hoodie", "blazerAndShirt", "blazerAndSweater",
                          "overall", "graphicShirt"]
    static let graphics = ["bat", "bear", "cumbia", "deer", "diamond", "hola", "pizza", "resist", "skull", "skullOutline"]
    static let fabrics = ["262e33", "3c4f5c", "929598", "e6e6e6", "ffffff", "25557c", "5199e4", "65c9ff", "b1e2ff", "a7ffc4", "ffffb1",
                          "ffafb9", "ff488e", "ff5c5c"]

    var options: [String: Any] {
        var options: [String: Any] = [
            "skinColor": [skin], "hairColor": [hairColor], "hatColor": [hatColor], "facialHairColor": [facialHairColor],
            "accessoriesColor": [accessoriesColor], "clothing": [clothing], "clothesColor": [clothesColor],
            "clothingGraphic": [clothingGraphic], "topProbability": top == nil ? 0 : 100,
            "facialHairProbability": facialHair == nil ? 0 : 100, "accessoriesProbability": accessories == nil ? 0 : 100,
        ]
        if let top { options["top"] = [top] }
        if let facialHair { options["facialHair"] = [facialHair] }
        if let accessories { options["accessories"] = [accessories] }
        return options
    }

    /// The face a name gets until you make one: always the same for the
    /// same name, with no glasses.
    static func derived(from seed: String) -> AvatarLook {
        var hash: UInt64 = 0xcbf29ce484222325
        for byte in seed.utf8 {
            hash = (hash ^ UInt64(byte)) &* 0x100000001b3
        }
        var generator = Seeded(state: hash)
        return random(using: &generator, glasses: false)
    }

    static func random(glasses: Bool = true) -> AvatarLook {
        var generator = SystemRandomNumberGenerator()
        return random(using: &generator, glasses: glasses)
    }

    private static func random<G: RandomNumberGenerator>(using generator: inout G, glasses withGlasses: Bool) -> AvatarLook {
        AvatarLook(
            skin: skins.randomElement(using: &generator)!,
            top: hairs.filter { !headwear.contains($0) }.randomElement(using: &generator),
            hairColor: hairColors.prefix(7).randomElement(using: &generator)!,
            hatColor: fabrics.randomElement(using: &generator)!,
            facialHair: Int.random(in: 0..<5, using: &generator) == 0 ? beards.randomElement(using: &generator) : nil,
            facialHairColor: hairColors.prefix(7).randomElement(using: &generator)!,
            accessories: withGlasses && Bool.random(using: &generator) ? glasses.prefix(4).randomElement(using: &generator) : nil,
            accessoriesColor: "262e33",
            clothing: clothes.dropLast().randomElement(using: &generator)!,
            clothesColor: fabrics.randomElement(using: &generator)!,
            clothingGraphic: graphics.randomElement(using: &generator)!
        )
    }

    /// The look as the profile store holds it: every part, `none` for no
    /// hair, beard or glasses.
    var json: JSONValue {
        .object([
            "skin": .string(skin), "top": .string(top ?? Self.none), "hairColor": .string(hairColor), "hatColor": .string(hatColor),
            "facialHair": .string(facialHair ?? Self.none), "facialHairColor": .string(facialHairColor),
            "accessories": .string(accessories ?? Self.none), "accessoriesColor": .string(accessoriesColor),
            "clothing": .string(clothing), "clothesColor": .string(clothesColor), "clothingGraphic": .string(clothingGraphic),
        ])
    }

    static let none = "none"

    private struct Seeded: RandomNumberGenerator {
        var state: UInt64

        mutating func next() -> UInt64 {
            state = state &* 6364136223846793005 &+ 1442695040888963407
            return state ^ (state >> 33)
        }
    }
}

extension AvatarLook {
    /// The parts the profile store gives, over `base` for those it leaves out
    /// or names wrongly.
    init(_ value: JSONValue, over base: AvatarLook) {
        func part(_ key: String, _ known: [String], _ fallback: String) -> String {
            value[key]?.string.flatMap { known.contains($0) ? $0 : nil } ?? fallback
        }
        func optional(_ key: String, _ known: [String], _ fallback: String?) -> String? {
            guard let given = value[key]?.string else { return fallback }
            return given == Self.none ? nil : known.contains(given) ? given : fallback
        }
        self.init(skin: part("skin", Self.skins, base.skin), top: optional("top", Self.hairs, base.top),
                  hairColor: part("hairColor", Self.hairColors, base.hairColor), hatColor: part("hatColor", Self.fabrics, base.hatColor),
                  facialHair: optional("facialHair", Self.beards, base.facialHair),
                  facialHairColor: part("facialHairColor", Self.hairColors, base.facialHairColor),
                  accessories: optional("accessories", Self.glasses, base.accessories),
                  accessoriesColor: part("accessoriesColor", Self.fabrics, base.accessoriesColor),
                  clothing: part("clothing", Self.clothes, base.clothing), clothesColor: part("clothesColor", Self.fabrics, base.clothesColor),
                  clothingGraphic: part("clothingGraphic", Self.graphics, base.clothingGraphic))
    }
}
