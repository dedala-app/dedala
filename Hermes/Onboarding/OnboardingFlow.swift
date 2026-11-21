// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import SwiftUI
import UserNotifications
import VisionKit

/// Where a new install begins: what the app is, in three pictures, then
/// connecting the assistant, asking to notify, and what came back.
@Observable
final class Onboarding {
    enum Step: String, CaseIterable {
        case welcome, ask, upkeep, outside, connect, scan, notifications, connected
    }

    var step: Step
    /// Whether the flow was seen to its end once; unpaired later, it starts at connecting.
    var done = UserDefaults.standard.bool(forKey: "onboarded") {
        didSet { UserDefaults.standard.set(done, forKey: "onboarded") }
    }
    #if DEBUG
    /// A screen shown from the Mac over USB, whatever the state: a step, `paywall` or `ended`.
    var shown: String?
    #endif

    init(paired: Bool) {
        let done = UserDefaults.standard.bool(forKey: "onboarded")
        step = done ? .connect : paired ? .connected : .welcome
    }

    static let tutorial: [Step] = [.ask, .upkeep, .outside]

    func go(_ step: Step) {
        withAnimation(.snappy) { self.step = step }
    }
}

/// The app, or what stands before it: the onboarding while no assistant is
/// connected, the paywall while nothing is paid for.
struct AppRoot: View {
    @Environment(Relay.self) private var relay
    @Environment(Store.self) private var store
    @Environment(Onboarding.self) private var onboarding

    var body: some View {
        Group {
            #if DEBUG
            if let shown = onboarding.shown {
                if shown == "app" {
                    RootTabs()
                } else if shown == "paywall" || shown == "ended" {
                    PaywallView(ended: shown == "ended")
                } else {
                    OnboardingFlow(step: Onboarding.Step(rawValue: shown) ?? .welcome)
                }
            } else {
                gate
            }
            #else
            gate
            #endif
        }
        .animation(.snappy, value: relay.state == .unpaired)
        .animation(.snappy, value: onboarding.done)
    }

    @ViewBuilder private var gate: some View {
        if relay.state == .unpaired || !onboarding.done {
            OnboardingFlow(step: nil)
        } else if store.locked {
            PaywallView(ended: !store.trialAvailable)
        } else {
            RootTabs()
        }
    }
}

struct OnboardingFlow: View {
    @Environment(Onboarding.self) private var onboarding
    /// A step to show whatever the flow's own, from the Mac.
    let step: Onboarding.Step?

    var body: some View {
        let current = step ?? onboarding.step
        ZStack {
            Brand.ground.ignoresSafeArea()
            switch current {
            case .welcome: Welcome()
            case .ask, .upkeep, .outside: Tutorial(page: current)
            case .connect: Connect()
            case .scan: Scan()
            case .notifications: AskToNotify()
            case .connected: Connected()
            }
        }
        .foregroundStyle(Brand.ink)
    }
}

private struct Welcome: View {
    @Environment(Onboarding.self) private var onboarding

    var body: some View {
        VStack(spacing: 14) {
            Spacer()
            DedalaMark(size: 96)
                .frame(width: 132, height: 132)
                .background(Brand.surface, in: .rect(cornerRadius: 30, style: .continuous))
                .shadow(color: Color(hex: 0x784614).opacity(0.14), radius: 16, y: 12)
                .padding(.bottom, 14)
            Text("Dedala")
                .font(.system(size: 40, weight: .bold))
            Text("The app for your personal AI assistant")
                .font(.title3.weight(.semibold))
            Text("Your assistant builds this app as you talk to it: pages, cards, and reminders on your Lock Screen.")
                .font(.body)
                .foregroundStyle(Brand.quiet)
            Spacer()
            BrandButton(title: "Get started") { onboarding.go(.ask) }
            BrandLink(title: "I've used Dedala before") { onboarding.go(.connect) }
        }
        .multilineTextAlignment(.center)
        .padding(.horizontal, 28)
        .padding(.bottom, 12)
    }
}

/// The three pictures, swiped or stepped through.
private struct Tutorial: View {
    @Environment(Onboarding.self) private var onboarding
    let page: Onboarding.Step

