[CmdletBinding()]
param(
    [string]$AndroidSdk
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'workspace-core.ps1')

$root = Get-LoomWorkspaceRoot
$platform = Get-LoomComponent -Name 'platform'
$phone = Get-LoomComponent -Name 'phone'
Assert-LoomGitRepository -Path $root

$hookPath = (Join-Path $root '.githooks').Replace('\', '/')
& git -C $root config core.hooksPath $hookPath
if ($LASTEXITCODE -ne 0) {
    throw 'Unable to configure the versioned Git hooks.'
}

Write-Host '[Platform dependencies]' -ForegroundColor Cyan
& npm --prefix (Join-Path $platform.Path 'openclaw_new_launcher') ci
if ($LASTEXITCODE -ne 0) {
    throw 'npm ci failed for the LOOM platform.'
}

if ([string]::IsNullOrWhiteSpace($AndroidSdk)) {
    $AndroidSdk = $env:ANDROID_SDK_ROOT
}
if ([string]::IsNullOrWhiteSpace($AndroidSdk)) {
    $AndroidSdk = $env:ANDROID_HOME
}
if ([string]::IsNullOrWhiteSpace($AndroidSdk)) {
    $knownSdk = 'D:\android-sdk-windows\android-sdk-windows'
    if (Test-Path -LiteralPath $knownSdk -PathType Container) {
        $AndroidSdk = $knownSdk
    }
}
if ([string]::IsNullOrWhiteSpace($AndroidSdk) -or -not (Test-Path -LiteralPath $AndroidSdk -PathType Container)) {
    throw 'Android SDK was not found. Re-run with -AndroidSdk <absolute-path>.'
}

$sdkForGradle = [System.IO.Path]::GetFullPath($AndroidSdk).Replace('\', '/')
$localProperties = Join-Path $phone.Path 'local.properties'
[System.IO.File]::WriteAllText($localProperties, "sdk.dir=$sdkForGradle`n", [System.Text.UTF8Encoding]::new($false))

& git -C $root check-ignore --quiet -- 'apps/loom-phone-agent/local.properties'
if ($LASTEXITCODE -ne 0) {
    throw 'Phone local.properties is not ignored; refusing to continue.'
}

Write-Host '[Workspace contract tests]' -ForegroundColor Cyan
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'test-workspace.ps1')
if ($LASTEXITCODE -ne 0) {
    throw 'Workspace contract tests failed.'
}

Write-Host 'Bootstrap completed.' -ForegroundColor Green
