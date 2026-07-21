import Foundation
import Network
import UIKit

final class LocalHTTPServer: ObservableObject {
    @Published private(set) var isRunning = false
    @Published private(set) var baseURL: String?
    @Published private(set) var lastError: String?

    private let queue = DispatchQueue(label: "com.openclaw.iosclaw.http")
    private var listener: NWListener?
    private lazy var router = LumiRouter { [weak self] in self?.baseURL }

    func start(port: UInt16 = PairingStore.defaultPort) {
        stop()
        do {
            let endpointPort = NWEndpoint.Port(rawValue: port) ?? 9527
            let listener = try NWListener(using: .tcp, on: endpointPort)
            listener.service = NWListener.Service(name: UIDevice.current.name, type: "_iosclaw._tcp")
            listener.newConnectionHandler = { [weak self] connection in
                self?.handle(connection)
            }
            listener.stateUpdateHandler = { [weak self] state in
                DispatchQueue.main.async {
                    switch state {
                    case .ready:
                        self?.isRunning = true
                        self?.lastError = nil
                        let ip = DeviceInfo.localIPv4Addresses().first ?? "127.0.0.1"
                        self?.baseURL = "http://\(ip):\(port)"
                    case .failed(let error):
                        self?.isRunning = false
                        self?.lastError = error.localizedDescription
                    case .cancelled:
                        self?.isRunning = false
                    default:
                        break
                    }
                }
            }
            self.listener = listener
            listener.start(queue: queue)
        } catch {
            lastError = error.localizedDescription
            isRunning = false
        }
    }

    func stop() {
        listener?.cancel()
        listener = nil
        isRunning = false
        baseURL = nil
    }

    private func handle(_ connection: NWConnection) {
        connection.start(queue: queue)
        receive(connection, buffer: Data())
    }

    private func receive(_ connection: NWConnection, buffer: Data) {
        connection.receive(minimumIncompleteLength: 1, maximumLength: 64 * 1024) { [weak self] data, _, isComplete, error in
            guard let self else { return }
            if let error {
                self.send(.error(error.localizedDescription, statusCode: 500, reason: "Internal Server Error"), on: connection)
                return
            }
            var nextBuffer = buffer
            if let data {
                nextBuffer.append(data)
            }
            if let request = HTTPRequest.parseIfComplete(nextBuffer) {
                Task {
                    let response = await self.router.route(request)
                    self.send(response, on: connection)
                }
                return
            }
            if isComplete {
                self.send(.error("Malformed HTTP request", statusCode: 400, reason: "Bad Request"), on: connection)
                return
            }
            self.receive(connection, buffer: nextBuffer)
        }
    }

    private func send(_ response: HTTPResponse, on connection: NWConnection) {
        connection.send(content: response.serialize(), completion: .contentProcessed { _ in
            connection.cancel()
        })
    }
}
