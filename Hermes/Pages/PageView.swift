// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import SwiftUI

/// A page the agent made: a Hermes UI view bound to the server's stores, kept
/// up to date by whatever updates those stores. In the bar, swiped sideways,
/// its content slides to the next page under its buttons, which stay.
///
/// The page draws its own title, so the navigation bar shows none: a clear
/// title where the bar is across the top, and no title at all where iPhone
/// Duo moves the buttons to a side bar, since a title would keep an empty
/// bar over the page, one iOS folds away as you scroll and brings back at
/// each tab change, moving the page with it.
struct PageView: View {
    @Environment(Hub.self) private var hub
    @Environment(Router.self) private var router
    @Environment(Agent.self) private var agent
    @Environment(Background.self) private var background
    let pageID: String
    var swipes = false
    @State private var naming: String?
    @State private var navigator = Navigator()

    var body: some View {
        SideBarReader { sideBar in
            stack(sideBar: sideBar)
        }
    }

    private func stack(sideBar: Bool) -> some View {
        NavigationStack(path: $navigator.path) {
            if let page = hub.page(pageID) {
                PageContent(pageID: pageID, navigator: navigator)
                    .navigationDestination(for: Shown.self) { shown in
                        ScreenView(shown: shown, navigator: navigator, stores: hub.stores)
                    }
                    .onChange(of: page.revision) { navigator.path = [] }
                    .modifier(PageSwipe(id: pageID, active: swipes))
                    .navigationTitle(sideBar ? "" : page.title)
                    .toolbarTitleDisplayMode(.inline)
                    .toolbar {
                        if !sideBar {
                            ToolbarItem(placement: .principal) { Color.clear.frame(width: 1, height: 1) }
                        }
                        ActivityButton(shown: !background.jobs.isEmpty || !background.runs.isEmpty,
                                       running: background.running.count) { router.activity = .list }
                    }
                    .overflowMenu { actions(page) }
                    .background(ActivityBreathing())
                    .namingTab($naming)
            }
        }
    }

    /// What can be done with the page: in the system's overflow menu, which
    /// iPhone Duo places with the bar's other items.
    @ViewBuilder private func actions(_ page: Hub.PageSpec) -> some View {
        let place = hub.bar.firstIndex(of: pageID)
        if page.upkeep != nil {
            Button("Refresh now", systemImage: "arrow.clockwise") { hub.refresh(pageID) }
        }
        Button("Ask \(agent.name) to change it", systemImage: "bubble.left") {
            router.sheetPage = nil
            router.open(conversation: Conversations.main)
        }
        if hub.pinned.contains(pageID) {
            if let place, place > 0 {
                Button("Put first in the bar", systemImage: "arrow.up.to.line") {
                    withAnimation(.snappy) { hub.moveInBar(from: [place], to: 0) }
                }
            }
            Button("Rename in the bar", systemImage: "character.cursor.ibeam") { naming = pageID }
            Button("Remove from the bar", systemImage: "rectangle.badge.minus") {
                hub.pin(pageID, false)
            }
        } else {
            Button("Add to the bar", systemImage: "rectangle.badge.plus") {
                hub.pin(pageID, true)
                router.show(page: pageID)
            }
        }
        Button("Delete page", systemImage: "trash", role: .destructive) {
            router.sheetPage = nil
            hub.removePage(pageID)
        }
    }
}

/// What a page shows under its buttons: its title and how fresh it is, then
/// its view; what slides when pages are swiped. It opens where you left
/// it, so a page coming in beside another lands where its own tab is.
struct PageContent: View {
    @Environment(Hub.self) private var hub
    @Environment(Router.self) private var router
    @Environment(Background.self) private var background
    @Environment(Relay.self) private var relay
    @Environment(Agent.self) private var agent
    @Environment(\.scenePhase) private var scenePhase
    let pageID: String
    let navigator: Navigator
    @State private var position: ScrollPosition
    /// The scroll view's width, which the page is held at while the app is
    /// not active. On the way to the background iOS lays the scene out in its
    /// other orientation for its snapshots; followed, a page would go to two
    /// columns, get shorter than the viewport and have its offset clamped to
    /// the top, where it stays when you come back.
    @State private var width: CGFloat?
    @State private var fold: CGFloat = 0

    /// Where each page was left, by id.
    static var left: [String: CGFloat] = [:]

    /// The width of the fold across the page when iPhone Duo is partly open.
    static func fold(_ proxy: GeometryProxy) -> CGFloat {
        guard #available(iOS 27.1, *) else { return 0 }
        return proxy.reservedRegions(kind: .division).filter(\.isActive).map(\.frame.width).max() ?? 0
    }

