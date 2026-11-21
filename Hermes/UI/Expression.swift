// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import Foundation

/// The expression language of Hermes UI: paths, literals, arithmetic,
/// comparisons, logic, the ternary and a handful of functions.
indirect enum Expression {
    case literal(JSONValue)
    case path(String)
    case list([Expression])
    case member(Expression, String)
    case index(Expression, Expression)
    case unary(String, Expression)
    case binary(String, Expression, Expression)
    case ternary(Expression, Expression, Expression)
    case call(String, [Expression])

    struct ParseError: Error, CustomStringConvertible {
        let description: String
    }

    static func parse(_ source: String) throws -> Expression {
        if let cached = cache[source] { return cached }
        var parser = Parser(tokens: try tokenize(source))
        let expression = try parser.expression()
        guard parser.atEnd else {
            throw ParseError(description: "Unexpected \(parser.peek.map { "'\($0.text)'" } ?? "end") in '\(source)'")
        }
        cache[source] = expression
        return expression
    }

    private static var cache: [String: Expression] = [:]

    // MARK: - Tokens

    private struct Token {
        enum Kind { case number, string, identifier, symbol }
        let kind: Kind
        let text: String
    }

    private static let symbols = ["==", "!=", "<=", ">=", "&&", "||", "+", "-", "*", "/", "%", "<", ">", "!", "?", ":", "(", ")", "[", "]", ",", "."]

    private static func tokenize(_ source: String) throws -> [Token] {
        var tokens: [Token] = []
        let characters = Array(source)
        var index = 0
        while index < characters.count {
            let character = characters[index]
            if character.isWhitespace {
                index += 1
            } else if character.isNumber {
                var end = index
                while end < characters.count, characters[end].isNumber || characters[end] == "." && end + 1 < characters.count && characters[end + 1].isNumber {
                    end += 1
                }
                tokens.append(Token(kind: .number, text: String(characters[index..<end])))
                index = end
            } else if character == "'" || character == "\"" {
                var end = index + 1
                var text = ""
                while end < characters.count, characters[end] != character {
                    if characters[end] == "\\", end + 1 < characters.count {
                        end += 1
                    }
                    text.append(characters[end])
                    end += 1
                }
                guard end < characters.count else { throw ParseError(description: "Unterminated string in '\(source)'") }
                tokens.append(Token(kind: .string, text: text))
                index = end + 1
            } else if character.isLetter || character == "_" || character == "$" {
                var end = index + 1
                while end < characters.count, characters[end].isLetter || characters[end].isNumber || characters[end] == "_" {
                    end += 1
                }
                let text = String(characters[index..<end])
                tokens.append(Token(kind: .identifier, text: text.hasPrefix("$") ? String(text.dropFirst()) : text))
                index = end
            } else if let symbol = symbols.first(where: { symbol in
                symbol.count <= characters.count - index && String(characters[index..<index + symbol.count]) == symbol
            }) {
                tokens.append(Token(kind: .symbol, text: symbol))
                index += symbol.count
            } else {
                throw ParseError(description: "Unexpected '\(character)' in '\(source)'")
            }
        }
        return tokens
    }

    // MARK: - Parser

    private struct Parser {
        let tokens: [Token]
        var position = 0

        var atEnd: Bool { position >= tokens.count }
        var peek: Token? { atEnd ? nil : tokens[position] }

        mutating func take(_ symbol: String) -> Bool {
            guard let token = peek, token.kind == .symbol, token.text == symbol else { return false }
            position += 1
            return true
        }

        mutating func expect(_ symbol: String) throws {
            guard take(symbol) else {
                throw ParseError(description: "Expected '\(symbol)' but found \(peek.map { "'\($0.text)'" } ?? "the end")")
            }
        }

        mutating func expression() throws -> Expression {
            let condition = try binary(level: 0)
            guard take("?") else { return condition }
            let then = try expression()
            try expect(":")
            return .ternary(condition, then, try expression())
        }

        private static let levels: [[String]] = [["||"], ["&&"], ["==", "!="], ["<", "<=", ">", ">="], ["+", "-"], ["*", "/", "%"]]

        mutating func binary(level: Int) throws -> Expression {
            guard level < Self.levels.count else { return try unary() }
            var left = try binary(level: level + 1)
            while let token = peek, token.kind == .symbol, Self.levels[level].contains(token.text) {
                position += 1
                left = .binary(token.text, left, try binary(level: level + 1))
            }
            return left
        }

        mutating func unary() throws -> Expression {
            if take("!") { return .unary("!", try unary()) }
            if take("-") { return .unary("-", try unary()) }
            return try postfix()
        }

        mutating func postfix() throws -> Expression {
            var expression = try primary()
            while true {
                if take(".") {
                    guard let token = peek, token.kind == .identifier || token.kind == .number else {
                        throw ParseError(description: "Expected a name after '.'")
                    }
                    position += 1
                    expression = .member(expression, token.text)
                } else if take("[") {
                    let index = try self.expression()
                    try expect("]")
                    expression = .index(expression, index)
                } else {
                    return expression
                }
            }
        }

        mutating func primary() throws -> Expression {
            guard let token = peek else { throw ParseError(description: "Unexpected end of expression") }
            position += 1
            switch token.kind {
            case .number:
                return .literal(.number(Double(token.text) ?? 0))
            case .string:
                return .literal(.string(token.text))
            case .identifier:
                switch token.text {
                case "true": return .literal(.bool(true))
                case "false": return .literal(.bool(false))
                case "null", "nil": return .literal(.null)
                default: break
                }
                if take("(") {
                    var arguments: [Expression] = []
                    if !take(")") {
                        repeat { arguments.append(try expression()) } while take(",")
                        try expect(")")
                    }
                    return .call(token.text, arguments)
                }
                return .path(token.text)
            case .symbol where token.text == "(":
                let inner = try expression()
                try expect(")")
                return inner
            case .symbol where token.text == "[":
                var items: [Expression] = []
                if !take("]") {
                    repeat { items.append(try expression()) } while take(",")
                    try expect("]")
                }
                return .list(items)
            case .symbol:
                throw ParseError(description: "Unexpected '\(token.text)'")
            }
        }
    }

    // MARK: - Evaluation

    func evaluate(_ lookup: (String) -> JSONValue?) throws -> JSONValue {
        switch self {
        case .literal(let value):
            return value
        case .path(let name):
            return lookup(name) ?? .null
        case .list(let items):
            return .array(try items.map { try $0.evaluate(lookup) })
        case .member(let base, let name):
            let value = try base.evaluate(lookup)
            if let index = Int(name), let array = value.array { return array.indices.contains(index) ? array[index] : .null }
            if name == "count" || name == "length", let array = value.array { return .number(Double(array.count)) }
            if name == "length", let text = value.string { return .number(Double(text.count)) }
            return value[name] ?? .null
        case .index(let base, let index):
            let value = try base.evaluate(lookup)
            let key = try index.evaluate(lookup)
            if let array = value.array, let position = key.int {
                return array.indices.contains(position) ? array[position] : .null
            }
            return key.string.flatMap { value[$0] } ?? .null
        case .unary(let op, let operand):
            let value = try operand.evaluate(lookup)
            return op == "!" ? .bool(!value.truthy) : .number(-(value.number ?? 0))
        case .binary(let op, let left, let right):
            let lhs = try left.evaluate(lookup)
            if op == "&&" { return lhs.truthy ? try right.evaluate(lookup) : lhs }
            if op == "||" { return lhs.truthy ? lhs : try right.evaluate(lookup) }
            return Self.apply(op, lhs, try right.evaluate(lookup))
        case .ternary(let condition, let then, let otherwise):
            return try condition.evaluate(lookup).truthy ? then.evaluate(lookup) : otherwise.evaluate(lookup)
        case .call(let name, let arguments):
            return try ExpressionFunctions.call(name, try arguments.map { try $0.evaluate(lookup) })
        }
    }

    private static func apply(_ op: String, _ lhs: JSONValue, _ rhs: JSONValue) -> JSONValue {
        switch op {
        case "==": return .bool(equal(lhs, rhs))
        case "!=": return .bool(!equal(lhs, rhs))
        case "+":
            if case .string = lhs { return .string(lhs.text + rhs.text) }
            if case .string = rhs { return .string(lhs.text + rhs.text) }
            if let left = lhs.array, let right = rhs.array { return .array(left + right) }
            return .number((lhs.number ?? 0) + (rhs.number ?? 0))
        default:
            break
        }
        if let left = lhs.number, let right = rhs.number {
            switch op {
            case "-": return .number(left - right)
            case "*": return .number(left * right)
            case "/": return right == 0 ? .null : .number(left / right)
            case "%": return right == 0 ? .null : .number(left.truncatingRemainder(dividingBy: right))
            case "<": return .bool(left < right)
            case "<=": return .bool(left <= right)
            case ">": return .bool(left > right)
            case ">=": return .bool(left >= right)
            default: return .null
            }
        }
        if let left = lhs.date, let right = rhs.date {
            switch op {
            case "<": return .bool(left < right)
            case "<=": return .bool(left <= right)
            case ">": return .bool(left > right)
            case ">=": return .bool(left >= right)
            case "-": return .number(left.timeIntervalSince(right))
            default: return .null
            }
        }
        if let left = lhs.string, let right = rhs.string {
            switch op {
            case "<": return .bool(left < right)
            case "<=": return .bool(left <= right)
            case ">": return .bool(left > right)
            case ">=": return .bool(left >= right)
            default: return .null
            }
        }
        return .null
    }

    private static func equal(_ lhs: JSONValue, _ rhs: JSONValue) -> Bool {
        if let left = lhs.number, let right = rhs.number, lhs.string == nil || rhs.string == nil {
            return left == right
        }
        return lhs == rhs
    }
}

