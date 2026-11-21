// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import CoreText
import UIKit

/// The phone's system fonts, rebuilt from their tables for the agent's layout
/// twin: Apple's font files cannot ship with the agent, and only this phone has
/// the ones its iOS draws with. Each is deflated into a file the relay uploads
/// in sealed blobs, named as the twin names its designs.
enum FontTables {
    nonisolated static func event(os: String) -> JSONValue {
        var files: [String: JSONValue] = [:]
        for (name, font) in fonts {
            guard let file = sfnt(font), let packed = try? (file as NSData).compressed(using: .zlib) as Data else { continue }
            let url = FileManager.default.temporaryDirectory.appending(path: "font-\(name).deflate")
            guard (try? packed.write(to: url)) != nil else { continue }
            files[name] = .string(url.path)
        }
        return .object(["kind": .string("fonts"), "os": .string(os), "files": .object(files)])
    }

    nonisolated static var fonts: [(String, CTFont)] {
        let base = UIFont.systemFont(ofSize: 17)
        func design(_ design: UIFontDescriptor.SystemDesign) -> CTFont {
            UIFont(descriptor: base.fontDescriptor.withDesign(design) ?? base.fontDescriptor, size: 17) as CTFont
        }
        return [("default", base as CTFont), ("italic", UIFont.italicSystemFont(ofSize: 17) as CTFont),
                ("rounded", design(.rounded)), ("monospaced", design(.monospaced)), ("serif", design(.serif))]
    }

    /// The font's tables as one OpenType file: the header, a record per table
    /// in tag order, then each table padded to four bytes.
    nonisolated static func sfnt(_ font: CTFont) -> Data? {
        guard let available = CTFontCopyAvailableTables(font, []) else { return nil }
        var tables: [(tag: UInt32, data: Data)] = []
        for index in 0..<CFArrayGetCount(available) {
            let tag = UInt32(truncatingIfNeeded: Int(bitPattern: CFArrayGetValueAtIndex(available, index)))
            if let data = CTFontCopyTable(font, tag, []) as Data? { tables.append((tag, data)) }
        }
        guard !tables.isEmpty else { return nil }
        tables.sort { $0.tag < $1.tag }
        var power = 1
        var selector = 0
        while power * 2 <= tables.count {
            power *= 2
            selector += 1
        }
        var out = Data()
        func put(_ value: UInt32) { withUnsafeBytes(of: value.bigEndian) { out.append(contentsOf: $0) } }
        func put(_ value: UInt16) { withUnsafeBytes(of: value.bigEndian) { out.append(contentsOf: $0) } }
        put(tables.contains { $0.tag == 0x4346_4620 } ? UInt32(0x4F54_544F) : UInt32(0x0001_0000))
        put(UInt16(tables.count))
        put(UInt16(power * 16))
        put(UInt16(selector))
        put(UInt16(tables.count * 16 - power * 16))
        var offset = 12 + 16 * tables.count
        for table in tables {
            put(table.tag)
            put(checksum(table.data))
            put(UInt32(offset))
            put(UInt32(table.data.count))
            offset += (table.data.count + 3) & ~3
        }
        for table in tables {
            out.append(table.data)
            out.append(Data(count: (4 - table.data.count % 4) % 4))
        }
        return out
    }

    nonisolated static func checksum(_ data: Data) -> UInt32 {
        data.withUnsafeBytes { bytes in
            var sum: UInt32 = 0
            var index = 0
            while index < bytes.count {
                var word: UInt32 = 0
                for byte in 0..<4 {
                    word = word << 8 | UInt32(index + byte < bytes.count ? bytes[index + byte] : 0)
                }
                sum &+= word
                index += 4
            }
            return sum
        }
    }
}
