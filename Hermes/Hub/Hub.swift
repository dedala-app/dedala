// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import Observation
import SwiftUI
import UIKit

/// Where the agent's operations land: pages and their stores, components, and
/// the events going back. Ops for conversations, activities and the profile
/// are handed on. Its parts are in the files beside this one: what you
/// edit (Hub+Edits), the reports of what was drawn (Hub+Reports), and the
/// drive server of debug builds (Hub+Drive).
@Observable
final class Hub {
    struct PageSpec: Identifiable {
        let id: String
        var title: String
        var symbol: String
        var view: JSONValue
        var state: [String: JSONValue]
        var revision: Int
        /// How the page is kept up to date, from the plugin: the job's schedule,
        /// last and next runs, its status; nil for a page nothing maintains.
        var upkeep: JSONValue?
        var script: ScriptSpec?
        var toolbar: [JSONValue] = []
    }

    private(set) var pages: [PageSpec] = []
    private(set) var pinned: [String] = []
    /// The names you gave the pages' tabs, over their titles.
    private(set) var tabNames: [String: String] = [:]
    /// The pages a newly paired phone was told you had, until each comes in:
    /// they take the place you gave them instead of being offered as new.
    @ObservationIgnored private var arranged: Set<String> = []
    @ObservationIgnored private var arrangementSent: JSONValue?
    @ObservationIgnored private var arranging: Task<Void, Never>?
    /// The face you made for the agent, which goes with how you arranged the app.
    @ObservationIgnored var choices: () -> [String: JSONValue] = { [:] }
    @ObservationIgnored var onArrangement: ((JSONValue) -> Void)?
    private(set) var log: [LogEntry] = []
    /// What pages and cards read under each store's name: the store as the
    /// agent's machine holds it with your edits it has not confirmed made to
    /// it, or a linked file the same way.
    private(set) var stores: [String: JSONValue] = [:]
    private(set) var storeUpdated: [String: Date] = [:]
    /// Each store as the plugin last sent it: its file on the agent's machine.
    @ObservationIgnored var storeTruth: [String: JSONValue] = [:]
    /// The shape of each store that is not plain JSON: `text`, `folder`.
    @ObservationIgnored var storeKinds: [String: String] = [:]
    /// What makes a store's records findable (protocol.md, Data): `{name,
    /// symbol, screen, title, subtitle, words}`, by store.
    private(set) var declarations: [String: JSONValue] = [:]
    @ObservationIgnored let attachments = Attachments()
    /// The last run of each command, by name: what `$commands` shows.
    @ObservationIgnored var commandRuns: [String: JSONValue] = [:]
    /// What you changed on each page, by state scope.
    @ObservationIgnored private var pageStates: [String: [String: [String: JSONValue]]] = [:]
    private(set) var pageFocus: String?
    private(set) var pageFocusRequests = 0
    @ObservationIgnored var onConversation: ((JSONValue) -> Void)?
    @ObservationIgnored var onProfile: ((JSONValue) -> Void)?
    @ObservationIgnored var onBackground: ((JSONValue) -> Void)?
    @ObservationIgnored var onPageCreated: ((String, String) -> Void)?
    /// A tab to show, from the drive server, for looking at the app from the Mac.
    @ObservationIgnored var onShow: ((_ tab: String?, _ record: String?, _ message: String?) -> Void)?
    @ObservationIgnored private var loading = false
    @ObservationIgnored let pending = EditBatch()
    @ObservationIgnored var onActivity: ((JSONValue) -> Void)?
    @ObservationIgnored var pushTokens: (() -> JSONValue)?
    @ObservationIgnored var onReset: (() -> Void)?
    /// A screen of the onboarding or the paywall to show from the Mac, nil to go back.
    @ObservationIgnored var onOnboarding: ((String?) -> Void)?
    /// The card of a message as it stands (view, data, state), for its report.
    @ObservationIgnored var cardSpec: ((String) -> JSONValue?)?
    /// Where events go: the relay, once paired.
    @ObservationIgnored var onEmit: ((JSONValue) -> Void)?
    @ObservationIgnored private(set) var contexts: [String: CardContext] = [:]
    private(set) var components: [String: JSONValue] = [:]
    /// The buttons a notification of each kind shows (protocol.md, `buttons`).
    private(set) var buttonKinds: [String: JSONValue] = [:]
    /// Registers the notification categories when the kinds change.
    @ObservationIgnored var onButtons: (([String: JSONValue]) -> Void)?
    /// The Home Screen widgets the agent declared, by id (protocol.md, Widgets).
    private(set) var widgets: [String: JSONValue] = [:]
    @ObservationIgnored let snapshots = WidgetSnapshots()
    /// Sends a file the phone holds as sealed blobs; its blobs, or nil when it could not go.
    @ObservationIgnored var uploader: (Data) async -> [String]? = { data in
        guard let pairing = PairingStore.load(), let keys = try? pairing.keys() else { return nil }
        return await RelayPost.upload(data, pairing: pairing, keys: keys)
    }
    @ObservationIgnored var cardFrames: [String: CGRect] = [:]
    /// The part of the screen where conversation content can be seen: below
    /// its header, above the message field and the tab bar.
    @ObservationIgnored var viewport: CGRect?
    @ObservationIgnored let captures = Captures()
    /// What the agent must get of your edits, until the plugin acknowledges it.
    @ObservationIgnored let outgoing = Outgoing()
    @ObservationIgnored let fileSync = FileSync()
    @ObservationIgnored private var previews: [JSONValue] = []
    @ObservationIgnored private var reporting: Task<Void, Never>?
    @ObservationIgnored private var revision = 0
    #if DEBUG
    @ObservationIgnored var server: DriveServer?
    /// The events since the drive server was last read.
    @ObservationIgnored var driven: [JSONValue] = []
    #endif

