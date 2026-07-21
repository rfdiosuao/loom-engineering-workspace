# LOOM Installer Handoff 2026-07-03

## Current User Expectation

The expected installer is the older "thin setup" experience:

- A normal-looking LOOM installer users can download and run directly.
- Around 6 MB, not a 160 KB bare NSIS downloader shell.
- Uses LOOM/麓鸣 visual assets.
- Does not bundle Codex, Claude Code, opencode, OpenClaw, Hermes, or APKClaw.
- The setup downloads the LOOM online package, verifies SHA256, extracts it, creates shortcuts, and writes uninstall metadata.

## Evidence From Existing rc6

Reference URL:

`https://gitee.com/rfdiosuao/lumi/releases/download/v2.1.44-20260703-rc6/LOOM-Setup-v2.1.44-20260703-rc6-gitee-thin.exe`

Verified on 2026-07-03:

- HTTP HEAD status: `200`
- Content-Length: `6240924`
- Content-Type: `application/vnd.microsoft.portable-executable`

Local file:

`D:\Axiangmu\AUSTART\release\LOOM-Setup-v2.1.44-20260703-rc6-gitee-thin.exe`

- Size: `6240924`
- SHA256: `AC0D781F00767E3ECD7EE50823B97508A1EADBDCBE555FE144CA79B2054E8A6D`

## Important Difference

Two installer lanes currently exist:

1. `scripts\build-nsis-online-installer.ps1`
   - Produces a very small NSIS setup, about 160 KB.
   - This is a standard NSIS downloader shell.
   - It only works for users when the remote online zip URL is already live.

2. `scripts\build-online-exe-installer.ps1`
   - Produces the older branded thin setup style, around 6 MB.
   - It compiles a C# WinForms installer with embedded LOOM visual assets.
   - This is the lane that matches the user's remembered rc6 installer.

The last generated `rc9-nsis-gitee.exe` used lane 1. That is why it does not match the rc6 experience.

## Latest Built rc9 Artifacts

Online package:

`D:\Axiangmu\AUSTART\release\LOOM-Online-v2.1.44-20260703-rc9.zip`

- SHA256: `FB984273783FB7E8747C0A1AA36C60E7903E90234CECA5FA7B2E1E380F330905`
- Verification: `scripts\verify-release.ps1 -Online` passed.
- Forbidden Agent payload scan: `ForbiddenPayloadCount=0`

NSIS setup:

`D:\Axiangmu\AUSTART\release\LOOM-Setup-v2.1.44-20260703-rc9-nsis-gitee.exe`

- SHA256: `C168C82CD10DA33AFB05319A70A4D00CE4594255790E553BEB2C7C423E189896`
- Local smoke install/uninstall passed.
- Not the user's preferred visual/size style.

## Current Blocker

The rc9 online zip public Gitee URL is not live yet:

`https://gitee.com/rfdiosuao/lumi/releases/download/v2.1.44-20260703-rc9/LOOM-Online-v2.1.44-20260703-rc9.zip`

Observed status: `404`

Without the online zip uploaded, any online setup that points to this URL will fail for real users.

## Correct Next Build

Use the rc6-style builder:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\build-online-exe-installer.ps1 `
  -PackageUrl "https://gitee.com/rfdiosuao/lumi/releases/download/v2.1.44-20260703-rc9/LOOM-Online-v2.1.44-20260703-rc9.zip" `
  -PackageSha256 "FB984273783FB7E8747C0A1AA36C60E7903E90234CECA5FA7B2E1E380F330905" `
  -PackageRootName "LOOM-Online-v2.1.44-20260703-rc9" `
  -Version "2.1.44-20260703-rc9" `
  -OutputPath "D:\Axiangmu\AUSTART\release\LOOM-Setup-v2.1.44-20260703-rc9-gitee-thin.exe"
```

Then verify:

```powershell
Get-FileHash -Algorithm SHA256 release\LOOM-Setup-v2.1.44-20260703-rc9-gitee-thin.exe
```

Smoke test with localhost if the public zip is not live:

1. Start local server:

```powershell
python -m http.server 18765 --bind 127.0.0.1 -d release
```

2. Build a smoke setup using:

`http://127.0.0.1:18765/LOOM-Online-v2.1.44-20260703-rc9.zip`

3. Install into:

`D:\Axiangmu\AUSTART\artifacts\thin-smoke\LOOM`

4. Confirm:

- `LOOM.exe` exists.
- Uninstaller exists.
- Uninstall removes the disposable directory.

## Upload Order

1. Upload `LOOM-Online-v2.1.44-20260703-rc9.zip`.
2. Verify public URL returns `200`.
3. Upload `LOOM-Setup-v2.1.44-20260703-rc9-gitee-thin.exe`.
4. Update NewAPI homepage install button to the setup exe URL.
5. Test the button from a clean browser.

## Do Not Do

- Do not call the 160 KB NSIS downloader the final expected installer unless the user explicitly accepts it.
- Do not bundle third-party Agent binaries.
- Do not point setup to a 404 zip.
- Do not claim Gitee upload succeeded without a verified public URL.
