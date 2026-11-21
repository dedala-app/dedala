// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import SwiftUI

/// A conversation with the agent, the main one or a topic: its rows (see
/// ConversationRows) in a column of readable width, what the agent is doing
/// at the end, and the message field, whose button stops it. It stays
/// on its last line while you read it, and offers a way back down when you
/// scroll up.
///
/// Every row it shows is laid out, none guessed, as in Hermex: the last ones,
/// and older ones a page at a time when you ask for them, which come in above
/// without moving what you read. A scroll down goes to a mark after the last
/// row, so it lands on the end as measured.
struct ConversationView<Header: View>: View {
    @Environment(Conversations.self) private var conversations
    @Environment(Agent.self) private var agent
    @Environment(Hub.self) private var hub
    @Environment(Router.self) private var router
    @Environment(\.colorScheme) private var colorScheme
    @Environment(\.scenePhase) private var scenePhase
    let conversation: String
    @ViewBuilder let header: Header

    @State private var position = ScrollPosition(idType: String.self)
    @State private var atBottom = true
    /// Whether it keeps to the end as the conversation grows: off as soon as
    /// you scroll, back on when you come to rest at the end, go down, or send.
    @State private var following = true
    /// How many of the first rows are left out until you ask for them; the
    /// last page shows until then, however many messages there are.
    @State private var hidden: Int?
    /// Older rows coming in above: the conversation keeps to its end while
    /// they lay out, so what you read stays where it is.
    @State private var prepending = false
    @State private var unseen = 0
    /// The width the column is laid out for: the scroll view's, taken only
    /// while the app is active. On the way to the background iOS lays the
    /// scene out in landscape for its snapshots; followed, that would re-wrap
    /// every row, clamp the offset to the shorter content and leave the
    /// conversation a screen or two above where you read it. The rows are
    /// held at it only while the app is not active: a scroll view is as wide
    /// as what it holds, so rows held wide after a turn back to portrait
    /// would keep it, and this width, at the landscape one.
    @State private var width: CGFloat = 390
    /// Where the conversation shows on screen, between the bars over it.
    @State private var frame = CGRect.zero
    @State private var insets = EdgeInsets()
    /// A card shown from a page, lit up a moment.
    @State private var lit: String?

    static var readable: CGFloat { 680 }
    /// How many rows show at first, and how many more each time you ask.
    static var page: Int { 60 }
    private static var end: String { "end" }

    private var messages: [Conversations.Message] {
        conversations.messages(in: conversation)
    }

    private var column: CGFloat { min(width - 32, Self.readable) }

    private var working: Bool {
        if case .working = conversations.presence(in: conversation) { true } else { false }
    }

    /// The rows left out when no more were asked for: all but the last page.
    private static func cut(_ rows: Int) -> Int { max(0, rows - page) }

    /// Whether you are reading the end of the conversation.
    private struct Fill: Equatable {
        let atBottom: Bool
        let width: CGFloat
        let insets: EdgeInsets
    }

