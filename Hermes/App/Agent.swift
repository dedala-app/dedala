// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import Observation
import SwiftUI

/// Who the app talks to: the name and face the agent gives itself with
/// `{"op": "profile", "name", "avatar": {"asset"}}`, and the name and face you
/// gave him, which win over his.
@Observable
final class Agent {
    private(set) var ownName: String
    private(set) var givenName: String?
    private(set) var avatar: String?
    private(set) var look: AvatarLook?

    var name: String { givenName ?? ownName }

    init() {
        let saved = UserDefaults.standard
        ownName = saved.string(forKey: "agentName") ?? "Assistant"
        givenName = saved.string(forKey: "agentGivenName")
        avatar = saved.string(forKey: "agentAvatar")
        look = saved.data(forKey: "agentLook").flatMap { try? JSONDecoder().decode(AvatarLook.self, from: $0) }
    }

    func apply(_ op: JSONValue) {
        if let name = op["name"]?.string, !name.isEmpty {
            ownName = name
            UserDefaults.standard.set(name, forKey: "agentName")
            PairingStore.rename(self.name)
        }
        if let asset = op["avatar"]?["asset"]?.string {
            avatar = asset
            UserDefaults.standard.set(asset, forKey: "agentAvatar")
        }
    }

    /// The name you gave him; empty or nil gives him back his own.
    func setGivenName(_ name: String?) {
        let name = name?.trimmingCharacters(in: .whitespacesAndNewlines)
        let given = name?.isEmpty == false ? name : nil
        guard given != givenName else { return }
        givenName = given
        UserDefaults.standard.set(given, forKey: "agentGivenName")
        PairingStore.rename(self.name)
        onChoice?()
    }

    /// The face you made for him; nil gives him back his own.
    func setLook(_ look: AvatarLook?) {
        self.look = look
        UserDefaults.standard.set(look.flatMap { try? JSONEncoder().encode($0) }, forKey: "agentLook")
        onChoice?()
    }

    @ObservationIgnored var onChoice: (() -> Void)?

    /// The name and face you gave him, as they go to the agent's machine with
    /// how you arranged the app.
    var choices: [String: JSONValue] {
        var choices: [String: JSONValue] = [:]
        if let look = look.flatMap({ try? JSONEncoder().encode($0) }).flatMap({ try? JSONValue.parse($0) }) {
            choices["look"] = look
        }
        if let givenName { choices["name"] = .string(givenName) }
        return choices
    }

    /// The name and face you gave him on a phone paired before.
    func takeChoices(_ op: JSONValue) {
        if let value = op["look"], let look = try? JSONDecoder().decode(AvatarLook.self, from: value.data()), look != self.look {
            setLook(look)
        }
        if let name = op["name"]?.string {
            setGivenName(name)
        }
    }

    /// A look that comes over his mood for a moment: a wink, a glance up at
    /// the page, raised brows.
    private(set) var reaction: AgentMood?
    @ObservationIgnored private var reacting: Task<Void, Never>?

    func react(_ mood: AgentMood, for seconds: Double) {
        reacting?.cancel()
        reaction = mood
        reacting = Task {
            try? await Task.sleep(for: .seconds(seconds))
            guard !Task.isCancelled else { return }
            reaction = nil
        }
    }

    /// How he looks from what the app knows: his reaction while it lasts,
    /// thinking while he works, sleepy while he is away or in the small
    /// hours, else at ease.
    func mood(working: Bool, away: Bool) -> AgentMood {
        if let reaction { return reaction }
        if working { return .thinking }
        if away || Calendar.current.component(.hour, from: Clock.shared.minute) < 6 { return .sleepy }
        return .idle
    }
}

/// What the agent is doing, which his face shows: what he is up to, and the
/// short looks he gives.
enum AgentMood {
    case idle, thinking, speaking
    case glancing, sleepy, winking, surprised
}

/// The agent's face: the one you made for him, else his own picture, else an
/// Avataaars face drawn from his name.
struct AgentFace: View {
    @Environment(Agent.self) private var agent
    var mood = AgentMood.idle

    var body: some View {
        if let look = agent.look {
            AvataaarFace(mood: mood, look: look)
        } else if let asset = agent.avatar, let image = Assets.shared.image(asset) {
            Image(uiImage: image)
                .resizable()
                .scaledToFill()
                .clipShape(.circle)
        } else {
            AvataaarFace(mood: mood, look: AvatarLook.derived(from: agent.name))
        }
    }
}
