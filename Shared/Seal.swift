// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import CryptoKit
import Foundation

/// Sealing as docs/relay.md describes it, matching relay/hermes_relay/seal.py
/// byte for byte: X25519 between the agent's and the device's keys, HKDF-SHA256
/// to one key per direction, ChaCha20-Poly1305 with the sequence number
/// authenticated.
nonisolated enum Seal {
    struct Message: Codable, Equatable, Sendable {
        let seq: Int
        let nonce: String
        let box: String
    }

    struct Keys: Sendable {
        let toApp: SymmetricKey
        let toAgent: SymmetricKey
    }

    enum Failure: Error {
        case badKey, badMessage
    }

    static func publicKey(_ key: Curve25519.KeyAgreement.PrivateKey) -> String {
        key.publicKey.rawRepresentation.base64EncodedString()
    }

    static func keys(own: Curve25519.KeyAgreement.PrivateKey, other: String, pairing: String) throws -> Keys {
        guard let raw = Data(base64Encoded: other),
              let theirs = try? Curve25519.KeyAgreement.PublicKey(rawRepresentation: raw) else { throw Failure.badKey }
        let shared = try own.sharedSecretFromKeyAgreement(with: theirs)
        func derive(_ info: String) -> SymmetricKey {
            shared.hkdfDerivedSymmetricKey(using: SHA256.self, salt: Data(pairing.utf8), sharedInfo: Data(info.utf8), outputByteCount: 32)
        }
        return Keys(toApp: derive("hermes-app v1 to-app"), toAgent: derive("hermes-app v1 to-agent"))
    }

    static func seal(_ plain: Data, seq: Int, key: SymmetricKey, nonce: ChaChaPoly.Nonce = ChaChaPoly.Nonce()) throws -> Message {
        let sealed = try ChaChaPoly.seal(plain, using: key, nonce: nonce, authenticating: Data(String(seq).utf8))
        return Message(seq: seq, nonce: Data(sealed.nonce).base64EncodedString(), box: (sealed.ciphertext + sealed.tag).base64EncodedString())
    }

    static func open(_ message: Message, key: SymmetricKey) throws -> Data {
        guard let nonceData = Data(base64Encoded: message.nonce), let box = Data(base64Encoded: message.box), box.count >= 16,
              let nonce = try? ChaChaPoly.Nonce(data: nonceData) else { throw Failure.badMessage }
        let sealed = try ChaChaPoly.SealedBox(nonce: nonce, ciphertext: box.dropLast(16), tag: box.suffix(16))
        return try ChaChaPoly.open(sealed, using: key, authenticating: Data(String(message.seq).utf8))
    }

    static func proofMac(proof: String, deviceKey: String) -> String {
        Data(HMAC<SHA256>.authenticationCode(for: Data(deviceKey.utf8), using: SymmetricKey(data: Data(proof.utf8)))).base64EncodedString()
    }
}
