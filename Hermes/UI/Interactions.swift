// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import SwiftUI
import UIKit

/// What a finger can do to a node besides tapping it. `actions` is a list of
/// titled handlers: the hold menu on any node, and swipe actions on a row of a
/// ForEach. A ForEach with `onMove` lets its rows be held and dragged into a new
/// order. The handlers are the ones a Button holds, fired from another place.
enum Interactions {
    /// A titled action as it is offered: in a hold menu, behind a swipe, in a `Menu`.
    struct Item: Identifiable {
        let id: Int
        let title: String
        let symbol: String?
        let role: ButtonRole?
        let leading: Bool
        let destructive: Bool
        let action: Action
    }

    /// A list of titled actions as written (`actions`, a `Menu`'s `items`),
    /// read once: the titles and symbols are resolved when it is drawn.
    struct Decoded {
        private struct Entry {
            let index: Int
            let title: Dynamic?
            let symbol: Dynamic?
            let role: String?
            let leading: Bool
            /// Nil when the entry has nothing but its title: it does nothing.
            let action: Action?
        }

        private let entries: [Entry]?
        /// What is wrong with the list as written.
        let problems: [String]

        init(_ value: JSONValue) {
            guard let list = value.array else {
                entries = nil
                problems = ["actions is a list of {title, symbol, role, edge, …action}"]
                return
            }
            var problems: [String] = []
            entries = list.enumerated().map { index, entry in
                guard var object = entry.object, object["title"] != nil else {
                    problems.append("actions[\(index)] needs a title")
                    return Entry(index: index, title: nil, symbol: nil, role: nil, leading: false, action: nil)
                }
                let title = object["title"].map(Dynamic.init)
                let symbol = object["symbol"].map(Dynamic.init)
                let role = object["role"]?.string
                let leading = object["edge"]?.string == "leading"
                for key in own { object[key] = nil }
                let action = object.isEmpty ? nil : Action(.object(object))
                problems += (title?.problems ?? []) + (symbol?.problems ?? []) + (action?.problems ?? [])
                return Entry(index: index, title: title, symbol: symbol, role: role, leading: leading, action: action)
            }
            self.problems = problems
        }

        /// The actions to offer here: those with a title once resolved, that do something.
        func items(_ scope: Scope) -> [Item] {
            guard let entries else {
                scope.context.report("actions is a list of {title, symbol, role, edge, …action}")
                return []
            }
            return entries.compactMap { entry in
                let title = scope.text(entry.title)
                guard !title.isEmpty else {
                    scope.context.report("actions[\(entry.index)] needs a title")
                    return nil
                }
                let symbol = entry.symbol.map { scope.text($0) }
                if let symbol { Views.checkSymbol(symbol, scope) }
                guard let action = entry.action else {
                    scope.context.report("actions[\(entry.index)] '\(title)' does nothing: give it an action (send, edit, open…)")
                    return nil
                }
                return Item(id: entry.index, title: title, symbol: symbol?.isEmpty == true ? nil : symbol,
                            role: entry.role == "destructive" ? .destructive : nil, leading: entry.leading,
                            destructive: entry.role == "destructive", action: action)
            }
        }
    }

    private static let own: Set<String> = ["title", "symbol", "role", "edge"]

    static func apply(_ actions: Decoded?, to view: AnyView, _ scope: Scope, row: Bool, move: (list: Reorder.List, index: Int)?) -> AnyView {
        var view = view
        let actions = actions?.items(scope) ?? []
        if !actions.isEmpty {
            if move == nil {
                view = AnyView(view.contextMenu {
                    ForEach(actions) { action in
                        Button(action.title, systemImage: action.symbol ?? "", role: action.role) { run(action, scope) }
                    }
                })
            }
            if row {
                view = AnyView(view.modifier(SwipeRow(leading: actions.filter(\.leading), trailing: actions.filter { !$0.leading }) { run($0, scope) }))
            }
        }
        if let move {
            view = AnyView(view.modifier(ReorderRow(list: move.list, index: move.index)))
        }
        return view
    }

