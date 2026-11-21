// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import SwiftUI

/// One row of a conversation.
struct RowView: View {
    let row: ConversationRows.Row
    let messages: [Conversations.Message]
    let conversation: String

    var body: some View {
        switch row.kind {
        case .day(let date):
            DaySeparator(date: date)
        case .time(let date):
            Text(date.formatted(date: .omitted, time: .shortened))
                .font(.caption.weight(.medium))
                .foregroundStyle(.secondary)
                .frame(maxWidth: .infinity)
                .padding(.top, 10)
                .padding(.bottom, 6)
        case .notice(let index, let count):
            if let notice = messages[index].notice {
                NoticeRow(notice: notice, count: count)
            }
        case .message(let index, let position):
            MessageRow(message: messages[index], conversation: conversation, position: position)
        }
    }
}

struct DaySeparator: View {
    let date: Date

    var body: some View {
        Text(label)
            .font(.caption.weight(.semibold))
            .foregroundStyle(.secondary)
            .frame(maxWidth: .infinity)
            .padding(.top, 14)
            .padding(.bottom, 8)
    }

    private var label: String {
        let calendar = Calendar.current
        if calendar.isDateInToday(date) { return "Today" }
        if calendar.isDateInYesterday(date) { return "Yesterday" }
        if let days = calendar.dateComponents([.day], from: date, to: .now).day, days < 7 {
            return date.formatted(.dateTime.weekday(.wide))
        }
        return date.formatted(.dateTime.weekday(.wide).day().month(.wide))
    }
}

struct MessageRow: View {
    @Environment(\.conversationWidth) private var width
    let message: Conversations.Message
    let conversation: String
    var position = ConversationRows.Position.alone

    var body: some View {
        if let night = message.night {
            NightMarker(night: night)
        } else if message.who == .you, message.text.hasPrefix("/") {
            Text(message.text)
                .font(.caption.monospaced())
                .foregroundStyle(.secondary)
                .frame(maxWidth: .infinity, alignment: .trailing)
                .padding(.horizontal, 6)
        } else if let page = message.page {
            PageProposal(pageID: page, title: message.text)
        } else if let topicID = message.topic {
            TopicLink(topicID: topicID, line: message.text)
        } else if message.who == .you {
            VStack(alignment: .trailing, spacing: 4) {
                if let shared = message.shared, !shared.isEmpty {
                    SharedItems(items: shared, share: message.share)
                        .frame(maxWidth: min(width * 0.82, 420), alignment: .trailing)
                }
                if !message.text.isEmpty {
                    TextBubble(text: message.text, isYou: true, position: position)
                }
                if let note = message.note {
                    Text(note)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .padding(.horizontal, 6)
                }
            }
            .frame(maxWidth: .infinity, alignment: .trailing)
        } else {
            VStack(alignment: .leading, spacing: 6) {
                if let steps = message.steps, !steps.isEmpty {
                    StepsTrace(steps: steps)
                }
                if !message.text.isEmpty {
                    TextBubble(text: message.text, isYou: false, position: position)
                }
                if let record = message.record {
                    RecordChip(ref: record)
                        .frame(maxWidth: min(width * 0.82, 420), alignment: .leading)
                }
                if let receipt = message.receipt {
                    CardReceipt(line: receipt, symbol: "checkmark.circle.fill", tint: .green)
                } else if let card = message.card {
                    InlineCard(card: card, messageID: message.id, conversation: conversation, loved: message.loved == true)
                        .environment(\.cardSurface, [Color(.secondarySystemBackground), Color(.tertiarySystemBackground)])
                        .frame(maxWidth: InlineCard.width(in: width), alignment: .leading)
                        .padding(.top, 2)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }
}

/// What the agent did before it answered: one quiet line, the steps on a tap.
struct StepsTrace: View {
    let steps: [Conversations.Step]
    @State private var open = false

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Button {
                withAnimation(.snappy) { open.toggle() }
            } label: {
                HStack(spacing: 4) {
                    Text(steps.count == 1 ? "1 step" : "\(steps.count) steps")
                    if steps.contains(where: { $0.failed == true }) {
                        Image(systemName: "exclamationmark.circle").foregroundStyle(.orange)
                    }
                    Image(systemName: "chevron.right")
                        .font(.caption2.weight(.semibold))
                        .rotationEffect(.degrees(open ? 90 : 0))
                }
                .font(.caption.weight(.medium))
                .foregroundStyle(.secondary)
                .contentShape(.rect)
            }
            .buttonStyle(.plain)
            if open {
                VStack(alignment: .leading, spacing: 6) {
                    ForEach(steps.indices, id: \.self) { index in
                        let step = steps[index]
                        Label {
                            Text(step.text).lineLimit(2)
                        } icon: {
                            Image(systemName: step.failed == true ? "exclamationmark.circle" : step.symbol)
                                .foregroundStyle(step.failed == true ? .orange : .secondary)
                                .frame(width: 16)
                        }
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    }
                }
                .padding(.leading, 2)
                .transition(.opacity.combined(with: .move(edge: .top)))
            }
        }
        .padding(.horizontal, 6)
    }
}

/// A Hermes UI card inside a conversation; its actions go back to the agent,
/// and what it draws is reported back like any card. Long press to flag it.
struct InlineCard: View {
    /// Its share of the conversation's column.
    static func width(in column: CGFloat) -> CGFloat {
        min(column * 0.94, 440)
    }

