// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import SwiftUI

/// `VStack`, `HStack`, `ZStack`.
struct StackSpec: ViewSpec {
    enum Axis {
        case vertical, horizontal, depth
    }

    let axis: Axis
    let alignment: Dynamic?
    let spacing: Dynamic?
    let children: Children

    init(_ axis: Axis, _ reader: inout Reader) {
        self.axis = axis
        alignment = reader.value("alignment")
        spacing = axis == .depth ? nil : reader.value("spacing")
        children = reader.mainChildren()
    }

    func view(_ scope: Scope, _ element: Element) -> AnyView {
        let alignment = scope.string(alignment)
        switch axis {
        case .vertical:
            return AnyView(VStack(alignment: Tokens.horizontal(alignment), spacing: scope.length(spacing)) { Tree.children(children, scope) })
        case .horizontal:
            return AnyView(HStack(alignment: Tokens.vertical(alignment), spacing: scope.length(spacing)) { Tree.children(children, scope) })
        case .depth:
            return AnyView(ZStack(alignment: Tokens.alignment(alignment)) { Tree.children(children, scope) })
        }
    }
}

struct GroupSpec: ViewSpec {
    let children: Children

    init(_ reader: inout Reader) {
        children = reader.mainChildren()
    }

    func view(_ scope: Scope, _ element: Element) -> AnyView {
        AnyView(Group { Tree.children(children, scope) })
    }
}

struct CardSpec: ViewSpec {
    let spacing: Dynamic?
    let children: Children

    init(_ reader: inout Reader) {
        spacing = reader.value("spacing")
        children = reader.mainChildren()
    }

    func view(_ scope: Scope, _ element: Element) -> AnyView {
        AnyView(VStack(alignment: .leading, spacing: scope.length(spacing) ?? 12) {
            Tree.children(children, scope)
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .modifier(CardSurface()))
    }
}

struct SectionSpec: ViewSpec {
    let title: Dynamic?
    let content: Children
    let footer: Dynamic?

    init(_ reader: inout Reader) {
        title = reader.main == .null ? nil : reader.mainValue()
        content = reader.children("content")
        footer = reader.value("footer")
    }

    func view(_ scope: Scope, _ element: Element) -> AnyView {
        AnyView(VStack(alignment: .leading, spacing: 10) {
            if let title {
                Text(scope.text(title)).font(.title3.bold())
            }
            Tree.children(content, scope)
            if let footer {
                Text(scope.text(footer)).font(.footnote).foregroundStyle(.secondary)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading))
    }
}

/// A page's widgets in two columns on a wide display (see PageColumns): the
/// app's own, not a view the agent writes.
struct MasonrySpec: ViewSpec {
    let spacing: Dynamic?
    let gap: Dynamic?
    let children: Children

    init(_ reader: inout Reader) {
        spacing = reader.value("spacing")
        gap = reader.value("hSpacing")
        children = reader.mainChildren()
    }

    func view(_ scope: Scope, _ element: Element) -> AnyView {
        AnyView(MasonryLayout(spacing: scope.length(spacing) ?? 16, gap: scope.length(gap) ?? 16) {
            Tree.children(children, scope)
        }
        .frame(maxWidth: .infinity, alignment: .topLeading))
    }
}

struct ColumnsSpec: ViewSpec {
    let spacing: Dynamic?
    let minWidth: Dynamic?
    let count: Dynamic?
    let children: Children

    init(_ reader: inout Reader) {
        spacing = reader.value("spacing")
        minWidth = reader.value("minWidth")
        count = reader.value("count")
        children = reader.mainChildren()
    }

    func view(_ scope: Scope, _ element: Element) -> AnyView {
        let spacing = scope.length(spacing) ?? 12
        let columns: [GridItem] = if let minWidth = scope.number(minWidth) {
            [GridItem(.adaptive(minimum: minWidth), spacing: spacing, alignment: .topLeading)]
        } else {
            Array(repeating: GridItem(.flexible(), spacing: spacing, alignment: .topLeading), count: min(max(1, scope.int(count) ?? 2), 12))
        }
        return AnyView(LazyVGrid(columns: columns, alignment: .leading, spacing: spacing) {
            Tree.children(children, scope)
        })
    }
}

struct GridSpec: ViewSpec {
    let alignment: Dynamic?
    let hSpacing: Dynamic?
    let vSpacing: Dynamic?
    let rows: Children

