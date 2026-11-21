// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import SwiftUI

/// A message as a bubble: yours on the right in the accent color, the agent's
/// on the left. Its corners close where it joins its group. A long press
/// copies or shares it, or selects in place, as in Messages: the text turns
/// into a native one with the selection handles, until you tap away or scroll.
struct TextBubble: View {
    @Environment(\.conversationWidth) private var width
    let text: String
    let isYou: Bool
    var position = ConversationRows.Position.alone
    @State private var selecting = false
    @State private var textWidth: CGFloat = 0

    private static let round: CGFloat = 20
    private static let joined: CGFloat = 6

    var body: some View {
        content
            .padding(.horizontal, 14)
            .padding(.vertical, 9)
            .background(isYou ? Color.accentColor : Color(.systemGray5), in: shape)
            .contentShape(.contextMenuPreview, shape)
            .contextMenu {
                if !selecting {
                    Button("Copy", systemImage: "doc.on.doc") { UIPasteboard.general.string = String(Self.markdown(text).characters) }
                    Button("Select", systemImage: "selection.pin.in.out") { selecting = true }
                    ShareLink(item: String(Self.markdown(text).characters))
                }
            }
            .frame(maxWidth: width * 0.8, alignment: isYou ? .trailing : .leading)
    }

    @ViewBuilder private var content: some View {
        if selecting, textWidth > 0 {
            SelectingText(text: Self.native(text, color: isYou ? .white : .label)) { selecting = false }
                .frame(width: textWidth)
        } else {
            Text(Self.markdown(text))
                .foregroundStyle(isYou ? Color.white : Color.primary)
                .tint(isYou ? .white : .accentColor)
                .onGeometryChange(for: CGFloat.self) { $0.size.width } action: { textWidth = $0 }
        }
    }

    private var shape: UnevenRoundedRectangle {
        let top = position.opensGroup ? Self.round : Self.joined
        let bottom = position.closesGroup ? Self.round : Self.joined
        return UnevenRoundedRectangle(
            topLeadingRadius: isYou ? Self.round : top,
            bottomLeadingRadius: isYou ? Self.round : bottom,
            bottomTrailingRadius: isYou ? bottom : Self.round,
            topTrailingRadius: isYou ? top : Self.round,
            style: .continuous
        )
    }

    /// Gives back the bubble being selected, if any.
    static func endSelection() {
        _ = SelectingText.SelectionView.current?.resignFirstResponder()
    }

    /// Inline Markdown (bold, italic, code, links), keeping the line breaks.
    static func markdown(_ text: String) -> AttributedString {
        (try? AttributedString(markdown: text, options: .init(interpretedSyntax: .inlineOnlyPreservingWhitespace))) ?? AttributedString(text)
    }

    /// The same text for UIKit, with the fonts the Markdown asks for.
    static func native(_ text: String, color: UIColor) -> NSAttributedString {
        let body = UIFont.preferredFont(forTextStyle: .body)
        let result = NSMutableAttributedString()
        for run in markdown(text).runs {
            var font = body
            let intent = run.inlinePresentationIntent ?? []
            if intent.contains(.code) {
                font = .monospacedSystemFont(ofSize: body.pointSize, weight: .regular)
            } else {
                var traits: UIFontDescriptor.SymbolicTraits = []
                if intent.contains(.stronglyEmphasized) { traits.insert(.traitBold) }
                if intent.contains(.emphasized) { traits.insert(.traitItalic) }
                if !traits.isEmpty, let descriptor = body.fontDescriptor.withSymbolicTraits(traits) {
                    font = UIFont(descriptor: descriptor, size: body.pointSize)
                }
            }
            var attributes: [NSAttributedString.Key: Any] = [.font: font, .foregroundColor: color]
            if let link = run.link {
                attributes[.link] = link
            }
            result.append(NSAttributedString(string: String(markdown(text)[run.range].characters), attributes: attributes))
        }
        return result
    }
}

/// A bubble's text being selected: a native text view that opens with all of
/// it selected and gives the bubble back once it loses the selection.
struct SelectingText: UIViewRepresentable {
    let text: NSAttributedString
    let done: () -> Void

    func makeUIView(context: Context) -> SelectionView {
        let view = SelectionView()
        view.isEditable = false
        view.isSelectable = true
        view.isScrollEnabled = false
        view.backgroundColor = .clear
        view.textContainerInset = .zero
        view.textContainer.lineFragmentPadding = 0
        view.attributedText = text
        view.linkTextAttributes = [.underlineStyle: NSUnderlineStyle.single.rawValue]
        view.done = done
        Task { @MainActor in
            view.becomeFirstResponder()
            view.selectedRange = NSRange(location: 0, length: text.length)
        }
        return view
    }

    func updateUIView(_ view: SelectionView, context: Context) {
        view.done = done
    }

