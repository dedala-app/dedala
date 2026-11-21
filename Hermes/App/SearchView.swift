// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import SwiftUI

/// The bar's last tab: everything on the phone, found by a word. Typed, it
/// finds pages by name and by what is on them, the records of the stores the
/// agent declared by what he said of them, messages, topics and his jobs,
/// each opening where it lives. Empty, it shows what you searched and opened
/// lately, which fits above the keyboard it opens with, then every page, the
/// latest records and each declared store's. Which pages stay in the bar is
/// the pages' own menu's business.
struct SearchView: View {
    @Environment(Hub.self) private var hub
    @Environment(Router.self) private var router
    @Environment(Agent.self) private var agent
    @Environment(Conversations.self) private var conversations
    @Environment(Background.self) private var background
    @State private var query = ""
    @State private var searching = false
    @State private var history = Search.History.load()

    private var typed: String { query.trimmingCharacters(in: .whitespaces) }

    var body: some View {
        NavigationStack {
            Group {
                if typed.isEmpty {
                    kept
                } else {
                    results
                }
            }
            .searchable(text: $query, isPresented: $searching, prompt: "Pages, records, messages")
            .searchPresentationToolbarBehavior(.avoidHidingContent)
            .navigationTitle("Search")
            .agentPill(hidden: searching)
        }
    }

    // MARK: - Nothing typed

    private var kept: some View {
        let records = Search.records(hub: hub)
        let recent = Search.latest(hub: hub)
        let groups = records.reduce(into: [String]()) { if let group = $1.group, !$0.contains(group) { $0.append(group) } }
        return List {
            if !history.searches.isEmpty {
                Section("Recent searches") {
                    ForEach(history.searches, id: \.self) { words in
                        Button { query = words } label: {
                            Label(words, systemImage: "clock.arrow.circlepath")
                        }
                        .tint(.primary)
                    }
                }
            }
            if !history.opened.isEmpty {
                Section("Recently opened") {
                    ForEach(history.opened) { thing in
                        Button { go(thing) } label: {
                            Label(thing.title, systemImage: thing.symbol)
                        }
                        .tint(.primary)
                    }
                }
            }
            if !hub.pages.isEmpty {
                Section("Pages") {
                    ForEach(hub.bar + hub.pages.map(\.id).filter { !hub.pinned.contains($0) }, id: \.self) { page($0) }
                }
            }
            if !recent.isEmpty {
                Section("Latest") {
                    ForEach(recent, id: \.key) { entry in
                        row(entry, detail: entry.subtitle ?? entry.group)
                    }
                }
            }
            ForEach(groups, id: \.self) { group in
                Section(group) {
                    ForEach(Array(records.filter { $0.group == group }.prefix(5)), id: \.key) { entry in
                        row(entry, detail: entry.subtitle)
                    }
                }
            }
        }
        .overlay {
            if hub.pages.isEmpty, records.isEmpty {
                ContentUnavailableView("Nothing here yet", systemImage: "magnifyingglass", description: Text("Ask \(agent.name) for your first page: your day, a project, something to keep an eye on. Everything he makes is found here."))
            }
        }
    }

    private func row(_ entry: Search.Entry, detail: String?) -> some View {
        Button {
            go(.init(kind: entry.kind, target: entry.id, title: entry.title, symbol: entry.symbol))
        } label: {
            Label {
                VStack(alignment: .leading, spacing: 1) {
                    Text(entry.title).lineLimit(1)
                    if let detail, !detail.isEmpty {
                        Text(detail).font(.caption).foregroundStyle(.secondary).lineLimit(1)
                    }
                }
            } icon: {
                Image(systemName: entry.symbol)
            }
        }
        .tint(.primary)
    }