    init(_ reader: inout Reader) {
        alignment = reader.value("alignment")
        hSpacing = reader.value("hSpacing")
        vSpacing = reader.value("vSpacing")
        rows = reader.mainChildren()
    }

    func view(_ scope: Scope, _ element: Element) -> AnyView {
        let rows = Tree.items(rows, scope)
        return AnyView(Grid(alignment: Tokens.alignment(scope.string(alignment) ?? "leading"),
                            horizontalSpacing: scope.length(hSpacing), verticalSpacing: scope.length(vSpacing)) {
            ForEach(rows) { row in
                if case .list(let cells) = row.node {
                    GridRow {
                        ForEach(Tree.items(Children(list: cells), row.scope, prefix: "\(row.id)-")) { cell in
                            TreeView(node: cell.node, scope: cell.scope)
                        }
                    }
                } else {
                    TreeView(node: row.node, scope: row.scope)
                }
            }
        })
    }
}

struct ScrollViewSpec: ViewSpec {
    let spacing: Dynamic?
    let axis: String?
    let paging: Condition?
    let children: Children

    init(_ reader: inout Reader) {
        spacing = reader.value("spacing")
        axis = reader.word("axis")
        paging = reader.condition("paging")
        children = reader.mainChildren()
    }

    func view(_ scope: Scope, _ element: Element) -> AnyView {
        let scope = scope.unprobed
        let spacing = scope.length(spacing) ?? 12
        guard axis == "horizontal" else {
            return AnyView(ScrollView {
                VStack(alignment: .leading, spacing: spacing) { Tree.children(children, scope) }
            })
        }
        let content = ScrollView(.horizontal) {
            HStack(alignment: .top, spacing: spacing) { Tree.children(children, scope) }
                .scrollTargetLayout()
        }
        .scrollIndicators(.hidden)
        if paging?.holds(scope) == true {
            return AnyView(content.scrollTargetBehavior(.viewAligned))
        }
        return AnyView(content)
    }
}

struct CarouselSpec: ViewSpec {
    let pageWidth: Dynamic?
    let spacing: Dynamic?
    let children: Children

    init(_ reader: inout Reader) {
        pageWidth = reader.value("pageWidth")
        spacing = reader.value("spacing")
        children = reader.mainChildren()
    }

    func view(_ scope: Scope, _ element: Element) -> AnyView {
        let fraction = scope.number(pageWidth) ?? 0.85
        var scope = scope
        scope.sideways = true
        return AnyView(ScrollView(.horizontal) {
            LazyHStack(alignment: .top, spacing: scope.length(spacing) ?? 12) {
                ForEach(Tree.items(children, scope)) { item in
                    TreeView(node: item.node, scope: item.scope)
                        .containerRelativeFrame(.horizontal) { width, _ in width * fraction }
                }
            }
            .scrollTargetLayout()
        }
        .scrollTargetBehavior(.viewAligned)
        .scrollIndicators(.hidden))
    }
}

struct PagesSpec: ViewSpec {
    let dots: Condition?
    let children: Children

    init(_ reader: inout Reader) {
        dots = reader.condition("dots")
        children = reader.mainChildren()
    }

    func view(_ scope: Scope, _ element: Element) -> AnyView {
        let scope = scope.unprobed
        let dots = dots?.holds(scope) ?? true
        return AnyView(TabView {
            ForEach(Tree.items(children, scope)) { item in
                TreeView(node: item.node, scope: item.scope)
            }
        }
        .tabViewStyle(.page(indexDisplayMode: dots ? .always : .never))
        .indexViewStyle(.page(backgroundDisplayMode: .interactive))
        .frame(height: element.facts.hasHeight ? nil : 220))
    }
}

struct DisclosureGroupSpec: ViewSpec {
    let title: Dynamic
    let expanded: JSONValue?
    let content: Children

