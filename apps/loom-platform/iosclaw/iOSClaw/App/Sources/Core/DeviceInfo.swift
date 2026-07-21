import Foundation
import UIKit
import Darwin

enum DeviceInfo {
    static func current(baseURL: String?) -> [String: Any] {
        UIDevice.current.isBatteryMonitoringEnabled = true
        return [
            "id": UIDevice.current.identifierForVendor?.uuidString ?? "iosclaw-device",
            "name": UIDevice.current.name,
            "platform": "ios",
            "model": UIDevice.current.model,
            "systemName": UIDevice.current.systemName,
            "systemVersion": UIDevice.current.systemVersion,
            "app": "iOSClaw",
            "appVersion": Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "0.1.0",
            "baseUrl": baseURL ?? "",
            "ipAddresses": localIPv4Addresses(),
            "battery": batteryPayload(),
            "capabilities": [
                "device.status",
                "device.profile",
                "lumi.security.pair",
                "lumi.security.signedRequests",
                "media.importImage",
                "media.importVideo",
                "replaykit.screenFrame"
            ],
            "limitations": [
                "noGlobalTapWithoutWebDriverAgent",
                "noSilentBackgroundScreenCapture",
                "requiresUserStartedReplayKitBroadcast"
            ]
        ]
    }

    static func localIPv4Addresses() -> [String] {
        var results: [String] = []
        var interfaces: UnsafeMutablePointer<ifaddrs>?
        guard getifaddrs(&interfaces) == 0 else { return results }
        defer { freeifaddrs(interfaces) }

        var pointer = interfaces
        while pointer != nil {
            guard let interface = pointer?.pointee else { break }
            pointer = interface.ifa_next

            let flags = Int32(interface.ifa_flags)
            guard (flags & IFF_UP) == IFF_UP, (flags & IFF_LOOPBACK) == 0 else { continue }
            guard let address = interface.ifa_addr, address.pointee.sa_family == UInt8(AF_INET) else { continue }

            var addr = address.withMemoryRebound(to: sockaddr_in.self, capacity: 1) { $0.pointee.sin_addr }
            var buffer = [CChar](repeating: 0, count: Int(INET_ADDRSTRLEN))
            if inet_ntop(AF_INET, &addr, &buffer, socklen_t(INET_ADDRSTRLEN)) != nil {
                let value = String(cString: buffer)
                if value.hasPrefix("10.") || value.hasPrefix("172.") || value.hasPrefix("192.168.") {
                    results.append(value)
                }
            }
        }
        return Array(Set(results)).sorted()
    }

    private static func batteryPayload() -> [String: Any] {
        let state: String
        switch UIDevice.current.batteryState {
        case .charging: state = "charging"
        case .full: state = "full"
        case .unplugged: state = "unplugged"
        default: state = "unknown"
        }
        let level = UIDevice.current.batteryLevel
        return [
            "level": level >= 0 ? Int(level * 100) : NSNull(),
            "state": state
        ]
    }
}
