// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import Foundation

/// An expression of a view, parsed once: what it evaluates to in a scope, or
/// why it could not be read.
struct Compiled {
    let source: String
    private let parsed: Result<Expression, Error>

    init(_ source: String) {
        self.source = source
        parsed = Result { try Expression.parse(source) }
    }

    /// Why the expression cannot be read, if it cannot.
    var problem: String? {
        if case .failure(let error) = parsed { return "\(error)" }
        return nil
    }

    func evaluate(_ scope: Scope) -> JSONValue {
        do {
            return try parsed.get().evaluate(scope.lookup)
        } catch {
            scope.context.report("\(error)")
            return .null
        }
    }
}

/// A string of a view as it was written: plain text, a `$reference`, a
/// `${expression}`, or text with those inside. Read once, resolved in a scope
/// as often as the view is drawn.
struct Template {
    private enum Form {
        case plain
        case value(Compiled)
        case mixed([Segment])
    }

    private enum Segment {
        case text(String)
        case expression(Compiled)
        case reference(path: String, root: String, compiled: Compiled)
    }

    let source: String
    private let form: Form

    init(_ source: String) {
        self.source = source
        if source.hasPrefix("$"), !source.hasPrefix("${"), Self.isReference(source) {
            form = .value(Compiled(String(source.dropFirst())))
        } else if !source.contains("$") {
            form = .plain
        } else {
            let segments = Self.segments(of: source)
            if segments.count == 1, case .expression(let compiled) = segments[0] {
                form = .value(compiled)
            } else {
                form = .mixed(segments)
            }
        }
    }

    private static var cache: [String: Template] = [:]

    /// The template of a string met while drawing, kept: a string is read once
    /// however often it is resolved.
    static func of(_ source: String) -> Template {
        if let known = cache[source] { return known }
        let template = Template(source)
        cache[source] = template
        return template
    }

    /// Whether it names one thing in scope, `$name` or `$item.field`, and nothing else.
    var isReference: Bool {
        source.hasPrefix("$") && !source.hasPrefix("${") && Self.isReference(source)
    }

    /// Whether anything in it is computed.
    var isComputed: Bool {
        if case .plain = form { return false }
        return true
    }

    /// The expressions it holds that cannot be read.
    var problems: [String] {
        switch form {
        case .plain: []
        case .value(let compiled): [compiled.problem].compactMap { $0 }
        case .mixed(let segments):
            segments.compactMap { segment in
                if case .expression(let compiled) = segment { return compiled.problem }
                return nil
            }
        }
    }

    /// The value it stands for: of any type for a reference or one expression, text otherwise.
    func resolve(_ scope: Scope) -> JSONValue {
        switch form {
        case .plain:
            return .string(source)
        case .value(let compiled):
            return compiled.evaluate(scope)
        case .mixed(let segments):
            return .string(segments.map { segment in
                switch segment {
                case .text(let text): text
                case .expression(let compiled): compiled.evaluate(scope).text
                case .reference(let path, let root, let compiled):
                    scope.lookup(root) == nil ? "$" + path : compiled.evaluate(scope).text
                }
            }.joined())
        }
    }