    private func page(_ id: String) -> some View {
        Button {
            go(.init(kind: .page, target: id, title: hub.tabName(id), symbol: hub.symbol(id)))
        } label: {
            Label {
                VStack(alignment: .leading, spacing: 1) {
                    Text(hub.tabName(id))
                    if hub.tabNames[id] != nil, let page = hub.page(id) {
                        Text(page.title)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
            } icon: {
                Image(systemName: hub.symbol(id))
            }
        }
        .tint(.primary)
    }

    // MARK: - Something typed

    private var results: some View {
        let hits = Search.hits(for: typed, in: Search.entries(hub: hub, conversations: conversations, background: background, agent: agent.name))
        let groups = hits.reduce(into: [String]()) { if !$0.contains($1.group) { $0.append($1.group) } }
        return List {
            ForEach(groups, id: \.self) { group in
                Section(group) {
                    ForEach(hits.filter { $0.group == group }) { hit in
                        Button { open(hit) } label: { HitRow(hit: hit) }
                            .tint(.primary)
                    }
                }
            }
        }
        .overlay {
            if hits.isEmpty {
                ContentUnavailableView.search(text: typed)
            }
        }
    }

    private func open(_ hit: Search.Hit) {
        history.searched(typed)
        go(.init(kind: hit.kind, target: hit.target, title: hit.kind == .message ? hit.line ?? hit.title : hit.title,
                 symbol: hit.symbol, conversation: hit.conversation))
    }

    /// Opens something where it lives, and keeps it among what you opened.
    private func go(_ thing: Search.History.Opened) {
        history.opened(thing)
        history.save()
        router.open(thing.kind, thing.target, conversation: thing.conversation, pinned: hub.pinned.contains(thing.target))
    }
}

/// One thing found: what it is, the text it was found in, and when.
private struct HitRow: View {
    let hit: Search.Hit

    var body: some View {
        Label {
            HStack(alignment: .firstTextBaseline) {
                VStack(alignment: .leading, spacing: 2) {
                    Text(hit.title)
                        .lineLimit(1)
                    if let line = hit.line, !line.isEmpty {
                        Text(line)
                            .font(.footnote)
                            .foregroundStyle(.secondary)
                            .lineLimit(2)
                    }
                }
                Spacer(minLength: 8)
                if hit.kind == .message, let at = hit.at {
                    Text(at.formatted(Calendar.current.isDateInToday(at) ? .dateTime.hour().minute() : .dateTime.day().month(.abbreviated)))
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
        } icon: {
            Image(systemName: hit.symbol)
        }
    }
}

/// The agent over every page, small at its bottom leading corner: his face,
/// alive while he works, his name, and how many of his messages you have not
/// read. While he works a ring runs around his face in the colour of the tool
/// in his hands, whose symbol sits on the face as a badge, three dots while
/// he only thinks; when he answers while you are on a page, the pill hops,
/// the ring closes and the badge is a speech bubble while he mouths it,
/// which then turns into the count, until he takes up a tool again. He glances up at the
/// page when he has just changed it. While you scroll down a page it
/// folds to his face, as iPhone Duo's bars do not, and unfolds when you
/// scroll back up. A tap opens the conversation over everything; held, it
/// listens, writing what you say at the top of the screen, away from the
/// thumb, and sends it to him when you let go, unless you slid away first.
struct AgentPill: View {
    @Environment(Conversations.self) private var conversations
    @Environment(Agent.self) private var agent
    @Environment(Router.self) private var router
    @Environment(Listener.self) private var listener
    @Environment(Relay.self) private var relay
    @Environment(Hub.self) private var hub
    var page: String?
    @State private var pressing = false
    @State private var holding: Task<Void, Never>?
    @State private var sent = 0
    @State private var announced = 0
    @State private var announcing = false

    /// The glass left showing between his face and the badge pinned on it.
    private static let gap: CGFloat = 1.5

    var body: some View {
        let presence = conversations.presence(in: Conversations.main)
        let said = conversations.main.filter { $0.who == .agent && !$0.text.isEmpty }
        let unseen = said.filter { $0.at > router.seen }.count
        let line = AgentTitle.doing(presence) ?? said.last?.text ?? "Ask \(agent.name) anything"
        let tool = AgentTitle.symbol(presence)
        let badge = announcing ? "bubble.left.fill" : tool
        let mood: AgentMood = announcing ? .speaking
            : listener.state == .listening ? .thinking
            : agent.mood(working: presence != .idle, away: relay.sync == .agentAway)
        let shown = page.flatMap { hub.page($0) }
        let pinned = badge != nil || unseen > 0
        let pin = PillBadge(symbol: badge, count: unseen, color: announcing ? .accentColor : tool.map(AgentTitle.tint) ?? .accentColor)
        HStack(spacing: 8) {
            AgentFace(mood: mood)
                .frame(width: 28, height: 28)
                .clipShape(.circle)
                .background {
                    WorkRing(color: tool.map(AgentTitle.tint), closed: announcing, closing: announced)
                        .padding(-3)
                }
                .overlay(alignment: .bottomTrailing) {
                    if pinned {
                        pin.hidden()
                            .padding(Self.gap)
                            .background(.black, in: .capsule)
                            .blendMode(.destinationOut)
                            .offset(x: 6 + Self.gap, y: 4 + Self.gap)
                            .transition(.scale.combined(with: .opacity))
                    }
                }
                .compositingGroup()
                .overlay(alignment: .bottomTrailing) {
                    if pinned {
                        pin.offset(x: 6, y: 4)
                            .transition(.scale.combined(with: .opacity))
                    }
                }
            if !router.pillFolded {
                Text(agent.name)
                    .font(.subheadline.weight(.semibold))
                    .lineLimit(1)
                    .transition(.opacity)
            }
        }
        .padding(.leading, 5)
        .padding(.trailing, router.pillFolded ? 5 : 12)
        .padding(.vertical, 5)
        .glassEffect(pressing ? .regular.tint(.white.opacity(0.22)) : .regular, in: .capsule)
        .overlay {
            PillTouches(pressing: { pressing = $0 }, tapped: open, held: hold, slid: { listener.away = $0 }, released: release)
                .padding(-6)
        }
        .scaleEffect(listener.state == .listening ? 1.08 : pressing ? 1.05 : 1)
        .animation(.snappy, value: unseen)
        .animation(.snappy, value: badge)
        .animation(.snappy, value: announcing)
        .phaseAnimator([0, -8, 0], trigger: announced) { view, lift in
            view.offset(y: lift)
        } animation: { _ in
            .spring(duration: 0.24, bounce: 0.5)
        }
        .sensoryFeedback(.impact(weight: .light), trigger: announced)
        .task(id: said.last?.id) {
            guard let last = said.last, !router.chatOpen, last.at > router.seen, Date.now.timeIntervalSince(last.at) < 10 else { return }
            announced += 1
            announcing = true
            try? await Task.sleep(for: .seconds(1.8))
            guard !Task.isCancelled else { return }
            announcing = false
        }
        .onChange(of: shown?.revision) { agent.react(.glancing, for: 2.5) }
        .onChange(of: shown.flatMap(hub.updated)) { agent.react(.glancing, for: 2.5) }
        .animation(.snappy, value: listener.state)
        .animation(.spring(duration: 0.3, bounce: 0.35), value: pressing)
        .sensoryFeedback(.start, trigger: listener.state == .listening)
        .sensoryFeedback(.impact(weight: .light), trigger: listener.away)
        .sensoryFeedback(.success, trigger: sent)
        .task(id: listener.state) {
            guard case .failed = listener.state else { return }
            try? await Task.sleep(for: .seconds(2.5))
            listener.dismissFailure()
        }
        .accessibilityElement(children: .ignore)
        .accessibilityAddTraits(.isButton)
        .accessibilityLabel(unseen > 0 ? "\(agent.name), \(unseen) new" : agent.name)
        .accessibilityValue(line)
        .accessibilityHint("Opens the conversation")
        .accessibilityAction { open() }
    }

    /// A tap opens the conversation.
    private func open() {
        guard listener.state == .idle else { return }
        router.chatOpen = true
    }

    /// A press held a moment listens until it is let go.
    private func hold() {
        guard holding == nil else { return }
        holding = Task { await listener.start() }
    }

    /// Let go: sends what was heard, unless the finger slid away first.
    private func release(away: Bool) {
        holding = nil
        listener.away = false
        if away || listener.state != .listening {
            listener.cancel()
        } else {
            Task {
                let words = await listener.finish()
                guard !words.isEmpty else { return }
                conversations.send(words, in: Conversations.main)
                agent.react(.winking, for: 1)
                sent += 1
            }
        }
    }
}

/// What he is at, pinned on his face in the pill as Messages pins an app on
/// a contact's photo, the face and its ring cut away around it: the tool's
/// symbol on a disc of its colour, else how many of his messages wait.
private struct PillBadge: View {
    let symbol: String?
    let count: Int
    let color: Color

    var body: some View {
        ZStack {
            if let symbol {
                Image(systemName: symbol)
                    .font(.system(size: 9, weight: .heavy))
                    .symbolEffect(.variableColor.iterative.reversing, options: .repeat(.continuous), isActive: symbol == "ellipsis")
                    .contentTransition(.symbolEffect(.replace))
                    .transition(.scale.combined(with: .opacity))
            } else {
                Text("\(count)")
                    .font(.caption2.bold())
                    .contentTransition(.numericText())
                    .padding(.horizontal, 5)
                    .transition(.scale.combined(with: .opacity))
            }
        }
        .foregroundStyle(.white)
        .frame(minWidth: 18, minHeight: 18)
        .background(color, in: .capsule)
    }
}

/// The pill's touches, taken by a UIKit view over it: a SwiftUI gesture there
/// loses the hit test to the page's scroll view under the pill now and then
/// (right after a sheet closes, for one), and the tap goes nowhere; UIKit
/// hit-tests this view first, being above the scroll view. A short press that
/// ends on or near the pill is a tap, however the finger wandered; one held
/// still for `hold` is a hold until it is let go, cancelled when the finger
/// slides `slide` away.
private struct PillTouches: UIViewRepresentable {
    let pressing: (Bool) -> Void
    let tapped: () -> Void
    let held: () -> Void
    let slid: (Bool) -> Void
    let released: (_ away: Bool) -> Void

    static let hold: TimeInterval = 0.35
    static let slide: CGFloat = 70
    static let still: CGFloat = 12
    static let near: CGFloat = 30

    func makeUIView(context: Context) -> TouchView {
        let view = TouchView()
        view.isAccessibilityElement = false
        view.backgroundColor = .clear
        update(view)
        return view
    }

    func updateUIView(_ view: TouchView, context: Context) {
        update(view)
    }

    private func update(_ view: TouchView) {
        view.pressing = pressing
        view.tapped = tapped
        view.held = held
        view.slid = slid
        view.released = released
    }

    final class TouchView: UIView {
        var pressing: (Bool) -> Void = { _ in }
        var tapped: () -> Void = {}
        var held: () -> Void = {}
        var slid: (Bool) -> Void = { _ in }
        var released: (_ away: Bool) -> Void = { _ in }
        private var start: CGPoint?
        private var last: CGPoint?
        private var holding = false
        private var away = false
        private var timer: Timer?

        override func touchesBegan(_ touches: Set<UITouch>, with event: UIEvent?) {
            guard start == nil, let touch = touches.first else { return }
            start = touch.location(in: window)
            last = touch.location(in: self)
            holding = false
            away = false
            pressing(true)
            timer = Timer.scheduledTimer(withTimeInterval: PillTouches.hold, repeats: false) { [weak self] _ in
                guard let self, start != nil else { return }
                holding = true
                held()
            }
        }

        override func touchesMoved(_ touches: Set<UITouch>, with event: UIEvent?) {
            guard let start, let touch = touches.first else { return }
            let point = touch.location(in: window)
            last = touch.location(in: self)
            let distance = hypot(point.x - start.x, point.y - start.y)
            if holding {
                let now = distance > PillTouches.slide
                if now != away {
                    away = now
                    slid(now)
                }
            } else if distance > PillTouches.still {
                timer?.invalidate()
            }
        }

        override func touchesEnded(_ touches: Set<UITouch>, with event: UIEvent?) {
            end(cancelled: false)
        }

        override func touchesCancelled(_ touches: Set<UITouch>, with event: UIEvent?) {
            end(cancelled: true)
        }

        private func end(cancelled: Bool) {
            guard start != nil else { return }
            timer?.invalidate()
            timer = nil
            start = nil
            pressing(false)
            if holding {
                released(away || cancelled)
            } else if !cancelled, let last, bounds.insetBy(dx: -PillTouches.near, dy: -PillTouches.near).contains(last) {
                tapped()
            }
            last = nil
            holding = false
            away = false
        }
    }
}

/// What the pill hears while it is held, at the top of the screen.
struct ListeningPanel: View {
    @Environment(Listener.self) private var listener

    var body: some View {
        let state = listener.state
        let text = listener.text
        let away = listener.away
        VStack(alignment: .leading, spacing: 8) {
            switch state {
            case .failed(let problem):
                Label(problem, systemImage: "exclamationmark.triangle")
                    .font(.subheadline)
            case .preparing:
                Label("Getting ready…", systemImage: "waveform")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            default:
                Text(text.isEmpty ? "Listening…" : text)
                    .font(.body)
                    .foregroundStyle(text.isEmpty ? .secondary : .primary)
                    .lineLimit(8)
                    .contentTransition(.opacity)
                Label(away ? "Release to cancel" : "Release to send · slide away to cancel",
                      systemImage: away ? "xmark.circle.fill" : "waveform")
                    .font(.footnote)
                    .foregroundStyle(away ? AnyShapeStyle(.red) : AnyShapeStyle(.secondary))
                    .symbolEffect(.variableColor.iterative, isActive: !away)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(14)
        .glassEffect(.regular, in: .rect(cornerRadius: 22))
        .frame(maxWidth: 440)
        .accessibilityElement(children: .combine)
    }
}

extension View {
    /// The agent's pill at the bottom leading corner, above the tab bar, its
    /// face in line with what the cards hold rather than with their edge;
    /// away while the search field or the keyboard takes that place.
    func agentPill(page: String? = nil, hidden: Bool = false) -> some View {
        modifier(AgentPillPlace(page: page, hidden: hidden))
    }
}

private struct AgentPillPlace: ViewModifier {
    let page: String?
    let hidden: Bool
    @State private var typing = false

    func body(content: Content) -> some View {
        content
            .safeAreaInset(edge: .bottom, alignment: .leading) {
                if !hidden && !typing {
                    AgentPill(page: page)
                        .padding(.leading, 23)
                        .padding(.bottom, 8)
                        .transition(.opacity)
                }
            }
            .onReceive(NotificationCenter.default.publisher(for: UIResponder.keyboardWillShowNotification)) { _ in
                withAnimation(.snappy) { typing = true }
            }
            .onReceive(NotificationCenter.default.publisher(for: UIResponder.keyboardWillHideNotification)) { _ in
                withAnimation(.snappy) { typing = false }
            }
    }
}
