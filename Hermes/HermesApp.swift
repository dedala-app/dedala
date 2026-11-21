// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import CoreSpotlight
import SwiftUI
import UserNotifications

@main
struct HermesApp: App {
    @State private var hub: Hub
    @State private var conversations: Conversations
    @State private var agent: Agent
    @State private var router: Router
    @State private var background: Background
    @State private var relay: Relay
    @State private var listener = Listener()
    @State private var store = Store()
    @State private var onboarding: Onboarding
    @UIApplicationDelegateAdaptor(AppDelegate.self) private var delegate
    @Environment(\.scenePhase) private var scenePhase
    private let activities: AgentActivities
    private let live: LiveFeed
    private let spotlight: Spotlight

    init() {
        let hub = Hub()
        let conversations = Conversations()
        let agent = Agent()
        let router = Router()
        let background = Background()
        let activities = AgentActivities()
        let relay = Relay()
        let onboarding = Onboarding(paired: relay.isPaired)

        hub.onConversation = { [weak conversations] op in conversations?.receive(op) }
        hub.cardSpec = { [weak conversations] id in conversations?.card(id) }
        hub.onProfile = { [weak agent] op in agent?.apply(op) }
        ActionRunner.edit = { [weak hub] patch, source in
            do {
                try hub?.edit(patch, from: source)
                return nil
            } catch {
                return "\(error)"
            }
        }
        ActionRunner.command = { [weak hub] name, args, source in hub?.command(name, args: args, from: source) }
        ActionRunner.hasStore = { [weak hub] id in hub?.stores[id] != nil }
        ActionRunner.failed = { [weak hub] problem, source, tapped in hub?.failed(problem, on: source, tapped: tapped) }
        hub.onBackground = { [weak background] op in background?.apply(op) }
        background.onEvent = { [weak hub] event in hub?.enqueue(event) }
        hub.onActivity = { op in
            if op["op"]?.string == "assets" { activities.storeAssets(op) } else { activities.apply(op) }
        }
        hub.onPageCreated = { [weak conversations] id, title in conversations?.proposePage(id, title: title) }
        hub.pushTokens = { activities.tokens }
        hub.onReset = { [weak conversations] in conversations?.reset() }
        #if DEBUG
        hub.onOnboarding = { [weak onboarding] shown in onboarding?.shown = shown }
        #endif
        hub.onShow = { [weak router] tab, record, message in
            router?.chatOpen = tab == "chat"
            if let tab, tab != "chat" { router?.tab = tab }
            if let record { router?.sheetRecord = RecordRef(record) }
            if let message { router?.show(message, in: Conversations.main) }
        }
        conversations.onEvent = { [weak hub] event in hub?.enqueue(event) }
        conversations.reading = { [weak router] in router?.chatOpen == true ? router?.path.last : nil }
        activities.report = { [weak hub] event in hub?.enqueue(event) }
        ActionRunner.openPage = { [weak router, weak hub] id in
            router?.show(page: id, pinned: hub?.pinned.contains(id) == true)
        }
        ActionRunner.present = { [weak router] shown in router?.sheetScreen = shown }
        ActionRunner.openRecord = { [weak router] store, record in router?.sheetRecord = RecordRef(store: store, record: record) }
        ActionRunner.openURL = { UIApplication.shared.open($0) }
        ActionRunner.openConversation = { [weak router, weak conversations] id in
            guard id == Conversations.main || conversations?.topic(id) != nil else { return false }
            router?.open(conversation: id)
            return true
        }
        ActionRunner.openCard = { [weak router, weak conversations] id in
            guard let held = conversations?.holding(id) else { return false }
            router?.show(id, in: held.conversation)
            return true
        }
        AppViews.install(conversations: conversations, agent: agent, hub: hub, relay: relay)
        relay.onOps = { [weak hub] ops in hub?.receive(ops) }
        relay.onPaired = { [weak agent] name in
            agent?.apply(.object(["name": .string(name)]))
            activities.endAll()
        }
        hub.choices = { [weak agent] in agent?.choices ?? [:] }
        hub.onArrangement = { [weak agent] op in agent?.takeChoices(op) }
        agent.onChoice = { [weak hub] in hub?.arrangementChanged() }
        relay.onCaughtUp = { [weak hub] in hub?.resend() }
        hub.onEmit = { [weak relay] event in relay?.queue(event) }
        relay.capture = { [weak hub] key in hub?.captureData(key) }
        activities.onStartToken = { [weak relay] token in relay?.updatePush(start: token) }
        hub.onButtons = { kinds in NotificationActions.register(kinds) }
        NotificationActions.register(hub.buttonKinds)
        Views.pickPhoto = { source in await PhotoPicking.pick(source) }
        Views.dictate = { heard in Dictation.start(heard) }

        _hub = State(initialValue: hub)
        _conversations = State(initialValue: conversations)
        _agent = State(initialValue: agent)
        _router = State(initialValue: router)
        _background = State(initialValue: background)
        _relay = State(initialValue: relay)
        _onboarding = State(initialValue: onboarding)
        self.activities = activities
        live = LiveFeed(conversations: conversations, background: background, hub: hub)
        spotlight = Spotlight(hub: hub, conversations: conversations, background: background, agent: agent)
    }

