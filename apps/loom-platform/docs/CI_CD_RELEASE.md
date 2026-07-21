# CI/CD Release Guide

GitHub Actions is the authoritative build and release path. Gitee Releases is a
domestic mirror and must receive the same recommended installer and SHA256
sidecar after GitHub validation succeeds.

## Authoritative Versions

The LOOM desktop version must match in:

- `openclaw_new_launcher/package.json`
- `openclaw_new_launcher/package-lock.json`
- `openclaw_new_launcher/src-tauri/Cargo.toml`
- `openclaw_new_launcher/src-tauri/Cargo.lock`
- `openclaw_new_launcher/src-tauri/tauri.conf.json`

`release-manifest.json` is a signed component catalog for Codex, Claude Code,
opencode, OpenClaw, and Hermes. Its catalog version is intentionally independent
from the LOOM desktop version. Do not use it to decide whether the desktop app
has an update.

## Required Release Secrets

Stable Windows publishing is blocked unless both GitHub Actions secrets exist:

- `WINDOWS_PFX_BASE64`: base64 encoding of a trusted OV or EV Authenticode PFX.
- `WINDOWS_PFX_PASSWORD`: the PFX import password.

The workflow imports the certificate into the ephemeral runner, signs the NSIS
outputs with SHA256 plus a timestamp, and rejects any installer whose signature
is not `Valid`. Never commit a PFX, password, token, or private signing key.

## Release Workflow

`.github/workflows/release.yml` runs for tags matching `v*` or a manual dispatch.
It performs these release gates:

1. Source text, secret scan, version consistency, frontend build, and Rust check.
2. Verified Codex seed download using the signed component catalog size and SHA256.
3. Dual NSIS build using `scripts/build-dual-nsis.ps1`.
4. Authenticode validation of the built installers.
5. Exact recommended-installer smoke tests in ASCII and Chinese install paths.
6. Packaged Python/FastAPI Bridge, authorization boundary, secret, and cleanup checks.
7. Publication of only `LOOM-X.Y.Z-setup.exe` and its SHA256 sidecar as the desktop installer.

The recommended installer is the complete variant. It embeds the Codex seed and
the WebView2 offline installer. The `online` and `complete` diagnostic variants
may be retained as CI artifacts, but must not compete with the single recommended
release filename.

## Local Candidate Build

Local unsigned builds are suitable for engineering validation only:

```powershell
cd D:\Axiangmu\AUSTART
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\build-dual-nsis.ps1 `
  -CodexPackagePath D:\path\to\codex-X.Y.Z-win32-x64.tgz `
  -OutputRoot D:\Axiangmu\AUSTART\artifacts\nsis-candidate
```

For a production build, import the trusted certificate and require validation:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\build-dual-nsis.ps1 `
  -CodexPackagePath D:\path\to\codex-X.Y.Z-win32-x64.tgz `
  -OutputRoot D:\Axiangmu\AUSTART\artifacts\nsis-signed `
  -CertificateThumbprint YOUR_CERTIFICATE_THUMBPRINT `
  -RequireCodeSignature
```

## Update Resolution

The desktop updater checks the configured Gitee and GitHub stable release APIs,
rejects drafts and prereleases, and chooses the highest valid semantic version.
Only an exact `LOOM-X.Y.Z-setup.exe` asset is accepted. The installer must have a
GitHub asset SHA256 digest or a matching `.sha256.txt` sidecar before it can run.

## Gitee Mirror

Store a Gitee release-write token through the local DPAPI helper:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\set-gitee-token.ps1
```

Then use `scripts/publish-gitee-release.ps1` to upload the exact recommended
installer and SHA256 sidecar. A token that can read the repository but cannot
create a release is not sufficient.
