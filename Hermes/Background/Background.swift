// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import SwiftUI
import Observation

/// What the agent does in the background: his scheduled jobs and their runs,
/// the ones under way with the steps they take, as the plugin sees them.
@Observable
final class Background {
    struct Job: Identifiable, Equatable {
        let id: String
        var name: String
        var schedule: String
        var next: Date?
        var last: Date?
        var failed: Bool
        var error: String?
        var paused: Bool
        /// A one-time job that ran: it will not run again.
        var done: Bool
        var silent: Bool
        var page: String?
        /// A change detector: it checks at each tick and runs the agent only
        /// when what it watches changed (`last`).
        var watching: Bool
        var checked: Date?
    }

    struct Run: Identifiable, Equatable {
        let id: String
        var job: String
        var name: String
        var started: Date?
        var finished: Date?
        var status: String
        var error: String?
        var steps: [Conversations.Step]
        var tokens: Int
        var doing: String?
        /// Handed by the agent to a subagent from a conversation, not a job.
        var background = false

        var running: Bool { status == "running" }
    }

    private(set) var jobs: [Job] = []
    private(set) var runs: [Run] = []
    @ObservationIgnored var onEvent: ((JSONValue) -> Void)?

    var running: [Run] { runs.filter(\.running) }

    func apply(_ op: JSONValue) {
        jobs = (op["jobs"]?.array ?? []).compactMap { job in
            job["id"]?.string.map { id in
                Job(id: id, name: job["name"]?.string ?? id, schedule: job["schedule"]?.string ?? "",
                    next: job["next"]?.date, last: job["last"]?.date, failed: job["status"]?.string == "error",
                    error: job["error"]?.string, paused: job["paused"]?.truthy == true, done: job["done"]?.truthy == true,
                    silent: job["silent"]?.truthy == true, page: job["page"]?.string,
                    watching: job["watching"]?.truthy == true, checked: job["checked"]?.date)
            }
        }
        runs = (op["runs"]?.array ?? []).compactMap { run in
            run["id"]?.string.map { id in
                Run(id: id, job: run["job"]?.string ?? "", name: run["name"]?.string ?? "", started: run["started"]?.date,
                    finished: run["finished"]?.date, status: run["status"]?.string ?? "ok", error: run["error"]?.string,
                    steps: (run["steps"]?.array ?? []).compactMap { step in
                        step["text"]?.string.map { Conversations.Step(text: $0, symbol: step["symbol"]?.string ?? "circle", failed: step["failed"]?.bool) }
                    },
                    tokens: run["tokens"]?.int ?? 0, doing: run["doing"]?.string, background: run["background"]?.truthy == true)
            }
        }
    }

    func job(_ id: String) -> Job? { jobs.first { $0.id == id } }

    func act(_ action: String, on job: String) {
        if let index = jobs.firstIndex(where: { $0.id == job }), action != "run" {
            jobs[index].paused = action == "pause"
        }
        onEvent?(.object(["kind": "job", "job": .string(job), "action": .string(action), "at": JSONValue.iso(.now)]))
    }

    static func duration(from start: Date?, to end: Date) -> String {
        let seconds = max(0, Int(end.timeIntervalSince(start ?? end)))
        return seconds < 3600 ? String(format: "%d:%02d", seconds / 60, seconds % 60) : "\(seconds / 3600)h \(seconds % 3600 / 60)m"
    }

    static func tokens(_ count: Int) -> String {
        count < 1000 ? "\(count) tokens" : String(format: "%.1fk tokens", Double(count) / 1000)
    }
}
