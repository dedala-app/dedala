// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import SwiftUI
import UIKit

struct ButtonSpec: ViewSpec {
    let title: Dynamic
    let label: Node?
    let symbol: Dynamic?
    let role: String?
    let action: Action?
    let style: Dynamic?

    init(_ reader: inout Reader) {
        label = reader.mainNode()
        title = reader.mainValue()
        symbol = reader.value("symbol")
        role = reader.word("role")
        action = reader.action("action")
        style = reader.value("style")
    }

    func view(_ scope: Scope, _ element: Element) -> AnyView {
        let title = label != nil ? (element.facts.accessibilityLabel.map { scope.text($0) } ?? "") : scope.text(title)
        let symbol = symbol.map { scope.text($0) }
        if let symbol { Views.checkSymbol(symbol, scope) }
        let role: ButtonRole? = switch role {
        case "destructive": .destructive
        case "cancel": .cancel
        default: nil
        }
        let fills = element.facts.fillsWidth
        let content = Group {
            if let label {
                TreeView(node: label, scope: scope)
            } else if let symbol {
                Label(title, systemImage: symbol)
            } else {
                Text(title)
            }
        }
        .frame(maxWidth: fills ? .infinity : nil)
        if action == nil {
            scope.context.report("Button '\(title)' has no action")
        }
        if let link = Views.widgetLink {
            guard let url = action.flatMap({ link($0.written) }) else { return AnyView(content.opacity(0.5)) }
            return AnyView(Link(destination: url) { content })
        }
        let button = Button(role: role) {
            ActionRunner.run(action, title: title, in: scope)
        } label: {
            content
        }
        switch scope.string(style) {
        case "prominent": return AnyView(button.buttonStyle(.glassProminent))
        case "glass": return AnyView(button.buttonStyle(.glass))
        case "bordered": return AnyView(button.buttonStyle(.bordered))
        case "borderedProminent": return AnyView(button.buttonStyle(.borderedProminent))
        case "plain": return AnyView(button.buttonStyle(.plain))
        case "borderless": return AnyView(button.buttonStyle(.borderless))
        default: return AnyView(button)
        }
    }
}

struct MenuSpec: ViewSpec {
    let title: Dynamic
    let label: Node?
    let symbol: Dynamic?
    let items: Interactions.Decoded?
    let style: Dynamic?

    init(_ reader: inout Reader) {
        label = reader.mainNode()
        title = reader.mainValue()
        symbol = reader.value("symbol")
        items = reader.raw("items").map(Interactions.Decoded.init)
        items?.problems.forEach { reader.report($0) }
        style = reader.value("style")
    }

    func view(_ scope: Scope, _ element: Element) -> AnyView {
        let title = label != nil ? "" : scope.text(title)
        let symbol = symbol.map { scope.text($0) }
        if let symbol { Views.checkSymbol(symbol, scope) }
        let items = items?.items(scope) ?? []
        if items.isEmpty { scope.context.report("Menu needs items: [{title, symbol, role, …action}]") }
        let menu = Menu {
            ForEach(items) { item in
                Button(item.title, systemImage: item.symbol ?? "", role: item.role) { Interactions.run(item, scope) }
            }
        } label: {
            if let label {
                TreeView(node: label, scope: scope)
            } else if let symbol, title.isEmpty {
                Image(systemName: symbol).accessibilityLabel(element.facts.accessibilityLabel.map { scope.text($0) } ?? "More")
            } else if let symbol {
                Label(title, systemImage: symbol)
            } else {
                Text(title)
            }
        }
        switch scope.string(style) {
        case "bordered": return AnyView(menu.buttonStyle(.bordered))
        case "borderedProminent": return AnyView(menu.buttonStyle(.borderedProminent))
        case "glass": return AnyView(menu.buttonStyle(.glass))
        default: return AnyView(menu)
        }
    }
}

/// What every input has: the state it changes and what runs when it does.
struct Bound {
    let view: String
    let reference: JSONValue?
    let onChange: JSONValue?

    init(_ reader: inout Reader) {
        view = reader.view
        (reference, onChange) = reader.binding()
    }

