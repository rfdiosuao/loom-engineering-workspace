[CmdletBinding()]
param(
    [ValidateSet('all', 'hub', 'platform', 'phone')]
    [string]$Repository = 'all',

    [switch]$Fast
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'workspace-core.ps1')

$root = Get-LoomWorkspaceRoot

function Invoke-LoomStep {
    param(
        [string]$Name,
        [scriptblock]$Action
    )

    Write-Host "`n[$Name]" -ForegroundColor Cyan
    & $Action
    if ($LASTEXITCODE -ne 0) {
        throw "Verification failed: $Name"
    }
}

if ($Repository -in @('all', 'hub')) {
    Invoke-LoomStep -Name 'Workspace contracts' -Action {
        & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'test-workspace.ps1')
    }
    Invoke-LoomStep -Name 'Hub whitespace' -Action {
        & git -C $root diff --check
    }
}

if ($Repository -in @('all', 'platform')) {
    $platform = Get-LoomRepository -Name 'platform'
    $platformModules = Join-Path $platform.Path 'openclaw_new_launcher\node_modules'
    if (-not (Test-Path -LiteralPath $platformModules -PathType Container)) {
        throw 'Platform dependencies are missing. Run scripts\bootstrap.ps1 first.'
    }
    Invoke-LoomStep -Name 'Platform frontend build' -Action {
        & npm --prefix (Join-Path $platform.Path 'openclaw_new_launcher') run build
    }
    if (-not $Fast) {
        Invoke-LoomStep -Name 'Platform Python tests' -Action {
            Push-Location (Join-Path $platform.Path 'openclaw_new_launcher')
            try {
                & python -m pytest python/tests -q
            } finally {
                Pop-Location
            }
        }
    }
}

if ($Repository -in @('all', 'phone')) {
    $phone = Get-LoomRepository -Name 'phone'
    $phoneLocalProperties = Join-Path $phone.Path 'local.properties'
    if (-not (Test-Path -LiteralPath $phoneLocalProperties -PathType Leaf) -and
        [string]::IsNullOrWhiteSpace($env:ANDROID_SDK_ROOT) -and
        [string]::IsNullOrWhiteSpace($env:ANDROID_HOME)) {
        throw 'Android SDK configuration is missing. Run scripts\bootstrap.ps1 first.'
    }
    if ($Fast) {
        Invoke-LoomStep -Name 'Phone source whitespace' -Action {
            & git -C $phone.Path diff --check
        }
    } else {
        Invoke-LoomStep -Name 'Phone unit tests' -Action {
            Push-Location $phone.Path
            try {
                & .\gradlew.bat testDebugUnitTest
            } finally {
                Pop-Location
            }
        }
    }
}

Write-Host "`nVerification completed." -ForegroundColor Green
