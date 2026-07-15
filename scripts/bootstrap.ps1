[CmdletBinding()]
param(
    [string]$AndroidSdk
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'workspace-core.ps1')

$platform = Get-LoomRepository -Name 'platform'
$phone = Get-LoomRepository -Name 'phone'
Assert-LoomGitRepository -Path $platform.Path
Assert-LoomGitRepository -Path $phone.Path

$hookPath = (Join-Path (Get-LoomWorkspaceRoot) '.githooks').Replace('\', '/')
foreach ($gitPath in @((Get-LoomWorkspaceRoot), $platform.Path, $phone.Path)) {
    & git -C $gitPath config core.hooksPath $hookPath
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to configure Git hooks for $gitPath"
    }
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

& git -C $phone.Path check-ignore --quiet -- 'local.properties'
if ($LASTEXITCODE -ne 0) {
    throw 'Phone local.properties is not ignored; refusing to continue.'
}

Write-Host '[Workspace contract tests]' -ForegroundColor Cyan
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'test-workspace.ps1')
if ($LASTEXITCODE -ne 0) {
    throw 'Workspace contract tests failed.'
}

Write-Host 'Bootstrap completed.' -ForegroundColor Green
