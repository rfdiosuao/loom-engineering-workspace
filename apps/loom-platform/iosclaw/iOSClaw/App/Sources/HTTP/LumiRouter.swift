import Foundation

final class LumiRouter {
    private let store = PairingStore.shared
    private let security = LumiSecurity()
    private let taskStore = AgentTaskStore()
    private let baseURLProvider: () -> String?

    init(baseURLProvider: @escaping () -> String?) {
        self.baseURLProvider = baseURLProvider
    }

    func route(_ request: HTTPRequest) async -> HTTPResponse {
        if request.method == "OPTIONS" {
            return .options()
        }
        if request.path == "/" || request.path == "/index.html" {
            return .html(indexHTML())
        }

        switch (request.method, request.path) {
        case ("GET", "/api/device/status"), ("GET", "/api/agent/status"):
            if let error = security.checkToken(request) { return .error(error, statusCode: 403, reason: "Forbidden") }
            return deviceStatus()

        case ("POST", "/api/device/wake"):
            if let error = security.checkToken(request) { return .error(error, statusCode: 403, reason: "Forbidden") }
            return .json(["success": true, "data": ["awake": true, "platform": "ios"]])

        case ("POST", "/api/lumi/security/pair"):
            if let error = security.checkToken(request) { return .error(error, statusCode: 403, reason: "Forbidden") }
            let json = request.jsonBody
            let pairing = store.pair(
                launcherId: (json["launcherId"] as? String) ?? (json["launcher_id"] as? String) ?? "",
                launcherName: (json["launcherName"] as? String) ?? (json["launcher_name"] as? String) ?? ""
            )
            return .json(["success": true, "data": codableToDictionary(pairing)])

        case ("GET", "/api/lumi/security/status"):
            if let error = security.checkToken(request) { return .error(error, statusCode: 403, reason: "Forbidden") }
            return .json(["success": true, "data": securityStatus()])

        default:
            break
        }

        if request.path.hasPrefix("/api/lumi/") {
            if let error = security.authorize(request) {
                return .error(error, statusCode: 403, reason: "Forbidden")
            }
            return await routeSignedLumi(request)
        }

        if request.path == "/api/tool/list" && request.method == "GET" {
            if let error = security.checkToken(request) { return .error(error, statusCode: 403, reason: "Forbidden") }
            return .json(["success": true, "data": toolList()])
        }

        if request.path.hasPrefix("/api/tool/") {
            if let error = security.checkToken(request) { return .error(error, statusCode: 403, reason: "Forbidden") }
            return .error("iOS global tool control requires the future WebDriverAgent mode.", statusCode: 501, reason: "Not Implemented")
        }

        return .error("not found", statusCode: 404, reason: "Not Found")
    }

    private func routeSignedLumi(_ request: HTTPRequest) async -> HTTPResponse {
        switch (request.method, request.path) {
        case ("GET", "/api/lumi/device/profile"):
            return .json(["success": true, "data": DeviceInfo.current(baseURL: baseURLProvider())])

        case ("GET", "/api/lumi/vision/status"):
            return .json(["success": true, "data": visionStatus()])

        case ("GET", "/api/lumi/vision/frame"):
            return visionFrame()

        case ("POST", "/api/lumi/media/import_image"):
            return await mediaImport(request, kind: "image")

        case ("POST", "/api/lumi/media/import_video"):
            return await mediaImport(request, kind: "video")

        case ("POST", "/api/lumi/agent/tasks"):
            let prompt = (request.jsonBody["prompt"] as? String)
                ?? (request.jsonBody["task"] as? String)
                ?? (request.jsonBody["instruction"] as? String)
                ?? ""
            let task = taskStore.create(prompt: prompt)
            return .json(["success": true, "data": codableToDictionary(task)])

        default:
            if request.path.hasPrefix("/api/lumi/agent/tasks/") {
                return routeTaskPath(request)
            }
            return .error("Unsupported iOSClaw Lite endpoint", statusCode: 501, reason: "Not Implemented")
        }
    }

