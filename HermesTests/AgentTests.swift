// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import Foundation
import Testing
@testable import Hermes

/// The agent's name and face come from the store `profile`, which the agent
/// and you both write.
@MainActor
@Suite("Agent")
struct AgentTests {
    @Test func aLookWrittenToTheStoreReadsBackTheSame() {
        let look = AvatarLook(skin: "edb98a", top: nil, hairColor: "4a312c", hatColor: "262e33", facialHair: "beardLight", facialHairColor: "4a312c",
                              accessories: nil, accessoriesColor: "262e33", clothing: "hoodie", clothesColor: "5199e4", clothingGraphic: "bat")
        #expect(AvatarLook(look.json, over: AvatarLook.derived(from: "Jo")) == look)
    }

    @Test func partsLeftOutOrUnknownAreDrawnFromTheName() {
        let base = AvatarLook.derived(from: "Jo")
        let look = AvatarLook(.object(["skin": "614335", "top": "fedora"]), over: base)
        #expect(look.skin == "614335" && look.top == base.top && look.clothing == base.clothing)
    }

    @Test func theProfileNamesTheAgentAndDrawsItsLook() {
        let agent = Agent()
        agent.show(.object(["name": "Jo", "look": .object(["skin": "614335", "accessories": "none"])]), picture: nil)
        #expect(agent.name == "Jo" && agent.look?.skin == "614335" && agent.look?.accessories == nil && agent.picture == nil)
        agent.show(.object(["name": "Jo"]), picture: nil)
        #expect(agent.look == nil)
    }
}
