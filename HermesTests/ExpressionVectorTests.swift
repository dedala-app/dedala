// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import Foundation
import Testing
@testable import Hermes

/// Expressions as the phone evaluates them, written down once for the layout
/// twin to agree with (twin/tests/test_expressions.py reads the same file).
@MainActor
@Suite("Expression vectors")
struct ExpressionVectorTests {
    struct Vectors: Decodable {
        struct Case: Decodable {
            let expr: String
            let value: JSONValue
            let text: String?
        }

        let scope: [String: JSONValue]
        let cases: [Case]
    }

    @Test func thePhoneEvaluatesEveryVectorAsWritten() throws {
        let url = try #require(Bundle(for: VectorMarker.self).url(forResource: "expression-vectors", withExtension: "json"))
        let vectors = try JSONDecoder().decode(Vectors.self, from: Data(contentsOf: url))
        let scope = Scope(values: vectors.scope, boxes: [], context: CardContext(cardID: "vectors", component: { _ in nil }, onSend: { _, _ in }))
        #expect(vectors.cases.count > 80)
        for vector in vectors.cases {
            let found = scope.evaluate(vector.expr)
            #expect(Self.same(found, vector.value), "\(vector.expr) is \(found.text), not \(vector.value.text)")
            if let text = vector.text {
                #expect(found.text == text, "\(vector.expr) reads \(found.text), not \(text)")
            }
        }
    }

    private static func same(_ found: JSONValue, _ expected: JSONValue) -> Bool {
        switch (found, expected) {
        case (.number(let a), .number(let b)): abs(a - b) < 1e-9
        case (.array(let a), .array(let b)): a.count == b.count && zip(a, b).allSatisfy { same($0, $1) }
        default: found == expected
        }
    }
}
private final class VectorMarker {}
