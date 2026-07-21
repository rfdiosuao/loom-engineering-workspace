import Foundation
import Photos

enum MediaImporter {
    static func importPayload(_ payload: [String: Any], preferredKind: String) async -> Result<[String: Any], Error> {
        do {
            let kind = (payload["kind"] as? String) ?? preferredKind
            let fileURL = try await materializePayload(payload, kind: kind)
            try await saveToPhotos(fileURL: fileURL, kind: kind)
            return .success([
                "success": true,
                "kind": kind,
                "filename": fileURL.lastPathComponent,
                "savedToPhotos": true
            ])
        } catch {
            return .failure(error)
        }
    }

    private static func materializePayload(_ payload: [String: Any], kind: String) async throws -> URL {
        if let urlText = payload["url"] as? String, let url = URL(string: urlText) {
            let (data, _) = try await URLSession.shared.data(from: url)
            return try writeTemp(data: data, kind: kind, mime: payload["mime"] as? String)
        }

        let base64 = (payload["data"] as? String)
            ?? (payload["base64"] as? String)
            ?? (payload["imageBase64"] as? String)
            ?? (payload["videoBase64"] as? String)
            ?? ""
        let stripped = base64.components(separatedBy: ",").last ?? base64
        guard let data = Data(base64Encoded: stripped) else {
            throw NSError(domain: "iOSClaw.Media", code: 400, userInfo: [NSLocalizedDescriptionKey: "Missing or invalid media payload"])
        }
        return try writeTemp(data: data, kind: kind, mime: payload["mime"] as? String)
    }

    private static func writeTemp(data: Data, kind: String, mime: String?) throws -> URL {
        let ext: String
        if let mime {
            if mime.contains("png") { ext = "png" }
            else if mime.contains("jpeg") || mime.contains("jpg") { ext = "jpg" }
            else if mime.contains("webp") { ext = "webp" }
            else if mime.contains("quicktime") { ext = "mov" }
            else if mime.contains("mp4") { ext = "mp4" }
            else { ext = kind == "video" ? "mp4" : "png" }
        } else {
            ext = kind == "video" ? "mp4" : "png"
        }
        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent("iosclaw-\(UUID().uuidString)")
            .appendingPathExtension(ext)
        try data.write(to: url, options: .atomic)
        return url
    }

    private static func saveToPhotos(fileURL: URL, kind: String) async throws {
        let status = await PHPhotoLibrary.requestAuthorization(for: .addOnly)
        guard status == .authorized || status == .limited else {
            throw NSError(domain: "iOSClaw.Media", code: 403, userInfo: [NSLocalizedDescriptionKey: "Photos add permission denied"])
        }

        try await withCheckedThrowingContinuation { continuation in
            PHPhotoLibrary.shared().performChanges {
                if kind == "video" {
                    PHAssetCreationRequest.forAsset().addResource(with: .video, fileURL: fileURL, options: nil)
                } else {
                    PHAssetCreationRequest.forAsset().addResource(with: .photo, fileURL: fileURL, options: nil)
                }
            } completionHandler: { success, error in
                if let error {
                    continuation.resume(throwing: error)
                } else if success {
                    continuation.resume()
                } else {
                    continuation.resume(throwing: NSError(domain: "iOSClaw.Media", code: 500, userInfo: [NSLocalizedDescriptionKey: "Photos import failed"]))
                }
            }
        }
    }
}