    init() {
        load()
        storeTruth.keys.forEach(showStore)
        showCommands()
        pending.onSettled = { [weak self] in self?.flushEdits() }
        attachments.fetch = { [weak self] store, record in self?.requestFile(store, record) }
    }

    // MARK: - Operations

    struct OperationError: Error, CustomStringConvertible {
        let description: String
    }

    func apply(_ op: JSONValue) throws -> String? {
        guard let kind = op["op"]?.string else { throw OperationError(description: "An operation needs \"op\"") }
        switch kind {
        case "store":
            try store(op)
            return nil
        case "attachment":
            try attachments.apply(op)
            if let store = op["store"]?.string { showStore(store) }
            return nil
        case "check", "notify", "wake":
            return nil
        case "measure":
            Task { enqueue(await SymbolMetrics.measured(op)) }
            return nil
        case "fonts":
            let os = UIDevice.current.systemVersion
            Task { enqueue(await Task.detached(priority: .utility) { FontTables.event(os: os) }.value) }
            return nil
        case "buttons":
            guard let kinds = op["kinds"]?.object else { throw OperationError(description: "buttons needs kinds: {kind: [{id, title, destructive}] | null}") }
            for (kind, buttons) in kinds {
                if buttons == .null {
                    buttonKinds[kind] = nil
                    continue
                }
                guard let list = buttons.array, !list.isEmpty, list.count <= 4, list.allSatisfy({ $0["id"]?.string?.isEmpty == false && $0["title"]?.string?.isEmpty == false }) else {
                    throw OperationError(description: "buttons of \(kind): one to four of {id, title, destructive}")
                }
                buttonKinds[kind] = buttons
            }
            onButtons?(buttonKinds)
            return nil
        case "widget":
            guard let id = op["id"]?.string, !id.isEmpty else { throw OperationError(description: "widget needs id") }
            if op["remove"]?.truthy == true {
                widgets[id] = nil
                snapshots.remove(id)
                return nil
            }
            guard let store = op["store"]?.string, let component = op["component"]?.string else {
                throw OperationError(description: "widget needs store and component")
            }
            guard self.component(component) != nil else { throw OperationError(description: "widget \(id) names the component \(component), which is not defined") }
            widgets[id] = .object(["id": .string(id), "store": .string(store), "component": .string(component),
                                   "families": op["families"] ?? .array(["small", "medium", "large"])])
            snapshot(id)
            return nil
        case "acked":
            let ids = Set((op["ids"]?.array ?? []).compactMap(\.string))
            for id in ids {
                for answer in op["answers"]?[id]?.array ?? [] {
                    _ = try apply(answer)
                }
            }
            acknowledged(ids, failed: (op["failed"]?.object ?? [:]).compactMapValues(\.string))
            return nil
        case "command":
            try commandRan(op)
            return nil
        case "page":
            guard let id = op["id"]?.string else { throw OperationError(description: "page needs id") }
            if op["remove"]?.truthy == true {
                pages.removeAll { $0.id == id }
                pinned.removeAll { $0 == id }
                pageStates[id] = nil
                tabNames[id] = nil
                return nil
            }
            guard let view = op["view"] else { throw OperationError(description: "page needs view") }
            revision += 1
            let page = PageSpec(
                id: id,
                title: op["title"]?.text ?? id,
                symbol: op["symbol"]?.string ?? "square.grid.2x2",
                view: view,
                state: op["state"]?.object ?? [:],
                revision: revision,
                upkeep: op["upkeep"] ?? pages.first(where: { $0.id == id })?.upkeep,
                script: ScriptSpec(op),
                toolbar: op["toolbar"]?.array ?? []
            )
            if let script = page.script, !loading { ScriptEngine.shared.pardon(script.source) }
            if let index = pages.firstIndex(where: { $0.id == id }) {
                pages[index] = page
            } else {
                pages.append(page)
                if !loading, arranged.remove(id) == nil {
                    pinned.append(id)
                    onPageCreated?(id, page.title)
                }
            }
            if op["focus"]?.truthy == true {
                pageFocus = id
                pageFocusRequests += 1
            }
            return nil
        case "upkeep":
            guard let id = op["page"]?.string, let index = pages.firstIndex(where: { $0.id == id }) else { return nil }
            pages[index].upkeep = op["state"]
            return nil
        case "preview":
            let (report, shots) = ActivityPreview.run(op)
            captures.hold(shots)
            emit(report)
            previews.append(report)
            return nil
        case "activity", "assets":
            onActivity?(op)
            return nil
        case "say":
            guard op["card"] != nil else {
                onConversation?(op)
                return nil
            }
            let id = op["id"]?.string ?? UUID().uuidString
            onConversation?(op.merging(.object(["id": .string(id)])))
            return id
        case "patch":
            guard let id = op["id"]?.string else { throw OperationError(description: "patch needs the id of a message with a card") }
            onConversation?(op)
            return id
        case "presence", "topic", "receipt", "history":
            onConversation?(op)
            return nil
        case "profile":
            onProfile?(op)
            return nil
        case "arrangement":
            arrange(op)
            return nil
        case "background":
            onBackground?(op)
            return nil
        case "define":
            for (name, source) in op["scripts"]?.object ?? [:] {
                guard name.range(of: #"^[A-Za-z_$][A-Za-z0-9_$]*$"#, options: .regularExpression) != nil else {
                    throw OperationError(description: "A script module's name is a JavaScript name: \(name)")
                }
                ScriptEngine.modules[name] = source == .null ? nil : source.string
            }
            guard op["scripts"] != nil || op["components"] != nil else { throw OperationError(description: "define needs components or scripts") }
            for (name, definition) in op["components"]?.object ?? [:] {
                guard name.first?.isUppercase == true else { throw OperationError(description: "Component names are capitalised: \(name)") }
                guard definition != .null else {
                    components[name] = nil
                    continue
                }
                guard ComponentDefinition(definition) != nil else { throw OperationError(description: "Component \(name) needs a body") }
                components[name] = definition
            }
            return nil
        default:
            throw OperationError(description: "Unknown op \(kind)")
        }
    }

