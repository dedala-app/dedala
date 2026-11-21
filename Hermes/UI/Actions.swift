// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import LocalAuthentication
import SwiftUI
import UIKit

/// Runs Hermes UI actions: state changes and haptics on the card, phone
/// actions through system URLs, and `send` back to the agent.
enum ActionRunner {
    static var openPage: ((String) -> Void)?
    static var openURL: ((URL) -> Void)?
    /// Opens a conversation, the main one or a topic; false when there is no such topic.
    static var openConversation: ((String) -> Bool)?
    /// Shows a card in its conversation; false when no conversation holds it.
    static var openCard: ((String) -> Bool)?
    /// Changes a store on the phone, from the card or page named; the reason
    /// when it cannot.
    static var edit: ((JSONValue, String) -> String?)?
    /// Runs a command on the agent's machine, with its arguments, from the
    /// card or page named; the reason when it cannot start.
    static var command: ((String, JSONValue, String) -> String?)?
    static var hasStore: ((String) -> Bool)?
    /// Opens a screen as a sheet: from a card, or when asked for one.
    static var present: ((Shown) -> Void)?
    /// Opens a record of a store in its sheet, when no stack is there to push its screen on.
    static var openRecord: ((_ store: String, _ record: String) -> Void)?
    /// Tells the agent an action could not do what it says: why, on which
    /// card or page, and what you tapped when that is known.
    static var failed: ((String, String, String?) -> Void)?

    static func run(_ action: JSONValue?, title: String? = nil, in scope: Scope) {
        guard let action else { return }
        run(Action(action), title: title, in: scope)
    }

    static func run(_ action: Action?, title: String? = nil, in scope: Scope) {
        guard let action else { return }
        Task { @MainActor in
            for step in action.steps {
                if step.requiresFaceID, !(await authenticate()) {
                    UINotificationFeedbackGenerator().notificationOccurred(.error)
                    return
                }
                perform(step, title: title, in: scope)
            }
        }
    }

    private static func perform(_ step: Action.Step, title: String?, in scope: Scope) {
        if let invalid = step.invalid {
            scope.context.report(invalid)
            return
        }
        if let name = step.reference {
            handed(name, title: title, in: scope)
            return
        }
        for verb in step.verbs {
            let value = verb.value
            switch verb.name {
            case "send":
                let say = step.say.map { scope.text($0) } ?? title
                scope.context.onSend(value.resolve(scope), say)
            case "set":
                let changes = value.resolve(scope).object ?? [:]
                withAnimation(.spring(duration: 0.4)) {
                    for (name, new) in changes {
                        scope.box(for: name)?.values[name] = new
                    }
                }
            case "toggle":
                let name = verb.raw.text
                withAnimation(.spring(duration: 0.4)) {
                    if let box = scope.box(for: name) {
                        box.values[name] = .bool(!(box.values[name]?.truthy ?? false))
                    }
                }
            case "open":
                open(scope.text(value))
            case "call":
                open("tel:\(digits(scope.text(value)))")
            case "message":
                open("sms:\(digits(scope.text(value)))")
            case "mail":
                open("mailto:\(scope.text(value))")
            case "directions":
                let target = value.resolve(scope)
                if let lat = target["lat"]?.number, let lon = target["lon"]?.number {
                    let name = target["name"]?.text.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? ""
                    open("maps://?daddr=\(lat),\(lon)&q=\(name)")
                } else {
                    open("maps://?daddr=\(target.text.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? "")")
                }
            case "copy":
                UIPasteboard.general.string = scope.text(value)
                UINotificationFeedbackGenerator().notificationOccurred(.success)
            case "shortcut":
                var components = URLComponents(string: "shortcuts://run-shortcut")
                components?.queryItems = [URLQueryItem(name: "name", value: scope.text(value))]
                if let input = step.input {
                    components?.queryItems?.append(URLQueryItem(name: "input", value: "text"))
                    components?.queryItems?.append(URLQueryItem(name: "text", value: scope.text(input)))
                }
                if let url = components?.url { openURL?(url) }
            case "show":
                let shown = Shown(name: scope.text(value), call: Element.Call(step.with ?? .null), scope: scope)
                guard scope.context.component(shown.name) != nil else {
                    scope.context.fail("There is no component '\(shown.name)' to show: define it first", tapped: title)
                    continue
                }
                if let navigator = scope.navigator, !step.sheet {
                    navigator.show(shown, replacing: step.replace)
                } else {
                    present?(shown)
                }
            case "close":
                scope.navigator?.close(all: verb.raw.string == "all")
            case "page":
                openPage?(scope.text(value))
            case "conversation":
                if openConversation?(scope.text(value)) == false {
                    scope.context.fail("There is no conversation '\(scope.text(value))': use main or a topic's id", tapped: title)
                }
            case "card":
                if openCard?(scope.text(value)) == false {
                    scope.context.fail("No conversation holds the card '\(scope.text(value))'", tapped: title)
                }
            case "edit":
                if let problem = edit?(value.resolve(scope), scope.context.cardID) {
                    scope.context.fail(problem, tapped: title)
                }
            case "command":
                let args = step.args.map { $0.resolve(scope) } ?? .null
                if let problem = command?(scope.text(value), args, scope.context.cardID) {
                    scope.context.fail(problem, tapped: title)
                }
            case "haptic":
                haptic(verb.raw.text)
            case "run":
                guard let host = scope.script else {
                    scope.context.fail("run needs a script on the card or page", tapped: title)
                    continue
                }
                let args = step.args.map { $0.resolve(scope) }
                Task { @MainActor in
                    guard let outcome = await host.handle(scope.text(value), args: args, tapped: title) else { return }
                    withAnimation(.spring(duration: 0.4)) {
                        for (name, new) in outcome.state {
                            (scope.box(declaring: name) ?? host.state).values[name] = new
                        }
                    }
                    run(outcome.then, title: title, in: scope)
                }
            default:
                scope.context.report("Unknown action '\(verb.name)'")
            }
        }
    }

