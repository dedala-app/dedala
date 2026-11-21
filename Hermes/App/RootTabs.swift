// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import SwiftUI

/// The whole app, in the system's tab bar: your first three pages, which
/// stay, then the page you last opened from elsewhere, and apart at the end
/// Search, which finds everything and keeps your pages. The agent sits in a
/// small pill at their bottom corner, and his conversation opens over
/// everything.
struct RootTabs: View {
    @Environment(Router.self) private var router
    @Environment(Hub.self) private var hub
    @Environment(Listener.self) private var listener

    static let fixed = 3

    var body: some View {
        @Bindable var router = router
        let bar = hub.bar
        let fixed = Array(bar.prefix(Self.fixed))
        let moving = router.recent.flatMap { bar.contains($0) && !fixed.contains($0) ? $0 : nil } ?? bar.dropFirst(Self.fixed).first
        let tabs = fixed + (moving.map { [$0] } ?? [])
        TabView(selection: Binding(get: { router.tab.flatMap { tabs.contains($0) || $0 == Router.search ? $0 : nil } ?? tabs.first ?? Router.search },
                                   set: { router.tab = $0 })) {
            ForEach(fixed.enumerated().map(BarTab.init)) { item in
                Tab(value: item.page) {
                    Self.screen(item.page)
                } label: {
                    TabIcon(title: hub.tabName(item.page), symbol: hub.symbol(item.page))
                }
            }
            ForEach(moving.map { [$0] } ?? [], id: \.self) { id in
                Tab(value: id) {
                    Self.screen(id)
                } label: {
                    TabIcon(title: hub.tabName(id), symbol: hub.symbol(id))
                }
            }
            Tab("Search", systemImage: "magnifyingglass", value: Router.search, role: .search) {
                SearchView()
            }
        }
        .tabBarMinimizeBehavior(.onScrollDown)
        .tabViewSearchActivation(.searchTabSelection)
        .onChange(of: router.tab, initial: true) {
            router.pillFolded = false
            if let tab = router.tab, tab != Router.search, !fixed.contains(tab), bar.contains(tab) { router.recent = tab }
        }
        .sheet(isPresented: $router.chatOpen, onDismiss: router.read) {
            AgentConversation()
                .modifier(RouterSheets(active: true))
                .presentationDragIndicator(.visible)
        }
        .modifier(RouterSheets(active: !router.chatOpen))
        .overlay(alignment: .top) {
            if listener.state != .idle {
                ListeningPanel()
                    .padding(.horizontal, 16)
                    .padding(.top, 8)
                    .transition(.move(edge: .top).combined(with: .opacity))
            }
        }
        .animation(.snappy, value: listener.state)
        .animation(.snappy, value: listener.away)
        .onChange(of: hub.pageFocusRequests) {
            guard let id = hub.pageFocus else { return }
            if hub.pinned.contains(id) {
                router.show(page: id)
            } else {
                router.sheetPage = id
            }
        }
    }

    static func screen(_ id: String) -> some View {
        PageView(pageID: id, swipes: true)
            .agentPill(page: id)
    }
}

/// A page's tab: its name over its symbol. A symbol much wider than most,
/// three people side by side, is drawn shrunk to their width, so it does not
/// look bigger than its neighbours; the others are the system's own.
struct TabIcon: View {
    let title: String
    let symbol: String

    static let widest: CGFloat = 25
    @MainActor private static var shrunk: [String: UIImage] = [:]

    var body: some View {
        if let image = Self.fitted(symbol) {
            Label { Text(title) } icon: { Image(uiImage: image) }
        } else {
            Label(title, systemImage: symbol)
        }
    }

