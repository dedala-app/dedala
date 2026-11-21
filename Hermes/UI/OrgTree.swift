// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import Foundation
import HermesOrg

/// Org and Markdown read into the org-element tree (native/, the Rust library
/// the app links): `{"type", …properties, "children"}` nodes with their byte
/// range in the text. What `org()` and `markdown()` give Hermes UI and what
/// the `File` view draws; a text is parsed once and remembered.
nonisolated enum OrgTree {
    private static let remembered = NSCache<NSString, Box>()

    private final class Box {
        let value: JSONValue
        init(_ value: JSONValue) { self.value = value }
    }

    static func parse(_ text: String, format: String) -> JSONValue {
        let key = "\(format)\u{0}\(text)" as NSString
        if let found = remembered.object(forKey: key) { return found.value }
        let tree = (try? JSONValue.parse(Data(json(text, format: format).utf8))) ?? .object(["type": "org-data", "children": []])
        remembered.setObject(Box(tree), forKey: key, cost: text.utf8.count)
        return tree
    }

    private static let written = NSCache<NSString, NSString>()

    /// The tree as the library writes it, for a script's `h.org()`.
    static func json(_ text: String, format: String) -> String {
        let key = "\(format)\u{0}\(text)" as NSString
        if let found = written.object(forKey: key) { return found as String }
        guard let pointer = hermes_org_parse(text, format) else { return "{\"type\":\"org-data\",\"children\":[]}" }
        defer { hermes_org_free(pointer) }
        let json = String(cString: pointer)
        written.setObject(json as NSString, forKey: key, cost: json.utf8.count)
        return json
    }

    /// The nodes of one type anywhere under a node, in document order.
    static func select(_ tree: JSONValue, _ kind: String) -> [JSONValue] {
        var found: [JSONValue] = []
        func walk(_ node: JSONValue) {
            if node["type"]?.string == kind { found.append(node) }
            for child in node["children"]?.array ?? [] { walk(child) }
            for child in node["objects"]?.array ?? [] { walk(child) }
        }
        walk(tree)
        return found
    }
}
