# Wrap the verified thin-portable package into a per-user desktop installer
# (OpenClaw-Setup.exe). The installer just lays that proven payload into
# %LOCALAPPDATA%\OpenClaw + makes shortcuts, so runtime path resolution is
# identical to the portable and the first-run bootstrap downloads layers into
# the writable install dir.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts/dist/build-installer.ps1 `
#     -ThinZip "release\OpenClaw-Online-v2.0.6.zip" `
#     -Out     "release\OpenClaw-Setup-v2.0.6.exe" `
#     -Version "2.0.6"

param(
    [Parameter(Mandatory = $true)][string]$ThinZip,
    [string]$Out = "",
    [string]$Version = "2.0.6",
    # -AppName = install IDENTITY (folder + registry + uninstall key). MUST stay
    # "OpenClaw" so updates land in-place over the legacy OpenClaw installs.
    # -Brand = DISPLAY brand (window title, shortcuts, wizard text) = "LumiClaw".
    # The payload executable is always OpenClaw.exe (the engine).
    [string]$AppName = "OpenClaw",
    [string]$Brand = "LumiClaw",
    [string]$Makensis = "$env:LOCALAPPDATA\tauri\NSIS\makensis.exe"
)

$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$nsi = Join-Path $here "installer.nsi"

if (-not (Test-Path -LiteralPath $ThinZip)) { throw "ThinZip not found: $ThinZip" }
if (-not (Test-Path -LiteralPath $Makensis)) { throw "makensis not found: $Makensis (install via a Tauri NSIS build, or set -Makensis)" }
if (-not (Test-Path -LiteralPath $nsi)) { throw "installer.nsi not found: $nsi" }
if ($Out -eq "") { $Out = Join-Path (Split-Path $ThinZip -Parent) ("$Brand-Setup-v$Version.exe") }

$stage = Join-Path $env:TEMP ("openclaw-setup-" + [System.IO.Path]::GetRandomFileName())
$payload = Join-Path $stage "payload"
New-Item -ItemType Directory -Force -Path $payload | Out-Null
try {
    Write-Host "Expanding thin package -> $payload"
    Expand-Archive -LiteralPath $ThinZip -DestinationPath $payload -Force
    if (-not (Test-Path -LiteralPath (Join-Path $payload "OpenClaw.exe"))) {
        throw "payload missing OpenClaw.exe — is $ThinZip a valid thin package?"
    }

    $outAbs = [System.IO.Path]::GetFullPath($Out)
    New-Item -ItemType Directory -Force -Path (Split-Path $outAbs -Parent) | Out-Null
    if (Test-Path -LiteralPath $outAbs) { Remove-Item -LiteralPath $outAbs -Force }

    $artDir = Join-Path $here "assets"
    $icon = [System.IO.Path]::GetFullPath((Join-Path $here "..\..\src-tauri\icons\icon.ico"))
    # makensis with `Unicode true` needs a UTF-8 BOM to read the Chinese strings;
    # editors save the .nsi without one, so emit a BOM'd copy just for the build.
    $nsiBom = Join-Path $stage "installer.bom.nsi"
    $nsiText = [System.IO.File]::ReadAllText($nsi, [System.Text.Encoding]::UTF8)
    [System.IO.File]::WriteAllText($nsiBom, $nsiText, (New-Object System.Text.UTF8Encoding $true))
    $nsisArgs = @("/DAPP=$AppName", "/DBRAND=$Brand", "/DAPPVERSION=$Version", "/DPAYLOAD_DIR=$payload", "/DOUTFILE=$outAbs", "/DART_DIR=$artDir")
    if (Test-Path -LiteralPath $icon) { $nsisArgs += "/DICON=$icon" }
    $nsisArgs += $nsiBom

    Write-Host "Compiling installer -> $outAbs"
    & $Makensis @nsisArgs
    if ($LASTEXITCODE -ne 0) { throw "makensis failed with code $LASTEXITCODE" }

    $sizeMB = [math]::Round((Get-Item -LiteralPath $outAbs).Length / 1MB, 1)
    Write-Host ("Done: {0}  ({1} MB)" -f $outAbs, $sizeMB)
}
finally {
    Remove-Item -LiteralPath $stage -Recurse -Force -ErrorAction SilentlyContinue
}
