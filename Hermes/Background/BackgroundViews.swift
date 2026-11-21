// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import SwiftUI
import UIKit

/// Activity from a page's toolbar: there once the agent works on his own,
/// turning while something runs.
struct ActivityButton: ToolbarContent {
    let shown: Bool
    let running: Int
    let action: () -> Void

    var body: some ToolbarContent {
        if shown {
            ToolbarItem(placement: .topBarTrailing) {
                ActivityIcon(running: running, action: action)
            }
            ToolbarSpacer(.fixed, placement: .topBarTrailing)
        }
    }
}

/// The way into Activity, a button of the bar so it stays there, on the side
/// of iPhone Duo too: it breathes while something runs (see ActivityBreathing).
struct ActivityIcon: View {
    let running: Int
    let action: () -> Void

    var body: some View {
        Button("Activity", systemImage: "gearshape.2", action: action)
            .accessibilityValue(running > 0 ? "\(running) running" : "")
    }
}

/// Makes the Activity button breathe while something runs. iOS 27 draws
/// SwiftUI's bar buttons as still images, so the effect goes on the UIKit
/// button SwiftUI makes: found by its title in the bar of the screen this sits
/// in, and started again whenever SwiftUI makes a new one, gives it a new
/// image, or the screen comes back. Each screen has its own button, and a
/// breath starting over passes for the next one. UIKit draws a breathing
/// symbol in the button's tint, so the tint is the label's, as SwiftUI drew it.
struct ActivityBreathing: UIViewControllerRepresentable {
    @Environment(Background.self) private var background

    func makeUIViewController(context: Context) -> Controller {
        Controller()
    }

    func updateUIViewController(_ controller: Controller, context: Context) {
        controller.running = !background.running.isEmpty
    }

    final class Controller: UIViewController {
        var running = false {
            didSet {
                guard running != oldValue else { return }
                breathing = nil
                breathe()
            }
        }
        private weak var breathing: UIBarButtonItem?
        private weak var breathingImage: UIImage?
        private var watch: Timer?

        override func viewDidAppear(_ animated: Bool) {
            super.viewDidAppear(animated)
            breathing = nil
            watch = .scheduledTimer(withTimeInterval: 1, repeats: true) { [weak self] _ in
                MainActor.assumeIsolated { self?.breathe() }
            }
            breathe()
        }

        override func viewDidDisappear(_ animated: Bool) {
            super.viewDidDisappear(animated)
            watch?.invalidate()
            watch = nil
        }

        private func breathe() {
            guard let button = button(), button !== breathing || button.image !== breathingImage else { return }
            if running {
                button.tintColor = .label
                button.addSymbolEffect(.breathe, options: .repeat(.continuous))
            } else {
                button.removeAllSymbolEffects()
            }
            breathing = button
            breathingImage = button.image
        }

        private func button() -> UIBarButtonItem? {
            var controller: UIViewController? = self
            while let current = controller {
                let item = current.navigationItem
                let groups = item.leadingItemGroups + item.trailingItemGroups
                let buttons = (item.rightBarButtonItems ?? []) + (item.leftBarButtonItems ?? [])
                    + groups.flatMap(\.barButtonItems) + (current.toolbarItems ?? [])
                if let found = buttons.first(where: { $0.title == "Activity" || $0.accessibilityLabel == "Activity" }) {
                    return found
                }
                controller = current.parent
            }
            return nil
        }
    }
}

/// Everything the agent does on his own: what runs now, what is scheduled,
/// what ran, and the one-time jobs that are done.
struct ActivityView: View {
    @Environment(Background.self) private var background
    @Environment(Router.self) private var router
    @Environment(\.dismiss) private var dismiss
    @State private var path: [Router.ActivityRoute] = []