    // MARK: - Batches

    /// What a batch of ops left to report on once applied.
    struct Applied {
        let ops: [JSONValue]
        var errors: [JSONValue] = []
        var touched: [String] = []
        var previews: [JSONValue] = []
    }

    /// Applies a batch of ops from the agent and keeps what they changed.
    /// Errors go back as an event at once, and so does a clean result when the
    /// batch asks for it with a `check` op; what the ops drew is for `report`.
    func apply(batch ops: [JSONValue]) -> Applied {
        var applied = Applied(ops: ops)
        withAnimation(.spring(duration: 0.5)) {
            for (index, op) in ops.enumerated() {
                do {
                    if let id = try apply(op) { applied.touched.append(id) }
                    note(inbound: true, kind: op["op"]?.string ?? "?", detail: Self.subject(op))
                } catch {
                    applied.errors.append(.string("op \(index): \(error)"))
                    note(inbound: true, kind: op["op"]?.string ?? "?", detail: Self.subject(op), problem: "\(error)")
                }
            }
        }
        for id in applied.touched {
            contexts[id]?.resetDiagnostics()
        }
        let changed = Set(ops.compactMap { $0["op"]?.string })
        if !changed.isDisjoint(with: Self.kept) { saveSoon() }
        if changed.contains("define") {
            SharedCards.saveComponents(components)
            snapshotAllWidgets()
        }
        Storage.flush()
        applied.previews = previews
        previews = []
        if let check = ops.last(where: { $0["op"]?.string == "check" })?["id"] {
            emit(.object(["kind": "checked", "id": check, "errors": .array(applied.errors), "at": JSONValue.iso(.now)]))
        } else if !applied.errors.isEmpty {
            emit(.object(["kind": "errors", "errors": .array(applied.errors), "at": JSONValue.iso(.now)]))
        }
        return applied
    }

