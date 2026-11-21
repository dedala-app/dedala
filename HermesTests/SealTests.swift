// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import CryptoKit
import Foundation
import Testing
@testable import Hermes

/// The vectors come from relay/hermes_relay/seal.py: the app and the plugin
/// must agree byte for byte.
@Suite("Seal")
struct SealTests {
    struct Vector: Decodable {
        let agent_private: String
        let device_private: String
        let agent_public: String
        let device_public: String
        let pairing: String
        let to_app: String
        let to_agent: String
        let message: Seal.Message
        let plain: String
        let proof: String
        let mac: String
    }

    let vector: Vector = {
        let url = Bundle(for: Marker.self).url(forResource: "seal-vectors", withExtension: "json")!
        return try! JSONDecoder().decode(Vector.self, from: Data(contentsOf: url))
    }()

    private func key(_ base64: String) throws -> Curve25519.KeyAgreement.PrivateKey {
        try Curve25519.KeyAgreement.PrivateKey(rawRepresentation: Data(base64Encoded: base64)!)
    }

    @Test func publicKeysMatch() throws {
        #expect(Seal.publicKey(try key(vector.device_private)) == vector.device_public)
        #expect(Seal.publicKey(try key(vector.agent_private)) == vector.agent_public)
    }

    @Test func bothSidesDeriveTheReferenceKeys() throws {
        let device = try Seal.keys(own: try key(vector.device_private), other: vector.agent_public, pairing: vector.pairing)
        let agent = try Seal.keys(own: try key(vector.agent_private), other: vector.device_public, pairing: vector.pairing)
        for keys in [device, agent] {
            #expect(keys.toApp.withUnsafeBytes { Data($0) }.base64EncodedString() == vector.to_app)
            #expect(keys.toAgent.withUnsafeBytes { Data($0) }.base64EncodedString() == vector.to_agent)
        }
    }

    @Test func opensWhatPythonSealed() throws {
        let keys = try Seal.keys(own: try key(vector.device_private), other: vector.agent_public, pairing: vector.pairing)
        #expect(String(decoding: try Seal.open(vector.message, key: keys.toApp), as: UTF8.self) == vector.plain)
    }

    @Test func sealsWhatPythonSeals() throws {
        let keys = try Seal.keys(own: try key(vector.device_private), other: vector.agent_public, pairing: vector.pairing)
        let nonce = try ChaChaPoly.Nonce(data: Data(base64Encoded: vector.message.nonce)!)
        #expect(try Seal.seal(Data(vector.plain.utf8), seq: vector.message.seq, key: keys.toApp, nonce: nonce) == vector.message)
    }

    @Test func refusesAMessageMovedToAnotherSequenceNumber() throws {
        let keys = try Seal.keys(own: try key(vector.device_private), other: vector.agent_public, pairing: vector.pairing)
        let moved = Seal.Message(seq: vector.message.seq + 1, nonce: vector.message.nonce, box: vector.message.box)
        #expect(throws: (any Error).self) { try Seal.open(moved, key: keys.toApp) }
    }

    @Test func provesTheDeviceKeyLikePython() {
        #expect(Seal.proofMac(proof: vector.proof, deviceKey: vector.device_public) == vector.mac)
    }
}

private final class Marker {}
