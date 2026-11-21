// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import SwiftUI
import UserNotifications
import Vision
import VisionKit

/// Pairing with a Hermes: scan the code `hermes dedala pair` prints where Hermes
/// runs, or paste it.
struct PairingView: View {
    @Environment(Relay.self) private var relay
    @Environment(\.dismiss) private var dismiss
    @State private var pairing = false
    @State private var problem: String?

    var body: some View {
        NavigationStack {
            VStack(spacing: 20) {
                if DataScannerViewController.isSupported, DataScannerViewController.isAvailable {
                    QRScanner { code in pair(code) }
                        .clipShape(.rect(cornerRadius: 24, style: .continuous))
                        .frame(height: 320)
                        .overlay {
                            if pairing { ProgressView().controlSize(.large) }
                        }
                } else {
                    ContentUnavailableView("No camera", systemImage: "camera", description: Text("Paste the code instead."))
                        .frame(height: 320)
                }
                VStack(spacing: 6) {
                    Text("On the machine where Hermes runs:")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                    Text("hermes dedala pair")
                        .font(.body.monospaced().weight(.semibold))
                }
                Button("Paste the code", systemImage: "doc.on.clipboard") {
                    if let code = UIPasteboard.general.string { pair(code) }
                }
                .buttonStyle(.bordered)
                if let problem {
                    Text(problem)
                        .font(.footnote)
                        .foregroundStyle(.red)
                        .multilineTextAlignment(.center)
                }
                Spacer()
            }
            .padding(20)
            .navigationTitle("Pair with your agent")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel", systemImage: "xmark") { dismiss() }
                }
            }
        }
    }

    private func pair(_ code: String) {
        guard !pairing else { return }
        pairing = true
        problem = nil
        Task {
            _ = try? await UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound, .badge])
            do {
                try await relay.pair(with: code)
                UINotificationFeedbackGenerator().notificationOccurred(.success)
                dismiss()
            } catch {
                problem = error.localizedDescription
                pairing = false
            }
        }
    }
}

/// The camera, reading QR codes; the first one found is handed on.
struct QRScanner: UIViewControllerRepresentable {
    let found: (String) -> Void

    func makeUIViewController(context: Context) -> DataScannerViewController {
        let scanner = DataScannerViewController(recognizedDataTypes: [.barcode(symbologies: [.qr])], isHighlightingEnabled: true)
        scanner.delegate = context.coordinator
        try? scanner.startScanning()
        return scanner
    }

    func updateUIViewController(_ scanner: DataScannerViewController, context: Context) {}

    func makeCoordinator() -> Coordinator {
        Coordinator(found: found)
    }

    final class Coordinator: NSObject, DataScannerViewControllerDelegate {
        let found: (String) -> Void

        init(found: @escaping (String) -> Void) {
            self.found = found
        }

        func dataScanner(_ dataScanner: DataScannerViewController, didAdd addedItems: [RecognizedItem], allItems: [RecognizedItem]) {
            for item in addedItems {
                if case .barcode(let barcode) = item, let payload = barcode.payloadStringValue {
                    found(payload)
                    return
                }
            }
        }
    }
}
