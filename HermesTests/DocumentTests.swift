// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import Foundation
import SwiftUI
import Testing
@testable import Hermes

/// The org-element tree the app reads notes into (org/, through OrgTree),
/// what `org()` gives a screen, and how the tree draws.
@MainActor
@Suite("Documents")
struct DocumentTests {
    static let org = """
    #+TITLE: TOSEM revision plan
    #+AUTHOR: Julien
    #+TODO: TODO NEXT WAITING | DONE CANCELLED

    * Reviewers
    :PROPERTIES:
    :ID: 1234
    :END:
    The editor wants *major* revisions by =Nov 30=, see [[https://example.org/tosem][the decision letter]].
    ** TODO [#A] Answer reviewer 2 on threats to validity :writing:urgent:
       DEADLINE: <2026-11-30 Mon> SCHEDULED: <2026-11-02 Mon 09:00>
       - [X] Re-run the benchmark
       - [ ] Add the /second/ dataset
         - split by year
       - [-] Rewrite section 5
    ** DONE Fix the typos
       CLOSED: [2026-10-20 Tue 18:02]
    * Plan
    | Week | Task         |
    |------+--------------|
    | 45   | Experiments  |
    | 46   | Writing      |

    1. First pass
    2. Second pass
    - Term :: what it means
    #+BEGIN_SRC python
    print("hello")
    #+END_SRC
    #+BEGIN_QUOTE
    Reviewers are people too.
    #+END_QUOTE
    -----
    : fixed width
    """

    static let markdown = """
    ---
    title: Meeting brief
    date: 2026-10-24
    ---
    # Marta, Thursday

    We meet at **10:00** at the agency, about the *lease*. Bring `the inventory`.

    ## Points
    - [x] Notice period back to two months
    - [ ] Deposit
      1. Ask for the receipt
      2. Check the amount
    - Heating

    > She proposed this in her last email.
    > Second line.

    | Clause | Before | After |
    |---|:-:|---:|
    | 8.2 | 3 months | 2 months |

    ```swift
    let rent = 1480
    ```

    ***
    Setext heading
    ---
    The end.
    """

    @Test func orgHeadlinesKeepTheirKeywordsAndPlanning() throws {
        let tree = OrgTree.parse(Self.org, format: "org")
        #expect(tree["title"]?.string == "TOSEM revision plan")
        #expect(tree["keywords"]?["AUTHOR"]?.string == "Julien")
        let headlines = OrgTree.select(tree, "headline")
        #expect(headlines.map { $0["level"]?.int } == [1, 2, 2, 1])
        let answer = headlines[1]
        #expect(answer["todoKeyword"]?.string == "TODO")
        #expect(answer["priority"]?.string == "A")
        #expect(answer["tags"]?.array?.map(\.text) == ["writing", "urgent"])
        #expect(answer["title"]?.string == "Answer reviewer 2 on threats to validity")
        #expect(answer["scheduled"]?["start"]?.string == "2026-11-02T09:00")
        #expect(answer["deadline"]?["start"]?.string == "2026-11-30")
        #expect(headlines[2]["todoType"]?.string == "done")
        #expect(headlines[0]["properties"]?["ID"]?.string == "1234")
    }

    @Test func orgDrawersHideAndInlineMarkupStyles() throws {
        let tree = OrgTree.parse(Self.org, format: "org")
        let paragraph = try #require(OrgTree.select(tree, "paragraph").first)
        let text = Inline.attributed(paragraph["children"]?.array ?? [])
        #expect(String(text.characters) == "The editor wants major revisions by Nov 30, see the decision letter.")
        #expect(text.runs.contains { $0.inlinePresentationIntent == .stronglyEmphasized })
        #expect(text.runs.contains { $0.inlinePresentationIntent == .code })
        #expect(text.runs.contains { $0.link?.absoluteString == "https://example.org/tosem" })
        #expect(OrgTree.select(tree, "property-drawer").isEmpty)
    }

    @Test func orgListsNestAndCheck() throws {
        let tree = OrgTree.parse(Self.org, format: "org")
        let items = OrgTree.select(tree, "item")
        #expect(items.prefix(4).map { $0["checkbox"]?.string } == ["on", "off", nil, "trans"])
        #expect(items[1]["text"]?.string == "Add the second dataset")
        let nested = try #require(items[1]["children"]?.array?.first { $0["type"]?.string == "plain-list" })
        #expect(nested["children"]?.array?.first?["text"]?.string == "split by year" && items[2]["text"]?.string == "split by year")
        let term = try #require(items.first { $0["tag"] != nil })
        #expect(term["tag"]?.string == "Term" && term["text"]?.string == "what it means")
    }

    @Test func orgTablesBlocksAndRules() throws {
        let tree = OrgTree.parse(Self.org, format: "org")
        let table = try #require(OrgTree.select(tree, "table").first)
        let (header, rows) = TableBlock.rows(table)
        #expect(header?.map { String($0.characters) } == ["Week", "Task"])
        #expect(rows.count == 2)
        let source = try #require(OrgTree.select(tree, "src-block").first)
        #expect(source["language"]?.string == "python" && source["value"]?.string == "print(\"hello\")\n")
        #expect(!OrgTree.select(tree, "quote-block").isEmpty)
        #expect(!OrgTree.select(tree, "horizontal-rule").isEmpty)
        #expect(OrgTree.select(tree, "fixed-width").first?["value"]?.string == "fixed width")
    }