    var body: some View {
        let selection = Binding(get: { page }, set: { onboarding.go($0) })
        VStack(spacing: 0) {
            HStack {
                Spacer()
                Button("Skip") { onboarding.go(.connect) }
                    .font(.body.weight(.medium))
                    .foregroundStyle(Brand.bronze)
                    .frame(minWidth: 44, minHeight: 44)
            }
            .padding(.horizontal, 20)
            TabView(selection: selection) {
                ForEach(Onboarding.tutorial, id: \.self) { step in
                    TutorialPage(step: step).tag(step)
                }
            }
            .tabViewStyle(.page(indexDisplayMode: .never))
            HStack(spacing: 8) {
                ForEach(Onboarding.tutorial, id: \.self) { step in
                    Capsule()
                        .fill(step == page ? Brand.bronze : Brand.quiet.opacity(0.35))
                        .frame(width: step == page ? 22 : 8, height: 8)
                }
            }
            .padding(.vertical, 18)
            .accessibilityElement()
            .accessibilityLabel("Step \((Onboarding.tutorial.firstIndex(of: page) ?? 0) + 1) of 3")
            Group {
                if page == .outside {
                    BrandButton(title: "Connect your assistant") { onboarding.go(.connect) }
                } else {
                    BrandButton(title: "Continue") {
                        onboarding.go(Onboarding.tutorial[(Onboarding.tutorial.firstIndex(of: page) ?? 0) + 1])
                    }
                }
            }
            .padding(.horizontal, 24)
            .padding(.bottom, 12)
        }
    }
}

private struct TutorialPage: View {
    let step: Onboarding.Step

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Fitted(size: CGSize(width: 360, height: 540)) {
                Group {
                    switch step {
                    case .ask: AskIllustration()
                    case .upkeep: UpkeepIllustration()
                    default: OutsideIllustration()
                    }
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .clipShape(.rect(cornerRadius: 28, style: .continuous))
                .overlay {
                    RoundedRectangle(cornerRadius: 28, style: .continuous).strokeBorder(Brand.line, lineWidth: 1)
                }
                .dynamicTypeSize(.large)
            }
            .frame(minHeight: 160, maxHeight: 460)
            .accessibilityHidden(true)
            .padding(.top, 8)
            Text(title)
                .font(.system(size: 28, weight: .bold))
                .fixedSize(horizontal: false, vertical: true)
                .padding(.top, 28)
            Text(text)
                .font(.body)
                .foregroundStyle(Brand.quiet)
                .fixedSize(horizontal: false, vertical: true)
                .padding(.top, 10)
        }
        .padding(.horizontal, 24)
        .frame(maxHeight: .infinity, alignment: .top)
    }

    private var title: String {
        switch step {
        case .ask: "Ask, and it builds"
        case .upkeep: "It keeps what it built up to date"
        default: "It reaches you outside the app"
        }
    }

    private var text: String {
        switch step {
        case .ask: "Tell your assistant what you need. It writes the page, the card or the reminder itself, and it appears here. Nothing to set up by hand."
        case .upkeep: "On a schedule, when something changes, or when something breaks, your assistant updates its pages without being asked."
        default: "Notifications you can answer from the Lock Screen, Live Activities that follow what is happening, widgets on your Home Screen."
        }
    }
}

private struct BackButton: View {
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Image(systemName: "chevron.left")
                .font(.title3.weight(.semibold))
                .foregroundStyle(Brand.bronze)
                .frame(width: 44, height: 44)
        }
        .accessibilityLabel("Back")
    }
}

private struct Connect: View {
    @Environment(Onboarding.self) private var onboarding

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            BackButton { onboarding.go(onboarding.done ? .welcome : .outside) }
                .padding(.leading, -10)
            Fitting {
                VStack(alignment: .leading, spacing: 0) {
                    Text("Connect your assistant")
                        .font(.system(size: 32, weight: .bold))
                        .padding(.top, 16)
                    Text("Dedala works with Hermes Agent running on your own machine. Two commands there, then a scan here.")
                        .foregroundStyle(Brand.quiet)
                        .padding(.top, 12)
                    VStack(spacing: 0) {
                        Instruction(number: 1, title: "Add the app plugin to Hermes", command: "hermes plugins install dedala", detail: nil)
                        Divider().overlay(Brand.line)
                        Instruction(number: 2, title: "Show a pairing code", command: "hermes dedala pair", detail: nil)
                        Divider().overlay(Brand.line)
                        Instruction(number: 3, title: "Scan it with this \(UIDevice.current.model)", command: nil, detail: "The code is valid for ten minutes.")
                    }
                    .padding(.horizontal, 18)
                    .background(Brand.surface, in: .rect(cornerRadius: 22, style: .continuous))
                    .padding(.top, 28)
                    Label("What you and your assistant say is end-to-end encrypted. The server that carries it cannot read it.", systemImage: "lock")
                        .font(.subheadline)
                        .foregroundStyle(Brand.quiet)
                        .padding(.top, 16)
                        .padding(.horizontal, 4)
                        .padding(.bottom, 16)
                }
            }
            Spacer(minLength: 0)
            BrandButton(title: "Scan the code") { onboarding.go(.scan) }
            Link("I don't have an assistant yet", destination: URL(string: "https://github.com/NousResearch/hermes-agent")!)
                .font(.body.weight(.medium))
                .foregroundStyle(Brand.bronze)
                .frame(maxWidth: .infinity, minHeight: 44)
        }
        .padding(.horizontal, 24)
        .padding(.bottom, 12)
    }

    private struct Instruction: View {
        let number: Int
        let title: String
        let command: String?
        let detail: String?

        var body: some View {
            HStack(alignment: .top, spacing: 14) {
                Text("\(number)")
                    .font(.subheadline.bold())
                    .foregroundStyle(Brand.bronze)
                    .frame(width: 28, height: 28)
                    .background(Brand.tint, in: .circle)
                VStack(alignment: .leading, spacing: 8) {
                    Text(title).font(.body.weight(.semibold))
                    if let command { ShellCommand(text: command) }
                    if let detail { Text(detail).font(.subheadline).foregroundStyle(Brand.quiet) }
                }
            }
            .padding(.vertical, 16)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }
}

