// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

#if DEBUG
import UIKit

/// Lays text out the way `Text` does, for the layout twin's calibration: the string
/// drawing engine's line count and size, and TextKit's line strings.
enum TextLines {
    struct Case: Decodable {
        let text: String
        let size: Double?
        let weight: String?
        let width: Double?
        let lineLimit: Int?
        let hyphenate: Bool?
        let symbol: Bool?
        let metrics: Bool?
        let scale: String?
        let design: String?
        let monospacedDigit: Bool?
        let markdown: Bool?
        let renderers: Int?
        let glyph: Bool?
        let runs: Bool?
        let category: String?
    }

    static func measure(_ body: Data) -> Data {
        guard let cases = try? JSONDecoder().decode([Case].self, from: body) else {
            return Data(#"{"error":"body is a list of {text, size, weight, width, lineLimit}"}"#.utf8)
        }
        let results = cases.map(measure)
        return (try? JSONSerialization.data(withJSONObject: results)) ?? Data()
    }

    private static func font(_ size: Double, _ weight: String?, _ design: String? = nil) -> UIFont {
        let weights: [String: UIFont.Weight] = ["ultraLight": .ultraLight, "thin": .thin, "light": .light, "regular": .regular, "medium": .medium, "semibold": .semibold, "bold": .bold, "heavy": .heavy, "black": .black]
        let designs: [String: UIFontDescriptor.SystemDesign] = ["rounded": .rounded, "serif": .serif, "monospaced": .monospaced]
        let base = UIFont.systemFont(ofSize: size, weight: weights[weight ?? "regular"] ?? .regular)
        guard let design = design.flatMap({ designs[$0] }), let descriptor = base.fontDescriptor.withDesign(design) else { return base }
        return UIFont(descriptor: descriptor, size: size)
    }

    private static func attributed(_ c: Case, mode: NSLineBreakMode) -> NSAttributedString {
        let style = NSMutableParagraphStyle()
        style.lineBreakStrategy = .standard
        style.lineBreakMode = mode
        style.hyphenationFactor = 0
        style.setValue(1, forKey: "secondaryLineBreakMode")
        var f = font(c.size ?? 17, c.weight, c.design)
        if c.monospacedDigit == true {
            let weights: [String: UIFont.Weight] = ["ultraLight": .ultraLight, "thin": .thin, "light": .light, "regular": .regular, "medium": .medium, "semibold": .semibold, "bold": .bold, "heavy": .heavy, "black": .black]
            f = UIFont.monospacedDigitSystemFont(ofSize: c.size ?? 17, weight: weights[c.weight ?? "regular"] ?? .regular)
        }
        if c.markdown == true, let parsed = try? AttributedString(markdown: c.text, options: .init(interpretedSyntax: .inlineOnlyPreservingWhitespace)) {
            let string = NSMutableAttributedString(parsed)
            string.addAttributes([.font: f, .paragraphStyle: style], range: NSRange(location: 0, length: string.length))
            return string
        }
        return NSAttributedString(string: c.text, attributes: [.font: f, .paragraphStyle: style])
    }

    private static func hyphenation(_ text: String) -> [Int] {
        let string = text as CFString
        let locale = CFLocaleCopyCurrent()
        let range = CFRange(location: 0, length: CFStringGetLength(string))
        var points: [Int] = []
        var index = range.length
        while index > 0 {
            let location = CFStringGetHyphenationLocationBeforeIndex(string, index, range, 0, locale, nil)
            if location == kCFNotFound || location <= 0 { break }
            points.append(location)
            index = location
        }
        return points.reversed()
    }

    private static func symbol(_ c: Case) -> [String: Any] {
        let weights: [String: UIImage.SymbolWeight] = ["ultraLight": .ultraLight, "thin": .thin, "light": .light, "regular": .regular, "medium": .medium, "semibold": .semibold, "bold": .bold, "heavy": .heavy, "black": .black]
        let scales: [String: UIImage.SymbolScale] = ["small": .small, "medium": .medium, "large": .large]
        let configuration = UIImage.SymbolConfiguration(pointSize: c.size ?? 17, weight: weights[c.weight ?? "regular"] ?? .regular, scale: scales[c.scale ?? "medium"] ?? .medium)
        guard let image = UIImage(systemName: c.text, withConfiguration: configuration) else {
            return ["text": c.text, "error": "no such symbol"]
        }
        return ["text": c.text, "size": c.size ?? 17, "weight": c.weight ?? "regular", "scale": c.scale ?? "medium", "w": image.size.width, "h": image.size.height, "baseline": image.baselineOffsetFromBottom, "capInsets": [image.alignmentRectInsets.top, image.alignmentRectInsets.left, image.alignmentRectInsets.bottom, image.alignmentRectInsets.right]]
    }

    /// The symbol as CoreUI hands it to SwiftUI: `CUINamedVectorGlyph`, whose baseline offset, cap height,
    /// alignment rect and content bounds are what `Image.LayoutMetrics` is made of.
    private static func glyphValues(_ found: AnyObject, _ out: inout [String: Any]) {
        for key in ["baselineOffset", "capHeight", "alignmentRect", "contentBounds"] {
            guard found.responds(to: NSSelectorFromString(key)) else { continue }
            let value = found.value(forKey: key)
            if let rect = value as? NSValue, String(cString: rect.objCType).hasPrefix("{CGRect") {
                let r = rect.cgRectValue
                out[key] = [r.origin.x, r.origin.y, r.size.width, r.size.height]
            } else if let number = value as? NSNumber {
                out[key] = number.doubleValue
            }
        }
    }

    /// The CoreUI vector glyph UIKit resolved for a symbol image, through the image's private accessor: its baseline
    /// offset, cap height, alignment rect and content bounds are what SwiftUI's `Image.LayoutMetrics` is made of.
    private static func glyph(_ c: Case) -> [String: Any] {
        let weights: [String: UIImage.SymbolWeight] = ["ultraLight": .ultraLight, "thin": .thin, "light": .light, "regular": .regular, "medium": .medium, "semibold": .semibold, "bold": .bold, "heavy": .heavy, "black": .black]
        let scales: [String: UIImage.SymbolScale] = ["small": .small, "medium": .medium, "large": .large]
        let configuration = UIImage.SymbolConfiguration(pointSize: c.size ?? 17, weight: weights[c.weight ?? "regular"] ?? .regular, scale: scales[c.scale ?? "medium"] ?? .medium)
        guard let image = UIImage(systemName: c.text, withConfiguration: configuration) else { return ["text": c.text, "error": "no such symbol"] }
        guard image.responds(to: NSSelectorFromString("_vectorGlyph")), let found = image.value(forKey: "_vectorGlyph") as AnyObject? else {
            return ["text": c.text, "error": "no vector glyph"]
        }
        var out: [String: Any] = ["text": c.text, "size": c.size ?? 17, "weight": c.weight ?? "regular", "scale": c.scale ?? "medium", "w": image.size.width, "h": image.size.height, "baseline": image.baselineOffsetFromBottom]
        glyphValues(found, &out)
        return out
    }

    /// The fonts CoreText actually used for a string: each run's font name and character range, from a CTLine.
    private static func runs(_ c: Case) -> [String: Any] {
        let line = CTLineCreateWithAttributedString(attributed(c, mode: .byWordWrapping))
        var out: [[String: Any]] = []
        for run in (CTLineGetGlyphRuns(line) as NSArray) {
            let run = run as! CTRun
            let attributes = CTRunGetAttributes(run) as NSDictionary
            let font = attributes[kCTFontAttributeName as String] as! CTFont
            let range = CTRunGetStringRange(run)
            out.append(["font": CTFontCopyPostScriptName(font) as String, "family": CTFontCopyFamilyName(font) as String, "size": CTFontGetSize(font), "location": range.location, "length": range.length, "width": CTRunGetTypographicBounds(run, CFRange(location: 0, length: 0), nil, nil, nil), "ascent": CTFontGetAscent(font), "descent": CTFontGetDescent(font)])
        }
        return ["text": c.text, "runs": out, "width": CTLineGetTypographicBounds(line, nil, nil, nil)]
    }

    private static func metrics(_ c: Case) -> [String: Any] {
        let f = font(c.size ?? 17, c.weight, c.design)
        return ["size": c.size ?? 17, "weight": c.weight ?? "regular", "ascender": f.ascender, "descender": f.descender, "lineHeight": f.lineHeight, "capHeight": f.capHeight, "xHeight": f.xHeight, "leading": f.leading]
    }

    /// Each text style at a content size category, and what `UIFontMetrics` makes of the body style's values there:
    /// `text` is a list of values to scale, as numbers.
    private static func category(_ c: Case) -> [String: Any] {
        let categories: [String: UIContentSizeCategory] = ["xSmall": .extraSmall, "small": .small, "medium": .medium, "large": .large, "xLarge": .extraLarge, "xxLarge": .extraExtraLarge, "xxxLarge": .extraExtraExtraLarge, "accessibility1": .accessibilityMedium, "accessibility2": .accessibilityLarge, "accessibility3": .accessibilityExtraLarge, "accessibility4": .accessibilityExtraExtraLarge, "accessibility5": .accessibilityExtraExtraExtraLarge]
        let styles: [String: UIFont.TextStyle] = ["largeTitle": .largeTitle, "title": .title1, "title2": .title2, "title3": .title3, "headline": .headline, "body": .body, "callout": .callout, "subheadline": .subheadline, "footnote": .footnote, "caption": .caption1, "caption2": .caption2]
        let traits = UITraitCollection(preferredContentSizeCategory: categories[c.category ?? "large"] ?? .large)
        var fonts: [String: Any] = [:]
        for (name, style) in styles {
            let f = UIFont.preferredFont(forTextStyle: style, compatibleWith: traits)
            fonts[name] = ["size": f.pointSize, "lineHeight": f.lineHeight, "leading": f.leading, "ascender": f.ascender, "descender": f.descender]
        }
        let values = c.text.split(separator: ",").compactMap { Double($0.trimmingCharacters(in: .whitespaces)) }
        var scaled: [String: Any] = [:]
        for (name, style) in styles {
            scaled[name] = values.map { UIFontMetrics(forTextStyle: style).scaledValue(for: $0, compatibleWith: traits) }
        }
        return ["category": c.category ?? "large", "fonts": fonts, "values": values, "scaled": scaled]
    }

    private static func measure(_ c: Case) -> [String: Any] {
        if c.category != nil {
            return category(c)
        }
        if c.symbol == true {
            return symbol(c)
        }
        if c.glyph == true {
            return glyph(c)
        }
        if c.runs == true {
            return runs(c)
        }
        if c.metrics == true {
            return metrics(c)
        }
        if c.hyphenate == true {
            return ["text": c.text, "points": hyphenation(c.text), "locale": Locale.current.identifier]
        }
        guard let width = c.width, let size = c.size else { return ["text": c.text, "error": "size and width"] }
        var out: [String: Any] = ["text": c.text, "width": width, "size": size, "weight": c.weight ?? "regular"]
        if let limit = c.lineLimit { out["lineLimit"] = limit }
        let context = NSStringDrawingContext()
        context.minimumScaleFactor = 0
        context.setValue(c.lineLimit ?? 0, forKey: "maximumNumberOfLines")
        context.setValue(true, forKey: "cachesLayout")
        context.setValue(true, forKey: "wantsNumberOfLineFragments")
        context.setValue(true, forKey: "wrapsForTruncationMode")
        if let renderers = c.renderers, context.responds(to: NSSelectorFromString("setActiveRenderers:")) {
            context.setValue(renderers, forKey: "activeRenderers")
            out["renderers"] = renderers
        }
        let drawn = attributed(c, mode: .byTruncatingTail)
        out["links"] = drawn.attribute(.link, at: 0, longestEffectiveRange: nil, in: NSRange(location: 0, length: drawn.length)) != nil || hasLink(drawn)
        let options = NSStringDrawingOptions(rawValue: NSStringDrawingOptions.usesLineFragmentOrigin.rawValue | (1 << 20))
        let rect = drawn.boundingRect(with: CGSize(width: width, height: CGFloat.greatestFiniteMagnitude), options: options, context: context)
        out["w"] = rect.width
        out["h"] = rect.height
        out["lines"] = context.value(forKey: "numberOfLineFragments") ?? 0
        out["truncated"] = context.value(forKey: "hasTruncatedRanges") ?? false

        let storage = NSTextContentStorage()
        let manager = NSTextLayoutManager()
        storage.addTextLayoutManager(manager)
        let container = NSTextContainer(size: CGSize(width: width, height: 1_000_000))
        container.lineFragmentPadding = 0
        manager.textContainer = container
        storage.textStorage = NSTextStorage(attributedString: attributed(c, mode: .byWordWrapping))
        manager.ensureLayout(for: manager.documentRange)
        var strings: [String] = []
        var widths: [Double] = []
        let text = c.text as NSString
        manager.enumerateTextLayoutFragments(from: manager.documentRange.location, options: [.ensuresLayout]) { fragment in
            let base = manager.offset(from: manager.documentRange.location, to: fragment.rangeInElement.location)
            for line in fragment.textLineFragments {
                let range = line.characterRange
                let location = base + range.location
                if range.length > 0 && location + range.length <= text.length {
                    strings.append(text.substring(with: NSRange(location: location, length: range.length)).trimmingCharacters(in: .newlines))
                    widths.append(line.typographicBounds.width)
                }
            }
            return true
        }
        out["tk2"] = strings
        out["widths"] = widths

        if c.markdown == true {
            let legacy = NSLayoutManager()
            let legacyStorage = NSTextStorage(attributedString: drawn)
            legacyStorage.addLayoutManager(legacy)
            let legacyContainer = NSTextContainer(size: CGSize(width: width, height: 1_000_000))
            legacyContainer.lineFragmentPadding = 0
            legacyContainer.maximumNumberOfLines = c.lineLimit ?? 0
            legacyContainer.lineBreakMode = .byTruncatingTail
            legacy.addTextContainer(legacyContainer)
            legacy.ensureLayout(for: legacyContainer)
            var fragments: [[Double]] = []
            var fragmentStrings: [String] = []
            legacy.enumerateLineFragments(forGlyphRange: legacy.glyphRange(for: legacyContainer)) { rect, used, _, glyphRange, _ in
                fragments.append([used.origin.x, used.origin.y, used.width, used.height, rect.height])
                let characters = legacy.characterRange(forGlyphRange: glyphRange, actualGlyphRange: nil)
                fragmentStrings.append((drawn.string as NSString).substring(with: characters))
            }
            out["tk1"] = fragments
            out["tk1strings"] = fragmentStrings
            out["tk1used"] = [legacy.usedRect(for: legacyContainer).width, legacy.usedRect(for: legacyContainer).height]
        }
        return out
    }

    private static func hasLink(_ string: NSAttributedString) -> Bool {
        var found = false
        string.enumerateAttribute(.link, in: NSRange(location: 0, length: string.length)) { value, _, stop in
            if value != nil { found = true; stop.pointee = true }
        }
        return found
    }
}
#endif
