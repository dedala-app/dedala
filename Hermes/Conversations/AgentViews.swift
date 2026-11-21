// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import SwiftUI

/// The conversation, open over your pages or beside them: the main one under
/// a bar as in Messages on iPhone Duo: his face and name at its leading edge,
/// which open his sheet, then settings, what he does in the background and
/// the topics, which the Duo moves to its side column. The bar stays as you
/// scroll, where iOS 27 would fold it away.
struct AgentConversation: View {
    @Environment(Conversations.self) private var conversations
    @Environment(Agent.self) private var agent
    @Environment(Background.self) private var background
    @Environment(Router.self) private var router
    @State private var settings = false

    var body: some View {
        SideBarReader { sideBar in
            stack(sideBar: sideBar)
        }
    }

    private func stack(sideBar: Bool) -> some View {
        @Bindable var router = router
        return NavigationStack(path: $router.path) {
            ConversationView(conversation: Conversations.main) {
                if conversations.main.isEmpty {
                    ContentUnavailableView("Say hello to \(agent.name)", systemImage: "bubble.left.and.text.bubble.right", description: Text("Everything in this app starts here: ask for a page, a document, something to keep an eye on."))
                        .padding(.top, 40)
                }
            }
            .navigationTitle(agent.name)
            .navigationBarTitleDisplayMode(.inline)
            .titleAtLeadingEdge()
            .barStaysOnScroll()
            .background(ActivityBreathing())
            .toolbar {
                ToolbarItem(placement: .title) {
                    AgentHeader(large: sideBar)
                }
                ToolbarItem(placement: .topBarLeading) {
                    Button("Settings", systemImage: "slider.horizontal.3") { settings = true }
                }
                ToolbarItemGroup(placement: .topBarTrailing) {
                    if !background.jobs.isEmpty || !background.runs.isEmpty {
                        ActivityIcon(running: background.running.count) { router.activity = .list }
                    }
                    if !conversations.topics.isEmpty {
                        Button("Topics", systemImage: "square.stack.3d.up.fill") {
                            router.path.append(Conversations.topicsList)
                        }
                        .badge(conversations.unreadTopics)
                    }
                }
            }
            .sheet(isPresented: $settings) {
                SettingsView()
            }
            .navigationDestination(for: String.self) { id in
                if id == Conversations.topicsList {
                    TopicsList()
                } else {
                    TopicView(topicID: id)
                }
            }
        }
    }
}

/// The agent at the head of his conversation, as a contact in Messages on
/// iPhone Duo: his face, then his name, which open his sheet. It says who he
/// is and whether he can be reached, nothing about the turn: out of reach, the
/// reason stands beside his name once it has lasted three seconds with the
/// app in front, so that coming back to the app shows nothing of the
/// reconnection. Large where the bar is his alone, at the bar's size where he
/// shares it with the buttons.
struct AgentHeader: View {
    @Environment(Agent.self) private var agent
    @Environment(Relay.self) private var relay
    @Environment(\.scenePhase) private var phase
    @State private var profile = false
    @State private var lasting = false
    let large: Bool

    var body: some View {
        let reason = lasting ? AgentTitle.unreachable(relay.sync) : nil
        Button { profile = true } label: {
            HStack(spacing: large ? 12 : 8) {
                AgentDot(size: large ? 44 : 32, reachable: reason == nil)
                HStack(alignment: .firstTextBaseline, spacing: 5) {
                    Text(agent.name)
                        .font(large ? .title2.bold() : .headline)
                    if let reason {
                        Text(reason)
                            .font(large ? .title3.weight(.semibold) : .subheadline.weight(.semibold))
                            .foregroundStyle(.orange)
                            .transition(.opacity)
                    }
                    Image(systemName: "chevron.right")
                        .font(.system(size: large ? 14 : 10, weight: .bold))
                        .foregroundStyle(.tertiary)
                }
            }
            .lineLimit(1)
            .fixedSize()
            .contentShape(.rect)
            .animation(.snappy, value: reason)
        }
        .buttonStyle(.plain)
        .accessibilityLabel([agent.name, reason].compactMap(\.self).joined(separator: ", "))
        .task(id: [relay.sync == .upToDate, phase == .active]) {
            lasting = false
            guard relay.sync != .upToDate, phase == .active, (try? await Task.sleep(for: .seconds(3))) != nil else { return }
            lasting = true
        }
        .sheet(isPresented: $profile) {
            AgentProfile()
        }
    }
}

/// The agent's face in a circle on the poster's colors, alive while he works,
/// with an orange dot while the app cannot reach him.
struct AgentDot: View {
    @Environment(Conversations.self) private var conversations
    @Environment(Agent.self) private var agent
    @Environment(Relay.self) private var relay
    let size: CGFloat
    let reachable: Bool