    init(_ reader: inout Reader) {
        title = reader.mainValue()
        expanded = reader.raw("expanded")
        content = reader.children("content")
    }

    func view(_ scope: Scope, _ element: Element) -> AnyView {
        if let expanded = scope.binding(expanded) {
            return AnyView(DisclosureGroup(isExpanded: Binding(get: { expanded.wrappedValue.truthy }, set: { expanded.wrappedValue = .bool($0) })) {
                VStack(alignment: .leading, spacing: 10) { Tree.children(content, scope) }
                    .padding(.top, 8)
            } label: {
                Text(scope.text(title))
            })
        }
        return AnyView(DisclosureGroup(scope.text(title)) {
            VStack(alignment: .leading, spacing: 10) { Tree.children(content, scope) }
                .padding(.top, 8)
        })
    }
}

struct GlassGroupSpec: ViewSpec {
    let spacing: Dynamic?
    let children: Children

    init(_ reader: inout Reader) {
        spacing = reader.value("spacing")
        children = reader.mainChildren()
    }

    func view(_ scope: Scope, _ element: Element) -> AnyView {
        let spacing = scope.length(spacing) ?? 12
        return AnyView(GlassEffectContainer(spacing: spacing) {
            HStack(spacing: spacing) { Tree.children(children, scope) }
        })
    }
}

struct SpacerSpec: ViewSpec {
    let minLength: Dynamic

    init(_ reader: inout Reader) {
        minLength = reader.mainValue()
    }

    func view(_ scope: Scope, _ element: Element) -> AnyView {
        AnyView(Spacer(minLength: scope.length(minLength)))
    }
}

struct DividerSpec: ViewSpec {
    init(_ reader: inout Reader) {}

    func view(_ scope: Scope, _ element: Element) -> AnyView {
        AnyView(Divider())
    }
}

extension Scope {
    /// The same scope for what is not measured: the inside of a scroll view or
    /// of pages, which runs past the card on purpose.
    var unprobed: Scope {
        var scope = self
        scope.probes = false
        return scope
    }
}

/// `{"List": list, "as", "index", "content"}`: a `ForEach` for a long list,
/// its rows drawn only as they scroll into view, separators between them.
struct ListSpec: ViewSpec {
    let source: Dynamic
    let name: String
    let indexName: String
    let content: Children

    init(_ reader: inout Reader) {
        source = reader.mainValue()
        name = reader.word("as") ?? "item"
        indexName = reader.word("index") ?? "index"
        content = reader.children("content")
    }

    /// A check draws this many rows of a List: the rest scroll into view
    /// on the phone and look like the first.
    static let probedRows = 12

    func view(_ scope: Scope, _ element: Element) -> AnyView {
        let resolved = source.resolve(scope)
        let elements = resolved.array ?? resolved.object.map { $0.sorted { $0.key < $1.key }.map { JSONValue.object(["key": .string($0.key), "value": $0.value]) } } ?? []
        if resolved != .null, resolved.array == nil, resolved.object == nil {
            scope.context.report("List needs a list, got \(resolved.text)")
        }
        let shown = scope.checking ? Array(elements.prefix(ListSpec.probedRows)) : elements
        let rows: [(id: String, items: [ChildItem])] = shown.enumerated().map { index, element in
            let elementID = element["id"]?.text ?? "\(index)"
            var inner = scope.with([name: element, indexName: .number(Double(index))])
            inner.path += "List[\(index)]"
            inner.row = true
            return (elementID, Tree.items(content, inner, prefix: "\(elementID)-"))
        }
        return AnyView(LazyVStack(alignment: .leading, spacing: 0) {
            ForEach(Array(rows.enumerated()), id: \.element.id) { place, row in
                VStack(alignment: .leading, spacing: 0) {
                    ForEach(row.items) { item in
                        TreeView(node: item.node, scope: item.scope)
                    }
                }
                .padding(.vertical, 8)
                .frame(maxWidth: .infinity, alignment: .leading)
                if place < rows.count - 1 {
                    Divider()
                }
            }
        })
    }
}
