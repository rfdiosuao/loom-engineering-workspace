param(
    [switch]$SkipFrontend,
    [switch]$SkipRust,
    [switch]$SkipPython,
    [switch]$SkipBundledPythonRuntime,
    [switch]$SkipLicenseServer,
    [switch]$SkipSourceText,
    [switch]$SkipWorkspaceHygiene,
    [switch]$SkipDistSelftest,
    [switch]$SkipInstallerManifest,
    [switch]$SkipAdminConsole,
    [switch]$SkipLicenseFlowTests
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot

function Resolve-LauncherDir {
    $candidates = @("openclaw_new_launcher")
    foreach ($candidate in $candidates) {
        $path = Join-Path $Root $candidate
        if (
            (Test-Path -LiteralPath (Join-Path $path "package.json")) -and
            (Test-Path -LiteralPath (Join-Path $path "src-tauri"))
        ) {
            return $path
        }
    }
    throw "No launcher project found. Expected openclaw_new_launcher."
}

$LauncherDir = Resolve-LauncherDir
$TauriDir = Join-Path $LauncherDir "src-tauri"
$LicenseServerDir = Join-Path $Root "license_server"
$VerifySourceTextScript = Join-Path $PSScriptRoot "verify-source-text.ps1"
$VerifyVersionScript = Join-Path $PSScriptRoot "verify-version-consistency.ps1"
$VerifyAdminConsoleScript = Join-Path $PSScriptRoot "verify-admin-console.ps1"
$WorkspaceHygieneScript = Join-Path $PSScriptRoot "check-workspace-hygiene.ps1"
$VerifyInstallerManifestScript = Join-Path $PSScriptRoot "verify-installer-manifest.ps1"
$VerifyReleaseSecretsScript = Join-Path $PSScriptRoot "verify-release-secrets.ps1"

function Invoke-Step {
    param(
        [string]$Name,
        [scriptblock]$Script
    )
    Write-Host ""
    Write-Host "==> $Name" -ForegroundColor Cyan
    $global:LASTEXITCODE = 0
    & $Script
    if ($global:LASTEXITCODE -ne 0) {
        throw "Step failed with exit code $global:LASTEXITCODE: $Name"
    }
    Write-Host "OK: $Name" -ForegroundColor Green
}

function Invoke-Native {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FilePath,
        [Parameter(ValueFromRemainingArguments = $true)]
        [string[]]$Arguments
    )

    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code ${LASTEXITCODE}: $FilePath $($Arguments -join ' ')"
    }
}

if (-not $SkipSourceText) {
    Invoke-Step "Source text guard" {
        & powershell -ExecutionPolicy Bypass -File $VerifySourceTextScript
    }
}

Invoke-Step "Source secret scan" {
    & powershell -ExecutionPolicy Bypass -File $VerifyReleaseSecretsScript -Source
}

Invoke-Step "Version consistency" {
    & powershell -ExecutionPolicy Bypass -File $VerifyVersionScript
}

if (-not $SkipWorkspaceHygiene) {
    Invoke-Step "Workspace hygiene" {
        & powershell -ExecutionPolicy Bypass -File $WorkspaceHygieneScript
    }
}

if (-not $SkipFrontend) {
    Invoke-Step "Frontend build" {
        Push-Location $LauncherDir
        try {
            if (Test-Path -LiteralPath "package-lock.json") {
                Invoke-Native npm ci
            } else {
                Invoke-Native npm install
            }
            Invoke-Native npm run build
            Invoke-Native npm run test:platform-contracts
            Invoke-Native npm run test:node-contracts
        } finally {
            Pop-Location
        }
    }
}

