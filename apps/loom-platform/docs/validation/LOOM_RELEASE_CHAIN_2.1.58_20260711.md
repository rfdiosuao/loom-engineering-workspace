# LOOM 2.1.58 Release Chain Validation

Date: 2026-07-11

Branch: `codex/customer-acquisition-v1`

## Outcome

The application and installer delivery chain is ready for a signed production
build. The locally generated candidate is deliberately not promoted as a stable
release because this machine does not contain a trusted Authenticode certificate.

## Candidate

- Recommended installer: `LOOM-2.1.58-setup.exe`
- Candidate directory: `artifacts/nsis-release-2.1.58-offline-complete-candidate-r2`
- Size: `382266938` bytes
- SHA256: `6332e50aaa972b63b42cdee7b5df69c62e7c7dff88710c7767cf1070c21ae076`
- Authenticode status: `NotSigned`
- Contents: LOOM desktop app, packaged Python/FastAPI Bridge, WebView2 offline installer, and verified Codex seed

The recommended installer is byte-identical to
`LOOM-2.1.58-complete-setup.exe`. The `online` diagnostic variant is not a
customer-facing recommendation.

## Verification Evidence

- `npm run build`: passed.
- Python launcher suite: `574` tests passed.
- `cargo check`: passed for app `2.1.58`.
- Release workflow YAML parsing: passed, `22` steps.
- Source text guard: `280` files checked, passed.
- Source secret scan: `429` files checked, zero findings.
- Version consistency: `2.1.58`, passed.
- Workspace hygiene: passed.
- Signed component catalog verification: passed, `5` components.
- License server suite: `40` tests passed.
- Admin console contract: passed.

## Exact Installer Smoke

The exact `r2` recommended installer was installed, started, checked, and
uninstalled in both paths:

- ASCII: `artifacts/nsis-smoke-2.1.58-r2/ascii/LOOM`
- Chinese: `artifacts/nsis-smoke-2.1.58-r2/中文用户/麓鸣`

Both cases passed:

- Packaged Python runtime selected.
- FastAPI Bridge started successfully.
- Public license endpoint returned `200`.
- Unlicensed matrix endpoint returned `403`.
- Unlicensed acquisition endpoint returned `403`.
- Test install directories were removed.
- Existing LOOM uninstall registration and shortcuts were restored.

## Update Channel

The desktop updater now checks stable Gitee and GitHub releases, rejects drafts
and prereleases, compares all valid sources, and selects the highest semantic
version. It accepts only an exact `LOOM-X.Y.Z-setup.exe` asset with a verifiable
SHA256 digest or sidecar.

GitHub's current stable/latest release was corrected to
`v2.1.57-complete-setup-r1`, containing `LOOM-2.1.57-setup.exe` with SHA256
`f8066cca3d7a21da5f52332dfe1c4ce9f896fc519b0ec1935ae56ecf83c0af74`.

## Production Blocks

1. Import a trusted OV or EV Authenticode PFX and configure GitHub secrets
   `WINDOWS_PFX_BASE64` and `WINDOWS_PFX_PASSWORD`.
2. Replace the local Gitee API token with one that can create releases and
   upload assets. The configured token can read the repository but Gitee rejects
   release creation.
3. Run the release workflow from the intended `v2.1.58` tag. The workflow will
   fail closed if signing is unavailable or either ASCII/Chinese smoke case fails.

Do not publish the unsigned local candidate as the commercial stable installer.