    @MainActor private static func fitted(_ name: String) -> UIImage? {
        if let image = shrunk[name] { return image }
        let configuration = UIImage.SymbolConfiguration(pointSize: 17, weight: .medium)
        guard let symbol = UIImage(systemName: name + ".fill", withConfiguration: configuration)
                ?? UIImage(systemName: name, withConfiguration: configuration),
              symbol.size.width > widest else { return nil }
        let size = CGSize(width: widest, height: symbol.size.height * widest / symbol.size.width)
        let image = UIGraphicsImageRenderer(size: size).image { _ in
            symbol.draw(in: CGRect(origin: .zero, size: size))
        }.withRenderingMode(.alwaysTemplate)
        shrunk[name] = image
        return image
    }
}

/// The sheets the app opens over what shows: a record, a screen, a page
/// outside the bar, Activity. Over the pages, or over the conversation while
/// it is open.
private struct RouterSheets: ViewModifier {
    @Environment(Router.self) private var router
    @Environment(Hub.self) private var hub
    let active: Bool

    func body(content: Content) -> some View {
        content
            .sheet(item: record(when: active && router.sheetPage == nil)) { ref in
                recordSheet(ref)
            }
            .sheet(item: screen(when: active && router.sheetPage == nil && router.sheetRecord == nil)) { shown in
                ScreenSheet(root: shown, stores: hub.stores) { router.sheetScreen = nil }
            }
            .sheet(item: Binding(get: { active ? router.sheetPage.map(SheetItem.init) : nil }, set: { router.sheetPage = $0?.id })) { sheet in
                PageView(pageID: sheet.id)
                    .sheet(item: record(when: true)) { ref in
                        recordSheet(ref)
                    }
                    .sheet(item: screen(when: router.sheetRecord == nil)) { shown in
                        ScreenSheet(root: shown, stores: hub.stores) { router.sheetScreen = nil }
                    }
                    .sheet(isPresented: activity(when: true)) {
                        ActivityView()
                    }
            }
            .sheet(isPresented: activity(when: active && router.sheetPage == nil)) {
                ActivityView()
            }
    }

    /// A record's sheet, with the screen its own bar or body asks for as a
    /// sheet presented from inside it: a view presents one sheet at a time,
    /// so one asked from the root would wait for the record to close.
    private func recordSheet(_ ref: RecordRef) -> some View {
        RecordSheet(ref: ref) { router.sheetRecord = nil }
            .sheet(item: screen(when: true)) { shown in
                ScreenSheet(root: shown, stores: hub.stores) { router.sheetScreen = nil }
            }
    }

    /// A record a card, a page or Search opened: over the page when one is
    /// open in a sheet, since a view presents one sheet at a time.
    private func record(when shown: Bool) -> Binding<RecordRef?> {
        Binding(get: { shown ? router.sheetRecord : nil }, set: { router.sheetRecord = $0 })
    }

    private func screen(when shown: Bool) -> Binding<Shown?> {
        Binding(get: { shown ? router.sheetScreen : nil }, set: { router.sheetScreen = $0 })
    }

    private func activity(when shown: Bool) -> Binding<Bool> {
        Binding(get: { shown && router.activity != nil }, set: { if !$0 { router.activity = nil } })
    }

    private struct SheetItem: Identifiable {
        let id: String
    }
}

/// A page swiped sideways goes to the next or the previous one in the bar's
/// order, as a pager does: the next page comes in beside it under the
/// finger, and past a third of the screen, or flicked, it takes the screen;
/// short of that, both spring back. At the first or the last page it resists.
/// A swipe from the screen's edge stays the way back.
struct PageSwipe: ViewModifier {
    @Environment(Router.self) private var router
    @Environment(Hub.self) private var hub
    let id: String
    var active = true
    @State private var drag: CGFloat = 0
    @State private var width: CGFloat = 390

    func body(content: Content) -> some View {
        if active { swiping(content) } else { content }
    }

