// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import AVFoundation
import Speech

/// Listening for the agent: what you say, written as you say it, heard in
/// French and in English at once and kept in whichever language is surer of
/// what it hears, all on the phone.
@MainActor @Observable
final class Listener {
    enum State: Equatable {
        case idle, preparing, listening
        case failed(String)
    }

    private(set) var state: State = .idle
    private(set) var text = ""
    /// Whether the finger holding the pill slid away, so letting go cancels.
    var away = false

    /// What one language has heard: the settled part and the part still moving.
    private struct Heard {
        var settled = AttributedString()
        var moving = AttributedString()

        var all: AttributedString { settled + moving }

        var confidence: Double? {
            var sum = 0.0
            var count = 0.0
            for run in all.runs {
                guard let confidence = run.attributes[AttributeScopes.SpeechAttributes.ConfidenceAttribute.self] else { continue }
                let length = Double(all[run.range].characters.count)
                sum += confidence * length
                count += length
            }
            return count > 0 ? sum / count : nil
        }
    }

    @ObservationIgnored private var heard: [Heard] = []
    @ObservationIgnored private var engine: AVAudioEngine?
    @ObservationIgnored private var analyzer: SpeechAnalyzer?
    @ObservationIgnored private var feeder: Feeder?
    @ObservationIgnored private var reading: [Task<Void, Never>] = []
    @ObservationIgnored private var attempt = 0

    static let languages = ["fr_FR", "en_US"]

    /// Fetches the languages' speech models ahead, so the first time you
    /// talk does not wait for them.
    static func prepare() async {
        let transcribers = await transcribers()
        guard !transcribers.isEmpty, let request = try? await AssetInventory.assetInstallationRequest(supporting: transcribers) else { return }
        try? await request.downloadAndInstall()
    }

    func start() async {
        guard state != .listening, state != .preparing else { return }
        attempt += 1
        let mine = attempt
        state = .preparing
        text = ""
        guard await AVAudioApplication.requestRecordPermission() else {
            state = .failed("Microphone access is off in Settings.")
            return
        }
        let transcribers = await Self.transcribers()
        guard !transcribers.isEmpty else {
            state = .failed("Speech recognition isn't available on this phone.")
            return
        }
        let engine = AVAudioEngine()
        var feeder: Feeder?
        do {
            if let request = try await AssetInventory.assetInstallationRequest(supporting: transcribers) {
                try await request.downloadAndInstall()
            }
            guard attempt == mine else { return }
            let session = AVAudioSession.sharedInstance()
            try session.setCategory(.record, mode: .default, options: .duckOthers)
            try session.setActive(true)
            let analyzer = SpeechAnalyzer(modules: transcribers)
            let natural = engine.inputNode.outputFormat(forBus: 0)
            guard let format = await SpeechAnalyzer.bestAvailableAudioFormat(compatibleWith: transcribers, considering: natural) else {
                throw ListenerError.noFormat
            }
            try await analyzer.prepareToAnalyze(in: format)
            let (stream, continuation) = AsyncStream.makeStream(of: AnalyzerInput.self)
            let feeding = Feeder(from: natural, to: format, into: continuation)
            feeder = feeding
            feeding.install(on: engine)
            engine.prepare()
            try engine.start()
            try await analyzer.start(inputSequence: stream)
            guard attempt == mine else {
                engine.stop()
                engine.inputNode.removeTap(onBus: 0)
                feeding.finish()
                await analyzer.cancelAndFinishNow()
                return
            }
            heard = Array(repeating: Heard(), count: transcribers.count)
            reading = transcribers.enumerated().map { index, transcriber in
                Task { [weak self] in
                    do {
                        for try await result in transcriber.results {
                            self?.hear(result, from: index)
                        }
                    } catch {
                        return
                    }
                }
            }
            self.analyzer = analyzer
            self.engine = engine
            self.feeder = feeding
            state = .listening
        } catch {
            engine.stop()
            engine.inputNode.removeTap(onBus: 0)
            feeder?.finish()
            guard attempt == mine else { return }
            try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
            state = .failed("Couldn't start listening: \(error.localizedDescription)")
        }
    }

    /// Stops listening and gives what was heard, once it has settled.
    func finish() async -> String {
        guard state == .listening, let analyzer else {
            cancel()
            return ""
        }
        stopAudio()
        try? await analyzer.finalizeAndFinishThroughEndOfInput()
        for task in reading { await task.value }
        let said = text.trimmingCharacters(in: .whitespacesAndNewlines)
        reset()
        return said
    }

    func cancel() {
        attempt += 1
        stopAudio()
        if let analyzer { Task { await analyzer.cancelAndFinishNow() } }
        reading.forEach { $0.cancel() }
        reset()
    }

    func dismissFailure() {
        if case .failed = state { state = .idle }
    }

    private func hear(_ result: SpeechTranscriber.Result, from index: Int) {
        guard heard.indices.contains(index) else { return }
        if result.isFinal {
            heard[index].settled += result.text
            heard[index].moving = AttributedString()
        } else {
            heard[index].moving = result.text
        }
        let best = heard.max { ($0.confidence ?? 0) < ($1.confidence ?? 0) } ?? Heard()
        text = String(best.all.characters)
    }

    private func stopAudio() {
        engine?.stop()
        engine?.inputNode.removeTap(onBus: 0)
        feeder?.finish()
        try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
    }

    private func reset() {
        engine = nil
        feeder = nil
        analyzer = nil
        reading = []
        heard = []
        text = ""
        state = .idle
    }

    private static func transcribers() async -> [SpeechTranscriber] {
        var locales: [Locale] = []
        for identifier in languages {
            if let locale = await SpeechTranscriber.supportedLocale(equivalentTo: Locale(identifier: identifier)), !locales.contains(locale) {
                locales.append(locale)
            }
        }
        return locales.map {
            SpeechTranscriber(locale: $0, transcriptionOptions: [], reportingOptions: [.volatileResults], attributeOptions: [.transcriptionConfidence])
        }
    }

    private enum ListenerError: Error {
        case noFormat
    }
}

/// Takes the microphone's sound, off the main thread, to the format the
/// analyzer reads.
private nonisolated final class Feeder: @unchecked Sendable {
    private let converter: AVAudioConverter?
    private let format: AVAudioFormat
    private let continuation: AsyncStream<AnalyzerInput>.Continuation

    init(from natural: AVAudioFormat, to format: AVAudioFormat, into continuation: AsyncStream<AnalyzerInput>.Continuation) {
        converter = natural == format ? nil : AVAudioConverter(from: natural, to: format)
        self.format = format
        self.continuation = continuation
    }

    func install(on engine: AVAudioEngine) {
        let input = engine.inputNode
        input.installTap(onBus: 0, bufferSize: 4096, format: input.outputFormat(forBus: 0)) { [self] buffer, _ in
            feed(buffer)
        }
    }

    func finish() {
        continuation.finish()
    }

    private func feed(_ buffer: AVAudioPCMBuffer) {
        guard let converter else {
            continuation.yield(AnalyzerInput(buffer: buffer))
            return
        }
        let capacity = AVAudioFrameCount(Double(buffer.frameLength) * format.sampleRate / buffer.format.sampleRate) + 1
        guard let converted = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: capacity) else { return }
        var given = false
        var error: NSError?
        converter.convert(to: converted, error: &error) { _, status in
            if given {
                status.pointee = .noDataNow
                return nil
            }
            given = true
            status.pointee = .haveData
            return buffer
        }
        if error == nil, converted.frameLength > 0 {
            continuation.yield(AnalyzerInput(buffer: converted))
        }
    }
}