    var body: some View {
        let messages = self.messages
        ScrollView {
            VStack(spacing: 0) {
                let rows = ConversationRows.rows(messages)
                let cut = min(hidden ?? Self.cut(rows.count), rows.count)
                if cut > 0 {
                    Button("Load Older Messages", systemImage: "arrow.up") { showOlder() }
                        .font(.caption.weight(.semibold))
                        .buttonStyle(.glass)
                        .controlSize(.small)
                        .padding(.vertical, 12)
                } else {
                    header
                }
                VStack(alignment: .leading, spacing: 0) {
                    ForEach(rows[cut...]) { row in
                        RowView(row: row, messages: messages, conversation: conversation)
                            .background {
                                if lit == row.id {
                                    RoundedRectangle(cornerRadius: 28, style: .continuous)
                                        .fill(Color.accentColor.opacity(0.14))
                                        .padding(-8)
                                        .transition(.opacity)
                                }
                            }
                            .padding(.top, row.gap)
                            .transition(.opacity.combined(with: .offset(y: 12)))
                    }
                    if case .working(let activity) = conversations.presence(in: conversation) {
                        LiveTrace(activity: activity)
                            .padding(.top, 14)
                            .transition(.opacity)
                    }
                    Color.clear
                        .frame(height: 1)
                        .padding(.top, 15)
                        .id(Self.end)
                }
                .scrollTargetLayout()
                .frame(minWidth: scenePhase == .active ? nil : column, maxWidth: column)
                .padding(.horizontal, 16)
            }
            .frame(maxWidth: .infinity)
        }
        .environment(\.conversationWidth, column)
        .scrollPosition($position)
        .defaultScrollAnchor(.bottom, for: .initialOffset)
        .defaultScrollAnchor(following || prepending ? .bottom : nil, for: .sizeChanges)
        .scrollDismissesKeyboard(.interactively)
        .onScrollPhaseChange { _, phase in
            if phase == .interacting {
                following = false
                endSelection()
            } else if phase == .idle, atBottom {
                following = true
            }
        }
        .simultaneousGesture(TapGesture().onEnded(endSelection))
        .onGeometryChange(for: CGRect.self) { $0.frame(in: .global) } action: { frame in
            self.frame = frame
            showViewport()
        }
        .onAppear(perform: showViewport)
        .onScrollGeometryChange(for: Fill.self) { geometry in
            Fill(atBottom: geometry.visibleRect.maxY >= geometry.contentSize.height + geometry.contentInsets.bottom - 40,
                 width: geometry.containerSize.width, insets: geometry.contentInsets)
        } action: { _, new in
            if scenePhase == .active { width = new.width }
            atBottom = new.atBottom
            if new.atBottom { unseen = 0 }
            if new.insets != insets {
                insets = new.insets
                showViewport()
            }
        }
        .onChange(of: messages.count) { old, new in
            if following || messages.last?.who == .you {
                toBottom()
            } else if new > old {
                unseen += new - old
            }
        }
        .task(id: router.focus) { await showFocus() }
        .task(id: width) {
            try? await Task.sleep(for: .seconds(1))
            guard !Task.isCancelled, PageColumns.narrow(column + 32) else { return }
            let before = SharedCards.width
            SharedCards.width = InlineCard.width(in: column)
            if abs(before - SharedCards.width) > 0.5 { hub.enqueue(Display.event) }
        }
        .overlay(alignment: .bottomTrailing) {
            if !atBottom {
                BackDown(unseen: unseen, action: toBottom)
                    .padding(16)
                    .transition(.scale(scale: 0.6).combined(with: .opacity))
            }
        }
        .animation(.snappy, value: atBottom)
        .safeAreaBar(edge: .bottom) {
            Composer(placeholder: conversation == Conversations.main ? "Message \(agent.name)" : "About \(conversations.topic(conversation)?.title ?? "this")", onStop: working ? { conversations.stop(conversation) } : nil) { text, photos in
                if photos.isEmpty {
                    conversations.send(text, in: conversation)
                } else {
                    conversations.send(text, photos: photos, in: conversation)
                }
            }
        }
    }

    /// A page of older rows, above what you read.
    private func showOlder() {
        prepending = true
        hidden = max(0, (hidden ?? Self.cut(ConversationRows.rows(messages).count)) - Self.page)
        Task {
            try? await Task.sleep(for: .milliseconds(300))
            prepending = false
        }
    }

    /// A tap or a scroll ends a selection in a bubble, as in Messages.
    private func endSelection() {
        TextBubble.endSelection()
    }

    /// A card asked for from a page: brought to the middle and lit up.
    private func showFocus() async {
        guard let focus = router.focus, messages.contains(where: { $0.id == focus }) else { return }
        let rows = ConversationRows.rows(messages)
        if let index = rows.firstIndex(where: { $0.id == focus }), index < hidden ?? Self.cut(rows.count) {
            hidden = max(0, index - 4)
        }
        try? await Task.sleep(for: .milliseconds(350))
        following = false
        withAnimation(.spring(duration: 0.5)) { position.scrollTo(id: focus, anchor: .center) }
        withAnimation(.easeOut(duration: 0.3)) { lit = focus }
        try? await Task.sleep(for: .seconds(1.6))
        withAnimation(.easeOut(duration: 0.6)) { lit = nil }
        if router.focus == focus { router.focus = nil }
    }

    private func toBottom() {
        following = true
        withAnimation(.spring(duration: 0.4)) { position.scrollTo(id: Self.end, anchor: .bottom) }
    }

    /// The part of the screen the conversation shows in, for the cards' reports.
    private func showViewport() {
        guard frame.height > 0 else { return }
        let shown = CGRect(x: frame.minX, y: frame.minY + insets.top, width: frame.width,
                           height: max(0, frame.height - insets.top - insets.bottom))
        hub.viewport = shown
        SharedCards.viewport = shown.height
        SharedCards.dark = colorScheme == .dark
    }
}

extension EnvironmentValues {
    /// The width of a conversation's column, which bubbles and cards take a share of.
    @Entry var conversationWidth: CGFloat = 358
}

/// Back to the last message, with how many arrived while you read above.
struct BackDown: View {
    let unseen: Int
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Image(systemName: "chevron.down")
                .font(.body.weight(.semibold))
                .frame(width: 40, height: 40)
        }
        .buttonStyle(.plain)
        .glassEffect(.regular.interactive(), in: .circle)
        .overlay(alignment: .topTrailing) {
            if unseen > 0 {
                Text("\(unseen)")
                    .font(.caption2.bold())
                    .foregroundStyle(.white)
                    .padding(.horizontal, 5)
                    .frame(minWidth: 18, minHeight: 18)
                    .background(Color.accentColor, in: .capsule)
                    .offset(x: 4, y: -4)
            }
        }
        .accessibilityLabel(unseen > 0 ? "Back to the latest, \(unseen) new" : "Back to the latest")
    }
}