    private func routeTaskPath(_ request: HTTPRequest) -> HTTPResponse {
        let raw = request.path.replacingOccurrences(of: "/api/lumi/agent/tasks/", with: "")
        if raw.hasSuffix("/cancel"), request.method == "POST" {
            let id = raw.replacingOccurrences(of: "/cancel", with: "")
            guard let task = taskStore.cancel(id) else { return .error("task not found", statusCode: 404, reason: "Not Found") }
            return .json(["success": true, "data": codableToDictionary(task)])
        }
        if raw.hasSuffix("/events"), request.method == "GET" {
            let id = raw.replacingOccurrences(of: "/events", with: "")
            guard let task = taskStore.get(id) else { return .error("task not found", statusCode: 404, reason: "Not Found") }
            return .json(["success": true, "data": ["taskId": task.taskId, "events": task.events]])
        }
        guard request.method == "GET" else {
            return .error("unsupported task method", statusCode: 405, reason: "Method Not Allowed")
        }
        guard let task = taskStore.get(raw) else { return .error("task not found", statusCode: 404, reason: "Not Found") }
        return .json(["success": true, "data": codableToDictionary(task)])
    }

    private func deviceStatus() -> HTTPResponse {
        let profile = DeviceInfo.current(baseURL: baseURLProvider())
        return .json([
            "success": true,
            "data": profile,
            "configured": true,
            "connected": true,
            "tokenAvailable": true,
            "platform": "ios",
            "mode": "iosclaw-lite"
        ])
    }

    private func securityStatus() -> [String: Any] {
        [
            "paired": store.isPaired,
            "launcherId": store.launcherId,
            "launcherName": store.launcherName,
            "pairedAt": store.pairedAt,
            "algorithm": "HMAC-SHA256",
            "signatureVersion": 1,
            "launcherOnlyNamespace": "/api/lumi"
        ]
    }

    private func visionStatus() -> [String: Any] {
        let frameURL = appGroupURL()?.appendingPathComponent("latest-frame.jpg")
        return [
            "available": true,
            "source": "replaykit-broadcast-extension",
            "broadcasting": frameURL.map { FileManager.default.fileExists(atPath: $0.path) } ?? false,
            "requiresUserAction": true,
            "message": "Start the iOSClaw Screen broadcast from the app or Control Center."
        ]
    }

    private func visionFrame() -> HTTPResponse {
        guard
            let url = appGroupURL()?.appendingPathComponent("latest-frame.jpg"),
            let data = try? Data(contentsOf: url)
        else {
            return .error("replaykit_frame_unavailable", statusCode: 404, reason: "Not Found")
        }
        return .json([
            "success": true,
            "data": [
                "mime": "image/jpeg",
                "base64": data.base64EncodedString(),
                "source": "replaykit-broadcast-extension"
            ]
        ])
    }

    private func mediaImport(_ request: HTTPRequest, kind: String) async -> HTTPResponse {
        switch await MediaImporter.importPayload(request.jsonBody, preferredKind: kind) {
        case .success(let payload):
            return .json(["success": true, "data": payload])
        case .failure(let error):
            return .error(error.localizedDescription, statusCode: 400, reason: "Bad Request")
        }
    }

    private func toolList() -> [[String: Any]] {
        [
            [
                "name": "iosclaw_status",
                "displayName": "iOSClaw Status",
                "description": "Read iOSClaw device status."
            ],
            [
                "name": "iosclaw_import_media",
                "displayName": "Import Media",
                "description": "Save launcher generated image/video to Photos."
            ],
            [
                "name": "iosclaw_replaykit_frame",
                "displayName": "ReplayKit Frame",
                "description": "Read the latest frame after the user starts screen broadcast."
            ]
        ]
    }

    private func appGroupURL() -> URL? {
        FileManager.default.containerURL(forSecurityApplicationGroupIdentifier: PairingStore.appGroupID)
    }

    private func indexHTML() -> String {
        """
        <!doctype html>
        <html>
        <head><meta charset="utf-8"><title>iOSClaw</title></head>
        <body style="font-family:-apple-system,BlinkMacSystemFont,sans-serif;background:#0b1220;color:#eef6ff;padding:24px">
        <h1>iOSClaw</h1>
        <p>Local bridge is running. Pair through the OpenClaw launcher using the token shown in the app.</p>
        <pre>GET /api/device/status</pre>
        </body>
        </html>
        """
    }
}