if (-not $SkipPython) {
    Invoke-Step "Python launcher compile" {
        Push-Location $LauncherDir
        try {
            $files = @("python/bridge.py")
            $files += Get-ChildItem -LiteralPath "python/core" -Filter "*.py" | ForEach-Object { $_.FullName }
            $files += Get-ChildItem -LiteralPath "python/services" -Filter "*.py" | ForEach-Object { $_.FullName }
            if (Test-Path -LiteralPath "python/api") {
                $files += Get-ChildItem -LiteralPath "python/api" -Filter "*.py" | ForEach-Object { $_.FullName }
            }
            Invoke-Native python -m py_compile @files
        } finally {
            Pop-Location
        }
    }

    Invoke-Step "Python launcher unit tests" {
        Push-Location $LauncherDir
        try {
            Invoke-Native python -m unittest discover -s python\tests -p "test_*.py"
        } finally {
            Pop-Location
        }
    }

    if (-not $SkipBundledPythonRuntime) {
        Invoke-Step "Bundled Python runtime build" {
            Push-Location $LauncherDir
            try {
                Invoke-Native -FilePath powershell -Arguments @(
                    "-NoProfile",
                    "-ExecutionPolicy", "Bypass",
                    "-File", "scripts\build-python-runtime.ps1"
                )
            } finally {
                Pop-Location
            }
        }

        Invoke-Step "Bundled Python runtime unit tests" {
            Push-Location $LauncherDir
            try {
                $runtimePython = Join-Path $LauncherDir "python-runtime\python.exe"
                Invoke-Native $runtimePython -m unittest discover -s python\tests -p "test_*.py"
            } finally {
                Pop-Location
            }
        }
    }
}

if (-not $SkipRust) {
    Invoke-Step "Bundled Node runtime build" {
        Push-Location $LauncherDir
        try {
            Invoke-Native -FilePath powershell -Arguments @(
                "-NoProfile",
                "-ExecutionPolicy", "Bypass",
                "-File", "scripts\build-node-runtime.ps1"
            )
        } finally {
            Pop-Location
        }
    }

    if (-not (Test-Path -LiteralPath (Join-Path $LauncherDir "python-runtime\python.exe"))) {
        Invoke-Step "Bundled Python runtime build for Rust" {
            Push-Location $LauncherDir
            try {
                Invoke-Native -FilePath powershell -Arguments @(
                    "-NoProfile",
                    "-ExecutionPolicy", "Bypass",
                    "-File", "scripts\build-python-runtime.ps1"
                )
            } finally {
                Pop-Location
            }
        }
    }

    Invoke-Step "Rust cargo check" {
        Push-Location $TauriDir
        try {
            Invoke-Native cargo check
        } finally {
            Pop-Location
        }
    }

    Invoke-Step "Rust cargo test" {
        Push-Location $TauriDir
        try {
            Invoke-Native cargo test
        } finally {
            Pop-Location
        }
    }
}

if (-not $SkipDistSelftest) {
    $distSelftest = Join-Path $LauncherDir "scripts\dist\dist-selftest.mjs"
    if (Test-Path -LiteralPath $distSelftest) {
        Invoke-Step "Distribution layer self-test" {
            Invoke-Native node $distSelftest
        }
    }
}

if (-not $SkipInstallerManifest -and (Test-Path -LiteralPath $VerifyInstallerManifestScript)) {
    Invoke-Step "Installer manifest contract" {
        & powershell -ExecutionPolicy Bypass -File $VerifyInstallerManifestScript
    }
}

if (-not $SkipLicenseServer -and (Test-Path -LiteralPath (Join-Path $LicenseServerDir "server.py"))) {
    Invoke-Step "Python license server compile" {
        Push-Location $LicenseServerDir
        try {
            Invoke-Native python -m py_compile server.py
        } finally {
            Pop-Location
        }
    }

    if (-not $SkipAdminConsole) {
        Invoke-Step "Admin console contract" {
            & powershell -ExecutionPolicy Bypass -File $VerifyAdminConsoleScript
        }
    }

    if (-not $SkipLicenseFlowTests) {
        Invoke-Step "License server flow tests" {
            Push-Location $Root
            try {
                Invoke-Native python -m unittest discover -s license_server/tests -p "test_*.py" -v
            } finally {
                Pop-Location
            }
        }
    }
}

Write-Host ""
Write-Host "All CI checks passed." -ForegroundColor Green
