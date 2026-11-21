// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import Foundation

/// Any JSON value. Dedala UI trees, card data and state are all made of these.
nonisolated enum JSONValue: Hashable, Sendable, Codable {
    case null
    case bool(Bool)
    case number(Double)
    case string(String)
    case array([JSONValue])
    case object([String: JSONValue])

    init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if container.decodeNil() {
            self = .null
        } else if let value = try? container.decode(Bool.self) {
            self = .bool(value)
        } else if let value = try? container.decode(Double.self) {
            self = .number(value)
        } else if let value = try? container.decode(String.self) {
            self = .string(value)
        } else if let value = try? container.decode([JSONValue].self) {
            self = .array(value)
        } else {
            self = .object(try container.decode([String: JSONValue].self))
        }
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        switch self {
        case .null: try container.encodeNil()
        case .bool(let value): try container.encode(value)
        case .number(let value): try container.encode(value)
        case .string(let value): try container.encode(value)
        case .array(let value): try container.encode(value)
        case .object(let value): try container.encode(value)
        }
    }

    static func parse(_ data: Data) throws -> JSONValue {
        try JSONDecoder().decode(JSONValue.self, from: data)
    }

    func data() -> Data {
        (try? JSONEncoder().encode(self)) ?? Data("null".utf8)
    }

    subscript(key: String) -> JSONValue? {
        if case .object(let object) = self { return object[key] }
        return nil
    }

    var object: [String: JSONValue]? {
        if case .object(let value) = self { return value }
        return nil
    }

    var array: [JSONValue]? {
        if case .array(let value) = self { return value }
        return nil
    }

    var string: String? {
        if case .string(let value) = self { return value }
        return nil
    }

    var number: Double? {
        switch self {
        case .number(let value): value
        case .bool(let value): value ? 1 : 0
        case .string(let value): Double(value)
        default: nil
        }
    }

    /// A whole number the agent wrote, within what a count, a line or an index
    /// can be: a number written as "infinity", or beyond counting, is none.
    var int: Int? {
        guard let number, number.isFinite, abs(number) <= 1_000_000_000 else { return nil }
        return Int(number)
    }

    /// A number that can measure or bound something: not infinite, not NaN.
    var finite: Double? {
        number.flatMap { $0.isFinite ? $0 : nil }
    }

    var bool: Bool? {
        if case .bool(let value) = self { return value }
        return nil
    }

    var truthy: Bool {
        switch self {
        case .null: false
        case .bool(let value): value
        case .number(let value): value != 0
        case .string(let value): !value.isEmpty
        case .array(let value): !value.isEmpty
        case .object: true
        }
    }

    var date: Date? {
        switch self {
        case .number(let value):
            return Date(timeIntervalSince1970: value)
        case .string(let value):
            for formatter in JSONValue.dateFormatters {
                if let date = formatter.date(from: value) { return date }
            }
            return nil
        default:
            return nil
        }
    }

    private static let dateFormatters: [ISO8601DateFormatter] = {
        let options: [ISO8601DateFormatter.Options] = [
            [.withInternetDateTime, .withFractionalSeconds],
            [.withInternetDateTime],
            [.withFullDate, .withTime, .withColonSeparatorInTime],
            [.withFullDate],
        ]
        return options.map {
            let formatter = ISO8601DateFormatter()
            formatter.formatOptions = $0
            formatter.timeZone = .current
            return formatter
        }
    }()

    static func iso(_ date: Date) -> JSONValue {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime]
        return .string(formatter.string(from: date))
    }

    /// How the value reads when interpolated into text.
    var text: String {
        switch self {
        case .null: ""
        case .bool(let value): value ? "true" : "false"
        case .number(let value):
            value.rounded() == value && abs(value) < 1e15 ? String(Int64(value)) : value.formatted(.number.precision(.fractionLength(0...2)))
        case .string(let value): value
        case .array(let value): value.map(\.text).joined(separator: ", ")
        case .object: String(decoding: data(), as: UTF8.self)
        }
    }

    /// Objects merge key by key, `null` removes a key, anything else replaces.
    func merging(_ patch: JSONValue) -> JSONValue {
        guard case .object(var base) = self, case .object(let changes) = patch else { return patch }
        for (key, value) in changes {
            if value == .null {
                base[key] = nil
            } else if let existing = base[key], existing.object != nil, value.object != nil {
                base[key] = existing.merging(value)
            } else {
                base[key] = value
            }
        }
        return .object(base)
    }
}

nonisolated extension JSONValue: ExpressibleByStringLiteral, ExpressibleByBooleanLiteral, ExpressibleByArrayLiteral {
    init(stringLiteral value: String) {
        self = .string(value)
    }

    init(booleanLiteral value: Bool) {
        self = .bool(value)
    }

    init(arrayLiteral elements: JSONValue...) {
        self = .array(elements)
    }
}
