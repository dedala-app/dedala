// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import Foundation
import JavaScriptCore
import Observation

/// A card's or page's script: its source and the values it derives, by name.
struct ScriptSpec: Hashable {
    var source: String
    var derive: [String: String]

    init?(_ surface: JSONValue?) {
        guard let source = surface?["script"]?.string, !source.isEmpty else { return nil }
        self.source = source
        derive = (surface?["derive"]?.object ?? [:]).compactMapValues(\.string)
    }

    var json: [String: JSONValue] {
        ["script": .string(source), "derive": .object(derive.mapValues(JSONValue.string))]
    }

    /// The stores the script names, `stores.daily` or `stores['daily']`: only
    /// they are given to it, and only their changes run it again.
    var stores: Set<String> {
        let pattern = /stores\s*(?:\.\s*([A-Za-z_$][\w$]*)|\[\s*['"]([^'"]+)['"]\s*\])/
        return Set(source.matches(of: pattern).compactMap { match in (match.output.1 ?? match.output.2).map(String.init) })
    }

    func stores(from all: [String: JSONValue]) -> [String: JSONValue] {
        all.filter { stores.contains($0.key) }
    }
}

/// Runs scripts in JavaScriptCore, one at a time, off the main thread. A run
/// that outlives its time is abandoned with its engine, which cannot be
/// interrupted: the next run gets a fresh one. Scripts never reach the network
/// and never read the clock; `helpers.js` freezes the time to the `now` given.
final class ScriptEngine: @unchecked Sendable {
    static let shared = ScriptEngine()

    struct Failure: Error, CustomStringConvertible {
        let message: String
        var timedOut = false
        var description: String { message }
    }

    /// Shared modules from `define`, by name: `{"invoices": "function unpaid… return {unpaid}"}`.
    nonisolated(unsafe) static var modules: [String: String] = [:]
    static let derivedLimit: TimeInterval = 0.5
    static let handlerLimit: TimeInterval = 0.5
    static let resultLimit = 256 * 1024

    private final class Runtime {
        let queue = DispatchQueue(label: "hermes.scripts")
        var machine: JSVirtualMachine?
        var scopes: [Int: (context: JSContext, scope: JSValue)] = [:]
    }

    private let lock = NSLock()
    private var runtime = Runtime()
    private var strikes: [Int: Int] = [:]

    private static let helpers: String = {
        guard let url = Bundle.main.url(forResource: "helpers", withExtension: "js"),
              let source = try? String(contentsOf: url, encoding: .utf8) else { return "" }
        return source
    }()

    /// Runs `function` of `source` on `input`; its JSON result, or why not.
    func call(_ source: String, function: String, input: JSONValue, limit: TimeInterval) async -> Result<JSONValue, Failure> {
        let modules = Self.modules
        let key = Self.key(source, modules: modules)
        if strikesFor(key) >= 2 {
            return .failure(Failure(message: "switched off after running out of time twice; send the script again once fixed"))
        }
        let current = currentRuntime()
        let inputText = String(decoding: input.data(), as: UTF8.self)
        let outcome = await withCheckedContinuation { (continuation: CheckedContinuation<Result<JSONValue, Failure>, Never>) in
            let once = Once(continuation)
            current.queue.async {
                let scope: JSValue
                do {
                    scope = try Self.scope(source, modules: modules, key: key, in: current)
                } catch let failure as Failure {
                    once.resume(.failure(failure))
                    return
                } catch {
                    once.resume(.failure(Failure(message: "\(error)")))
                    return
                }
                DispatchQueue.global().asyncAfter(deadline: .now() + limit) {
                    once.resume(.failure(Failure(message: "ran out of time (\(Int(limit * 1000)) ms)", timedOut: true)))
                }
                let context = scope.context!
                let result = context.objectForKeyedSubscript("__call").call(withArguments: [scope, function, inputText])
                if let exception = context.exception {
                    context.exception = nil
                    once.resume(.failure(Failure(message: exception.toString() ?? "threw")))
                    return
                }
                guard let text = result?.toString() else {
                    once.resume(.failure(Failure(message: "returned nothing readable")))
                    return
                }
                guard text.utf8.count <= Self.resultLimit else {
                    once.resume(.failure(Failure(message: "returned \(text.utf8.count / 1024) KB, more than 256 KB")))
                    return
                }
                do {
                    once.resume(.success(try JSONValue.parse(Data(text.utf8))))
                } catch {
                    once.resume(.failure(Failure(message: "returned something that is not JSON")))
                }
            }
        }
        if case .failure(let failure) = outcome, failure.timedOut {
            strike(key)
            replace(current)
        }
        return outcome
    }

    private func currentRuntime() -> Runtime {
        lock.lock()
        defer { lock.unlock() }
        return runtime
    }

    private func replace(_ stuck: Runtime) {
        lock.lock()
        defer { lock.unlock() }
        if runtime === stuck { runtime = Runtime() }
    }

    private func strikesFor(_ key: Int) -> Int {
        lock.lock()
        defer { lock.unlock() }
        return strikes[key] ?? 0
    }

    private func strike(_ key: Int) {
        lock.lock()
        defer { lock.unlock() }
        strikes[key, default: 0] += 1
    }

    /// Forgets the time-outs of a script sent again.
    func pardon(_ source: String) {
        lock.lock()
        defer { lock.unlock() }
        strikes[Self.key(source, modules: Self.modules)] = nil
    }