    @Environment(Conversations.self) private var conversations
    @Environment(Hub.self) private var hub
    let card: Conversations.CardSpec
    let messageID: String
    let conversation: String
    var loved = false

    var body: some View {
        let context = hub.cardContext(messageID) { [conversations, messageID, conversation] payload, say in
            conversations.act(payload, say: say, from: messageID, in: conversation)
        }
        StateScopeView(
            initial: card.state,
            node: CardSurfaces.surfaced(card.view, components: Set(hub.components.keys), context: context),
            scope: Scope(values: [:], boxes: [], context: context, data: card.data.object ?? [:], stores: hub.stores,
                         saved: SavedState(card.saved ?? [:]) { [conversations, messageID] in conversations.saveState(messageID, $0) }),
            script: card.scriptSpec,
            data: card.data,
            key: "card"
        )
        .id(card.stateRevision ?? 0)
        .coordinateSpace(.named(CardContext.space))
        .onGeometryChange(for: CGRect.self) { $0.frame(in: .global) } action: { frame in
            hub.cardFrames[messageID] = frame
            context.size = frame.size
        }
        .onPreferenceChange(LivePaths.self) { paths in
            context.live = Set(paths)
        }
        .overlay(alignment: .topTrailing) {
            if loved {
                Image(systemName: "heart.fill")
                    .font(.caption)
                    .foregroundStyle(.pink)
                    .padding(10)
                    .transition(.scale.combined(with: .opacity))
            }
        }
        .contextMenu {
            Button(loved ? "Loved" : "Love it", systemImage: loved ? "heart.fill" : "heart") {
                guard let spec = withAnimation(.spring(duration: 0.4), { conversations.loved(messageID, in: conversation) }) else { return }
                UINotificationFeedbackGenerator().notificationOccurred(.success)
                hub.love(messageID, conversation: conversation, card: spec)
            }
            Button("Looks off", systemImage: "exclamationmark.bubble") {
                hub.flag(messageID, conversation: conversation, yours: conversations.flagged(in: conversation))
            }
        }
    }
}


/// Where a topic shows up in the main conversation, with its latest line.
struct TopicLink: View {
    @Environment(Conversations.self) private var conversations
    @Environment(\.conversationWidth) private var width
    let topicID: String
    let line: String

    var body: some View {
        if let topic = conversations.topic(topicID) {
            NavigationLink(value: topicID) {
                HStack(spacing: 12) {
                    TopicBadge(topic: topic, size: 36)
                    VStack(alignment: .leading, spacing: 2) {
                        HStack(spacing: 6) {
                            Text(topic.title).font(.subheadline.weight(.semibold))
                            if topic.unread > 0 {
                                Circle().fill(.blue).frame(width: 8, height: 8)
                            }
                        }
                        Text(line)
                            .font(.subheadline)
                            .foregroundStyle(.secondary)
                            .lineLimit(2)
                            .multilineTextAlignment(.leading)
                    }
                    Spacer(minLength: 0)
                    Image(systemName: "chevron.right")
                        .font(.footnote.weight(.semibold))
                        .foregroundStyle(.tertiary)
                }
                .padding(12)
                .background(Color(.secondarySystemBackground), in: .rect(cornerRadius: 18, style: .continuous))
                .contentShape(.rect)
            }
            .buttonStyle(.plain)
            .padding(.vertical, 4)
            .frame(maxWidth: min(width, 480), alignment: .leading)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }
}

struct TopicBadge: View {
    let topic: Conversations.Topic
    var size: CGFloat = 40

    var body: some View {
        Image(systemName: topic.symbol)
            .font(.system(size: size * 0.42, weight: .semibold))
            .foregroundStyle(.white)
            .frame(width: size, height: size)
            .background((Tokens.color(.string(topic.color)) ?? .accentColor).gradient, in: .circle)
            .opacity(topic.closed == nil ? 1 : 0.55)
    }
}

/// The boundary between two days: what the agent kept from the day before and
/// what it did overnight.
struct NightMarker: View {
    @Environment(Agent.self) private var agent
    let night: Conversations.Night
    @State private var expanded = false