    var body: some View {
        AgentFace(mood: agent.mood(working: conversations.presence(in: Conversations.main) != .idle, away: relay.sync == .agentAway))
            .frame(width: size, height: size)
            .clipShape(.circle)
            .glassEffect(.regular, in: .circle)
            .overlay(alignment: .topTrailing) {
                if !reachable {
                    Circle()
                        .fill(.orange)
                        .frame(width: size * 0.2, height: size * 0.2)
                        .overlay(Circle().stroke(Color(.systemBackground), lineWidth: 2))
                        .offset(x: -size * 0.02, y: size * 0.02)
                        .transition(.scale.combined(with: .opacity))
                }
            }
            .animation(.snappy, value: reachable)
    }
}

/// The agent's sheet, from his header: his poster, whether the app is in sync
/// with him, and the ways into what he does on his own.
struct AgentProfile: View {
    @Environment(Conversations.self) private var conversations
    @Environment(Agent.self) private var agent
    @Environment(Background.self) private var background
    @Environment(Router.self) private var router
    @Environment(Relay.self) private var relay
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            List {
                Section {
                    VStack(spacing: 4) {
                        AgentFace(mood: agent.mood(working: conversations.presence(in: Conversations.main) != .idle, away: relay.sync == .agentAway))
                            .frame(width: 96, height: 96)
                            .padding(.bottom, 8)
                        Text(agent.name)
                            .font(.title.bold())
                        Text(AgentTitle.doing(conversations.presence(in: Conversations.main)) ?? "Here")
                            .font(.subheadline)
                            .foregroundStyle(.secondary)
                        SyncPill(agent: agent.name)
                            .padding(.top, 6)
                    }
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 8)
                    .listRowBackground(Color.clear)
                }
                Section {
                    Button {
                        dismiss()
                        router.activity = .list
                    } label: {
                        LabeledContent {
                            Text(background.running.isEmpty ? "\(background.jobs.count) jobs" : "\(background.running.count) running")
                        } label: {
                            Label("Activity", systemImage: "gearshape.2")
                        }
                    }
                    NavigationLink {
                        AvatarEditor()
                    } label: {
                        Label("Name and face", systemImage: "face.smiling")
                    }
                    if !conversations.topics.isEmpty {
                        Button {
                            dismiss()
                            router.path.append(Conversations.topicsList)
                        } label: {
                            LabeledContent {
                                Text(conversations.unreadTopics > 0 ? "\(conversations.unreadTopics) unread" : "\(conversations.topics.count)")
                            } label: {
                                Label("Topics", systemImage: "square.stack.3d.up.fill")
                            }
                        }
                    }
                }
                .tint(.primary)
            }
            .background(alignment: .top) { PosterWash().frame(height: 320) }
            .scrollContentBackground(.hidden)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Done", systemImage: "checkmark") { dismiss() }
                }
            }
        }
        .presentationDetents([.medium, .large])
    }
}

enum AgentTitle {
    static func doing(_ presence: Conversations.Presence) -> String? {
        guard case .working(let activity) = presence else { return nil }
        return activity.doing.map { "\($0)…" } ?? activity.last?.text ?? "Thinking…"
    }

    /// What he is at, as the pill has room for: the symbol of the tool in his
    /// hands or of the step he just took, else three dots.
    static func symbol(_ presence: Conversations.Presence) -> String? {
        guard case .working(let activity) = presence else { return nil }
        return activity.glyph
    }

    /// The colour a symbol wears on his face: one per kind of work.
    static func tint(_ symbol: String) -> Color {
        switch symbol {
        case "ellipsis": .accentColor
        case "globe", "safari": .blue
        case "magnifyingglass", "clock.arrow.circlepath": .purple
        case "doc.text", "square.and.pencil", "book", "books.vertical": .orange
        case "terminal", "chevron.left.forwardslash.chevron.right": .green
        case "brain", "eye": .pink
        case "calendar.badge.clock", "checklist": .red
        case "square.grid.2x2", "square.grid.2x2.fill", "rectangle.on.rectangle", "externaldrive", "iphone", "livephoto": .teal
        default: .indigo
        }
    }

    /// Beside his name while the app cannot reach him: why, in a word or two.
    static func unreachable(_ sync: Relay.Sync) -> String? {
        switch sync {
        case .offline: "Offline"
        case .connecting: "Connecting"
        case .catchingUp: "Catching up"
        case .agentAway: "Away"
        case .upToDate: nil
        }
    }
}

/// The ring of work, around his face in the pill and around the step under
/// way in the conversation: it runs in the colour of the tool in his hands,
/// and closes with a beat when he answers.
struct WorkRing: View {
    let color: Color?
    let closed: Bool
    let closing: Int
    @Environment(\.accessibilityReduceMotion) private var still

