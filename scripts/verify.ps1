[CmdletBinding()]
param(
    [Alias('Repository')]
    [ValidateSet('all', 'workspace', 'hub', 'platform', 'phone')]
    [string]$Area = 'all',

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

if ($Area -in @('all', 'workspace', 'hub')) {
    Invoke-LoomStep -Name 'Workspace contracts' -Action {
        & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'test-workspace.ps1')
    }
    Invoke-LoomStep -Name 'Repository whitespace' -Action {
        & git -C $root diff --check
    }
}

if ($Area -in @('all', 'platform')) {
    $platform = Get-LoomComponent -Name 'platform'
    $launcher = Join-Path $platform.Path 'openclaw_new_launcher'
    if (-not (Test-Path -LiteralPath (Join-Path $launcher 'node_modules') -PathType Container)) {
        throw 'Platform dependencies are missing. Run scripts\bootstrap.ps1 first.'
    }

    Invoke-LoomStep -Name 'Build bundled Skill library' -Action {
        & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $platform.Path 'scripts\build-luming-skills-library.ps1')
    }
    Invoke-LoomStep -Name 'Platform frontend build' -Action {
        & npm --prefix $launcher run build
    }
    Invoke-LoomStep -Name 'Platform frontend contracts' -Action {
        & npm --prefix $launcher run test:platform-contracts
    }
    Invoke-LoomStep -Name 'Platform Node contracts' -Action {
        & npm --prefix $launcher run test:node-contracts
    }
    if (-not $Fast) {
        Invoke-LoomStep -Name 'Platform Python tests' -Action {
            Push-Location $launcher
            try {
                & python -m pytest python/tests -q
            } finally {
                Pop-Location
            }
        }
    }
}

if ($Area -in @('all', 'phone')) {
    $phone = Get-LoomComponent -Name 'phone'
    $phoneLocalProperties = Join-Path $phone.Path 'local.properties'
    if (-not $Fast -and
        -not (Test-Path -LiteralPath $phoneLocalProperties -PathType Leaf) -and
        [string]::IsNullOrWhiteSpace($env:ANDROID_SDK_ROOT) -and
        [string]::IsNullOrWhiteSpace($env:ANDROID_HOME)) {
        throw 'Android SDK configuration is missing. Run scripts\bootstrap.ps1 first.'
    }

    if ($Fast) {
        Invoke-LoomStep -Name 'Phone source whitespace' -Action {
            & git -C $root diff --check -- apps/loom-phone-agent
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
