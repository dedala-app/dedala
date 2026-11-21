// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import SwiftUI

/// The Hermes UI views drawn from what the app holds: the agent's face, the
/// cards he said and the files it keeps, for his pages and cards.
enum AppViews {
    /// They take what they draw from with them: a page is also drawn away
    /// from the app's views, to report on it.
    static func install(conversations: Conversations, agent: Agent, hub: Hub, relay: Relay) {
        Views.file = { [weak hub, weak agent] value, height, scope in
            guard let hub, let agent else { return AnyView(EmptyView()) }
            return AnyView(FileView(value: value, height: height, scope: scope)
                .environment(hub)
                .environment(agent))
        }
        Views.app["Face"] = { [weak conversations, weak agent, weak relay] value, scope in
            guard let conversations, let agent, let relay else { return AnyView(EmptyView()) }
            return AnyView(PageFace(size: (scope.number(value) ?? scope.number(value["size"])).map { CGFloat($0) } ?? 56)
                .environment(conversations)
                .environment(agent)
                .environment(relay))
        }
        Views.app["Said"] = { [weak conversations, weak hub] value, scope in
            let id = scope.text(value)
            guard let conversations, let hub else { return AnyView(EmptyView()) }
            guard let held = conversations.holding(id), held.message.card != nil || held.message.receipt != nil else {
                scope.context.report("Said: no conversation holds a card '\(id)'")
                return AnyView(EmptyView())
            }
            return AnyView(SaidCard(message: held.message, conversation: held.conversation)
                .environment(conversations)
                .environment(hub))
        }
    }
}

/// `{"Face": 56}`: the agent's face at that size, alive while he works.
private struct PageFace: View {
    @Environment(Conversations.self) private var conversations
    @Environment(Agent.self) private var agent
    @Environment(Relay.self) private var relay
    let size: CGFloat

    var body: some View {
        AgentFace(mood: agent.mood(working: conversations.presence(in: Conversations.main) != .idle, away: relay.sync == .agentAway))
            .frame(width: size, height: size)
            .clipShape(.circle)
            .glassEffect(.regular, in: .circle)
    }
}

/// `{"Said": id}`: a card the agent said, answerable where it shows; the
/// answer goes to its conversation. Once dealt with, what it left behind.
private struct SaidCard: View {
    let message: Conversations.Message
    let conversation: String

    var body: some View {
        if let receipt = message.receipt {
            CardReceipt(line: receipt, symbol: "checkmark.circle.fill", tint: .green)
                .frame(maxWidth: .infinity, alignment: .leading)
        } else if let card = message.card {
            InlineCard(card: card, messageID: message.id, conversation: conversation, loved: message.loved == true)
        }
    }
}