    /// Ops from the relay: applied and kept now, reported on after, one batch
    /// after the other.
    func receive(_ ops: [JSONValue]) {
        let applied = apply(batch: ops)
        let previous = reporting
        reporting = Task { [weak self] in
            await previous?.value
            _ = await self?.report(applied)
        }
    }

    /// `{"op": "store", "id", "data" | "patch" | "record" | "drop", "kind", "declare"}`
    /// (protocol.md, Data): the store whole or in part, its shape, and what
    /// makes its records findable; `data: null` deletes it with everything of it.
    private func store(_ op: JSONValue) throws {
        guard let id = op["id"]?.string else { throw OperationError(description: "store needs id") }
        if let kind = op["kind"]?.string {
            guard ["text", "folder"].contains(kind) else { throw OperationError(description: "store kind is text or folder, got \(kind)") }
            storeKinds[id] = kind
        }
        if let declared = op["declare"] {
            if declared == .null {
                declarations[id] = nil
            } else {
                guard declared.object != nil else { throw OperationError(description: "store declare is an object: {name, symbol, screen, title, subtitle, words}") }
                declarations[id] = declared
            }
        }
        if let data = op["data"] {
            if data == .null {
                storeTruth[id] = nil
                storeKinds[id] = nil
                declarations[id] = nil
                attachments.forget(store: id)
                fileSync.forget(id)
            } else {
                storeTruth[id] = data
                if let records = data.array {
                    let kept = Set(records.compactMap { $0["id"]?.string })
                    for key in attachments.held.keys where key.hasPrefix("\(id)/") && !kept.contains(String(key.dropFirst(id.count + 1))) {
                        attachments.forget(store: id, record: String(key.dropFirst(id.count + 1)))
                    }
                }
            }
        } else if let patch = op["patch"] {
            storeTruth[id] = (storeTruth[id] ?? .object([:])).merging(patch)
        } else if let record = op["record"] {
            guard let recordID = record["id"]?.string else { throw OperationError(description: "store record needs its id") }
            var records = (storeTruth[id]?.array ?? []).filter { $0["id"]?.string != recordID }
            records.append(record)
            storeTruth[id] = .array(records.sorted { ($0["id"]?.string ?? "") < ($1["id"]?.string ?? "") })
        } else if let dropped = op["drop"]?.string {
            storeTruth[id] = .array((storeTruth[id]?.array ?? []).filter { $0["id"]?.string != dropped })
            attachments.forget(store: id, record: dropped)
        } else if op["kind"] == nil && op["declare"] == nil {
            throw OperationError(description: "store needs data, patch, record, drop, kind or declare")
        }
        showStore(id)
        saveStoresSoon()
    }

    /// A record of a store, by id, as the store holds it.
    func record(_ store: String, _ id: String) -> JSONValue? {
        stores[store]?.array?.first { $0["id"]?.text == id }
    }

    /// A page's state as you left it, kept as you change it.
    func savedState(_ pageID: String) -> SavedState {
        SavedState(pageStates[pageID] ?? [:]) { [weak self] saved in
            self?.pageStates[pageID] = saved
            self?.saveSoon()
        }
    }

    /// What a page or a card reads under a name from now on; nil when there
    /// is nothing by that name any more.
    func show(_ data: JSONValue?, as store: String) {
        stores[store] = data
        storeUpdated[store] = .now
        if !widgets.isEmpty, !loading { snapshotWidgets(reading: store) }
    }

    // MARK: - Pages and the bar

    func component(_ name: String) -> ComponentDefinition? {
        components[name].flatMap(ComponentDefinition.init)
    }

    func page(_ id: String) -> PageSpec? {
        pages.first { $0.id == id }
    }

    /// When a store the page reads last changed: the latest of them.
    func updated(_ page: PageSpec) -> Date? {
        let written = String(decoding: page.view.data(), as: UTF8.self)
        return storeUpdated.filter { written.contains($0.key) }.values.max()
    }

    func removePage(_ id: String) {
        withAnimation {
            pages.removeAll { $0.id == id }
            pinned.removeAll { $0 == id }
        }
        tabNames[id] = nil
        contexts[id] = nil
        save()
    }