    /// The titled actions a value holds, as offered in a scope.
    static func parse(_ value: JSONValue, _ scope: Scope) -> [Item] {
        Decoded(value).items(scope)
    }

    static func run(_ item: Item, _ scope: Scope) {
        ActionRunner.run(item.action, title: item.title, in: scope)
    }
}

/// A pan that only a row's swipe takes: sideways, and only towards actions it
/// has. The page's own swipe waits for it, so a row with actions never turns
/// the page by mistake.
final class RowPanRecognizer: UIPanGestureRecognizer {}

struct RowPan: UIGestureRecognizerRepresentable {
    /// Whether a pull in that direction (negative towards the trailing edge) reveals anything.
    let allowed: (CGFloat) -> Bool
    let changed: (CGFloat) -> Void
    let ended: (_ travel: CGFloat, _ speed: CGFloat) -> Void

    func makeCoordinator(converter: CoordinateSpaceConverter) -> Coordinator { Coordinator(allowed: allowed) }

    func makeUIGestureRecognizer(context: Context) -> RowPanRecognizer {
        let pan = RowPanRecognizer()
        pan.delegate = context.coordinator
        return pan
    }

    func updateUIGestureRecognizer(_ recognizer: RowPanRecognizer, context: Context) {
        context.coordinator.allowed = allowed
    }

    func handleUIGestureRecognizerAction(_ pan: RowPanRecognizer, context: Context) {
        let travel = pan.translation(in: pan.view).x
        switch pan.state {
        case .changed: changed(travel)
        case .ended: ended(travel, pan.velocity(in: pan.view).x)
        case .cancelled, .failed: ended(0, 0)
        default: break
        }
    }

    final class Coordinator: NSObject, UIGestureRecognizerDelegate {
        var allowed: (CGFloat) -> Bool

        init(allowed: @escaping (CGFloat) -> Bool) {
            self.allowed = allowed
        }

        func gestureRecognizerShouldBegin(_ recognizer: UIGestureRecognizer) -> Bool {
            guard let pan = recognizer as? UIPanGestureRecognizer, let view = pan.view else { return false }
            let speed = pan.velocity(in: view)
            return abs(speed.x) > abs(speed.y) * 1.2 && allowed(speed.x)
        }

        func gestureRecognizer(_ recognizer: UIGestureRecognizer, shouldRecognizeSimultaneouslyWith other: UIGestureRecognizer) -> Bool {
            other.view is UIScrollView
        }
    }
}

/// A row that slides sideways over its actions: pulled a little, they show as
/// buttons; pulled past half the row, the first one runs when you let go.
struct SwipeRow: ViewModifier {
    let leading: [Interactions.Item]
    let trailing: [Interactions.Item]
    let run: (Interactions.Item) -> Void
    @State private var offset: CGFloat = 0
    @State private var rest: CGFloat = 0
    @State private var width: CGFloat = 0

    static let button: CGFloat = 76

    private var armed: Bool { width > 0 && abs(offset) > width * 0.5 }

    func body(content: Content) -> some View {
        content
            .offset(x: offset)
            .background(alignment: .trailing) {
                if offset < 0 { buttons(trailing, revealed: -offset) }
            }
            .background(alignment: .leading) {
                if offset > 0 { buttons(leading, revealed: offset) }
            }
            .overlay {
                if rest != 0 {
                    Color.clear.contentShape(.rect).onTapGesture { settle(to: 0) }
                }
            }
            .onGeometryChange(for: CGFloat.self) { $0.size.width } action: { width = $0 }
            .gesture(RowPan(allowed: { speed in rest != 0 || (speed < 0 ? !trailing.isEmpty : !leading.isEmpty) },
                            changed: { travel in offset = clamp(rest + travel) },
                            ended: { travel, speed in release(rest + travel, speed: speed) }))
            .sensoryFeedback(.impact(weight: .light), trigger: armed)
    }