    @Test func markdownReadsIntoTheSameShape() throws {
        let tree = OrgTree.parse(Self.markdown, format: "markdown")
        #expect(tree["title"]?.string == "Meeting brief")
        #expect(tree["keywords"]?["DATE"]?.string == "2026-10-24")
        let headlines = OrgTree.select(tree, "headline")
        #expect(headlines.map { $0["title"]?.string } == ["Marta, Thursday", "Points", "Setext heading"])
        let points = headlines[1]
        let kinds = points["children"]?.array?.first?["children"]?.array?.map { $0["type"]?.string ?? "" } ?? []
        #expect(kinds == ["plain-list", "quote-block", "table", "src-block", "horizontal-rule"])
        let items = OrgTree.select(points, "item")
        #expect(items.prefix(3).map { $0["checkbox"]?.string } == ["on", "off", nil])
        #expect(items.count == 5 && items[2]["counter"]?.string == "1")
    }

    @Test func theLanguageReadsATextWithOrgAndMarkdown() throws {
        let headlines = try ExpressionFunctions.call("org", [.string(Self.org), "headline"])
        #expect(headlines.array?.count == 4)
        let tree = try ExpressionFunctions.call("markdown", [.string(Self.markdown)])
        #expect(tree["type"]?.string == "org-data")
        let open = try ExpressionFunctions.call("filter", [try ExpressionFunctions.call("org", [.string(Self.org), "item"]), "checkbox", "off"])
        #expect(open.array?.map { $0["text"]?.string } == ["Add the second dataset"])
    }

    @Test func aScriptReadsANoteThroughTheOrgHelper() async throws {
        let source = "function open({stores}) { return h.org(stores.daily.text, 'item').filter(i => i.checkbox == 'off').map(i => i.text) }"
        let input: JSONValue = .object(["stores": .object(["daily": .object(["text": .string(Self.org)])]), "now": JSONValue.iso(.now)])
        let result = await ScriptEngine.shared.call(source, function: "open", input: input, limit: 1)
        #expect(try result.get() == .array(["Add the second dataset"]))
    }

    @Test func editsLandOnTheItemTheyName() throws {
        let groceries = "# Groceries\n\n- [ ] Milk\n- [x] Bread\n- Eggs\n"
        #expect(try TextEdits.apply(groceries, .object(["change": "Milk", "to": "Oat milk"]), format: "markdown").contains("- [ ] Oat milk\n"))
        #expect(!(try TextEdits.apply(groceries, .object(["remove": "Bread"]), format: "markdown")).contains("Bread"))
        #expect(try TextEdits.apply(groceries, .object(["toggle": "Milk"]), format: "markdown").contains("- [x] Milk\n"))
        #expect(try TextEdits.apply(groceries, .object(["toggle": "Bread"]), format: "markdown").contains("- [ ] Bread\n"))
        #expect(try TextEdits.apply(groceries, .object(["toggle": "Eggs", "done": true]), format: "markdown").contains("- [x] Eggs\n"))
        #expect(try TextEdits.apply("- Fait\n", .object(["toggle": "Fait"]), format: "org").contains("- [X] Fait\n"))
        #expect(try TextEdits.apply("- [ ] Milk\n", .object(["append": "Bread"]), format: "markdown") == "- [ ] Milk\n- [ ] Bread\n")
        #expect(try TextEdits.apply("#+title: x\n", .object(["append": "Premier."]), format: "org") == "#+title: x\n\n- Premier.\n")
        let wrapped = "* Habits\n- [ ] A long task\n  that wraps\n- [X] Short\n"
        #expect(try TextEdits.apply(wrapped, .object(["toggle": "A long task that wraps"]), format: "org").hasPrefix("* Habits\n- [X] A long task\n  that wraps\n"))
        #expect(try TextEdits.apply(wrapped, .object(["remove": "A long task that wraps"]), format: "org") == "* Habits\n- [X] Short\n")
        #expect(throws: TextEdits.Refused.self) { try TextEdits.apply("- Milk\n", .object(["toggle": "Bread"]), format: "markdown") }
    }

    /// Set DOCUMENT_SNAPSHOTS to a folder to look at the documents drawn.
    @Test func documentsDraw() throws {
        for (name, format, text) in [("org", "org", Self.org), ("markdown", "markdown", Self.markdown)] {
            let content = DocumentView(tree: OrgTree.parse(text, format: format))
                .fixedSize(horizontal: false, vertical: true)
                .padding(20)
                .frame(width: 393)
                .background(Color(.systemBackground))
                .environment(\.documentSnapshot, true)
            let renderer = ImageRenderer(content: content)
            renderer.scale = 2
            let image = try #require(renderer.uiImage)
            #expect(image.size.height > 300)
            if let folder = ProcessInfo.processInfo.environment["DOCUMENT_SNAPSHOTS"] {
                try FileManager.default.createDirectory(atPath: folder, withIntermediateDirectories: true)
                try image.pngData()?.write(to: URL(filePath: folder).appending(path: "\(name).png"))
            }
        }
    }
}
