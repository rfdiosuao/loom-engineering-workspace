import Foundation
import CryptoKit

final class LumiSecurity {
    private let store: PairingStore
    private let maxClockSkewMs: Int64 = 120_000
    private let nonceTTL: TimeInterval = 300
    private var nonceCache: [String: Date] = [:]
    private let lock = NSLock()

    init(store: PairingStore = .shared) {
        self.store = store
    }

    func checkToken(_ request: HTTPRequest) -> String? {
        let headerToken = request.header("x-agent-phone-token") ?? request.header("x-apkclaw-token")
        guard headerToken == store.token else {
            return "Invalid or missing iOSClaw token"
        }
        return nil
    }

    func authorize(_ request: HTTPRequest) -> String? {
        guard store.isPaired else {
            return "Lumi launcher is not paired"
        }

        guard
            let launcherId = request.header("x-lumi-launcher-id"), !launcherId.isEmpty,
            let timestampText = request.header("x-lumi-timestamp"), !timestampText.isEmpty,
            let nonce = request.header("x-lumi-nonce"), !nonce.isEmpty,
            let signature = request.header("x-lumi-signature"), !signature.isEmpty,
            let declaredBodyHash = request.header("x-lumi-body-sha256")?.lowercased(), !declaredBodyHash.isEmpty
        else {
            return "Missing Lumi security headers"
        }

        guard launcherId == store.launcherId else {
            return "Unknown Lumi launcher"
        }

        guard let normalizedTimestamp = normalizeTimestamp(timestampText) else {
            return "Invalid Lumi timestamp"
        }
        let now = Int64(Date().timeIntervalSince1970 * 1000)
        guard abs(now - normalizedTimestamp) <= maxClockSkewMs else {
            return "Lumi request timestamp is outside the allowed window"
        }
        guard rememberNonce(launcherId: launcherId, nonce: nonce) else {
            return "Lumi nonce has already been used"
        }

        let bodyHash = Self.sha256Hex(request.body)
        guard declaredBodyHash == bodyHash else {
            return "Lumi body hash mismatch"
        }

        let signatureInput = [
            request.method,
            request.pathWithQuery,
            timestampText,
            nonce,
            bodyHash
        ].joined(separator: "\n")
        let expected = Self.hmacBase64URL(secret: store.launcherSecret, text: signatureInput)
        guard constantTimeEquals(signature, expected) else {
            return "Invalid Lumi signature"
        }
        return nil
    }

    static func sha256Hex(_ data: Data) -> String {
        let digest = SHA256.hash(data: data)
        return digest.map { String(format: "%02x", $0) }.joined()
    }

    static func hmacBase64URL(secret: String, text: String) -> String {
        let key = SymmetricKey(data: Data(secret.utf8))
        let code = HMAC<SHA256>.authenticationCode(for: Data(text.utf8), using: key)
        return Base64URL.encode(Data(code))
    }

    private func normalizeTimestamp(_ value: String) -> Int64? {
        guard let raw = Int64(value), raw > 0 else { return nil }
        return raw < 10_000_000_000 ? raw * 1000 : raw
    }

    private func rememberNonce(launcherId: String, nonce: String) -> Bool {
        let key = "\(launcherId):\(nonce)"
        let now = Date()
        lock.lock()
        defer { lock.unlock() }
        nonceCache = nonceCache.filter { $0.value > now }
        if nonceCache[key] != nil { return false }
        nonceCache[key] = now.addingTimeInterval(nonceTTL)
        return true
    }

    private func constantTimeEquals(_ left: String, _ right: String) -> Bool {
        let a = Array(left.utf8)
        let b = Array(right.utf8)
        var diff = a.count ^ b.count
        for index in 0..<max(a.count, b.count) {
            let l = index < a.count ? Int(a[index]) : 0
            let r = index < b.count ? Int(b[index]) : 0
            diff |= l ^ r
        }
        return diff == 0
    }
}
