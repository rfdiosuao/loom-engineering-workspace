# Build a "thin" portable package: the proven portable layout (OpenClaw.exe +
# OpenClawFiles/) MINUS the four heavy runtime layers, which the Rust bootstrap
# downloads + sha256-verifies into OpenClawFiles/ on first run. Result is <100MB
# and — unlike the NSIS installer — keeps the portable layout that all runtime
# path-resolution already expects, so it actually runs.
#
# The OpenClaw.exe you pass in MUST be built by `tauri build` with the manifest
# URL baked in. Do not pass a plain `cargo build --release` app.exe: that binary
# can still select the devUrl path and show "localhost refused" in production.
#   cd src-tauri
#   $env:OPENCLAW_DIST_MANIFEST_URL = "https://.../manifest.json"
#   cd ..
#   npm run tauri -- build       # -> src-tauri/target/release/app.exe
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts/dist/build-thin-portable.ps1 `
#     -Source "release\OpenClaw-Portable-v2.0.6-...." `
#     -Exe    "src-tauri\target\release\app.exe" `
#     -Out    "release\OpenClaw-Online-v2.0.6.zip"

param(
    [Parameter(Mandatory = $true)][string]$Source,
    [string]$Exe = "",
    [string]$Out = "",
    # Live python bridge source to sync into the package, so the bundled bridge
    # isn't frozen at whatever snapshot the source portable was built from.
    [string]$PythonSource = "",
    [string[]]$RemoveLayers = @(
        "OpenClawFiles\node",
        "OpenClawFiles\node_modules",
        "OpenClawFiles\_up_\python-runtime",
        "OpenClawFiles\agents\luminode-desktop",
        # APKClaw is distributed via QR link now — don't ship the ~100MB APK in the package.
        "OpenClawFiles\releases\agent-phone"
    )
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath (Join-Path $Source "OpenClaw.exe"))) {
    throw "Source missing OpenClaw.exe: $Source"
}
if (-not (Test-Path -LiteralPath (Join-Path $Source "OpenClawFiles"))) {
    throw "Source missing OpenClawFiles: $Source"
}

$stage = Join-Path $env:TEMP ("openclaw-thin-" + [System.IO.Path]::GetRandomFileName())
New-Item -ItemType Directory -Force -Path $stage | Out-Null
try {
    # robocopy mirrors the tree but skips the heavy layer dirs (by full path, so
    # we never copy the ~1GB we're about to drop).
    $excludeDirs = $RemoveLayers | ForEach-Object { Join-Path $Source $_ }
    Write-Host "Copying (excluding heavy layers) -> $stage"
    & robocopy $Source $stage /E /XD @excludeDirs /NFL /NDL /NJH /NJS /NP | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "robocopy failed with code $LASTEXITCODE" }
    $global:LASTEXITCODE = 0

    foreach ($rel in $RemoveLayers) {
        $p = Join-Path $stage $rel
        if (Test-Path -LiteralPath $p) { Remove-Item -LiteralPath $p -Recurse -Force }
    }

    # Drop per-user state files so the installer's `File /r` never clobbers a
    # user's saved settings on update. Missing = the app reads default {} and
    # recreates on first save; member users also fall back to the license gateway.
    $userState = @(
        "OpenClawFiles\imgapi_config.json",
        "OpenClawFiles\video_config.json"
    )
    foreach ($rel in $userState) {
        $p = Join-Path $stage $rel
        if (Test-Path -LiteralPath $p) { Remove-Item -LiteralPath $p -Force }
    }

    # Refresh the bundled bridge with the live python SOURCE only. CRITICAL: use
    # /E (overlay), NOT /MIR — the bundled _up_\python also holds ~37MB of
    # vendored deps (PIL/fastapi/uvicorn/cryptography/…) that are NOT in the repo
    # python/ tree; /MIR would delete them and brick the bridge. /E updates the
    # changed .py files and leaves the vendored packages intact.
    if ($PythonSource -ne "") {
        if (-not (Test-Path -LiteralPath $PythonSource)) { throw "PythonSource not found: $PythonSource" }
        $pyDest = Join-Path $stage "OpenClawFiles\_up_\python"
        Write-Host "Overlaying live bridge python -> $pyDest"
        & robocopy $PythonSource $pyDest /E /XD __pycache__ .pytest_cache /XF *.pyc /NFL /NDL /NJH /NJS /NP | Out-Null
        if ($LASTEXITCODE -ge 8) { throw "python sync robocopy failed with code $LASTEXITCODE" }
        $global:LASTEXITCODE = 0
    }

    if ($Exe -ne "") {
        if (-not (Test-Path -LiteralPath $Exe)) { throw "Baked exe not found: $Exe" }
        $exeItem = Get-Item -LiteralPath $Exe
        if ($exeItem.Length -lt 9MB) {
            throw "Baked exe is unexpectedly small ($([math]::Round($exeItem.Length / 1MB, 1)) MB). Use `npm run tauri -- build`, not plain `cargo build --release`, or the app may load localhost:1420."
        }
        Copy-Item -LiteralPath $Exe -Destination (Join-Path $stage "OpenClaw.exe") -Force
        Write-Host "Swapped OpenClaw.exe with baked build: $Exe"
    } else {
        Write-Warning "No -Exe given; keeping the source OpenClaw.exe. It MUST already have the manifest URL baked in, or first-run download will not trigger."
    }

    # Pre-create the layer parent dirs so the bootstrap has somewhere to land.
    foreach ($rel in $RemoveLayers) {
        $parent = Split-Path (Join-Path $stage $rel) -Parent
        New-Item -ItemType Directory -Force -Path $parent | Out-Null
    }

    if ($Out -eq "") {
        $Out = Join-Path (Split-Path $Source -Parent) ((Split-Path $Source -Leaf) + "-online.zip")
    }
    if (Test-Path -LiteralPath $Out) { Remove-Item -LiteralPath $Out -Force }
    Write-Host "Compressing -> $Out"
    Compress-Archive -Path (Join-Path $stage "*") -DestinationPath $Out -CompressionLevel Optimal

    $sizeMB = [math]::Round((Get-Item -LiteralPath $Out).Length / 1MB, 1)
    Write-Host ("Done: {0}  ({1} MB)" -f $Out, $sizeMB)
    if ($sizeMB -ge 100) { Write-Warning "Package is >= 100MB ($sizeMB MB) — check that all four heavy layers were excluded." }
}
finally {
    Remove-Item -LiteralPath $stage -Recurse -Force -ErrorAction SilentlyContinue
}
