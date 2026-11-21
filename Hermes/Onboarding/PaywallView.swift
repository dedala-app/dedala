// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import SwiftUI

/// What stands before the app while nothing is paid for: the free week first,
/// then, once it is over, the same two plans. It says why it costs something.
struct PaywallView: View {
    @Environment(Store.self) private var store
    @Environment(Agent.self) private var agent
    /// The free week was used: the plans alone, no trial.
    let ended: Bool
    @State private var plan = Store.monthly
    @State private var buying = false

    var body: some View {
        ZStack {
            Brand.ground.ignoresSafeArea()
            ScrollView {
                VStack(alignment: .leading, spacing: 0) {
                    if ended {
                        endedHeader
                    } else {
                        trialHeader
                    }
                    if ended {
                        Text("The price pays for the relay server, Apple's developer program, and the time to keep building Dedala. Made by one person.")
                            .font(.subheadline)
                            .foregroundStyle(Brand.quiet)
                            .multilineTextAlignment(.center)
                            .frame(maxWidth: .infinity)
                            .padding(.top, 22)
                    }
                    if let problem = store.problem {
                        Text(problem)
                            .font(.subheadline)
                            .foregroundStyle(.red)
                            .padding(.top, 14)
                    }
                }
                .padding(.horizontal, 24)
                .padding(.top, ended ? 60 : 24)
                .padding(.bottom, 16)
            }
            .scrollBounceBehavior(.basedOnSize)
            .safeAreaInset(edge: .bottom) { footer }
        }
        .foregroundStyle(Brand.ink)
        .tint(Brand.bronze)
        .onChange(of: ended, initial: true) { plan = ended ? Store.lifetime : Store.monthly }
    }

    private var trialHeader: some View {
        VStack(alignment: .leading, spacing: 0) {
            Text("Try Dedala free for a week")
                .font(.system(size: 28, weight: .bold))
            Text("Then \(store.price(Store.monthly)) a month, or pay once and keep it.")
                .foregroundStyle(Brand.quiet)
                .padding(.top, 8)
            VStack(alignment: .leading, spacing: 0) {
                Text("Dedala is made by one person. \(agent.name) runs on your machine; reaching your \(UIDevice.current.model) is what costs. Paying covers:")
                    .font(.subheadline)
                    .padding(.bottom, 4)
                Reason(symbol: "server.rack", title: "The relay server", text: "which carries your messages, encrypted, and wakes your phone.")
                Divider().overlay(Brand.line)
                Reason(symbol: "bell", title: "Apple's developer program", text: "needed for notifications and Live Activities.")
                Divider().overlay(Brand.line)
                Reason(symbol: "hammer", title: "Time to keep building it", text: "and to bring it to more assistants than Hermes.")
            }
            .padding(EdgeInsets(top: 14, leading: 18, bottom: 2, trailing: 18))
            .background(Brand.surface, in: .rect(cornerRadius: 22, style: .continuous))
            .padding(.top, 18)
        }
    }

    private var endedHeader: some View {
        VStack(spacing: 12) {
            AgentDot(size: 92, reachable: false)
                .saturation(0)
                .padding(.bottom, 12)
            Text("Your free week is over")
                .font(.system(size: 30, weight: .bold))
            Text("\(agent.name) keeps running on your machine, and everything \(agent.name) built is still there. Pick a plan to see it here again.")
                .foregroundStyle(Brand.quiet)
        }
        .multilineTextAlignment(.center)
        .frame(maxWidth: .infinity)
    }

    /// The plans, the button and what it commits to, always in view.
    private var footer: some View {
        VStack(spacing: 10) {
            VStack(spacing: 8) {
                PlanRow(title: "Monthly", detail: ended ? nil : "First week free", price: store.price(Store.monthly), period: " / month",
                        on: plan == Store.monthly) { plan = Store.monthly }
                PlanRow(title: "Lifetime", detail: ended ? nil : "Pay once, no renewal", price: store.price(Store.lifetime), period: nil,
                        on: plan == Store.lifetime) { plan = Store.lifetime }
            }
            .padding(.bottom, 6)
            BrandButton(title: buttonTitle, busy: buying) {
                buying = true
                Task {
                    _ = await store.buy(plan)
                    buying = false
                }
            }
            Text(finePrint)
                .font(.caption)
                .foregroundStyle(Brand.quiet)
                .multilineTextAlignment(.center)
            HStack(spacing: 18) {
                Button("Restore Purchases") { Task { await store.restore() } }
                Link("Terms", destination: URL(string: "https://dedala.app/terms")!)
                Link("Privacy", destination: URL(string: "https://dedala.app/privacy")!)
            }
            .font(.footnote)
            .frame(minHeight: 32)
            #if DEBUG || BETA
            Button("Continue without paying (test build)") { store.skipped = true }
                .font(.footnote)
                .foregroundStyle(Brand.quiet)
            #endif
        }
        .padding(.horizontal, 24)
        .padding(.top, 12)
        .padding(.bottom, 8)
        .background(Brand.ground)
    }

    private var buttonTitle: String {
        if plan == Store.lifetime { return "Buy for \(store.price(Store.lifetime))" }
        return ended ? "Subscribe for \(store.price(Store.monthly)) a month" : "Start the free week"
    }

    private var finePrint: String {
        if plan == Store.lifetime {
            return "One payment of \(store.price(Store.lifetime)), charged to your Apple Account. Yours on your iPhone and your iPad."
        }
        let renews = "charged to your Apple Account. Renews until you cancel in Settings, at least a day before it renews."
        return ended ? "\(store.price(Store.monthly)) a month, \(renews)" : "Free for 7 days, then \(store.price(Store.monthly)) a month, \(renews)"
    }

    private struct Reason: View {
        let symbol: String
        let title: String
        let text: String

        var body: some View {
            HStack(alignment: .top, spacing: 12) {
                Image(systemName: symbol)
                    .font(.body)
                    .foregroundStyle(Brand.bronze)
                    .frame(width: 24)
                Text("\(Text(title).fontWeight(.semibold).foregroundStyle(Brand.ink)), \(text)")
                    .font(.subheadline)
                    .foregroundStyle(Brand.quiet)
            }
            .padding(.vertical, 8)
        }
    }

    private struct PlanRow: View {
        let title: String
        let detail: String?
        let price: String
        let period: String?
        let on: Bool
        let pick: () -> Void

        var body: some View {
            Button(action: pick) {
                HStack(spacing: 12) {
                    Image(systemName: on ? "largecircle.fill.circle" : "circle")
                        .font(.title3)
                        .foregroundStyle(on ? Brand.bronze : Brand.quiet.opacity(0.6))
                    VStack(alignment: .leading, spacing: 2) {
                        Text(title).font(.body.weight(.semibold))
                        if let detail { Text(detail).font(.subheadline).foregroundStyle(Brand.quiet) }
                    }
                    Spacer()
                    Text("\(Text(price).fontWeight(.semibold))\(Text(period ?? "").font(.subheadline).foregroundStyle(Brand.quiet))")
                }
                .foregroundStyle(Brand.ink)
                .padding(.horizontal, 16)
                .padding(.vertical, 10)
                .frame(minHeight: 54)
                .background(Brand.surface, in: .rect(cornerRadius: 18, style: .continuous))
                .overlay {
                    RoundedRectangle(cornerRadius: 18, style: .continuous)
                        .strokeBorder(on ? Brand.bronze : Brand.line, lineWidth: on ? 2 : 1)
                }
            }
            .buttonStyle(.plain)
            .accessibilityAddTraits(on ? .isSelected : [])
        }
    }
}