    func binding(_ scope: Scope) -> Binding<JSONValue>? {
        guard let binding = scope.binding(reference, onChange: onChange) else {
            if reference?.string == nil { scope.context.report("\(view) needs bind: \"$name\"") }
            return nil
        }
        return binding
    }
}

struct ToggleSpec: ViewSpec {
    let title: Dynamic
    let bound: Bound

    init(_ reader: inout Reader) {
        title = reader.mainValue()
        bound = Bound(&reader)
    }

    func view(_ scope: Scope, _ element: Element) -> AnyView {
        guard let binding = bound.binding(scope) else { return AnyView(EmptyView()) }
        return AnyView(Toggle(isOn: Binding(get: { binding.wrappedValue.truthy }, set: { binding.wrappedValue = .bool($0) })) {
            Tree.markdown(scope.text(title))
        })
    }
}

struct PickerSpec: ViewSpec {
    private struct Option: Identifiable {
        let id: Int
        let label: String
        let value: JSONValue
        let symbol: String?
    }

    let title: Dynamic
    let bound: Bound
    let options: Dynamic?
    let style: Dynamic?

    init(_ reader: inout Reader) {
        title = reader.mainValue()
        bound = Bound(&reader)
        options = reader.value("options")
        style = reader.value("style")
    }

    func view(_ scope: Scope, _ element: Element) -> AnyView {
        guard let binding = bound.binding(scope) else { return AnyView(EmptyView()) }
        let options = (scope.value(options)?.array ?? []).enumerated().map { index, option in
            if option.object != nil {
                let label = option["label"]?.text ?? option["value"]?.text ?? ""
                return Option(id: index, label: label, value: option["value"] ?? .string(label), symbol: option["symbol"]?.string)
            }
            return Option(id: index, label: option.text, value: option, symbol: nil)
        }
        if options.isEmpty {
            scope.context.report("Picker needs options")
        }
        let picker = Picker(scope.text(title), selection: binding) {
            ForEach(options) { option in
                Group {
                    if let symbol = option.symbol {
                        Label(option.label, systemImage: symbol)
                    } else {
                        Text(option.label)
                    }
                }
                .tag(option.value)
            }
        }
        switch scope.string(style) {
        case "segmented": return AnyView(picker.pickerStyle(.segmented))
        case "wheel": return AnyView(picker.pickerStyle(.wheel))
        case "inline": return AnyView(picker.pickerStyle(.inline))
        case "palette": return AnyView(picker.pickerStyle(.palette))
        default: return AnyView(picker.pickerStyle(.menu))
        }
    }
}

struct SliderSpec: ViewSpec {
    let title: Dynamic
    let bound: Bound
    let range: Dynamic?
    let step: Dynamic?

    init(_ reader: inout Reader) {
        title = reader.mainValue()
        bound = Bound(&reader)
        range = reader.value("in")
        step = reader.value("step")
    }

    func view(_ scope: Scope, _ element: Element) -> AnyView {
        guard let binding = bound.binding(scope) else { return AnyView(EmptyView()) }
        let range = Views.range(range, scope)
        let number = Binding(get: { min(max(binding.wrappedValue.number ?? range.lowerBound, range.lowerBound), range.upperBound) }, set: { binding.wrappedValue = .number($0) })
        if let step = scope.step(step) {
            return AnyView(Slider(value: number, in: range, step: step).accessibilityLabel(scope.text(title)))
        }
        return AnyView(Slider(value: number, in: range).accessibilityLabel(scope.text(title)))
    }
}

struct StepperSpec: ViewSpec {
    let title: Dynamic
    let bound: Bound
    let range: Dynamic?
    let step: Dynamic?

    init(_ reader: inout Reader) {
        title = reader.mainValue()
        bound = Bound(&reader)
        range = reader.value("in")
        step = reader.value("step")
    }

    func view(_ scope: Scope, _ element: Element) -> AnyView {
        guard let binding = bound.binding(scope) else { return AnyView(EmptyView()) }
        let range = Views.range(range, scope, default: 0...100)
        let number = Binding(get: { binding.wrappedValue.number ?? range.lowerBound }, set: { binding.wrappedValue = .number($0) })
        return AnyView(Stepper(value: number, in: range, step: scope.step(step) ?? 1) {
            Tree.markdown(scope.text(title))
        })
    }
}