    var body: some View {
        let color = color ?? .clear
        TimelineView(.animation(paused: closed || still || self.color == nil)) { context in
            Circle()
                .trim(from: 0, to: closed ? 1 : 0.72)
                .stroke(
                    closed ? AnyShapeStyle(.tint) : AnyShapeStyle(AngularGradient(colors: [color.opacity(0), color], center: .center, startAngle: .zero, endAngle: .degrees(260))),
                    style: StrokeStyle(lineWidth: 2.5, lineCap: .round)
                )
                .rotationEffect(.degrees(context.date.timeIntervalSinceReferenceDate.truncatingRemainder(dividingBy: 1.1) / 1.1 * 360))
        }
        .opacity(closed || self.color != nil ? 1 : 0)
        .phaseAnimator([1.0, 1.22, 1.0], trigger: closing) { view, beat in
            view.scaleEffect(beat)
        } animation: { _ in
            .spring(duration: 0.26, bounce: 0.4)
        }
        .animation(.snappy, value: closed)
        .animation(.snappy, value: self.color)
    }
}

/// Whether what the app shows is the agent's: green once connected and in
/// sync, orange until then.
struct SyncPill: View {
    @Environment(Relay.self) private var relay
    let agent: String

    var body: some View {
        HStack(spacing: 5) {
            Circle()
                .fill(relay.sync == .upToDate ? Color.green : Color.orange)
                .frame(width: 7, height: 7)
            Text(label)
                .font(.caption2.weight(.semibold))
                .foregroundStyle(.secondary)
                .contentTransition(.opacity)
        }
        .padding(.horizontal, 8)
        .padding(.vertical, 4)
        .glassEffect(.regular, in: .capsule)
        .animation(.default, value: relay.sync)
        .accessibilityElement(children: .combine)
    }

    private var label: String { Self.label(relay.sync, agent: agent) }

    static func label(_ sync: Relay.Sync, agent: String) -> String {
        switch sync {
        case .offline: "Offline"
        case .connecting: "Connecting"
        case .catchingUp: "Catching up"
        case .agentAway: "\(agent) is away"
        case .upToDate: "Up to date"
        }
    }
}

struct TopicView: View {
    @Environment(Conversations.self) private var conversations
    @Environment(Router.self) private var router
    let topicID: String

    var body: some View {
        if let topic = conversations.topic(topicID) {
            ConversationView(conversation: topicID) {
                TopicHeader(topic: topic)
            }
            .navigationTitle(topic.title)
            .navigationBarTitleDisplayMode(.inline)
            .barStaysOnScroll()
            .onAppear { conversations.markRead(topicID) }
            .onChange(of: topic.messages.count) { conversations.markRead(topicID) }
        }
    }
}

struct TopicHeader: View {
    let topic: Conversations.Topic

    var body: some View {
        VStack(spacing: 12) {
            TopicBadge(topic: topic, size: 64)
            VStack(spacing: 2) {
                Text(topic.title)
                    .font(.title2.bold())
                Text(subtitle)
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            }
            if let outcome = topic.outcome {
                Label(outcome, systemImage: "checkmark.seal.fill")
                    .font(.subheadline.weight(.medium))
                    .foregroundStyle(.green)
            }
        }
        .frame(maxWidth: .infinity)
        .padding(.top, 12)
        .padding(.bottom, 8)
    }

    private var subtitle: String {
        let count = topic.messages.count
        if let closed = topic.closed {
            return "Closed \(closed.formatted(.relative(presentation: .named))) · \(count) messages"
        }
        return "Since \(topic.started.formatted(.dateTime.weekday(.wide).day().month())) · \(count) messages"
    }
}

struct TopicsList: View {
    @Environment(Conversations.self) private var conversations

    var body: some View {
        List {
            Section("Ongoing") {
                ForEach(conversations.ongoing) { topic in
                    NavigationLink(value: topic.id) { TopicListRow(topic: topic) }
                }
            }
            if !conversations.closedTopics.isEmpty {
                Section("Closed") {
                    ForEach(conversations.closedTopics) { topic in
                        NavigationLink(value: topic.id) { TopicListRow(topic: topic) }
                    }
                }
            }
        }
        .navigationTitle("Topics")
    }
}

struct TopicListRow: View {
    @Environment(Conversations.self) private var conversations
    let topic: Conversations.Topic

    var body: some View {
        HStack(spacing: 12) {
            TopicBadge(topic: topic, size: 44)
            VStack(alignment: .leading, spacing: 3) {
                HStack {
                    Text(topic.title).font(.headline)
                    Spacer()
                    Text(conversations.lastActivity(topic).formatted(.relative(presentation: .named)))
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                HStack(alignment: .top) {
                    Text(topic.outcome ?? topic.messages.last?.text ?? "")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                        .lineLimit(2)
                    Spacer(minLength: 0)
                    if topic.unread > 0 {
                        Text("\(topic.unread)")
                            .font(.caption2.bold())
                            .foregroundStyle(.white)
                            .padding(.horizontal, 6)
                            .frame(minWidth: 20, minHeight: 20)
                            .background(.blue, in: .capsule)
                    }
                }
            }
        }
        .padding(.vertical, 2)
    }
}
