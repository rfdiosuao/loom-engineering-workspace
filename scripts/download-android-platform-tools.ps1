param(
    [string]$Url = "https://dl.google.com/android/repository/platform-tools-latest-windows.zip"
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$LauncherDir = Join-Path $Root "openclaw_new_launcher"
$RedistDir = Join-Path $LauncherDir "redist"
$TargetDir = Join-Path $RedistDir "platform-tools"
$TempDir = Join-Path $Root "artifacts\platform-tools-download"
$ZipPath = Join-Path $TempDir "platform-tools.zip"

New-Item -ItemType Directory -Path $TempDir -Force | Out-Null
New-Item -ItemType Directory -Path $RedistDir -Force | Out-Null

Write-Host "Downloading Android platform-tools..." -ForegroundColor Cyan
Invoke-WebRequest -Uri $Url -OutFile $ZipPath -UseBasicParsing

$ExtractDir = Join-Path $TempDir "extract"
if (Test-Path -LiteralPath $ExtractDir) {
    Remove-Item -LiteralPath $ExtractDir -Recurse -Force
}
Expand-Archive -LiteralPath $ZipPath -DestinationPath $ExtractDir -Force

$SourceDir = Join-Path $ExtractDir "platform-tools"
$AdbPath = Join-Path $SourceDir "adb.exe"
if (-not (Test-Path -LiteralPath $AdbPath)) {
    throw "Downloaded platform-tools archive does not contain adb.exe."
}

if (Test-Path -LiteralPath $TargetDir) {
    Remove-Item -LiteralPath $TargetDir -Recurse -Force
}
Copy-Item -LiteralPath $SourceDir -Destination $TargetDir -Recurse -Force

$Version = & (Join-Path $TargetDir "adb.exe") version
Write-Host "Android platform-tools installed to $TargetDir" -ForegroundColor Green
Write-Host $Version