    private func clamp(_ value: CGFloat) -> CGFloat {
        min(max(value, trailing.isEmpty ? 0 : -width), leading.isEmpty ? 0 : width)
    }

    private func release(_ value: CGFloat, speed: CGFloat) {
        let actions = value < 0 ? trailing : leading
        guard let first = actions.first else { return settle(to: 0) }
        if abs(value) > width * 0.5 {
            run(first)
            return settle(to: 0)
        }
        let open = CGFloat(actions.count) * Self.button
        let towardsOpen = value < 0 ? speed < -200 : speed > 200
        let towardsClosed = value < 0 ? speed > 200 : speed < -200
        if towardsClosed || (!towardsOpen && abs(value) < open * 0.5) {
            settle(to: 0)
        } else {
            settle(to: value < 0 ? -open : open)
        }
    }

    private func settle(to value: CGFloat) {
        withAnimation(.snappy(duration: 0.3)) {
            offset = value
            rest = value
        }
    }

    @ViewBuilder private func buttons(_ actions: [Interactions.Item], revealed: CGFloat) -> some View {
        let shown = armed ? Array(actions.prefix(1)) : actions
        HStack(spacing: 0) {
            ForEach(shown) { action in
                Button {
                    run(action)
                    settle(to: 0)
                } label: {
                    VStack(spacing: 4) {
                        if let symbol = action.symbol {
                            Image(systemName: symbol).font(.title3)
                        }
                        Text(action.title)
                            .font(.caption2.weight(.medium))
                            .lineLimit(1)
                    }
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                    .contentShape(.rect)
                }
                .buttonStyle(.plain)
                .foregroundStyle(.white)
                .background(color(action))
            }
        }
        .frame(width: revealed)
        .clipShape(.rect(cornerRadius: 16, style: .continuous))
        .animation(.snappy(duration: 0.25), value: shown.count)
    }

    private func color(_ action: Interactions.Item) -> Color {
        if action.destructive { return .red }
        return action.id == (action.leading ? leading : trailing).first?.id ? .accentColor : Color(.systemGray)
    }
}

/// Rows dragged into another order: held, lifted, moved over their neighbours,
/// which make room; let go, the list they come from takes the new order and the
/// agent hears of it, or the ForEach's `onMove` action runs with `$from`, `$to`,
/// `$item` and `$order`.
enum Reorder {
    @Observable
    final class List {
        let key: String
        var frames: [Int: CGRect] = [:]
        var dragging: (from: Int, to: Int, height: CGFloat)?
        @ObservationIgnored var source: JSONValue = .null
        @ObservationIgnored var elements: [JSONValue] = []
        @ObservationIgnored var handler: JSONValue = .null
        @ObservationIgnored var scope: Scope?

        init(key: String) {
            self.key = key
        }

        /// How far a row steps aside while another is dragged over its place.
        func shift(for index: Int) -> CGFloat {
            guard let dragging, index != dragging.from else { return 0 }
            if dragging.from < dragging.to, index > dragging.from, index <= dragging.to { return -dragging.height }
            if dragging.to < dragging.from, index >= dragging.to, index < dragging.from { return dragging.height }
            return 0
        }

        /// The place a row dragged by `travel` would take: the row whose middle is nearest its own.
        func target(from index: Int, travel: CGFloat) -> Int {
            guard let own = frames[index] else { return index }
            let middle = own.midY + travel
            return frames.min { abs($0.value.midY - middle) < abs($1.value.midY - middle) }?.key ?? index
        }
    }

    nonisolated(unsafe) private static var lists: [String: List] = [:]

    /// The list a ForEach's rows belong to, the same across renders so a drag
    /// survives them, with what it needs to move an element when one is dropped.
    static func list(at path: String, source: JSONValue, elements: [JSONValue], handler: JSONValue, _ scope: Scope) -> List {
        let key = "\(scope.context.cardID)\(path)"
        let list = lists[key] ?? List(key: key)
        lists[key] = list
        list.source = source
        list.elements = elements
        list.handler = handler
        list.scope = scope
        return list
    }