/// The camera on the code `hermes dedala pair` shows, or the code pasted.
private struct Scan: View {
    @Environment(Onboarding.self) private var onboarding
    @Environment(Relay.self) private var relay
    @State private var pairing = false
    @State private var problem: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            BackButton { onboarding.go(.connect) }
                .padding(.leading, -10)
            Text("Scan the code")
                .font(.system(size: 32, weight: .bold))
                .padding(.top, 8)
            Text("Point the camera at the code that \(Text("hermes dedala pair").font(.subheadline.monospaced()).foregroundStyle(Brand.ink)) shows.")
                .foregroundStyle(Brand.quiet)
                .padding(.top, 10)
            Group {
                if DataScannerViewController.isSupported, DataScannerViewController.isAvailable {
                    QRScanner { code in pair(code) }
                } else {
                    ContentUnavailableView("No camera here", systemImage: "camera", description: Text("Paste the code instead."))
                        .foregroundStyle(.white)
                }
            }
            .frame(maxWidth: .infinity)
            .frame(minHeight: 180, maxHeight: 342)
            .background(Color(hex: 0x17130F))
            .clipShape(.rect(cornerRadius: 28, style: .continuous))
            .overlay {
                if pairing { ProgressView().controlSize(.large).tint(.white) }
            }
            .padding(.top, 24)
            if let problem {
                Text(problem)
                    .font(.subheadline)
                    .foregroundStyle(.red)
                    .padding(.top, 16)
            } else {
                Text("Can't scan from here?")
                    .font(.subheadline.weight(.semibold))
                    .padding(.top, 20)
                Text("Under the QR code, the command also prints the code as text. Copy it and paste it here.")
                    .font(.subheadline)
                    .foregroundStyle(Brand.quiet)
                    .padding(.top, 6)
            }
            Spacer(minLength: 0)
            Button {
                if let code = UIPasteboard.general.string { pair(code) }
            } label: {
                Label("Paste the code", systemImage: "doc.on.clipboard")
                    .font(.body.weight(.semibold))
                    .frame(maxWidth: .infinity, minHeight: 34)
            }
            .buttonStyle(.glass)
            .controlSize(.large)
            .disabled(pairing)
        }
        .padding(.horizontal, 24)
        .padding(.bottom, 12)
    }

    private func pair(_ code: String) {
        guard !pairing else { return }
        pairing = true
        problem = nil
        Task {
            do {
                try await relay.pair(with: code)
                UINotificationFeedbackGenerator().notificationOccurred(.success)
                let asked = await UNUserNotificationCenter.current().notificationSettings().authorizationStatus != .notDetermined
                onboarding.go(asked ? .connected : .notifications)
            } catch {
                problem = error.localizedDescription
            }
            pairing = false
        }
    }
}

private struct AskToNotify: View {
    @Environment(Onboarding.self) private var onboarding
    @Environment(Agent.self) private var agent

