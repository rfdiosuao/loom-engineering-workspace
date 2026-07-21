# iOSClaw

iOSClaw is the iOS companion/agent counterpart to APKClaw. It is intentionally not a direct Android port: iOS does not expose Android-style Accessibility control for arbitrary apps. The first milestone is a safe iOS Lite agent that keeps the OpenClaw launcher contract stable.

## What this source contains

- SwiftUI iOS app shell with an AppIcon asset catalog.
- Local HTTP bridge on port `9527` using `Network.framework`.
- Token pairing endpoint compatible with the launcher's APKClaw flow.
- Lumi signed request verification using HMAC-SHA256.
- Device status/profile endpoints.
- Media import endpoints for images/videos into Photos.
- ReplayKit Broadcast Upload Extension scaffold for screen-frame sharing.
- Migration plan, API contract, and installation notes under `docs/`.

## Generate the Xcode project

This repo uses XcodeGen so the project file can be regenerated cleanly on macOS.

```bash
brew install xcodegen
cd iosclaw
xcodegen generate
open iOSClaw.xcodeproj
```

Before installing on a real iPhone, update the bundle identifiers, Team ID, and App Group in `project.yml`, `iOSClaw/App/iOSClaw.entitlements`, and `iOSClaw/BroadcastExtension/iOSClawBroadcast.entitlements`.

## Build targets

- `iOSClaw`: main SwiftUI app.
- `iOSClawBroadcastExtension`: ReplayKit broadcast extension.

## Expected first install path

Use Xcode direct install for development, then TestFlight for a small beta. Ad Hoc/MDM can be added later once device management requirements are clear.