    /// What the bar holds, in its order: the pages you keep there.
    var bar: [String] {
        pinned.filter { page($0) != nil }
    }

    /// A page's name in the bar: yours, else its title.
    func tabName(_ id: String) -> String {
        tabNames[id] ?? page(id)?.title ?? id
    }

    func symbol(_ id: String) -> String {
        page(id)?.symbol ?? "doc.text"
    }

    /// Names a page's tab; an empty name gives it back its title.
    func nameTab(_ id: String, _ name: String) {
        let name = name.trimmingCharacters(in: .whitespacesAndNewlines)
        tabNames[id] = name.isEmpty || name == page(id)?.title ? nil : name
        save()
    }

    /// Reorders the bar, by places in it.
    func moveInBar(from source: IndexSet, to destination: Int) {
        var bar = self.bar
        bar.move(fromOffsets: source, toOffset: destination)
        pinned = bar + pinned.filter { !bar.contains($0) }
        save()
    }

    /// Moves a page one place along the bar.
    func move(_ id: String, by step: Int) {
        guard let at = bar.firstIndex(of: id), bar.indices.contains(at + step) else { return }
        withAnimation(.snappy) { moveInBar(from: [at], to: step > 0 ? at + step + 1 : at + step) }
    }

    /// Puts a page in the tab bar, or takes it out.
    func pin(_ id: String, _ on: Bool) {
        withAnimation {
            pinned.removeAll { $0 == id }
            if on { pinned.append(id) }
        }
        save()
    }

    /// Asks for a maintained page to be brought up to date now: its job runs at
    /// the cron's next tick, and the page says it is updating until then.
    func refresh(_ id: String) {
        guard let index = pages.firstIndex(where: { $0.id == id }), pages[index].upkeep != nil else { return }
        pages[index].upkeep = pages[index].upkeep?.merging(.object(["refreshing": true]))
        emit(.object(["kind": "refresh", "page": .string(id), "at": JSONValue.iso(.now)]))
        save()
    }

    // MARK: - The log and what goes back

    struct LogEntry: Identifiable {
        let id = UUID()
        let at = Date.now
        let inbound: Bool
        let kind: String
        let detail: String
        let problem: String?
    }

    /// Everything that came in and went out, newest first, for Settings › Monitoring.
    func note(inbound: Bool, kind: String, detail: String, problem: String? = nil) {
        log.insert(LogEntry(inbound: inbound, kind: kind, detail: detail, problem: problem), at: 0)
        if log.count > 300 { log.removeLast(log.count - 300) }
    }

    func emit(_ event: JSONValue) {
        #if DEBUG
        driven.append(event)
        if driven.count > 500 { driven.removeFirst(driven.count - 500) }
        #endif
        onEmit?(event)
        let issues = (event["issues"]?.array ?? []) + (event["diagnostics"]?.array ?? [])
        note(inbound: false, kind: event["kind"]?.string ?? "event", detail: Self.subject(event), problem: issues.isEmpty ? nil : issues.map(\.text).joined(separator: "\n"))
    }

    static func subject(_ value: JSONValue) -> String {
        for key in ["id", "card", "conversation", "page", "text"] {
            if let text = value[key]?.string { return String(text.prefix(80)) }
        }
        return ""
    }

    func enqueue(_ event: JSONValue) {
        emit(event)
    }

    /// The context of a card in a message: it collects what the card reports
    /// while drawing, and sends its actions where the message lives.
    func cardContext(_ id: String, onSend: @escaping (JSONValue, String?) -> Void) -> CardContext {
        if let context = contexts[id] { return context }
        let context = CardContext(
            cardID: id,
            component: { [weak self] name in self?.component(name) },
            onSend: { payload, say in
                UIImpactFeedbackGenerator(style: .light).impactOccurred()
                onSend(payload, say)
            }
        )
        contexts[id] = context
        return context
    }

    /// Pages share one context each: their actions go back to the server with
    /// the page's id.
    func pageContext(_ id: String) -> CardContext {
        if let context = contexts[id] { return context }
        let context = CardContext(
            cardID: id,
            component: { [weak self] name in self?.component(name) },
            onSend: { [weak self] payload, say in
                UIImpactFeedbackGenerator(style: .light).impactOccurred()
                var event: [String: JSONValue] = ["kind": "action", "page": .string(id), "payload": payload, "at": JSONValue.iso(.now)]
                if let say { event["say"] = .string(say) }
                self?.emit(.object(event))
            }
        )
        contexts[id] = context
        return context
    }

    // MARK: - Persistence

