param(
    [string]$PackageName = "",
    [string]$OpenClawRuntimeVersion = "2026.6.5",
    [switch]$NoZip
)

$ErrorActionPreference = "Stop"

$SourceDir = Split-Path -Parent $PSScriptRoot
$Root = Split-Path -Parent $SourceDir
$ReleaseDir = Join-Path $Root "release"

function Assert-InDirectory {
    param(
        [string]$Path,
        [string]$Parent
    )

    $resolvedPath = (Resolve-Path -LiteralPath $Path).Path
    $resolvedParent = (Resolve-Path -LiteralPath $Parent).Path
    if (-not $resolvedPath.StartsWith($resolvedParent, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to operate outside expected parent. Path=$resolvedPath Parent=$resolvedParent"
    }
}

function Get-LauncherVersion {
    $packageJsonPath = Join-Path $SourceDir "package.json"
    if (Test-Path -LiteralPath $packageJsonPath) {
        $packageJson = Get-Content -LiteralPath $packageJsonPath -Raw | ConvertFrom-Json
        if (-not [string]::IsNullOrWhiteSpace([string]$packageJson.version)) {
            return [string]$packageJson.version
        }
    }

    throw "Unable to determine launcher version from package.json."
}

function Get-SafeName {
    param([string]$Value)
    return ($Value -replace '[^0-9A-Za-z._-]', '-')
}

New-Item -ItemType Directory -Force -Path $ReleaseDir | Out-Null

if ([string]::IsNullOrWhiteSpace($PackageName)) {
    $date = Get-Date -Format "yyyy.MM.dd"
    $version = Get-LauncherVersion
    $runtime = Get-SafeName $OpenClawRuntimeVersion
    $PackageName = "OpenClaw-Launcher-Source-v$version-$date-openclaw-$runtime"
}

$StageDir = Join-Path $ReleaseDir $PackageName
$ZipPath = Join-Path $ReleaseDir "$PackageName.zip"
$HashPath = "$ZipPath.sha256.txt"

if (Test-Path -LiteralPath $StageDir) {
    Assert-InDirectory -Path $StageDir -Parent $ReleaseDir
    Remove-Item -LiteralPath $StageDir -Recurse -Force
}
foreach ($path in @($ZipPath, $HashPath)) {
    if (Test-Path -LiteralPath $path) {
        Assert-InDirectory -Path $path -Parent $ReleaseDir
        Remove-Item -LiteralPath $path -Force
    }
}

$excludeDirs = @(
    ".git",
    ".venv",
    "node_modules",
    "dist",
    "target",
    "test-artifacts",
    ".openclaw",
    "generated-images",
    "storyboards",
    "storyboards_temp",
    "diagnostics",
    "logs",
    "phone-frames",
    "phone-videos",
    "releases"
)

$excludeFiles = @(
    "*.apk",
    "*.app",
    "*.appimage",
    "*.bak-*",
    "*.deb",
    "*.dmg",
    "*.exe",
    "*.log",
    "*.msi",
    "*.rpm",
    "*.tar",
    "*.tgz",
    "*.zip",
    "*.7z"
)

$robocopyArgs = @(
    $SourceDir,
    $StageDir,
    "/E",
    "/NFL",
    "/NDL",
    "/NJH",
    "/NJS",
    "/NP",
    "/XD"
) + $excludeDirs + @("/XF") + $excludeFiles

& robocopy @robocopyArgs | Out-Null
$robocopyCode = $LASTEXITCODE
if ($robocopyCode -ge 8) {
    throw "robocopy failed with exit code $robocopyCode"
}

$docsDir = Join-Path $StageDir "docs"
if (Test-Path -LiteralPath $docsDir) {
    Get-ChildItem -LiteralPath $docsDir -File |
        Where-Object {
            $_.Name -like "*MEMORY_RECOVERY.md" -or
            $_.Name -like "openclaw*.md"
        } |
        Remove-Item -Force
}

$info = @"
OpenClaw launcher source package
Generated: $(Get-Date -Format "yyyy-MM-dd HH:mm:ss")
Source: $SourceDir
Launcher version: $(Get-LauncherVersion)
OpenClaw runtime pin: $OpenClawRuntimeVersion

Included:
- Frontend source, configs, and lock files.
- Tauri/Rust source without build artifacts.
- Python bridge source.
- Automation/runtime scripts.
- OpenClaw workspace skills and documentation needed for adaptation.

Excluded:
- node_modules, .venv, dist, src-tauri/target, and test artifacts.
- Local runtime state under data/.openclaw and generated media.
- APKs, installers, portable packages, and downloaded runtime binaries.
"@
Set-Content -LiteralPath (Join-Path $StageDir "SOURCE_PACKAGE_INFO.txt") -Value $info -Encoding UTF8

if (-not $NoZip) {
    Compress-Archive -LiteralPath $StageDir -DestinationPath $ZipPath -CompressionLevel Optimal
    $hash = Get-FileHash -Algorithm SHA256 -LiteralPath $ZipPath
    "$($hash.Hash)  $(Split-Path -Leaf $ZipPath)" | Set-Content -LiteralPath $HashPath -Encoding ASCII
    Write-Host "Package: $ZipPath"
    Write-Host "SHA256:  $($hash.Hash)"
}
else {
    Write-Host "Source staging directory: $StageDir"
}