enum ExpressionFunctions {
    struct UnknownFunction: Error, CustomStringConvertible {
        let name: String
        var description: String { "Unknown function \(name)()" }
    }

    static func call(_ name: String, _ arguments: [JSONValue]) throws -> JSONValue {
        let first = arguments.first ?? .null
        let second = arguments.count > 1 ? arguments[1] : .null
        switch name {
        case "format":
            return .string(format(first, spec: second.string ?? "number"))
        case "date":
            return .string(date(first, style: second.string ?? "datetime"))
        case "count", "len":
            if let array = first.array { return .number(Double(array.count)) }
            if let string = first.string { return .number(Double(string.count)) }
            if let object = first.object { return .number(Double(object.count)) }
            return .number(0)
        case "sum":
            return .number(numbers(first, key: second.string).reduce(0, +))
        case "avg":
            let values = numbers(first, key: second.string)
            return values.isEmpty ? .null : .number(values.reduce(0, +) / Double(values.count))
        case "min", "max":
            let values = arguments.count == 1 || (arguments.count == 2 && second.string != nil)
                ? numbers(first, key: second.string)
                : arguments.compactMap(\.number)
            guard let result = name == "min" ? values.min() : values.max() else { return .null }
            return .number(result)
        case "round":
            let digits = second.number ?? 0
            let factor = pow(10, digits)
            return .number(((first.number ?? 0) * factor).rounded() / factor)
        case "abs":
            return .number(abs(first.number ?? 0))
        case "clamp":
            let value = first.number ?? 0
            return .number(Swift.min(Swift.max(value, second.number ?? value), (arguments.count > 2 ? arguments[2].number : nil) ?? value))
        case "upper":
            return .string(first.text.uppercased())
        case "lower":
            return .string(first.text.lowercased())
        case "join":
            return .string((first.array ?? []).map(\.text).joined(separator: second.string ?? ", "))
        case "pluck":
            return .array((first.array ?? []).map { $0[second.text] ?? .null })
        case "contains":
            if let array = first.array { return .bool(array.contains(second)) }
            return .bool(first.text.localizedCaseInsensitiveContains(second.text))
        case "filter":
            let key = second.text
            let wanted = arguments.count > 2 ? arguments[2] : nil
            return .array((first.array ?? []).filter { element in
                let value = element[key] ?? .null
                return wanted.map { value == $0 } ?? value.truthy
            })
        case "find":
            let key = second.text
            let wanted = arguments.count > 2 ? arguments[2] : nil
            return (first.array ?? []).first { element in
                let value = element[key] ?? .null
                return wanted.map { value == $0 } ?? value.truthy
            } ?? .null
        case "now":
            return JSONValue.iso(first.string == "seconds" ? Clock.shared.second : Clock.shared.minute)
        case "until":
            guard let date = first.date else { return .null }
            return .string(until(date, now: Clock.shared.minute))
        case "ago":
            guard let date = first.date else { return .null }
            return .string(ago(date, now: Clock.shared.minute))
        case "isToday":
            return .bool(first.date.map { Calendar.current.isDate($0, inSameDayAs: Clock.shared.minute) } ?? false)
        case "isPast":
            return .bool(first.date.map { $0 <= Clock.shared.minute } ?? false)
        case "string":
            return .string(first.text)
        case "number":
            return first.number.map(JSONValue.number) ?? .null
        case "org", "markdown":
            let tree = OrgTree.parse(first.text, format: name)
            guard let kind = second.string else { return tree }
            return .array(OrgTree.select(tree, kind))
        default:
            throw UnknownFunction(name: name)
        }
    }

