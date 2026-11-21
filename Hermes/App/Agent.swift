// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import Observation
import SwiftUI

/// Who the app talks to: its name and face, from the store `profile`
/// (protocol.md, Who the agent is), which the agent and you both write.
@Observable
final class Agent {
    private(set) var name: String
    private(set) var look: AvatarLook?
    /// The picture the profile names, once the phone holds it; the last one
    /// stays while a new one is on its way.
    private(set) var picture: UIImage?
    @ObservationIgnored private var pictureURL: URL?

    init() {
        name = PairingStore.load()?.agentName ?? "Assistant"
    }

    /// The name the pairing code gave, until the profile comes.
    func paired(_ name: String) {
        self.name = name
    }

    /// The profile as the phone shows it, and its picture's file when here.
    func show(_ profile: JSONValue?, picture url: URL?) {
        if let given = profile?["name"]?.string?.trimmingCharacters(in: .whitespacesAndNewlines), !given.isEmpty, given != name {
            name = given
            PairingStore.rename(given)
        }
        let look = profile?["look"].flatMap { $0.object == nil ? nil : AvatarLook($0, over: AvatarLook.derived(from: name)) }
        if look != self.look { self.look = look }
        guard profile?["picture"].map({ $0 != .null }) == true else {
            pictureURL = nil
            if picture != nil { picture = nil }
            return
        }
        guard let url, url != pictureURL, let image = UIImage(contentsOfFile: url.path) else { return }
        pictureURL = url
        picture = image
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

/// The agent's face: its picture, else its drawn look, else a face drawn
/// from its name.
struct AgentFace: View {
    @Environment(Agent.self) private var agent
    var mood = AgentMood.idle

    var body: some View {
        if let picture = agent.picture {
            Image(uiImage: picture)
                .resizable()
                .scaledToFill()
                .clipShape(.circle)
        } else {
            AvataaarFace(mood: mood, look: agent.look ?? AvatarLook.derived(from: agent.name))
        }
    }
}