    var body: some View {
        NavigationStack(path: $path) {
            List {
                if !background.running.isEmpty {
                    Section("Running now") {
                        ForEach(background.running) { run in
                            NavigationLink(value: Router.ActivityRoute.run(run.id)) { RunRow(run: run) }
                        }
                    }
                }
                let scheduled = background.jobs.filter { !$0.done }
                Section("Scheduled") {
                    if scheduled.isEmpty {
                        Text("Nothing scheduled").foregroundStyle(.secondary)
                    }
                    ForEach(scheduled) { job in
                        NavigationLink(value: Router.ActivityRoute.job(job.id)) { JobRow(job: job) }
                    }
                }
                let recent = background.runs.filter { !$0.running }
                if !recent.isEmpty {
                    Section("Recent") {
                        ForEach(recent) { run in
                            NavigationLink(value: Router.ActivityRoute.run(run.id)) { RunRow(run: run) }
                        }
                    }
                }
                let done = background.jobs.filter(\.done)
                if !done.isEmpty {
                    Section("Done") {
                        ForEach(done) { job in
                            NavigationLink(value: Router.ActivityRoute.job(job.id)) { JobRow(job: job) }
                        }
                    }
                }
            }
            .navigationTitle("Activity")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Done", systemImage: "checkmark") { dismiss() }
                }
            }
            .navigationDestination(for: Router.ActivityRoute.self) { route in
                switch route {
                case .run(let id): RunDetail(runID: id)
                case .job(let id): JobDetail(jobID: id)
                case .list: EmptyView()
                }
            }
        }
        .onAppear {
            if let route = router.activity, route != .list { path = [route] }
        }
    }
}

private struct JobRow: View {
    let job: Background.Job

    var body: some View {
        VStack(alignment: .leading, spacing: 3) {
            HStack(spacing: 6) {
                Text(job.name).lineLimit(1)
                if job.failed {
                    Image(systemName: "exclamationmark.circle.fill").foregroundStyle(.orange).font(.caption)
                }
            }
            Text(line)
                .font(.caption)
                .foregroundStyle(.secondary)
                .lineLimit(1)
        }
    }

    private var line: String {
        if job.done { return job.last.map { "Ran \($0.formatted(.relative(presentation: .named)))" } ?? job.schedule }
        if job.paused { return "Paused · \(job.schedule)" }
        if job.watching {
            return "Watching \(job.schedule)" + (job.checked.map { " · checked \(Upkeep.ago($0, now: .now))" } ?? "")
        }
        guard let next = job.next, next > .now else { return job.schedule }
        return "Next \(next.formatted(.relative(presentation: .named))) · \(job.schedule)"
    }
}

private struct RunRow: View {
    let run: Background.Run

    var body: some View {
        HStack(spacing: 10) {
            icon.frame(width: 20)
            VStack(alignment: .leading, spacing: 3) {
                Text(run.name).lineLimit(1)
                TimelineView(.periodic(from: .now, by: 1)) { context in
                    Text(line(at: context.date))
                        .font(.caption.monospacedDigit())
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                }
            }
        }
    }

    @ViewBuilder private var icon: some View {
        if run.running {
            ProgressView().controlSize(.small)
        } else if run.status == "failed" {
            Image(systemName: "exclamationmark.circle.fill").foregroundStyle(.orange)
        } else {
            Image(systemName: "checkmark.circle").foregroundStyle(.secondary)
        }
    }

    private func line(at now: Date) -> String {
        if run.running {
            let doing = (run.background ? "In the background · " : "") + (run.doing ?? run.steps.last?.text ?? "Starting")
            return "\(doing) · \(Background.duration(from: run.started, to: now))"
        }
        let when = (run.finished ?? run.started).map { $0.formatted(.relative(presentation: .named)) } ?? ""
        let line = run.status == "failed" ? "Failed \(when)" : "\(when) · took \(Background.duration(from: run.started, to: run.finished ?? now))"
        return run.background ? "In the background · \(line)" : line
    }
}

/// One run: how it went, and every step it took.
struct RunDetail: View {
    @Environment(Background.self) private var background
    let runID: String

