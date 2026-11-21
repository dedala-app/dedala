// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import SwiftUI

/// The pages the tutorial shows, kept in Samples.json as an agent would send
/// them: a reading list, and a week whose train is late, with what they read.
enum Samples {
    static func load(agent: String) -> JSONValue {
        guard let url = Bundle.main.url(forResource: "Samples", withExtension: "json"),
              let text = try? String(contentsOf: url, encoding: .utf8),
              let now = JSONValue.iso(.now.addingTimeInterval(-60)).string,
              let value = try? JSONValue.parse(Data(text.replacingOccurrences(of: "@SINCE@", with: now).utf8)) else { return .null }
        let day = Date.now.formatted(.dateTime.weekday(.wide).day().month(.wide))
        return value.merging(.object(["week": .object(["stores": .object(["week": .object(["day": .string(day), "agent": .string(agent)])])])]))
    }
}

/// A sample page's view drawn by the app's own renderer, as a page draws it;
/// nothing in it answers a tap.
private struct SampleView: View {
    let sample: JSONValue
    let components: [String: JSONValue]
    @State private var context: CardContext

    init(sample: JSONValue, components: [String: JSONValue]) {
        self.sample = sample
        self.components = components
        _context = State(initialValue: CardContext(cardID: "sample", component: { name in components[name].flatMap(ComponentDefinition.init) },
                                                   onSend: { _, _ in }))
    }

    var body: some View {
        StateScopeView(initial: [:], node: sample["view"] ?? .null,
                       scope: Scope(values: [:], boxes: [], context: context, stores: sample["stores"]?.object ?? [:]))
            .allowsHitTesting(false)
    }
}

/// How the app's own screens look behind the pictures: its text colours over
/// the onboarding's; the accent is the app's, which the onboarding leaves alone.
private struct AppLook: ViewModifier {
    func body(content: Content) -> some View {
        content
            .foregroundStyle(.primary)
            .allowsHitTesting(false)
    }
}

/// A request in the conversation, then the page it made, new in the tab bar.
struct AskIllustration: View {
    @Environment(Agent.self) private var agent

    var body: some View {
        let samples = Samples.load(agent: agent.name)
        VStack(spacing: 0) {
            VStack(alignment: .leading, spacing: 8) {
                TextBubble(text: "Keep my reading list somewhere I can see it", isYou: true)
                    .frame(maxWidth: .infinity, alignment: .trailing)
                StepsTrace(steps: [.init(text: "Read books.org", symbol: "doc.text"), .init(text: "Worked on the page Reading", symbol: "square.grid.2x2")])
                    .padding(.top, 4)
                TextBubble(text: "Done. Your reading list has its own page.", isYou: false)
            }
            .padding(EdgeInsets(top: 20, leading: 14, bottom: 16, trailing: 14))
            .background(Color(.systemBackground))
            VStack(alignment: .leading, spacing: 10) {
                Text(samples["reading"]?["title"]?.string ?? "Reading")
                    .font(.title2.bold())
                    .padding(.horizontal, 4)
                SampleView(sample: samples["reading"] ?? .null, components: samples["components"]?.object ?? [:])
                Spacer(minLength: 0)
                TabBarSketch(tabs: [("This week", "calendar"), ("Budget", "eurosign.circle"), ("Reading", "books.vertical")], selected: 2)
            }
            .padding(EdgeInsets(top: 16, leading: 14, bottom: 12, trailing: 14))
            .frame(maxHeight: .infinity)
            .background(Color(.systemGroupedBackground))
        }
        .environment(\.conversationWidth, 332)
        .modifier(AppLook())
    }
}

/// The week page as its job left it: the train late, the agent saying so.
struct UpkeepIllustration: View {
    @Environment(Agent.self) private var agent

    var body: some View {
        let samples = Samples.load(agent: agent.name)
        let week = samples["week"] ?? .null
        VStack(alignment: .leading, spacing: 2) {
            Text(week["title"]?.string ?? "This week")
                .font(.largeTitle.bold())
            Freshness(upkeep: week["upkeep"], updated: .now) {}
            SampleView(sample: week, components: samples["components"]?.object ?? [:])
                .padding(.top, 14)
            Spacer(minLength: 0)
        }
        .padding(EdgeInsets(top: 22, leading: 16, bottom: 16, trailing: 16))
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .background(Color(.systemGroupedBackground))
        .modifier(AppLook())
    }
}

