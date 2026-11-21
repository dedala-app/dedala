// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import PDFKit
import QuickLook
import SwiftUI
import UIKit

/// A file drawn natively by its format: PDF pages, Markdown and Org rendered,
/// an image, plain text. What `{"File": …}` draws (Hermes UI) once the file
/// is on the phone.
struct FileReader: View {
    let url: URL
    let format: String
    var text: String?
    /// Whether the document's own title and keywords are drawn: not when the
    /// record it is has them as fields, drawn by the screen.
    var head = true

    @State private var tree: JSONValue?

    var body: some View {
        switch format {
        case "pdf":
            PDFReader(url: url)
        case "document":
            DocumentPreview(url: url)
        case "image":
            AsyncImage(url: url) { image in
                image.resizable().scaledToFit()
            } placeholder: {
                Color(.tertiarySystemFill)
            }
        case "markdown", "org":
            Group {
                if let tree {
                    DocumentView(tree: tree, head: head)
                        .textSelection(.enabled)
                } else {
                    Color.clear
                }
            }
            .task(id: text ?? url.path) {
                tree = OrgTree.parse(text ?? ((try? String(contentsOf: url, encoding: .utf8)) ?? ""), format: format)
            }
        default:
            Text(text ?? ((try? String(contentsOf: url, encoding: .utf8)) ?? ""))
                .font(.body.monospaced())
                .textSelection(.enabled)
                .frame(maxWidth: .infinity, alignment: .leading)
        }
    }
}

struct PDFReader: UIViewRepresentable {
    let url: URL

    func makeUIView(context: Context) -> PDFView {
        let view = PDFView()
        view.autoScales = true
        view.displayMode = .singlePageContinuous
        view.displayDirection = .vertical
        view.pageShadowsEnabled = true
        view.backgroundColor = .systemGroupedBackground
        view.document = PDFDocument(url: url)
        return view
    }

    func updateUIView(_ view: PDFView, context: Context) {
        if view.document?.documentURL != url {
            view.document = PDFDocument(url: url)
        }
    }
}

/// Any other document the system can show (Word, Pages, Keynote, spreadsheets,
/// archives…), through Quick Look.
struct DocumentPreview: UIViewControllerRepresentable {
    let url: URL

    func makeCoordinator() -> Coordinator { Coordinator(url: url) }

    func makeUIViewController(context: Context) -> QLPreviewController {
        let controller = QLPreviewController()
        controller.dataSource = context.coordinator
        return controller
    }

    func updateUIViewController(_ controller: QLPreviewController, context: Context) {
        if context.coordinator.url != url {
            context.coordinator.url = url
            controller.reloadData()
        }
    }

    final class Coordinator: NSObject, QLPreviewControllerDataSource {
        var url: URL
        init(url: URL) { self.url = url }
        func numberOfPreviewItems(in controller: QLPreviewController) -> Int { 1 }
        func previewController(_ controller: QLPreviewController, previewItemAt index: Int) -> QLPreviewItem { url as NSURL }
    }
}
