import ReplayKit
import CoreImage
import CoreMedia
import Foundation

final class SampleHandler: RPBroadcastSampleHandler {
    private let context = CIContext()
    private var lastFrameAt = Date.distantPast
    private let minFrameInterval: TimeInterval = 0.75

    override func broadcastStarted(withSetupInfo setupInfo: [String : NSObject]?) {
        writeStatus(["broadcasting": true, "startedAt": timestamp()])
    }

    override func broadcastPaused() {
        writeStatus(["broadcasting": false, "pausedAt": timestamp()])
    }

    override func broadcastResumed() {
        writeStatus(["broadcasting": true, "resumedAt": timestamp()])
    }

    override func broadcastFinished() {
        writeStatus(["broadcasting": false, "finishedAt": timestamp()])
    }

    override func processSampleBuffer(_ sampleBuffer: CMSampleBuffer, with sampleBufferType: RPSampleBufferType) {
        guard sampleBufferType == .video else { return }
        let now = Date()
        guard now.timeIntervalSince(lastFrameAt) >= minFrameInterval else { return }
        guard let pixelBuffer = CMSampleBufferGetImageBuffer(sampleBuffer) else { return }
        lastFrameAt = now

        let image = CIImage(cvPixelBuffer: pixelBuffer)
        let colorSpace = CGColorSpace(name: CGColorSpace.sRGB) ?? CGColorSpaceCreateDeviceRGB()
        guard let jpeg = context.jpegRepresentation(of: image, colorSpace: colorSpace, options: [:]) else {
            return
        }
        guard let container = FileManager.default.containerURL(forSecurityApplicationGroupIdentifier: "group.com.openclaw.iosclaw") else {
            return
        }
        let frameURL = container.appendingPathComponent("latest-frame.jpg")
        let metadataURL = container.appendingPathComponent("latest-frame.json")
        try? jpeg.write(to: frameURL, options: .atomic)
        let metadata: [String: Any] = [
            "updatedAt": timestamp(),
            "width": CVPixelBufferGetWidth(pixelBuffer),
            "height": CVPixelBufferGetHeight(pixelBuffer),
            "mime": "image/jpeg"
        ]
        if let data = try? JSONSerialization.data(withJSONObject: metadata, options: [.prettyPrinted, .sortedKeys]) {
            try? data.write(to: metadataURL, options: .atomic)
        }
    }

    private func writeStatus(_ payload: [String: Any]) {
        guard let container = FileManager.default.containerURL(forSecurityApplicationGroupIdentifier: "group.com.openclaw.iosclaw") else {
            return
        }
        let url = container.appendingPathComponent("broadcast-status.json")
        if let data = try? JSONSerialization.data(withJSONObject: payload, options: [.prettyPrinted, .sortedKeys]) {
            try? data.write(to: url, options: .atomic)
        }
    }

    private func timestamp() -> Int64 {
        Int64(Date().timeIntervalSince1970 * 1000)
    }
}