    static func move(_ list: List, from: Int, to: Int) {
        guard let scope = list.scope, from != to, list.elements.indices.contains(from), list.elements.indices.contains(to) else { return }
        var order = list.elements
        order.insert(order.remove(at: from), at: to)
        let moved = moveSource(list.source, to: .array(order), scope)
        if list.handler.object != nil || list.handler.array != nil {
            ActionRunner.run(list.handler, in: scope.with(["from": .number(Double(from)), "to": .number(Double(to)), "item": list.elements[from], "order": .array(order)]))
        } else if !moved {
            scope.context.fail("onMove: the app cannot reorder \(list.source.text) itself, it is not a state or a store; give onMove an action that edits where the list lives, with $order", tapped: nil)
        }
    }

    /// Gives the list's source its new order when the app holds it: a state
    /// name, or a store, edited and so told to the agent.
    private static func moveSource(_ source: JSONValue, to order: JSONValue, _ scope: Scope) -> Bool {
        guard let reference = source.string, reference.hasPrefix("$") else { return false }
        let path = reference.dropFirst().split(separator: ".").map(String.init)
        guard let root = path.first, root.range(of: #"^[A-Za-z_][A-Za-z0-9_]*$"#, options: .regularExpression) != nil else { return false }
        if let box = scope.boxes.last(where: { $0.values[root] != nil }) {
            box.values[root] = set(box.values[root] ?? .null, at: Array(path.dropFirst()), to: order)
            return true
        }
        guard ActionRunner.hasStore?(root) == true else { return false }
        var patch: [String: JSONValue] = ["store": .string(root)]
        if path.count == 1 {
            patch["replace"] = order
        } else {
            patch.merge(set(.object([:]), at: Array(path.dropFirst()), to: order).object ?? [:]) { $1 }
        }
        if let problem = ActionRunner.edit?(.object(patch), scope.context.cardID) {
            scope.context.fail(problem, tapped: nil)
        }
        return true
    }

    private static func set(_ value: JSONValue, at path: [String], to new: JSONValue) -> JSONValue {
        guard let key = path.first else { return new }
        var object = value.object ?? [:]
        object[key] = set(object[key] ?? .null, at: Array(path.dropFirst()), to: new)
        return .object(object)
    }
}

struct ReorderRow: ViewModifier {
    let list: Reorder.List
    let index: Int
    @State private var travel: CGFloat = 0
    @State private var lifted = false
    @State private var height: CGFloat = 0

    func body(content: Content) -> some View {
        let shift = list.shift(for: index)
        content
            .onGeometryChange(for: CGRect.self) { $0.frame(in: .named(CardContext.space)) } action: { frame in
                list.frames[index] = frame
                height = frame.height
            }
            .offset(y: lifted ? travel : shift)
            .scaleEffect(lifted ? 1.03 : 1)
            .shadow(color: .black.opacity(lifted ? 0.18 : 0), radius: 14, y: 8)
            .zIndex(lifted ? 1 : 0)
            .animation(.snappy(duration: 0.25), value: shift)
            .animation(.snappy(duration: 0.25), value: lifted)
            .sensoryFeedback(.impact(weight: .medium), trigger: lifted) { $1 }
            .gesture(
                LongPressGesture(minimumDuration: 0.4)
                    .sequenced(before: DragGesture(minimumDistance: 0))
                    .onChanged { value in
                        switch value {
                        case .first(true):
                            break
                        case .second(true, let drag):
                            if !lifted {
                                lifted = true
                                list.dragging = (index, index, height)
                            }
                            if let drag {
                                travel = drag.translation.height
                                list.dragging = (index, list.target(from: index, travel: travel), height)
                            }
                        default:
                            break
                        }
                    }
                    .onEnded { _ in
                        let to = list.dragging?.to ?? index
                        lifted = false
                        travel = 0
                        list.dragging = nil
                        if to != index { Reorder.move(list, from: index, to: to) }
                    }
            )
    }
}