struct TextFieldSpec: ViewSpec {
    let placeholder: Dynamic
    let bound: Bound
    let lines: Dynamic?
    let secure: Condition?
    let multiline: Condition?
    let style: Dynamic?

    init(_ reader: inout Reader) {
        placeholder = reader.mainValue()
        bound = Bound(&reader)
        lines = reader.value("lines")
        secure = reader.condition("secure")
        multiline = reader.condition("multiline")
        style = reader.value("style")
    }

    func view(_ scope: Scope, _ element: Element) -> AnyView {
        guard let binding = bound.binding(scope) else { return AnyView(EmptyView()) }
        let text = Binding(get: { binding.wrappedValue.text }, set: { binding.wrappedValue = .string($0) })
        let placeholder = scope.text(placeholder)
        let lines = scope.int(lines).map { min(max(1, $0), 100) }
        let field: AnyView = if secure?.holds(scope) == true {
            AnyView(SecureField(placeholder, text: text))
        } else if let lines {
            AnyView(TextField(placeholder, text: text, axis: .vertical).lineLimit(lines...max(lines, 8)))
        } else {
            AnyView(TextField(placeholder, text: text, axis: multiline?.holds(scope) == true ? .vertical : .horizontal))
        }
        switch scope.string(style) {
        case "plain":
            return AnyView(field.textFieldStyle(.plain))
        case "bordered", "roundedBorder":
            return AnyView(field.textFieldStyle(.roundedBorder))
        default:
            return AnyView(field.textFieldStyle(.plain)
                .padding(.horizontal, 12)
                .padding(.vertical, 9)
                .background(Color(.systemFill), in: RoundedRectangle(cornerRadius: 10, style: .continuous)))
        }
    }
}

/// `{"TextEditor": placeholder, "bind", "height", "font"}`: a whole text,
/// with the keyboard's toolbar; the cursor stays where it is when the page is
/// drawn again, as the binding keeps the view.
struct TextEditorSpec: ViewSpec {
    let placeholder: Dynamic
    let bound: Bound
    let height: Dynamic?
    let font: Dynamic?

    init(_ reader: inout Reader) {
        placeholder = reader.mainValue()
        bound = Bound(&reader)
        height = reader.value("height")
        font = reader.value("font")
    }

    func view(_ scope: Scope, _ element: Element) -> AnyView {
        guard let binding = bound.binding(scope) else { return AnyView(EmptyView()) }
        let text = Binding(get: { binding.wrappedValue.text }, set: { binding.wrappedValue = .string($0) })
        let placeholder = scope.text(placeholder)
        let height = scope.length(height)
        let mono = scope.string(font) == "mono"
        return AnyView(TextEditor(text: text)
            .font(mono ? .body.monospaced() : .body)
            .scrollContentBackground(.hidden)
            .frame(minHeight: height ?? 200, maxHeight: height)
            .padding(.horizontal, 8)
            .padding(.vertical, 6)
            .background(Color(.systemFill), in: RoundedRectangle(cornerRadius: 10, style: .continuous))
            .overlay(alignment: .topLeading) {
                if text.wrappedValue.isEmpty, !placeholder.isEmpty {
                    Text(placeholder)
                        .font(mono ? .body.monospaced() : .body)
                        .foregroundStyle(.tertiary)
                        .padding(.horizontal, 13)
                        .padding(.vertical, 14)
                        .allowsHitTesting(false)
                }
            })
    }
}

struct DatePickerSpec: ViewSpec {
    let title: Dynamic
    let bound: Bound
    let components: String?
    let style: Dynamic?

    init(_ reader: inout Reader) {
        title = reader.mainValue()
        bound = Bound(&reader)
        components = reader.word("components")
        style = reader.value("style")
    }