    private static func numbers(_ value: JSONValue, key: String?) -> [Double] {
        (value.array ?? []).compactMap { element in
            key.map { element[$0]?.number } ?? element.number
        }
    }

    static func format(_ value: JSONValue, spec: String) -> String {
        let parts = spec.split(separator: ":", maxSplits: 1).map(String.init)
        let option = parts.count > 1 ? parts[1] : nil
        guard let number = value.finite else { return value.text }
        func places(_ written: String?) -> Int? {
            written.flatMap { Int($0) }.map { min(max($0, 0), 10) }
        }
        switch parts.first ?? "number" {
        case "percent":
            return number.formatted(.percent.precision(.fractionLength(0...(places(option) ?? 0))))
        case "currency":
            let currency = (option ?? "EUR").split(separator: ":").map(String.init)
            let digits = currency.count > 1 ? places(currency[1]) : nil
            return number.formatted(.currency(code: currency.first ?? "EUR").precision(.fractionLength(digits ?? (number.rounded() == number ? 0 : 2))))
        case "compact":
            return number.formatted(.number.notation(.compactName))
        case "duration":
            return Duration.seconds(number).formatted(.units(allowed: [.hours, .minutes], width: .abbreviated))
        case "bytes":
            return Int64(min(max(number, 0), 1e18)).formatted(.byteCount(style: .file))
        default:
            let digits = places(option) ?? (number.rounded() == number ? 0 : 1)
            return number.formatted(.number.precision(.fractionLength(digits)))
        }
    }

