// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

#if DEBUG
import Foundation
import Network

/// A tiny HTTP server on the phone's loopback, reached from the Mac through
/// `iproxy` over USB. Debug builds only: it lets the Mac send ops and read events while developing.
nonisolated final class DriveServer: @unchecked Sendable {
    struct Request: Sendable {
        let method: String
        let path: String
        let query: [String: String]
        let body: Data
    }

    struct Response: Sendable {
        var status = 200
        var contentType = "application/json"
        var body: Data
    }

    var onState: (@Sendable (String) -> Void)?

    private let port: NWEndpoint.Port
    private let handler: @Sendable (Request) async -> Response
    private let queue = DispatchQueue(label: "hermes.drive")
    private var listener: NWListener?

    init(port: UInt16, handler: @escaping @Sendable (Request) async -> Response) {
        self.port = NWEndpoint.Port(rawValue: port)!
        self.handler = handler
    }

    func start() {
        queue.async { [self] in
            if let listener, listener.state == .ready { return }
            listener?.cancel()
            let parameters = NWParameters.tcp
            parameters.allowLocalEndpointReuse = true
            parameters.requiredLocalEndpoint = .hostPort(host: .ipv4(.loopback), port: port)
            do {
                let listener = try NWListener(using: parameters)
                listener.stateUpdateHandler = { [weak self] state in
                    guard let self else { return }
                    switch state {
                    case .ready:
                        self.onState?("Listening on USB · port \(self.port.rawValue)")
                    case .failed(let error):
                        self.onState?("Stopped: \(error.localizedDescription)")
                        self.queue.asyncAfter(deadline: .now() + 2) { self.start() }
                    case .cancelled:
                        self.onState?("Not listening")
                    default:
                        break
                    }
                }
                listener.newConnectionHandler = { [weak self] connection in
                    self?.accept(connection)
                }
                listener.start(queue: queue)
                self.listener = listener
            } catch {
                onState?("Could not listen: \(error.localizedDescription)")
            }
        }
    }

    private func accept(_ connection: NWConnection) {
        connection.start(queue: queue)
        receive(on: connection, buffer: Data())
    }

    private func receive(on connection: NWConnection, buffer: Data) {
        connection.receive(minimumIncompleteLength: 1, maximumLength: 1 << 16) { [weak self] data, _, complete, error in
            guard let self else { return }
            var buffer = buffer
            if let data { buffer.append(data) }
            if let request = Self.parse(buffer) {
                Task {
                    let response = await self.handler(request)
                    self.respond(response, on: connection)
                }
            } else if complete || error != nil || buffer.count > 16 << 20 {
                connection.cancel()
            } else {
                self.receive(on: connection, buffer: buffer)
            }
        }
    }

    private func respond(_ response: Response, on connection: NWConnection) {
        let head = "HTTP/1.1 \(response.status) \(response.status == 200 ? "OK" : "Error")\r\nContent-Type: \(response.contentType)\r\nContent-Length: \(response.body.count)\r\nConnection: close\r\n\r\n"
        connection.send(content: Data(head.utf8) + response.body, completion: .contentProcessed { _ in
            connection.cancel()
        })
    }

    private static func parse(_ buffer: Data) -> Request? {
        guard let end = buffer.range(of: Data("\r\n\r\n".utf8)) else { return nil }
        let head = String(decoding: buffer[..<end.lowerBound], as: UTF8.self)
        let lines = head.components(separatedBy: "\r\n")
        let parts = lines.first?.split(separator: " ") ?? []
        guard parts.count >= 2 else { return nil }
        let length = lines.dropFirst().compactMap { line -> Int? in
            let pair = line.split(separator: ":", maxSplits: 1)
            guard pair.count == 2, pair[0].lowercased() == "content-length" else { return nil }
            return Int(pair[1].trimmingCharacters(in: .whitespaces))
        }.first ?? 0
        let body = buffer[end.upperBound...]
        guard body.count >= length else { return nil }
        let target = URLComponents(string: String(parts[1]))
        let query = Dictionary((target?.queryItems ?? []).map { ($0.name, $0.value ?? "") }, uniquingKeysWith: { a, _ in a })
        return Request(method: String(parts[0]), path: target?.path ?? "/", query: query, body: Data(body.prefix(length)))
    }
}
#endif