    /// The ops that change what this file keeps.
    private static let kept: Set<String> = ["acked", "page", "define", "upkeep", "buttons", "widget"]

    func save() {
        let savedPages: [JSONValue] = pages.map { page in
            var object: [String: JSONValue] = ["op": "page", "id": .string(page.id), "title": .string(page.title), "symbol": .string(page.symbol), "view": page.view, "state": .object(page.state)]
            if let upkeep = page.upkeep { object["upkeep"] = upkeep }
            if let script = page.script { object.merge(script.json) { $1 } }
            return .object(object)
        }
        let file: JSONValue = .object(["components": .object(components), "scripts": .object(ScriptEngine.modules.mapValues(JSONValue.string)), "pages": .array(savedPages), "commands": .object(commandRuns), "pinned": .array(pinned.map(JSONValue.string)),
                                       "buttons": .object(buttonKinds), "widgets": .object(widgets),
                                       "tabNames": .object(tabNames.mapValues(JSONValue.string)),
                                       "pageStates": .object(pageStates.mapValues { .object($0.mapValues(JSONValue.object)) })])
        Storage.save(file, to: "hub.json")
        arrangementChanged()
    }

    /// How you arranged the app on a phone paired before: the bar, the tabs'
    /// names, what you set on each page and the face you made.
    private func arrange(_ op: JSONValue) {
        pinned = (op["pinned"]?.array ?? []).compactMap(\.string)
        tabNames = (op["tabNames"]?.object ?? [:]).compactMapValues(\.string)
        pageStates = (op["pageStates"]?.object ?? [:]).mapValues { ($0.object ?? [:]).compactMapValues(\.object) }
        arranged = Set((op["pages"]?.array ?? []).compactMap(\.string)).subtracting(pages.map(\.id))
        onArrangement?(op)
        save()
    }

    /// How you arranged the app, sent to the agent's machine a moment after it
    /// changes, for a phone paired later to take back.
    func arrangementChanged() {
        arranging?.cancel()
        arranging = Task { [weak self] in
            try? await Task.sleep(for: .seconds(3))
            guard !Task.isCancelled, let self else { return }
            var arrangement: [String: JSONValue] = [
                "kind": "arrangement", "pinned": .array(pinned.map(JSONValue.string)),
                "tabNames": .object(tabNames.mapValues(JSONValue.string)),
                "pageStates": .object(pageStates.mapValues { .object($0.mapValues(JSONValue.object)) }),
                "pages": .array(pages.map { .string($0.id) }),
            ]
            arrangement.merge(choices()) { kept, _ in kept }
            guard JSONValue.object(arrangement) != arrangementSent else { return }
            arrangementSent = .object(arrangement)
            emit(.object(arrangement))
        }
    }

    /// Keeps what a tap or a keystroke changed, shortly: a burst is one write.
    func saveSoon() {
        Storage.saveSoon("hub.json") { [weak self] in self?.save() }
    }

    /// The stores are kept apart from the rest: a folder of notes is large and
    /// changes on its own rhythm.
    private func saveStoresSoon() {
        Storage.saveSoon("stores.json") { [weak self] in
            guard let self else { return }
            Storage.save(.object(["truth": .object(storeTruth), "kinds": .object(storeKinds.mapValues(JSONValue.string)),
                                  "declarations": .object(declarations)]), to: "stores.json")
        }
    }

    private func load() {
        if let kept = Storage.load("stores.json") {
            storeTruth = kept["truth"]?.object ?? [:]
            storeKinds = (kept["kinds"]?.object ?? [:]).compactMapValues(\.string)
            declarations = kept["declarations"]?.object ?? [:]
        }
        guard let file = Storage.load("hub.json") else { return }
        loading = true
        defer { loading = false }
        pinned = (file["pinned"]?.array ?? []).compactMap(\.string)
        tabNames = (file["tabNames"]?.object ?? [:]).compactMapValues(\.string)
        components = file["components"]?.object ?? [:]
        ScriptEngine.modules = (file["scripts"]?.object ?? [:]).compactMapValues(\.string)
        commandRuns = file["commands"]?.object ?? [:]
        buttonKinds = file["buttons"]?.object ?? [:]
        widgets = file["widgets"]?.object ?? [:]
        pageStates = (file["pageStates"]?.object ?? [:]).mapValues { ($0.object ?? [:]).compactMapValues(\.object) }
        for page in file["pages"]?.array ?? [] {
            _ = try? apply(page)
        }
        loading = false
        snapshotAllWidgets()
    }
}