    var body: some View {
        VStack(spacing: 10) {
            Button {
                withAnimation(.spring(duration: 0.4)) { expanded.toggle() }
            } label: {
                HStack(spacing: 8) {
                    Image(systemName: "moon.zzz.fill")
                        .foregroundStyle(.indigo)
                    Text("\(agent.name) slept on it")
                        .fontWeight(.semibold)
                    Text("· remembered \(night.remembered.count) things")
                        .foregroundStyle(.secondary)
                    Image(systemName: "chevron.down")
                        .font(.caption.weight(.bold))
                        .foregroundStyle(.tertiary)
                        .rotationEffect(.degrees(expanded ? 180 : 0))
                }
                .font(.footnote)
                .padding(.horizontal, 14)
                .padding(.vertical, 8)
                .background(Color(.secondarySystemBackground), in: .capsule)
            }
            .buttonStyle(.plain)

            if expanded {
                VStack(alignment: .leading, spacing: 14) {
                    NightList(title: "Remembered", symbol: "brain.head.profile", tint: .pink, lines: night.remembered)
                    NightList(title: "Done overnight", symbol: "checkmark.circle.fill", tint: .green, lines: night.overnight)
                }
                .padding(16)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(Color(.secondarySystemBackground), in: .rect(cornerRadius: 20, style: .continuous))
                .transition(.opacity.combined(with: .scale(scale: 0.96, anchor: .top)))
            }
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 14)
    }
}

private struct NightList: View {
    let title: String
    let symbol: String
    let tint: Color
    let lines: [String]

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Label(title, systemImage: symbol)
                .font(.footnote.weight(.semibold))
                .foregroundStyle(tint)
            ForEach(lines, id: \.self) { line in
                Text(line)
                    .font(.subheadline)
                    .padding(.leading, 26)
            }
        }
    }
}

/// Hermes speaking for itself, as an event between messages: quiet, and said
/// once when it repeats.
struct NoticeRow: View {
    let notice: Conversations.Notice
    var count = 1