    init(pageID: String, navigator: Navigator) {
        self.pageID = pageID
        self.navigator = navigator
        _position = State(initialValue: ScrollPosition(y: Self.left[pageID] ?? 0))
    }

    var body: some View {
        if let page = hub.page(pageID) {
            ScrollView {
                VStack(alignment: .leading, spacing: 0) {
                    VStack(alignment: .leading, spacing: 2) {
                        Text(page.title)
                            .font(.largeTitle.bold())
                            .accessibilityAddTraits(.isHeader)
                        Freshness(upkeep: page.upkeep, updated: hub.updated(page)) {
                            if let run = background.running.first(where: { $0.job == page.upkeep?["job"]?.string }) {
                                router.activity = .run(run.id)
                            } else {
                                hub.refresh(pageID)
                            }
                        }
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.horizontal, 20)
                    .padding(.bottom, 8)
                    if let upkeep = page.upkeep, relay.sync == .upToDate {
                        TimelineView(.everyMinute) { timeline in
                            if let warning = Upkeep(upkeep).warning(at: timeline.date) {
                                UpkeepWarning(text: warning) { hub.refresh(pageID) }
                                    .padding(.horizontal, 16)
                                    .padding(.bottom, 8)
                            }
                        }
                    }
                    StateScopeView(
                        initial: page.state,
                        node: PageColumns.view(page.view, width: width ?? SharedCards.pageWidth, fold: fold),
                        scope: Scope(values: [:], boxes: [], context: hub.pageContext(pageID),
                                     data: [:], stores: hub.stores, saved: hub.savedState(pageID), navigator: navigator),
                        script: page.script,
                        data: .null,
                        key: "page",
                        toolbar: page.toolbar
                    )
                    .id(page.revision)
                    .padding(.horizontal, 16)
                    Color.clear
                        .frame(height: 24)
                }
                .frame(width: scenePhase == .active ? nil : width)
                .frame(minWidth: 0, maxWidth: .infinity, alignment: .leading)
            }
            .scrollPosition($position)
            .onScrollGeometryChange(for: CGFloat.self) { $0.contentOffset.y + $0.contentInsets.top } action: { old, offset in
                guard scenePhase == .active else { return }
                Self.left[pageID] = max(0, offset)
                let folded = offset > 40 && (offset > old + 4 || router.pillFolded && offset >= old - 4)
                if folded != router.pillFolded {
                    withAnimation(.snappy) { router.pillFolded = folded }
                }
            }
            .onGeometryChange(for: CGFloat.self) { $0.size.width } action: { if scenePhase == .active { width = $0 } }
            .task(id: width) {
                try? await Task.sleep(for: .seconds(1))
                guard !Task.isCancelled, let width, PageColumns.narrow(width) else { return }
                let before = SharedCards.pageWidth
                SharedCards.pageWidth = width
                if abs(before - width) > 0.5 { hub.enqueue(Display.event) }
            }
            .onGeometryChange(for: CGFloat.self) { Self.fold($0) } action: { fold = $0 }
            .modifier(PullToRun(job: page.upkeep.flatMap { upkeep in
                upkeep["job"]?.string.map { background.job($0)?.name ?? $0 }
            }) {
                agent.react(.surprised, for: 1.2)
                hub.refresh(pageID)
            })
            .background(Color(.systemGroupedBackground))
        }
    }
}

/// How a page is kept up to date, as the plugin reads it from the cron job
/// that maintains it.
struct Upkeep {
    let state: JSONValue

    init(_ state: JSONValue) {
        self.state = state
    }

    private var last: Date? { state["last"]?.date }
    private var next: Date? { state["next"]?.date }

    /// When the page was updated and when it will be next.
    func line(at now: Date) -> String {
        if state["refreshing"]?.truthy == true { return "Updating…" }
        if state["missing"]?.truthy == true { return "No longer maintained" }
        let updated = last.map { "Updated \(Self.ago($0, now: now))" } ?? "Not updated yet"
        if state["paused"]?.truthy == true { return "\(updated) · updates paused" }
        if state["error"] != nil || state["status"]?.string == "error" { return "Last update failed · \(updated.lowercased())" }
        if state["watching"]?.truthy == true, let checked = state["checked"]?.date {
            let unchanged = last.map { "No changes since \(Self.since($0, now: now))" } ?? "No changes yet"
            return "\(unchanged) · checked \(Self.ago(checked, now: now))"
        }
        guard let next, next > now else { return updated }
        let when = Calendar.current.isDateInToday(next) ? next.formatted(date: .omitted, time: .shortened) : next.formatted(.dateTime.weekday(.abbreviated).hour().minute())
        return "\(updated) · next \(when)"
    }

