import Foundation
import Combine

final class PairingStore: ObservableObject {
    static let shared = PairingStore()

    static let appGroupID = "group.com.openclaw.iosclaw"
    static let defaultPort: UInt16 = 9527

    @Published private(set) var token: String
    @Published private(set) var launcherId: String
    @Published private(set) var launcherName: String
    @Published private(set) var launcherSecret: String
    @Published private(set) var pairedAt: Int64

    private let defaults: UserDefaults
    private let tokenKey = "iosclaw.token"
    private let launcherIdKey = "iosclaw.launcherId"
    private let launcherNameKey = "iosclaw.launcherName"
    private let launcherSecretKey = "iosclaw.launcherSecret"
    private let pairedAtKey = "iosclaw.pairedAt"

    private init() {
        defaults = UserDefaults(suiteName: Self.appGroupID) ?? .standard
        let storedToken = defaults.string(forKey: tokenKey)
        if let storedToken, !storedToken.isEmpty {
            token = storedToken
        } else {
            token = Base64URL.random(byteCount: 16)
            defaults.set(token, forKey: tokenKey)
        }
        launcherId = defaults.string(forKey: launcherIdKey) ?? ""
        launcherName = defaults.string(forKey: launcherNameKey) ?? ""
        launcherSecret = defaults.string(forKey: launcherSecretKey) ?? ""
        pairedAt = Int64(defaults.integer(forKey: pairedAtKey))
    }

    var isPaired: Bool {
        !launcherId.isEmpty && !launcherSecret.isEmpty
    }

    func resetToken() {
        token = Base64URL.random(byteCount: 16)
        defaults.set(token, forKey: tokenKey)
    }

    func pair(launcherId requestedId: String, launcherName requestedName: String) -> LumiPairing {
        let id = sanitizeLauncherId(requestedId.isEmpty ? "openclaw-\(Base64URL.random(byteCount: 8))" : requestedId)
        let name = String((requestedName.isEmpty ? "OpenClaw Launcher" : requestedName).prefix(80))
        let secret: String
        let timestamp: Int64

        if id == launcherId && !launcherSecret.isEmpty {
            secret = launcherSecret
            timestamp = pairedAt > 0 ? pairedAt : Int64(Date().timeIntervalSince1970 * 1000)
        } else {
            secret = Base64URL.random(byteCount: 32)
            timestamp = Int64(Date().timeIntervalSince1970 * 1000)
        }

        launcherId = id
        launcherName = name
        launcherSecret = secret
        pairedAt = timestamp

        defaults.set(id, forKey: launcherIdKey)
        defaults.set(name, forKey: launcherNameKey)
        defaults.set(secret, forKey: launcherSecretKey)
        defaults.set(timestamp, forKey: pairedAtKey)

        return LumiPairing(
            paired: true,
            launcherId: id,
            launcherName: name,
            launcherSecret: secret,
            pairedAt: timestamp
        )
    }

    private func sanitizeLauncherId(_ value: String) -> String {
        let allowed = CharacterSet(charactersIn: "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.:-")
        let mapped = value.unicodeScalars.map { allowed.contains($0) ? Character($0) : "-" }
        let text = String(mapped)
            .replacingOccurrences(of: "--+", with: "-", options: .regularExpression)
            .trimmingCharacters(in: CharacterSet(charactersIn: "-._:"))
        return String((text.isEmpty ? "openclaw-\(Base64URL.random(byteCount: 8))" : text).prefix(80))
    }
}

struct LumiPairing: Codable {
    let paired: Bool
    let launcherId: String
    let launcherName: String
    let launcherSecret: String
    let pairedAt: Int64
    let algorithm = "HMAC-SHA256"
    let signatureVersion = 1
    let timestampSkewMs = 120_000
}