    func sizeThatFits(_ proposal: ProposedViewSize, uiView: SelectionView, context: Context) -> CGSize? {
        let width = proposal.width ?? uiView.bounds.width
        return CGSize(width: width, height: uiView.sizeThatFits(CGSize(width: width, height: .greatestFiniteMagnitude)).height)
    }

    final class SelectionView: UITextView {
        var done: (() -> Void)?
        @MainActor static weak var current: SelectionView?

        override func becomeFirstResponder() -> Bool {
            let became = super.becomeFirstResponder()
            if became { Self.current = self }
            return became
        }

        override func resignFirstResponder() -> Bool {
            let resigned = super.resignFirstResponder()
            if resigned {
                if Self.current === self { Self.current = nil }
                done?()
            }
            return resigned
        }
    }
}

/// The message field: one glass bar that grows with what you write, up to six
/// lines (Return starts a new one), and the button that sends it. While the
/// agent works and nothing is written, that button stops it instead.
struct Composer: View {
    var placeholder = "Message"
    var onStop: (() -> Void)?
    let onSend: (String) -> Void

    @State private var text = ""
    @FocusState private var focused: Bool

    private var empty: Bool {
        text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    private var stops: Bool {
        empty && onStop != nil
    }

    var body: some View {
        GlassEffectContainer(spacing: 8) {
            HStack(alignment: .bottom, spacing: 8) {
                TextField(placeholder, text: $text, axis: .vertical)
                    .lineLimit(1...6)
                    .focused($focused)
                    .padding(.horizontal, 16)
                    .padding(.vertical, 11)
                    .frame(minHeight: 44)
                    .contentShape(.rect(cornerRadius: 22, style: .continuous))
                    .onTapGesture { focused = true }
                    .glassEffect(.regular.interactive(), in: .rect(cornerRadius: 22, style: .continuous))
                Button {
                    if stops { onStop?() } else { send() }
                } label: {
                    Label(stops ? "Stop" : "Send", systemImage: stops ? "stop.fill" : "arrow.up")
                        .labelStyle(.iconOnly)
                        .font(.body.weight(.bold))
                        .contentTransition(.symbolEffect(.replace))
                        .frame(width: 44, height: 44)
                        .contentShape(.circle)
                }
                .foregroundStyle(stops ? AnyShapeStyle(.primary) : empty ? AnyShapeStyle(.secondary) : AnyShapeStyle(.white))
                .glassEffect(stops ? .regular.interactive() : empty ? .regular : .regular.tint(.accentColor).interactive(), in: .circle)
                .disabled(empty && !stops)
                .animation(.snappy, value: empty)
                .animation(.snappy, value: stops)
            }
        }
        .padding(.horizontal, 16)
        .padding(.top, 6)
        .padding(.bottom, 8)
    }

    private func send() {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }
        onSend(trimmed)
        text = ""
    }
}

/// What a card leaves behind once it's dealt with.
struct CardReceipt: View {
    let line: String
    let symbol: String
    let tint: Color

    var body: some View {
        Label {
            Text(line)
                .foregroundStyle(.primary)
        } icon: {
            Image(systemName: symbol)
                .foregroundStyle(tint)
        }
        .font(.subheadline.weight(.medium))
        .padding(.horizontal, 12)
        .padding(.vertical, 8)
        .background(Color(.systemGray6), in: .capsule)
        .transition(.scale(scale: 0.9, anchor: .leading).combined(with: .opacity))
    }
}

/// The soft Contact Poster wash behind the agent.
struct PosterWash: View {
    var body: some View {
        MeshGradient(
            width: 3,
            height: 3,
            points: [
                [0, 0], [0.5, 0], [1, 0],
                [0, 0.5], [0.6, 0.45], [1, 0.5],
                [0, 1], [0.5, 1], [1, 1],
            ],
            colors: [
                Color(red: 0.80, green: 0.85, blue: 1.00), Color(red: 0.88, green: 0.82, blue: 1.00), Color(red: 1.00, green: 0.86, blue: 0.80),
                Color(red: 0.75, green: 0.88, blue: 0.98), Color(red: 0.90, green: 0.86, blue: 0.98), Color(red: 0.98, green: 0.90, blue: 0.86),
                Color(.systemBackground), Color(.systemBackground), Color(.systemBackground),
            ]
        )
        .ignoresSafeArea(edges: .top)
    }
}

struct TitledSection<Content: View>: View {
    let title: String
    @ViewBuilder let content: Content

    init(_ title: String, @ViewBuilder content: () -> Content) {
        self.title = title
        self.content = content()
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(title)
                .font(.title3.bold())
            content
        }
    }
}

struct GroupedRows<Content: View>: View {
    @ViewBuilder let content: Content

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            content
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color(.secondarySystemGroupedBackground), in: .rect(cornerRadius: 22, style: .continuous))
    }
}