    static func isReference(_ string: String) -> Bool {
        string.dropFirst().range(of: #"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z0-9_]+|\[[0-9]+\])*$"#, options: .regularExpression) != nil
    }

    private static func segments(of string: String) -> [Segment] {
        var segments: [Segment] = []
        var text = ""
        var index = string.startIndex
        while index < string.endIndex {
            if string[index] == "$", string.index(after: index) < string.endIndex, string[string.index(after: index)] == "{" {
                var depth = 0
                var end = string.index(index, offsetBy: 2)
                var found = false
                while end < string.endIndex {
                    if string[end] == "{" { depth += 1 }
                    if string[end] == "}" {
                        if depth == 0 { found = true; break }
                        depth -= 1
                    }
                    end = string.index(after: end)
                }
                if found {
                    if !text.isEmpty { segments.append(.text(text)); text = "" }
                    segments.append(.expression(Compiled(String(string[string.index(index, offsetBy: 2)..<end]))))
                    index = string.index(after: end)
                    continue
                }
            }
            if string[index] == "$", let match = string[string.index(after: index)...].prefixMatch(of: /[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*/) {
                if !text.isEmpty { segments.append(.text(text)); text = "" }
                let path = String(match.output.0)
                segments.append(.reference(path: path, root: String(path.prefix { $0 != "." }), compiled: Compiled(path)))
                index = match.range.upperBound
                continue
            }
            text.append(string[index])
            index = string.index(after: index)
        }
        if !text.isEmpty { segments.append(.text(text)) }
        return segments
    }
}

/// A value of a view with the strings inside it read once: resolved in a
/// scope, it is the JSON value the view is drawn from.
indirect enum Dynamic {
    case constant(JSONValue)
    case template(Template)
    case array([Dynamic])
    case object([String: Dynamic])

    init(_ value: JSONValue) {
        switch value {
        case .string(let string):
            let template = Template.of(string)
            self = template.isComputed ? .template(template) : .constant(value)
        case .array(let items):
            let read = items.map(Dynamic.init)
            self = read.allSatisfy(\.isConstant) ? .constant(value) : .array(read)
        case .object(let object):
            let read = object.mapValues(Dynamic.init)
            self = read.values.allSatisfy(\.isConstant) ? .constant(value) : .object(read)
        default:
            self = .constant(value)
        }
    }

    var isConstant: Bool {
        if case .constant = self { return true }
        return false
    }

    func resolve(_ scope: Scope) -> JSONValue {
        switch self {
        case .constant(let value): value
        case .template(let template): template.resolve(scope)
        case .array(let items): .array(items.map { $0.resolve(scope) })
        case .object(let object): .object(object.mapValues { $0.resolve(scope) })
        }
    }

    /// The expressions inside it that cannot be read.
    var problems: [String] {
        switch self {
        case .constant: []
        case .template(let template): template.problems
        case .array(let items): items.flatMap(\.problems)
        case .object(let object): object.keys.sorted().flatMap { object[$0]?.problems ?? [] }
        }
    }
}

/// A condition of a view (`If`, `hidden`, `visible`, `disabled`): an
/// expression written bare (`count(items) == 0`, `$a && !$b`), a reference or
/// a `${…}`.
struct Condition {
    private enum Form {
        case bare(Compiled)
        case value(Dynamic)
    }

    private let form: Form

    init(_ value: JSONValue) {
        if case .string(let source) = value, !source.contains("${"), !Template.of(source).isReference {
            form = .bare(Compiled(source))
        } else {
            form = .value(Dynamic(value))
        }
    }

    func holds(_ scope: Scope) -> Bool {
        switch form {
        case .bare(let compiled): compiled.evaluate(scope).truthy
        case .value(let value): value.resolve(scope).truthy
        }
    }

    var problems: [String] {
        switch form {
        case .bare(let compiled): [compiled.problem].compactMap { $0 }
        case .value(let value): value.problems
        }
    }
}

extension Scope {
    func value(_ dynamic: Dynamic?) -> JSONValue? {
        dynamic?.resolve(self)
    }

    func text(_ dynamic: Dynamic?) -> String {
        dynamic?.resolve(self).text ?? ""
    }

    func string(_ dynamic: Dynamic?) -> String? {
        dynamic?.resolve(self).string
    }

    func number(_ dynamic: Dynamic?) -> Double? {
        dynamic?.resolve(self).number
    }

    func length(_ dynamic: Dynamic?) -> CGFloat? {
        dynamic?.resolve(self).number.map { CGFloat($0) }
    }

    func int(_ dynamic: Dynamic?) -> Int? {
        dynamic?.resolve(self).int
    }

    /// The step of a slider or a stepper: a positive, finite number.
    func step(_ dynamic: Dynamic?) -> Double? {
        dynamic?.resolve(self).finite.flatMap { $0 > 0 ? $0 : nil }
    }
}