    /// What deserves more than a line: an update that failed or is overdue.
    func warning(at now: Date) -> String? {
        guard state["refreshing"]?.truthy != true else { return nil }
        if state["missing"]?.truthy == true { return "Nothing keeps this page up to date anymore." }
        if let error = state["error"]?.string { return "The last update failed: \(error)" }
        if let next, next < now.addingTimeInterval(-15 * 60), state["paused"]?.truthy != true {
            return "Update overdue: " + (last.map { "last updated \(Self.ago($0, now: now))." } ?? "never updated yet.")
        }
        return nil
    }

    /// A moment as a person would name it: a time today, yesterday, a weekday
    /// this week, a date before that.
    static func since(_ date: Date, now: Date) -> String {
        let calendar = Calendar.current
        if calendar.isDate(date, inSameDayAs: now) { return date.formatted(date: .omitted, time: .shortened) }
        if let yesterday = calendar.date(byAdding: .day, value: -1, to: now), calendar.isDate(date, inSameDayAs: yesterday) { return "yesterday" }
        if now.timeIntervalSince(date) < 6 * 86400 { return date.formatted(.dateTime.weekday(.wide)) }
        return date.formatted(.dateTime.day().month(.abbreviated))
    }

    static func ago(_ date: Date, now: Date) -> String {
        guard now.timeIntervalSince(date) >= 60 else { return "just now" }
        return RelativeDateTimeFormatter().localizedString(for: date, relativeTo: now)
    }
}

/// The line under a page's title: how fresh it is, and a way to refresh it
/// when something maintains it.
struct Freshness: View {
    let upkeep: JSONValue?
    let updated: Date?
    let refresh: () -> Void

    var body: some View {
        TimelineView(.periodic(from: .now, by: 30)) { timeline in
            if let upkeep {
                Button(action: refresh) {
                    Label(Upkeep(upkeep).line(at: timeline.date), systemImage: "arrow.clockwise")
                }
                .buttonStyle(.plain)
            } else if let updated {
                Text("Updated \(Upkeep.ago(updated, now: timeline.date))")
            }
        }
        .font(.footnote)
        .foregroundStyle(.secondary)
    }
}

struct UpkeepWarning: View {
    let text: String
    let refresh: () -> Void

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 10) {
            Image(systemName: "clock.badge.exclamationmark")
                .foregroundStyle(.orange)
            Text(text)
                .font(.footnote)
                .frame(maxWidth: .infinity, alignment: .leading)
            Button("Refresh", action: refresh)
                .font(.footnote.weight(.semibold))
        }
        .padding(12)
        .background(Color.orange.opacity(0.12), in: .rect(cornerRadius: 14, style: .continuous))
    }
}

/// Pull to update a page a job keeps up to date. The job costs a run, so it
/// starts when you let go past the line, not as you cross it: pull back above
/// it before letting go and nothing runs.
private struct PullToRun: ViewModifier {
    let job: String?
    let run: () -> Void
    @State private var pull: CGFloat = 0
    @State private var interacting = false
    @State private var armed = false

    static let line: CGFloat = 140

    func body(content: Content) -> some View {
        if let job {
            content
                .onScrollGeometryChange(for: CGFloat.self) { geometry in
                    max(0, -(geometry.contentOffset.y + geometry.contentInsets.top))
                } action: { _, pulled in
                    pull = pulled
                    if interacting { armed = pulled >= Self.line }
                }
                .onScrollPhaseChange { old, new in
                    interacting = new == .interacting
                    if old == .interacting && new != .interacting {
                        if armed { run() }
                        armed = false
                    }
                }
                .sensoryFeedback(.impact(weight: .light), trigger: armed)
                .overlay(alignment: .top) {
                    if pull > 8 {
                        Label(armed ? "Release to run \(job)" : "Pull to update", systemImage: "arrow.clockwise")
                            .font(.footnote.weight(armed ? .semibold : .regular))
                            .foregroundStyle(armed ? AnyShapeStyle(.tint) : AnyShapeStyle(.secondary))
                            .symbolEffect(.bounce, value: armed)
                            .labelStyle(PullLabel(turn: min(pull / Self.line, 1)))
                            .lineLimit(1)
                            .padding(.horizontal, 24)
                            .opacity(min(1, pull / 50))
                            .padding(.top, 10)
                            .allowsHitTesting(false)
                    }
                }
        } else {
            content
        }
    }
}

private struct PullLabel: LabelStyle {
    let turn: CGFloat

    func makeBody(configuration: Configuration) -> some View {
        HStack(spacing: 6) {
            configuration.icon.rotationEffect(.degrees(turn * 300))
            configuration.title
        }
    }
}