    func view(_ scope: Scope, _ element: Element) -> AnyView {
        guard let binding = bound.binding(scope) else { return AnyView(EmptyView()) }
        let date = Binding(get: { binding.wrappedValue.date ?? .now }, set: { binding.wrappedValue = JSONValue.iso($0) })
        let components: DatePickerComponents = switch components {
        case "date": [.date]
        case "time": [.hourAndMinute]
        default: [.date, .hourAndMinute]
        }
        let picker = DatePicker(scope.text(title), selection: date, displayedComponents: components)
        switch scope.string(style) {
        case "graphical": return AnyView(picker.datePickerStyle(.graphical))
        case "wheel": return AnyView(picker.datePickerStyle(.wheel))
        default: return AnyView(picker.datePickerStyle(.compact))
        }
    }
}

/// `{"Photo": title, "bind", "source"}`: a button that takes or picks a photo,
/// shown once chosen; the bound state holds the picture as the phone keeps it
/// (`{local, name, size, type}`) until an edit carries it to the agent.
struct PhotoSpec: ViewSpec {
    let title: Dynamic
    let bound: Bound
    let source: Dynamic?

    init(_ reader: inout Reader) {
        title = reader.mainValue()
        bound = Bound(&reader)
        source = reader.value("source")
    }

    func view(_ scope: Scope, _ element: Element) -> AnyView {
        guard let binding = bound.binding(scope) else { return AnyView(EmptyView()) }
        let title = scope.text(title)
        let source = scope.string(source) ?? "both"
        return AnyView(PhotoButton(title: title, source: source, binding: binding, scope: scope))
    }
}

private struct PhotoButton: View {
    let title: String
    let source: String
    let binding: Binding<JSONValue>
    let scope: Scope

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            if let local = binding.wrappedValue["local"]?.string, let image = UIImage(contentsOfFile: local) {
                Image(uiImage: image)
                    .resizable()
                    .scaledToFit()
                    .frame(maxHeight: 220)
                    .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
            }
            if Views.pickPhoto == nil {
                Label(title, systemImage: "camera")
                    .foregroundStyle(.secondary)
            } else if source == "both" {
                Menu {
                    Button("Take a photo", systemImage: "camera") { pick("camera") }
                    Button("Choose from library", systemImage: "photo.on.rectangle") { pick("library") }
                    if binding.wrappedValue["local"] != nil {
                        Button("Remove", systemImage: "xmark", role: .destructive) { binding.wrappedValue = .null }
                    }
                } label: {
                    Label(title, systemImage: "camera")
                }
                .buttonStyle(.bordered)
            } else {
                Button { pick(source) } label: {
                    Label(title, systemImage: source == "camera" ? "camera" : "photo.on.rectangle")
                }
                .buttonStyle(.bordered)
            }
        }
    }

    private func pick(_ source: String) {
        guard let pick = Views.pickPhoto else { return }
        Task { @MainActor in
            if let picked = await pick(source) { binding.wrappedValue = picked }
        }
    }
}

/// `{"Dictate": title, "bind", "append"}`: a microphone button; what is said
/// is recognised on the phone and written to the bound state as it comes.
struct DictateSpec: ViewSpec {
    let title: Dynamic
    let bound: Bound
    let append: Condition?

    init(_ reader: inout Reader) {
        title = reader.mainValue()
        bound = Bound(&reader)
        append = reader.condition("append")
    }

    func view(_ scope: Scope, _ element: Element) -> AnyView {
        guard let binding = bound.binding(scope) else { return AnyView(EmptyView()) }
        return AnyView(DictateButton(title: scope.text(title), append: append?.holds(scope) == true, binding: binding))
    }
}

private struct DictateButton: View {
    let title: String
    let append: Bool
    let binding: Binding<JSONValue>
    @State private var stop: (() -> Void)?
    @State private var before = ""

    var body: some View {
        Button {
            if let stop {
                stop()
                self.stop = nil
            } else if let dictate = Views.dictate {
                before = binding.wrappedValue.string ?? ""
                stop = dictate { heard, final in
                    let prefix = append && !before.isEmpty ? before + " " : ""
                    binding.wrappedValue = .string(prefix + heard)
                    if final { stop = nil }
                }
            }
        } label: {
            Label(title, systemImage: stop == nil ? "mic" : "mic.fill")
                .symbolEffect(.pulse, isActive: stop != nil)
        }
        .buttonStyle(.bordered)
        .tint(stop == nil ? nil : .red)
        .disabled(Views.dictate == nil)
    }
}