    /// An action written as a reference. The one a component was handed under
    /// that name runs where it was written, in its caller's state and script,
    /// with the `$value` of here; any other reference is to a value that holds
    /// the action, and nothing when it holds none.
    private static func handed(_ name: String, title: String?, in scope: Scope) {
        if let caller = scope.caller, let written = caller.arguments[name] {
            let value = scope.lookup("value")
            run(written, title: title, in: value.map { caller.scope.with(["value": $0]) } ?? caller.scope)
            return
        }
        let held = scope.resolve("$" + name)
        switch held {
        case .null:
            return
        case .object, .array:
            run(held, title: title, in: scope)
        default:
            scope.context.fail("$\(name) is not an action: \(held.text)", tapped: title)
        }
    }

    /// The verbs of one action object always run in the same order, whatever
    /// order they were written in: what reads the state first (a send, an edit),
    /// then what changes it, then what leaves the screen.
    static let verbs = ["send", "edit", "command", "run", "copy", "shortcut", "set", "toggle", "haptic", "show", "close",
                        "open", "page", "conversation", "card", "call", "message", "mail", "directions"]
    private static let parameters: Set<String> = ["require", "say", "input", "args", "with", "as", "replace"]

    static func order(_ keys: some Collection<String>) -> [String] {
        let written = Set(keys).subtracting(parameters)
        return verbs.filter(written.contains) + written.subtracting(verbs).sorted()
    }

    private static func digits(_ number: String) -> String {
        number.filter { $0.isNumber || $0 == "+" }
    }

    private static func open(_ string: String) {
        guard let url = URL(string: string) else { return }
        openURL?(url)
    }

    private static func haptic(_ kind: String) {
        switch kind {
        case "success": UINotificationFeedbackGenerator().notificationOccurred(.success)
        case "warning": UINotificationFeedbackGenerator().notificationOccurred(.warning)
        case "error": UINotificationFeedbackGenerator().notificationOccurred(.error)
        case "light": UIImpactFeedbackGenerator(style: .light).impactOccurred()
        case "heavy": UIImpactFeedbackGenerator(style: .heavy).impactOccurred()
        case "selection": UISelectionFeedbackGenerator().selectionChanged()
        default: UIImpactFeedbackGenerator(style: .medium).impactOccurred()
        }
    }

    private static func authenticate() async -> Bool {
        let context = LAContext()
        return (try? await context.evaluatePolicy(.deviceOwnerAuthentication, localizedReason: "Confirm before your assistant goes ahead")) ?? false
    }
}

/// An action as it was written, read once: its steps run in order, the verbs
/// of each in the fixed order. What is wrong with it is known before any tap.
struct Action {
    struct Verb {
        let name: String
        let raw: JSONValue
        let value: Dynamic
    }

    struct Step {
        var requiresFaceID = false
        var verbs: [Verb] = []
        var say: Dynamic?
        var input: Dynamic?
        var args: Dynamic?
        /// What a `show` opens the screen with, as written: its props.
        var with: JSONValue?
        /// A `show` asked as a sheet, and one that takes the place of the screen on top.
        var sheet = false
        var replace = false
        /// The step written as a reference (`"$onPick"`), without its `$`:
        /// the action is what that names where it runs.
        var reference: String?
        /// Why the step is not one, when it is neither an object nor a reference.
        var invalid: String?
    }

    let steps: [Step]
    /// The action as it was written, for what carries it elsewhere (a widget's link).
    let written: JSONValue

    init(_ action: JSONValue) {
        written = action
        steps = (action.array ?? [action]).map { step in
            if let written = step.string, Template.of(written).isReference {
                return Step(reference: String(written.dropFirst()))
            }
            guard let object = step.object else {
                return Step(invalid: "An action must be an object, got \(step.text)")
            }
            return Step(
                requiresFaceID: object["require"]?.string == "faceid",
                verbs: ActionRunner.order(object.keys).map { Verb(name: $0, raw: object[$0] ?? .null, value: Dynamic(object[$0] ?? .null)) },
                say: object["say"].map(Dynamic.init),
                input: object["input"].map(Dynamic.init),
                args: object["args"].map(Dynamic.init),
                with: object["with"],
                sheet: object["as"]?.string == "sheet",
                replace: object["replace"]?.truthy ?? false
            )
        }
    }

    /// What is wrong with it as written: a step that is not an object, a verb
    /// that does not exist, an expression that cannot be read.
    var problems: [String] {
        steps.flatMap { step -> [String] in
            if let invalid = step.invalid { return [invalid] }
            let unknown = step.verbs.filter { !ActionRunner.verbs.contains($0.name) }.map { "Unknown action '\($0.name)'" }
            let unread = step.verbs.flatMap(\.value.problems) + [step.say, step.input, step.args].compactMap { $0 }.flatMap(\.problems)
            return unknown + unread
        }
    }
}