    private static func key(_ source: String, modules: [String: String]) -> Int {
        var hasher = Hasher()
        hasher.combine(source)
        hasher.combine(modules)
        return hasher.finalize()
    }

    /// On the runtime's queue: the script loaded after the helpers and the
    /// shared modules, kept while the same script and modules are asked for.
    private static func scope(_ source: String, modules: [String: String], key: Int, in runtime: Runtime) throws -> JSValue {
        if let known = runtime.scopes[key] { return known.scope }
        if runtime.machine == nil { runtime.machine = JSVirtualMachine() }
        guard let context = JSContext(virtualMachine: runtime.machine) else { throw Failure(message: "no JavaScript engine") }
        let orgParse: @convention(block) (String, String) -> String = { text, format in OrgTree.json(text, format: format) }
        context.setObject(orgParse, forKeyedSubscript: "__orgParse" as NSString)
        context.evaluateScript(helpers)
        for (name, module) in modules.sorted(by: { $0.key < $1.key }) where name.range(of: #"^[A-Za-z_$][A-Za-z0-9_$]*$"#, options: .regularExpression) != nil {
            context.evaluateScript("var \(name) = (function () {\n\(module)\n})()")
            if let exception = context.exception {
                throw Failure(message: "the module \(name) threw: \(exception.toString() ?? "")")
            }
        }
        let load = context.objectForKeyedSubscript("__load")
        guard let scope = load?.call(withArguments: [source]), context.exception == nil, !scope.isUndefined else {
            throw Failure(message: "the script does not load: \(context.exception?.toString() ?? "unknown error")")
        }
        if runtime.scopes.count > 32 { runtime.scopes.removeAll() }
        runtime.scopes[key] = (context, scope)
        return scope
    }

    /// Resumes a continuation once, from the run or from its time-out.
    private final class Once: @unchecked Sendable {
        private let lock = NSLock()
        private var continuation: CheckedContinuation<Result<JSONValue, Failure>, Never>?

        init(_ continuation: CheckedContinuation<Result<JSONValue, Failure>, Never>) {
            self.continuation = continuation
        }

        func resume(_ result: Result<JSONValue, Failure>) {
            lock.lock()
            let waiting = continuation
            continuation = nil
            lock.unlock()
            waiting?.resume(returning: result)
        }
    }
}

/// A card's or page's script at work: derives its values when what they read
/// changes, and runs its handlers.
@MainActor
final class ScriptHost {
    let spec: ScriptSpec
    let data: JSONValue
    let context: CardContext
    let state: StateBox
    let derived: StateBox
    let stores: [String: JSONValue]

    init(spec: ScriptSpec, data: JSONValue, context: CardContext, state: StateBox, derived: StateBox, stores: [String: JSONValue] = [:]) {
        self.spec = spec
        self.data = data
        self.context = context
        self.state = state
        self.derived = derived
        self.stores = spec.stores(from: stores)
    }

    /// What a function reads. A derived value gets the minute it is computed
    /// in; a handler the moment of the tap.
    func input(args: JSONValue? = nil, exact: Bool = false) -> JSONValue {
        var input: [String: JSONValue] = [
            "data": data, "state": .object(state.values), "stores": .object(stores), "now": JSONValue.iso(exact ? .now : Clock.shared.minute),
        ]
        for name in LiveValues.names {
            input[name] = LiveValues.shared.value(name)
        }
        if let args { input["args"] = args }
        return .object(input)
    }

    func derive() async {
        let input = input()
        let keys = Set(data.object?.keys.map { $0 } ?? [])
        for (name, function) in spec.derive.sorted(by: { $0.key < $1.key }) {
            guard !keys.contains(name) else {
                context.report("The derived value \(name) has the name of a data key; rename one of them")
                continue
            }
            switch await ScriptEngine.shared.call(spec.source, function: function, input: input, limit: ScriptEngine.derivedLimit) {
            case .success(let value):
                if derived.values[name] != value { derived.values[name] = value }
                context.derived[name] = value
            case .failure(let failure):
                derived.values[name] = .null
                context.derived[name] = .null
                context.report("Script: the derived value \(name) (\(function)) \(failure)")
            }
        }
    }

    /// What a handler asks for: changes to the state, then actions.
    struct Outcome {
        var state: [String: JSONValue]
        var then: JSONValue
    }

    /// Runs a handler; what it returns becomes state changes and actions.
    func handle(_ function: String, args: JSONValue?, tapped: String? = nil) async -> Outcome? {
        switch await ScriptEngine.shared.call(spec.source, function: function, input: input(args: args, exact: true), limit: ScriptEngine.handlerLimit) {
        case .success(let result):
            guard let object = result.object else { return nil }
            var steps: [JSONValue] = []
            if let send = object["send"] {
                var step: [String: JSONValue] = ["send": send]
                if let say = object["say"] { step["say"] = say }
                steps.append(.object(step))
            }
            if let command = object["command"] {
                var step: [String: JSONValue] = ["command": command]
                if let args = object["args"] { step["args"] = args }
                steps.append(.object(step))
            }
            for key in ["edit", "open", "page", "conversation", "card", "haptic"] {
                if let value = object[key] { steps.append(.object([key: value])) }
            }
            return Outcome(state: object["state"]?.object ?? [:], then: .array(steps))
        case .failure(let failure):
            context.fail("Script: the handler \(function) \(failure)", tapped: tapped)
            return nil
        }
    }
}