    var body: some View {
        VStack(spacing: 3) {
            Label {
                Text(count > 1 ? "\(notice.title) · \(count) times" : notice.title)
            } icon: {
                Image(systemName: notice.symbol)
                    .foregroundStyle(notice.warning ? AnyShapeStyle(.orange) : AnyShapeStyle(.secondary))
            }
            .font(.footnote.weight(.medium))
            .foregroundStyle(.secondary)
            if !notice.details.isEmpty {
                Text(notice.details.joined(separator: " · "))
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
        .multilineTextAlignment(.center)
        .frame(maxWidth: .infinity)
        .padding(.horizontal, 24)
        .padding(.vertical, 6)
    }
}

/// The agent at work, where its answer will appear: a trail of the steps it
/// took, one disc each in its tool's colour and tucked under the next, the
/// newest larger with the ring around it, then its line, the tokens it writes
/// and the time. The trail has three places: with more steps than that, the
/// first counts those it leaves out. The newest is the call it writes or the
/// tool it runs, and stays as the step that came of it until the next begins.
/// Stopping it is on the message field's button.
struct LiveTrace: View {
    let activity: Conversations.Activity
    @State private var seen = Date.now

    private static let places = 3
    private static let tuck: CGFloat = 4

    /// The steps the trail has no place for.
    private var left: Int {
        let done = activity.trail.count
        return done > Self.places ? done - Self.places + 1 : 0
    }

    private struct Disc: Identifiable {
        let id: Int
        let symbol: String
        let color: Color
        let current: Bool
    }

    private var discs: [Disc] {
        let trail = activity.trail
        let done = trail.indices.dropFirst(left).map { disc(trail[$0], id: $0, current: false) }
        if let last = activity.last {
            return done + [disc(last, id: trail.count, current: true)]
        }
        return done + [Disc(id: trail.count, symbol: activity.glyph, color: AgentTitle.tint(activity.glyph), current: true)]
    }

    private func disc(_ step: Conversations.Step, id: Int, current: Bool) -> Disc {
        let failed = step.failed == true
        return Disc(id: id, symbol: failed ? "exclamationmark" : step.symbol, color: failed ? .orange : AgentTitle.tint(step.symbol), current: current)
    }

    var body: some View {
        let steps = activity.steps.count
        let discs = self.discs
        HStack(spacing: 8) {
            HStack(spacing: 0) {
                if left > 0 {
                    Text("+\(left)")
                        .font(.system(size: 9, weight: .bold).monospacedDigit())
                        .foregroundStyle(.secondary)
                        .contentTransition(.numericText())
                        .fixedSize()
                        .padding(.leading, 5)
                        .padding(.trailing, 5 + Self.tuck)
                        .frame(minHeight: 20)
                        .background(.fill.secondary, in: .capsule)
                        .transition(.scale(scale: 0.3).combined(with: .opacity))
                }
                ForEach(discs) { disc in
                    let first = disc.id == discs.first?.id && left == 0
                    TraceDisc(symbol: disc.symbol, color: disc.color, current: disc.current)
                        .background {
                            if !disc.current && !first {
                                Circle()
                                    .padding(-1.5)
                                    .blendMode(.destinationOut)
                            }
                        }
                        .padding(.leading, first ? 0 : disc.current ? 5 : -Self.tuck)
                        .zIndex(Double(disc.id))
                        .transition(.scale(scale: 0.3).combined(with: .opacity))
                }
            }
            .compositingGroup()
            .accessibilityElement()
            .accessibilityLabel(steps == 1 ? "1 step" : "\(steps) steps")
            VStack(alignment: .leading, spacing: 1) {
                Text(activity.line)
                    .font(.footnote.weight(.semibold))
                    .lineLimit(1)
                TimelineView(.periodic(from: .now, by: 1)) { context in
                    Text(meta(at: context.date))
                        .font(.caption.monospacedDigit())
                        .foregroundStyle(.secondary)
                        .contentTransition(.numericText())
                        .animation(.snappy, value: activity.tokens)
                }
            }
        }
        .padding(.horizontal, 4)
        .frame(maxWidth: .infinity, alignment: .leading)
        .accessibilityElement(children: .combine)
    }

    private func meta(at date: Date) -> String {
        let seconds = max(0, Int(date.timeIntervalSince(activity.since ?? seen)))
        let time = seconds < 3600 ? String(format: "%d:%02d", seconds / 60, seconds % 60) : "\(seconds / 3600)h"
        guard activity.tokens > 0 else { return time }
        let tokens = activity.tokens < 1000 ? "\(activity.tokens)" : String(format: "%.1fk", Double(activity.tokens) / 1000)
        return "\(tokens) tokens · \(time)"
    }
}

/// One step on the trail: its tool's symbol on a disc of the tool's colour,
/// small once done, full size with the ring around it while under way.
private struct TraceDisc: View {
    let symbol: String
    let color: Color
    let current: Bool

    var body: some View {
        Image(systemName: symbol)
            .font(.system(size: 13, weight: .bold))
            .symbolEffect(.variableColor.iterative.reversing, options: .repeat(.continuous), isActive: current && symbol == "ellipsis")
            .contentTransition(.symbolEffect(.replace))
            .foregroundStyle(.white)
            .frame(width: 28, height: 28)
            .background(color, in: .circle)
            .background {
                WorkRing(color: current ? color : nil, closed: false, closing: 0)
                    .padding(-3)
            }
            .scaleEffect(current ? 1 : 0.7)
            .opacity(current ? 1 : 0.8)
            .frame(width: current ? 34 : 20, height: 34)
            .animation(.snappy, value: symbol)
            .animation(.snappy, value: current)
    }
}

/// A page the agent made, offered for the tab bar. Your choice stays yours:
/// pages also live in Settings.
struct PageProposal: View {
    @Environment(Hub.self) private var hub
    @Environment(\.conversationWidth) private var width
    @Environment(Router.self) private var router
    let pageID: String
    let title: String

    var body: some View {
        if let page = hub.page(pageID) {
            HStack(spacing: 12) {
                Image(systemName: page.symbol)
                    .font(.system(size: 16, weight: .semibold))
                    .foregroundStyle(.white)
                    .frame(width: 36, height: 36)
                    .background(Color.accentColor.gradient, in: .rect(cornerRadius: 10, style: .continuous))
                VStack(alignment: .leading, spacing: 2) {
                    Text("New page").font(.caption.weight(.semibold)).foregroundStyle(.secondary)
                    Text(page.title).font(.subheadline.weight(.semibold))
                }
                Spacer(minLength: 0)
                if hub.pinned.contains(pageID) {
                    Button("Open") { router.show(page: pageID) }
                        .buttonStyle(.bordered)
                } else {
                    Button("Open") { router.sheetPage = pageID }
                        .buttonStyle(.bordered)
                    Button("Add to the bar") {
                        hub.pin(pageID, true)
                        router.show(page: pageID)
                    }
                    .buttonStyle(.borderedProminent)
                }
            }
            .controlSize(.small)
            .padding(12)
            .background(Color(.secondarySystemBackground), in: .rect(cornerRadius: 18, style: .continuous))
            .padding(.vertical, 4)
            .frame(maxWidth: min(width, 480), alignment: .leading)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }
}