    var body: some View {
        VStack(spacing: 0) {
            Fitting {
                VStack(spacing: 28) {
                    Image(systemName: "bell")
                        .font(.system(size: 40, weight: .medium))
                        .foregroundStyle(Brand.bronze)
                        .frame(width: 96, height: 96)
                        .background(Brand.tint, in: .circle)
                    VStack(spacing: 12) {
                        Text("Let \(agent.name) reach you")
                            .font(.system(size: 30, weight: .bold))
                        Text("\(agent.name) can tell you when something needs you, and keep a Live Activity on your Lock Screen while something is under way.")
                            .foregroundStyle(Brand.quiet)
                    }
                    .multilineTextAlignment(.center)
                    VStack(spacing: 0) {
                        Example(text: "Your train is late, with the new platform")
                        Divider().overlay(Brand.line)
                        Example(text: "A bill to approve, answered from the notification")
                        Divider().overlay(Brand.line)
                        Example(text: "Something \(agent.name) was asked to watch has changed")
                    }
                    .padding(.horizontal, 18)
                    .background(Brand.surface, in: .rect(cornerRadius: 22, style: .continuous))
                    Text("Notifications are encrypted until they reach this \(UIDevice.current.model).")
                        .font(.subheadline)
                        .foregroundStyle(Brand.quiet)
                        .multilineTextAlignment(.center)
                }
                .padding(.vertical, 16)
                .frame(maxHeight: .infinity)
            }
            VStack(spacing: 0) {
                BrandButton(title: "Allow notifications") {
                    Task {
                        _ = try? await UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound, .badge])
                        onboarding.go(.connected)
                    }
                }
                BrandLink(title: "Not now") { onboarding.go(.connected) }
            }
        }
        .padding(.horizontal, 24)
        .padding(.bottom, 12)
    }

    private struct Example: View {
        let text: String

        var body: some View {
            HStack(spacing: 12) {
                Circle().fill(Brand.mark).frame(width: 8, height: 8)
                Text(text).font(.subheadline).fixedSize(horizontal: false, vertical: true)
                Spacer(minLength: 0)
            }
            .padding(.vertical, 14)
        }
    }
}

/// The assistant connected: what it gave back, once the app is in sync, or
/// an invitation to say hello when there was nothing to give back.
private struct Connected: View {
    @Environment(Onboarding.self) private var onboarding
    @Environment(Relay.self) private var relay
    @Environment(Agent.self) private var agent
    @Environment(Hub.self) private var hub
    @Environment(Conversations.self) private var conversations
    @State private var waited = false

    var body: some View {
        let settled = relay.sync == .upToDate || waited
        let returning = !hub.pages.isEmpty || !conversations.main.isEmpty || !conversations.topics.isEmpty
        VStack(spacing: 0) {
            Fitting {
                VStack(spacing: 28) {
                    AgentDot(size: 112, reachable: true)
                        .overlay(alignment: .bottomTrailing) {
                            Image(systemName: "checkmark")
                                .font(.body.bold())
                                .foregroundStyle(.white)
                                .frame(width: 36, height: 36)
                                .background(Color(hex: 0x2F8F5B), in: .circle)
                                .overlay { Circle().stroke(Brand.ground, lineWidth: 4) }
                                .offset(x: 2, y: 2)
                        }
                    VStack(spacing: 12) {
                        Text("\(agent.name) is connected")
                            .font(.system(size: 30, weight: .bold))
                        Text(!settled ? "Bringing back what \(agent.name) built…" : returning ? "Everything \(agent.name) built for you is back on this \(UIDevice.current.model)." : "Say hello. Ask for a page, a document, something to keep an eye on.")
                            .foregroundStyle(Brand.quiet)
                    }
                    .multilineTextAlignment(.center)
                    if !settled {
                        ProgressView()
                    } else if returning {
                        VStack(alignment: .leading, spacing: 0) {
                            Text("Brought back from \(agent.name)")
                                .font(.footnote.weight(.semibold))
                                .foregroundStyle(Brand.quiet)
                                .padding(.top, 12)
                                .padding(.bottom, 4)
                            Restored(title: "Pages", value: "\(hub.pages.count)")
                            Divider().overlay(Brand.line)
                            Restored(title: "Conversations", value: conversations.topics.isEmpty ? "\(conversations.main.count) messages" : "\(conversations.topics.count) topics")
                            Divider().overlay(Brand.line)
                            Restored(title: "Your tab bar", value: "as you left it")
                        }
                        .padding(.horizontal, 18)
                        .background(Brand.surface, in: .rect(cornerRadius: 22, style: .continuous))
                    }
                }
                .padding(.vertical, 16)
                .frame(maxHeight: .infinity)
            }
            BrandButton(title: "Continue") { onboarding.done = true }
        }
        .padding(.horizontal, 24)
        .padding(.bottom, 12)
        .task {
            try? await Task.sleep(for: .seconds(12))
            waited = true
        }
    }

    private struct Restored: View {
        let title: String
        let value: String

        var body: some View {
            HStack {
                Text(title)
                Spacer()
                Text(value).foregroundStyle(Brand.quiet)
                Image(systemName: "checkmark").font(.footnote.bold()).foregroundStyle(Color(hex: 0x2F8F5B))
            }
            .font(.subheadline)
            .padding(.vertical, 12)
        }
    }
}
