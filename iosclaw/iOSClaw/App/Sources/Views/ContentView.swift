import SwiftUI
import ReplayKit
import UIKit

struct ContentView: View {
    @StateObject private var server = LocalHTTPServer()
    @ObservedObject private var store = PairingStore.shared
    @State private var showResetTokenAlert = false

    var body: some View {
        NavigationStack {
            ZStack {
                LinearGradient(
                    colors: [Color(red: 0.04, green: 0.07, blue: 0.14), Color(red: 0.08, green: 0.16, blue: 0.28)],
                    startPoint: .topLeading,
                    endPoint: .bottomTrailing
                )
                .ignoresSafeArea()

                ScrollView {
                    VStack(alignment: .leading, spacing: 18) {
                        header
                        StatusCard(title: "Local Bridge", value: server.isRunning ? "Running" : "Stopped", detail: server.baseURL ?? "Start the server after joining the same LAN as your Mac/PC.", tone: server.isRunning ? .ok : .warn)
                        StatusCard(title: "Launcher Pairing", value: store.isPaired ? "Paired" : "Waiting", detail: store.isPaired ? "\(store.launcherName) / \(store.launcherId)" : "Scan or enter this device in the OpenClaw launcher.", tone: store.isPaired ? .ok : .neutral)

                        qrPanel
                        controls
                        replayKitPanel
                        capabilities

                        if let error = server.lastError {
                            Text(error)
                                .font(.footnote.weight(.semibold))
                                .foregroundStyle(.red)
                                .padding(.top, 4)
                        }
                    }
                    .padding(20)
                }
            }
            .navigationTitle("iOSClaw")
            .navigationBarTitleDisplayMode(.inline)
            .onAppear {
                if !server.isRunning {
                    server.start()
                }
            }
            .alert("Reset token?", isPresented: $showResetTokenAlert) {
                Button("Cancel", role: .cancel) {}
                Button("Reset", role: .destructive) {
                    store.resetToken()
                }
            } message: {
                Text("The launcher will need to pair again after the token changes.")
            }
        }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 8) {
            Image("AppIconPreview")
                .resizable()
                .frame(width: 56, height: 56)
                .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
                .shadow(color: .cyan.opacity(0.28), radius: 18, x: 0, y: 10)
                .accessibilityHidden(true)
            Text("iOSClaw")
                .font(.system(size: 34, weight: .bold, design: .rounded))
                .foregroundStyle(.white)
            Text("iOS bridge for OpenClaw. Pair, share screen frames with ReplayKit, and receive launcher-generated media.")
                .font(.callout)
                .foregroundStyle(.white.opacity(0.74))
        }
    }

    private var qrPanel: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Pairing Payload")
                .font(.headline)
                .foregroundStyle(.white)
            HStack(alignment: .top, spacing: 16) {
                QRCodeView(text: pairingPayload)
                    .frame(width: 176, height: 176)
                    .background(.white)
                    .clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
                VStack(alignment: .leading, spacing: 8) {
                    Label(server.baseURL ?? "No local URL", systemImage: "network")
                    Label(mask(store.token), systemImage: "key.fill")
                    Label(DeviceInfo.localIPv4Addresses().joined(separator: ", ").isEmpty ? "No LAN IP detected" : DeviceInfo.localIPv4Addresses().joined(separator: ", "), systemImage: "iphone.radiowaves.left.and.right")
                }
                .font(.footnote.monospaced())
                .foregroundStyle(.white.opacity(0.82))
            }
        }
        .panelStyle()
    }

    private var controls: some View {
        HStack(spacing: 12) {
            Button {
                server.start()
            } label: {
                Label("Start", systemImage: "play.fill")
            }
            .buttonStyle(.borderedProminent)

            Button {
                server.stop()
            } label: {
                Label("Stop", systemImage: "stop.fill")
            }
            .buttonStyle(.bordered)
            .tint(.red)

            Button {
                showResetTokenAlert = true
            } label: {
                Label("Reset Token", systemImage: "arrow.triangle.2.circlepath")
            }
            .buttonStyle(.bordered)
        }
    }

    private var replayKitPanel: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("Screen Broadcast")
                .font(.headline)
                .foregroundStyle(.white)
            Text("iOS requires the user to start screen sharing. The broadcast extension writes the latest frame into the shared app group for /api/lumi/vision/frame.")
                .font(.footnote)
                .foregroundStyle(.white.opacity(0.72))
            BroadcastPickerView(preferredExtension: "com.openclaw.iosclaw.broadcast")
                .frame(width: 54, height: 54)
                .background(Color.white.opacity(0.12))
                .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
        }
        .panelStyle()
    }

    private var capabilities: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("Supported Now")
                .font(.headline)
                .foregroundStyle(.white)
            capability("Scan/pair launcher", "Token + HMAC Lumi secure channel")
            capability("Device status/profile", "/api/device/status and /api/lumi/device/profile")
            capability("Media import", "Save generated images/videos to Photos")
            capability("Screen frames", "ReplayKit after user starts broadcast")
            Divider().overlay(.white.opacity(0.16))
            Text("Arbitrary app tap/swipe/input is reserved for WebDriverAgent mode.")
                .font(.footnote.weight(.semibold))
                .foregroundStyle(.orange)
        }
        .panelStyle()
    }

    private func capability(_ title: String, _ detail: String) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(title).font(.subheadline.weight(.semibold)).foregroundStyle(.white)
            Text(detail).font(.caption).foregroundStyle(.white.opacity(0.68))
        }
    }

    private var pairingPayload: String {
        let payload: [String: Any] = [
            "type": "iosclaw",
            "name": UIDevice.current.name,
            "baseUrl": server.baseURL ?? "",
            "token": store.token,
            "port": PairingStore.defaultPort,
            "capabilities": ["device.status", "lumi.security", "media.import", "replaykit.frame"]
        ]
        let data = try? JSONSerialization.data(withJSONObject: payload, options: [.sortedKeys])
        return data.flatMap { String(data: $0, encoding: .utf8) } ?? "{}"
    }

    private func mask(_ token: String) -> String {
        guard token.count > 4 else { return "****" }
        return String(repeating: "*", count: max(4, token.count - 4)) + token.suffix(4)
    }
}

private extension View {
    func panelStyle() -> some View {
        self
            .padding(16)
            .background(Color.white.opacity(0.09))
            .overlay(
                RoundedRectangle(cornerRadius: 18, style: .continuous)
                    .stroke(Color.white.opacity(0.14), lineWidth: 1)
            )
            .clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))
    }
}
