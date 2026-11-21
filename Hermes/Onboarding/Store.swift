// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import Foundation
import Observation
import StoreKit

/// What you paid for, through Apple: a monthly subscription whose first week
/// is free, or a lifetime purchase. Either opens the app; without one, only the
/// paywall shows. What is not known yet (no answer from the App Store) opens it.
@Observable
final class Store {
    static let monthly = "app.dedala.monthly"
    static let lifetime = "app.dedala.lifetime"

    private(set) var products: [String: Product] = [:]
    /// Whether a purchase covers this Apple Account; nil until StoreKit answers.
    private(set) var entitled: Bool?
    /// Whether the free week can still be offered; true until StoreKit says otherwise.
    private(set) var trialAvailable = true
    private(set) var problem: String?
    #if DEBUG || BETA
    /// Development and TestFlight builds may go on without paying: the products
    /// may not be on sale yet.
    var skipped = UserDefaults.standard.bool(forKey: "storeSkipped") {
        didSet { UserDefaults.standard.set(skipped, forKey: "storeSkipped") }
    }
    #endif
    @ObservationIgnored private var updates: Task<Void, Never>?

    init() {
        updates = Task { [weak self] in
            for await update in Transaction.updates {
                if case .verified(let transaction) = update { await transaction.finish() }
                await self?.refresh()
            }
        }
        Task { await load() }
    }

    /// Whether the paywall stands in front of the app.
    var locked: Bool {
        #if DEBUG || BETA
        if skipped { return false }
        #endif
        return entitled == false
    }

    func load() async {
        await fetch()
        if let subscription = products[Self.monthly]?.subscription {
            trialAvailable = await subscription.isEligibleForIntroOffer
        }
        await refresh()
    }

    /// Asks the App Store for both plans; says what went wrong when it cannot.
    private func fetch() async {
        do {
            for product in try await Product.products(for: [Self.monthly, Self.lifetime]) {
                products[product.id] = product
            }
            if products.isEmpty {
                problem = "Dedala isn't available to buy yet. Try again later."
            }
        } catch {
            problem = "The App Store could not be reached: \(error.localizedDescription)"
        }
    }

    func refresh() async {
        var found = false
        for await entitlement in Transaction.currentEntitlements {
            if case .verified(let transaction) = entitlement, [Self.monthly, Self.lifetime].contains(transaction.productID),
               transaction.revocationDate == nil {
                found = true
            }
        }
        entitled = found
    }

    /// Buys a product: true once it is paid for, false when you cancelled or
    /// it waits for approval; a failure is kept in `problem`.
    func buy(_ id: String) async -> Bool {
        problem = nil
        if products[id] == nil {
            await load()
        }
        guard let product = products[id] else {
            if problem == nil { problem = "Dedala isn't available to buy yet. Try again later." }
            return false
        }
        do {
            switch try await product.purchase() {
            case .success(.verified(let transaction)):
                await transaction.finish()
                await refresh()
                return entitled == true
            case .success(.unverified(_, let error)):
                problem = error.localizedDescription
            case .pending:
                problem = "The purchase waits for approval."
            case .userCancelled:
                break
            @unknown default:
                break
            }
        } catch {
            problem = error.localizedDescription
        }
        return false
    }

    func restore() async {
        problem = nil
        do {
            try await AppStore.sync()
        } catch {
            problem = error.localizedDescription
        }
        await refresh()
        if entitled != true, problem == nil {
            problem = "No purchase was found for this Apple Account."
        }
    }

    /// The price as the App Store shows it here, or the euro price before it answers.
    func price(_ id: String) -> String {
        products[id]?.displayPrice ?? (id == Self.monthly ? "€1.99" : "€29.99")
    }
}