    private func swiping(_ content: Content) -> some View {
        ZStack {
            if drag != 0, let next = neighbour(drag < 0 ? 1 : -1) {
                PageContent(pageID: next, navigator: Navigator())
                    .offset(x: drag + (drag < 0 ? width : -width))
                    .allowsHitTesting(false)
                    .accessibilityHidden(true)
            }
            content
                .offset(x: drag)
        }
        .onGeometryChange(for: CGFloat.self) { $0.size.width } action: { width = $0 }
        .gesture(SidewaysPan { travel in
            drag = neighbour(travel < 0 ? 1 : -1) == nil ? travel * 0.25 : travel
        } ended: { travel, speed in
            let landing = travel + speed * 0.25
            let step = landing < -width / 3 ? 1 : landing > width / 3 ? -1 : 0
            guard step != 0, let next = neighbour(step) else {
                withAnimation(.snappy) { drag = 0 }
                return
            }
            withAnimation(.snappy(duration: 0.28)) {
                drag = -CGFloat(step) * width
            } completion: {
                var settled = Transaction()
                settled.disablesAnimations = true
                withTransaction(settled) {
                    router.show(page: next)
                    drag = 0
                }
                UISelectionFeedbackGenerator().selectionChanged()
            }
        })
    }

    /// The page before (-1) or after (1) this one in the bar's order.
    private func neighbour(_ step: Int) -> String? {
        let bar = hub.bar
        guard let at = bar.firstIndex(of: id), bar.indices.contains(at + step) else { return nil }
        return bar[at + step]
    }
}

/// A pan that starts only when the finger goes more across than down and not
/// from the screen's edge, moves alongside the page's own scrolling, and
/// makes iOS's swipe back from anywhere wait for it. SwiftUI's drag loses
/// such swipes to the scroll view and to that swipe back.
private struct SidewaysPan: UIGestureRecognizerRepresentable {
    let changed: (CGFloat) -> Void
    let ended: (_ travel: CGFloat, _ speed: CGFloat) -> Void

    func makeCoordinator(converter: CoordinateSpaceConverter) -> Coordinator { Coordinator() }

    func makeUIGestureRecognizer(context: Context) -> UIPanGestureRecognizer {
        let pan = UIPanGestureRecognizer()
        pan.delegate = context.coordinator
        return pan
    }

    func handleUIGestureRecognizerAction(_ pan: UIPanGestureRecognizer, context: Context) {
        let travel = pan.translation(in: pan.view).x
        switch pan.state {
        case .changed: changed(travel)
        case .ended: ended(travel, pan.velocity(in: pan.view).x)
        case .cancelled, .failed: ended(0, 0)
        default: break
        }
    }

    final class Coordinator: NSObject, UIGestureRecognizerDelegate {
        func gestureRecognizerShouldBegin(_ recognizer: UIGestureRecognizer) -> Bool {
            guard let pan = recognizer as? UIPanGestureRecognizer, let view = pan.view else { return false }
            let speed = pan.velocity(in: view)
            return abs(speed.x) > abs(speed.y) * 1.2 && pan.location(in: view).x > 24
        }

        func gestureRecognizer(_ recognizer: UIGestureRecognizer, shouldRecognizeSimultaneouslyWith other: UIGestureRecognizer) -> Bool {
            other.view is UIScrollView
        }

        func gestureRecognizer(_ recognizer: UIGestureRecognizer, shouldBeRequiredToFailBy other: UIGestureRecognizer) -> Bool {
            if other is RowPanRecognizer { return true }
            guard let navigation = Self.navigation(from: other.view) else { return false }
            return other === navigation.interactiveContentPopGestureRecognizer
        }

        private static func navigation(from view: UIView?) -> UINavigationController? {
            var responder: UIResponder? = view
            while let next = responder {
                if let navigation = next as? UINavigationController { return navigation }
                responder = next.next
            }
            return nil
        }
    }
}

/// A page in the bar, where it sits. A tab bar item keeps its first image
/// when its tab moves, so a page that moved is a new tab.
private struct BarTab: Identifiable {
    let place: Int
    let page: String
    var id: String { "\(place)-\(page)" }
}