    var body: some View {
        if let run = background.runs.first(where: { $0.id == runID }) {
            List {
                Section {
                    LabeledContent("Started", value: run.started?.formatted(date: .abbreviated, time: .shortened) ?? "–")
                    TimelineView(.periodic(from: .now, by: 1)) { context in
                        LabeledContent(run.running ? "Running for" : "Took", value: Background.duration(from: run.started, to: run.finished ?? context.date))
                            .monospacedDigit()
                    }
                    if run.tokens > 0 {
                        LabeledContent("Written", value: Background.tokens(run.tokens))
                    }
                    if let error = run.error {
                        Label(error, systemImage: "exclamationmark.circle")
                            .foregroundStyle(.orange)
                    }
                }
                Section(run.steps.isEmpty ? "" : "\(run.steps.count) steps") {
                    if run.steps.isEmpty && !run.running {
                        Text(run.background ? "A subagent did this in the background, from a conversation; its steps are not followed."
                                            : "Its steps were not seen: it ran before the app's plugin watched them.")
                            .font(.footnote)
                            .foregroundStyle(.secondary)
                    }
                    ForEach(Array(run.steps.enumerated()), id: \.offset) { _, step in
                        Label {
                            Text(step.text)
                        } icon: {
                            Image(systemName: step.failed == true ? "exclamationmark.circle" : step.symbol)
                                .foregroundStyle(step.failed == true ? .orange : .secondary)
                        }
                        .font(.subheadline)
                    }
                    if run.running {
                        Label {
                            Text(run.doing ?? "Thinking").foregroundStyle(.secondary)
                        } icon: {
                            ProgressView().controlSize(.small)
                        }
                        .font(.subheadline)
                    }
                }
            }
            .navigationTitle(run.name)
            .navigationBarTitleDisplayMode(.inline)
        } else {
            ContentUnavailableView("This run is no longer listed", systemImage: "clock")
        }
    }
}

/// One job: when it runs, what it keeps up to date, its runs; run it now or
/// pause it.
struct JobDetail: View {
    @Environment(Background.self) private var background
    @Environment(Hub.self) private var hub
    @Environment(Router.self) private var router
    let jobID: String

    var body: some View {
        if let job = background.job(jobID) {
            List {
                Section {
                    LabeledContent(job.watching ? "Watches" : "Schedule", value: job.schedule)
                    if let next = job.next, !job.paused {
                        LabeledContent("Next", value: next.formatted(date: .abbreviated, time: .shortened))
                    }
                    if let checked = job.checked {
                        LabeledContent("Checked", value: checked.formatted(.relative(presentation: .named)))
                    }
                    if let last = job.last {
                        LabeledContent(job.watching ? "Last change" : "Last", value: last.formatted(.relative(presentation: .named)))
                    }
                    LabeledContent("Reports", value: job.silent ? "Works silently" : "Writes to you")
                    if let page = job.page, let spec = hub.page(page) {
                        Button {
                            router.activity = nil
                            router.openPage(page, pinned: hub.pinned.contains(page))
                        } label: {
                            LabeledContent("Keeps up to date") {
                                Label(spec.title, systemImage: spec.symbol)
                            }
                        }
                    }
                    if let error = job.error {
                        Label(error, systemImage: "exclamationmark.circle")
                            .foregroundStyle(.orange)
                    }
                }
                Section {
                    Button("Run now", systemImage: "play") { background.act("run", on: job.id) }
                        .disabled(background.running.contains { $0.job == job.id })
                    if job.paused && !job.done {
                        Button("Resume", systemImage: "playpause") { background.act("resume", on: job.id) }
                    } else if !job.done {
                        Button("Pause", systemImage: "pause") { background.act("pause", on: job.id) }
                    }
                }
                let runs = background.runs.filter { $0.job == job.id }
                if !runs.isEmpty {
                    Section("Runs") {
                        ForEach(runs) { run in
                            NavigationLink(value: Router.ActivityRoute.run(run.id)) { RunRow(run: run) }
                        }
                    }
                }
            }
            .navigationTitle(job.name)
            .navigationBarTitleDisplayMode(.inline)
        } else {
            ContentUnavailableView("This job is gone", systemImage: "clock")
        }
    }
}