    var body: some Scene {
        WindowGroup {
            AppRoot()
                .environment(store)
                .environment(onboarding)
                .environment(hub)
                .environment(conversations)
                .environment(agent)
                .environment(router)
                .environment(background)
                .environment(relay)
                .environment(listener)
                .task {
                    Clock.shared.start()
                    live.start()
                    spotlight.start()
                    delegate.onToken = { [weak relay] token in relay?.updatePush(token: token) }
                    delegate.onAction = { [weak hub] action in
                        guard let hub else { return }
                        ActionRunner.run(action, in: Records.scope(.object([:]), hub: hub, store: "notification"))
                    }
                    delegate.onFlush = { [weak hub, weak relay] in
                        hub?.flushEdits()
                        await relay?.flush()
                    }
                    delegate.onWake = { [weak hub, weak relay] in
                        let came = await relay?.fetchMailbox() ?? false
                        hub?.snapshotAllWidgets()
                        return came
                    }
                    await Listener.prepare()
                }
                .onOpenURL { url in
                    guard url.scheme == "hermes", url.host() == "open",
                          let written = URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems?.first(where: { $0.name == "action" })?.value,
                          let action = try? JSONValue.parse(Data(written.utf8)) else { return }
                    ActionRunner.run(action, in: Records.scope(.object([:]), hub: hub, store: "widget"))
                }
                .onContinueUserActivity(CSSearchableItemActionType) { activity in
                    guard let key = activity.userInfo?[CSSearchableItemActivityIdentifier] as? String,
                          let colon = key.firstIndex(of: ":"), let kind = Search.Kind(rawValue: String(key[..<colon])) else { return }
                    let target = String(key[key.index(after: colon)...])
                    router.open(kind, target, pinned: hub.pinned.contains(target))
                }
                .onReceive(NotificationCenter.default.publisher(for: UIContentSizeCategory.didChangeNotification)) { _ in
                    hub.enqueue(Display.event)
                }
                .onReceive(NotificationCenter.default.publisher(for: UIAccessibility.boldTextStatusDidChangeNotification)) { _ in
                    hub.enqueue(Display.event)
                }
                .onChange(of: scenePhase, initial: true) {
                    guard scenePhase == .active else {
                        if scenePhase == .background {
                            hub.flushEdits()
                            relay.leave()
                        }
                        return
                    }
                    relay.connect()
                    UNUserNotificationCenter.current().removeAllDeliveredNotifications()
                    Task { try? await UNUserNotificationCenter.current().setBadgeCount(0) }
                    #if DEBUG
                    hub.startServer()
                    #endif
                    hub.enqueue(Display.event)
                    activities.review { report, captures in hub.record(report, captures: captures) }
                }
        }
    }
}
