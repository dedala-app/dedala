// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import ActivityKit
import SwiftUI
import UserNotifications

/// The app's own controls: who it talks to, permissions, and what went
/// through, for spotting what goes wrong.
struct SettingsView: View {
    @Environment(Hub.self) private var hub
    @Environment(Agent.self) private var agent
    @Environment(Router.self) private var router
    @Environment(Relay.self) private var relay
    @State private var notifications = UNAuthorizationStatus.notDetermined
    @State private var showsPairing = false
    @State private var confirmsUnpair = false

    var body: some View {
        NavigationStack {
            List {
                Section {
                    NavigationLink {
                        AvatarEditor()
                    } label: {
                        HStack(spacing: 14) {
                            AgentFace()
                                .frame(width: 52, height: 52)
                                .clipShape(.circle)
                            VStack(alignment: .leading, spacing: 2) {
                                Text(agent.name).font(.headline)
                                Label(connection.text, systemImage: "circle.fill")
                                    .labelStyle(StatusLabelStyle(color: connection.color))
                                    .font(.subheadline)
                                    .foregroundStyle(.secondary)
                            }
                        }
                    }
                    if relay.isPaired {
                        Button("Unpair", systemImage: "link.badge.minus", role: .destructive) { confirmsUnpair = true }
                    } else {
                        Button("Pair with your agent", systemImage: "qrcode.viewfinder") { showsPairing = true }
                    }
                } footer: {
                    if let problem = relay.lastError, relay.state != .connected {
                        Text(problem)
                    }
                }


                Section("Permissions") {
                    LabeledContent("Notifications") {
                        if notifications == .notDetermined {
                            Button("Allow") {
                                Task {
                                    _ = try? await UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound, .badge])
                                    await refresh()
                                }
                            }
                        } else {
                            Text(notifications == .authorized ? "Allowed" : "Off")
                        }
                    }
                    LabeledContent("Live Activities", value: ActivityAuthorizationInfo().areActivitiesEnabled ? "Allowed" : "Off")
                }

                Section("Monitoring") {
                    NavigationLink {
                        MonitorView()
                    } label: {
                        LabeledContent("Activity log") {
                            let problems = hub.log.filter { $0.problem != nil }.count
                            if problems > 0 {
                                Text("\(problems) to look at").foregroundStyle(.orange)
                            }
                        }
                    }
                }

                Section("About") {
                    LabeledContent("Version", value: Self.version)
                    Link("Source code", destination: Self.source)
                    NavigationLink("Acknowledgements") {
                        AcknowledgementsView()
                    }
                }
            }
            .navigationTitle("Settings")
            .task { await refresh() }
            .sheet(isPresented: $showsPairing) {
                PairingView()
            }
            .confirmationDialog("Unpair from \(agent.name)?", isPresented: $confirmsUnpair, titleVisibility: .visible) {
                Button("Unpair", role: .destructive) { relay.unpair() }
            } message: {
                Text("Nothing more will arrive from it until you pair again. What is already in the app stays.")
            }
        }
    }

    /// Where the app's source is, as the AGPL asks it be found.
    static let source = URL(string: "https://github.com/dedala-app/dedala")!

    static var version: String {
        let info = Bundle.main.infoDictionary ?? [:]
        let short = info["CFBundleShortVersionString"] as? String ?? "?"
        let build = info["CFBundleVersion"] as? String ?? "?"
        return "\(short) (\(build))"
    }

    private var connection: (text: String, color: Color) {
        switch relay.state {
        case .unpaired: ("Not paired", .gray)
        case .offline: ("Offline", .orange)
        case .connecting: ("Connecting…", .yellow)
        case .connected: ("Connected", .green)
        }
    }

    private func refresh() async {
        notifications = await UNUserNotificationCenter.current().notificationSettings().authorizationStatus
    }
}

/// Every op that came in and every event that went out, newest first, with
/// what went wrong.
struct MonitorView: View {
    @Environment(Hub.self) private var hub
    @State private var problemsOnly = false

    var body: some View {
        List(hub.log.filter { !problemsOnly || $0.problem != nil }) { entry in
            VStack(alignment: .leading, spacing: 4) {
                HStack(spacing: 8) {
                    Image(systemName: entry.inbound ? "arrow.down.circle.fill" : "arrow.up.circle.fill")
                        .foregroundStyle(entry.inbound ? .blue : .green)
                    Text(entry.kind).font(.subheadline.weight(.semibold).monospaced())
                    Text(entry.detail).font(.subheadline).foregroundStyle(.secondary).lineLimit(1)
                    Spacer(minLength: 0)
                    Text(entry.at, format: .dateTime.hour().minute().second())
                        .font(.caption.monospacedDigit())
                        .foregroundStyle(.secondary)
                }
                if let problem = entry.problem {
                    Text(problem)
                        .font(.footnote)
                        .foregroundStyle(.orange)
                }
            }
        }
        .overlay {
            if hub.log.isEmpty {
                ContentUnavailableView("Nothing yet", systemImage: "waveform.path.ecg", description: Text("Operations from the agent and events back to it show up here."))
            }
        }
        .navigationTitle("Activity log")
        .toolbar {
            Toggle("Problems only", systemImage: "exclamationmark.triangle", isOn: $problemsOnly)
        }
    }
}

private struct StatusLabelStyle: LabelStyle {
    let color: Color

    func makeBody(configuration: Configuration) -> some View {
        HStack(spacing: 6) {
            configuration.icon
                .font(.system(size: 7))
                .foregroundStyle(color)
            configuration.title
        }
    }
}