    /// "in 3 days", "in 12 min", "now".
    static func until(_ date: Date, now: Date) -> String {
        guard abs(date.timeIntervalSince(now)) >= 60 else { return "now" }
        let formatter = RelativeDateTimeFormatter()
        formatter.unitsStyle = .short
        return formatter.localizedString(for: date, relativeTo: now)
    }

    /// "2 hr. ago", "yesterday", "just now".
    static func ago(_ date: Date, now: Date) -> String {
        guard now.timeIntervalSince(date) >= 60 else { return "just now" }
        let formatter = RelativeDateTimeFormatter()
        formatter.dateTimeStyle = .named
        formatter.unitsStyle = .short
        return formatter.localizedString(for: date, relativeTo: now)
    }

    static func date(_ value: JSONValue, style: String) -> String {
        guard let date = value.date else { return value.text }
        switch style {
        case "time": return date.formatted(date: .omitted, time: .shortened)
        case "date": return date.formatted(date: .abbreviated, time: .omitted)
        case "weekday": return date.formatted(.dateTime.weekday(.wide))
        case "day": return date.formatted(.dateTime.weekday(.abbreviated).day())
        case "month": return date.formatted(.dateTime.month(.wide))
        case "dayMonth": return date.formatted(.dateTime.day().month(.abbreviated))
        case "monthYear": return date.formatted(.dateTime.month(.abbreviated).year())
        case "relative": return RelativeDateTimeFormatter().localizedString(for: date, relativeTo: Clock.shared.minute)
        default: return date.formatted(date: .abbreviated, time: .shortened)
        }
    }
}
