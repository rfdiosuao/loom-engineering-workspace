param(
    [string]$SourceUrl = "https://go.microsoft.com/fwlink/p/?LinkId=2124703",
    [string]$OutputPath = ""
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$LauncherDir = Join-Path $Root "openclaw_new_launcher"
$RedistDir = Join-Path $LauncherDir "redist"
if ([string]::IsNullOrWhiteSpace($OutputPath)) {
    $OutputPath = Join-Path $RedistDir "MicrosoftEdgeWebView2RuntimeInstallerX64.exe"
}

New-Item -ItemType Directory -Path (Split-Path -Parent $OutputPath) -Force | Out-Null

if (Test-Path -LiteralPath $OutputPath) {
    $existing = Get-Item -LiteralPath $OutputPath
    if ($existing.Length -gt 1MB) {
        Write-Host "WebView2 runtime already exists: $OutputPath"
        return
    }
}

Write-Host "Downloading Microsoft Edge WebView2 Evergreen Runtime..."
Write-Host "Source: $SourceUrl"
Invoke-WebRequest -Uri $SourceUrl -OutFile $OutputPath

$file = Get-Item -LiteralPath $OutputPath
if ($file.Length -lt 1MB) {
    throw "Downloaded WebView2 runtime looks too small: $($file.Length) bytes"
}

$hash = Get-FileHash -Algorithm SHA256 -LiteralPath $OutputPath
Write-Host "WebView2 runtime saved: $OutputPath"
Write-Host "SHA256: $($hash.Hash)"