/// The system's tab bar as the app shows it: glass, the page you are on in the accent.
private struct TabBarSketch: View {
    let tabs: [(String, String)]
    let selected: Int

    var body: some View {
        HStack(spacing: 0) {
            ForEach(tabs.indices, id: \.self) { index in
                VStack(spacing: 2) {
                    Image(systemName: tabs[index].1).font(.title3)
                    Text(tabs[index].0).font(.caption2.weight(.medium))
                }
                .foregroundStyle(index == selected ? Color.accentColor : Color.primary)
                .frame(maxWidth: .infinity)
                .padding(.vertical, 6)
                .background(index == selected ? Color.primary.opacity(0.07) : .clear, in: .capsule)
            }
        }
        .padding(4)
        .glassEffect(.regular, in: .capsule)
    }
}

/// What iOS shows on the Lock Screen for the app: a notification with its
/// buttons, a Live Activity, widgets. iOS draws those, in its own colours.
struct OutsideIllustration: View {
    @Environment(Agent.self) private var agent

    var body: some View {
        VStack(spacing: 10) {
            VStack(spacing: 0) {
                Text(Date.now.formatted(.dateTime.weekday(.wide).day().month(.wide))).font(.subheadline.weight(.semibold)).opacity(0.85)
                Text("19:02").font(.system(size: 62, weight: .bold, design: .rounded))
            }
            VStack(alignment: .leading, spacing: 10) {
                HStack(alignment: .top, spacing: 10) {
                    DedalaMark(size: 22)
                        .frame(width: 30, height: 30)
                        .background(Color(hex: 0xFBF8F3), in: .rect(cornerRadius: 8, style: .continuous))
                    VStack(alignment: .leading, spacing: 2) {
                        HStack {
                            Text(agent.name).fontWeight(.semibold)
                            Spacer()
                            Text("now").opacity(0.75)
                        }
                        Text("The domain renews tomorrow for €14. Go ahead?")
                    }
                    .font(.footnote)
                }
                HStack(spacing: 8) {
                    Text("Approve").fontWeight(.semibold).frame(maxWidth: .infinity, minHeight: 32).background(.white.opacity(0.22), in: .capsule)
                    Text("Not now").frame(maxWidth: .infinity, minHeight: 32).background(.white.opacity(0.12), in: .capsule)
                }
                .font(.footnote)
            }
            .padding(12)
            .background(.white.opacity(0.16), in: .rect(cornerRadius: 22, style: .continuous))
            VStack(alignment: .leading, spacing: 7) {
                HStack {
                    Text("Train to Lyon").font(.subheadline.weight(.semibold))
                    Spacer()
                    Text("12 min late").font(.footnote.weight(.semibold)).foregroundStyle(.orange)
                }
                HStack {
                    Text("Platform 7")
                    Spacer()
                    Text("Leaves 19:16")
                }
                .font(.caption)
                .opacity(0.8)
                ProgressView(value: 0.68).tint(.orange)
            }
            .padding(12)
            .background(.black.opacity(0.55), in: .rect(cornerRadius: 22, style: .continuous))
            HStack(spacing: 10) {
                Widget(caption: "Budget · November", value: "€312 left")
                Widget(caption: "Reading", value: "Piranesi, p. 112")
            }
            Spacer(minLength: 0)
        }
        .padding(EdgeInsets(top: 22, leading: 18, bottom: 18, trailing: 18))
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Color(white: 0.16))
        .foregroundStyle(.white)
        .environment(\.colorScheme, .dark)
    }

    private struct Widget: View {
        let caption: String
        let value: String

        var body: some View {
            VStack(alignment: .leading, spacing: 2) {
                Text(caption).font(.caption2).opacity(0.75)
                Text(value).font(.subheadline.weight(.semibold)).lineLimit(1)
            }
            .padding(12)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(.white.opacity(0.16), in: .rect(cornerRadius: 18, style: .continuous))
        }
    }
}
