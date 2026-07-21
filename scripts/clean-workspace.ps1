param(
    [switch]$RemoveBuildOutputs,
    [switch]$RemoveOldReleaseZips,
    [switch]$RemoveScratch,
    [int]$KeepReleaseZips = 1
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$LauncherDir = Join-Path $Root "openclaw_new_launcher"
$ReleaseDir = Join-Path $Root "release"

function Resolve-ExistingPath {
    param([string]$Path)

    if (-not (Test-Path -LiteralPath $Path)) {
        return $null
    }

    return (Resolve-Path -LiteralPath $Path).Path
}

function Assert-InWorkspace {
    param([string]$ResolvedPath)

    $resolvedRoot = (Resolve-Path -LiteralPath $Root).Path
    if (-not $ResolvedPath.StartsWith($resolvedRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to remove path outside workspace: $ResolvedPath"
    }
}

function Remove-WorkspacePath {
    param([string]$Path)

    $resolved = Resolve-ExistingPath $Path
    if (-not $resolved) {
        return
    }

    Assert-InWorkspace $resolved
    Write-Host "Removing $resolved"
    Remove-Item -LiteralPath $resolved -Recurse -Force
}

Write-Host "Cleaning workspace caches..."

$defaultTargets = @(
    (Join-Path $Root ".cache"),
    (Join-Path $Root "build"),
    (Join-Path $Root "dist"),
    (Join-Path $Root "__pycache__"),
    (Join-Path $LauncherDir "dist"),
    (Join-Path $LauncherDir "python\__pycache__"),
    (Join-Path $LauncherDir "python\core\__pycache__"),
    (Join-Path $LauncherDir "python\services\__pycache__")
)

foreach ($target in $defaultTargets) {
    Remove-WorkspacePath $target
}

$pycRoots = @(
    (Join-Path $LauncherDir "python"),
    (Join-Path $LauncherDir "src-tauri\target\debug\_up_\python"),
    (Join-Path $LauncherDir "src-tauri\target\release\_up_\python")
)

foreach ($pycRoot in $pycRoots) {
    if (-not (Test-Path -LiteralPath $pycRoot)) {
        continue
    }

    foreach ($pyc in Get-ChildItem -LiteralPath $pycRoot -Recurse -Force -File -Filter "*.pyc" -ErrorAction SilentlyContinue) {
        Assert-InWorkspace $pyc.FullName
        Write-Host "Removing $($pyc.FullName)"
        Remove-Item -LiteralPath $pyc.FullName -Force
    }
}

if ($RemoveBuildOutputs) {
    Remove-WorkspacePath (Join-Path $LauncherDir "src-tauri\target")
}

if ($RemoveOldReleaseZips -and (Test-Path -LiteralPath $ReleaseDir)) {
    $keep = [Math]::Max(0, $KeepReleaseZips)
    $zips = Get-ChildItem -LiteralPath $ReleaseDir -Filter "*.zip" -File |
        Sort-Object LastWriteTime -Descending

    $oldZips = @($zips | Select-Object -Skip $keep)
    foreach ($zip in $oldZips) {
        Assert-InWorkspace $zip.FullName
        Write-Host "Removing old release zip $($zip.FullName)"
        Remove-Item -LiteralPath $zip.FullName -Force
    }
}

if ($RemoveScratch) {
    $scratchTargets = @(
        "electron-v28.3.3.zip",
        "electron-v39.zip",
        "electron.zip",
        "electron-extract",
        "electron-extract-v39",
        "tmp_license_admin_audit",
        "tmp_license_admin_nav_check",
        "check_electron.ps1",
        "copy_electron.js",
        "copy_electron.ps1",
        "copy_electron.py",
        "copy_electron2.ps1",
        "copy_utils.js",
        "cp_ps1.ps1",
        "create_electron_dist.js",
        "create_electron_entries.js",
        "create_electron_package_json.js",
        "debug_electron_start.ps1",
        "dl_electron.bat",
        "dl_electron.js",
        "download_electron.bat",
        "find_node.ps1",
        "find_node2.ps1",
        "find_python.ps1",
        "fix_electron39.ps1",
        "fix_electron39b.ps1",
        "fix_path_txt.js",
        "fix_path_txt2.js",
        "install_e.bat",
        "install_electron.bat",
        "install_electron.js",
        "install_electron.ps1",
        "install_electron39.ps1",
        "install_missing_deps.js",
        "launch_electron.ps1",
        "launch_electron2.ps1",
        "launch_electron39.ps1",
        "launch_luminode_final.ps1",
        "link_electron_toolkit.js",
        "list_d.ps1",
        "npm_install.ps1",
        "npm_install2.ps1",
        "npm_install3.ps1",
        "npm_install4.ps1",
        "pack_electron.bat",
        "run_copy.ps1",
        "shortpath.ps1",
        "start_luminode.ps1",
        "start_luminode2.ps1",
        "start_luminode3.ps1",
        "test_electron_direct.ps1",
        "test_luminode_final.ps1",
        "test_require_utils.js",
        "test_utils_detailed.js",
        "tmp_pack.js",
        "tmp_pack2.js"
    )

    foreach ($relative in $scratchTargets) {
        Remove-WorkspacePath (Join-Path $Root $relative)
    }

    Remove-WorkspacePath (Join-Path $LauncherDir "data\logs")
    Remove-WorkspacePath (Join-Path $LauncherDir "data\phone-frames")
    Remove-WorkspacePath (Join-Path $LauncherDir "data\phone-videos")
}

Write-Host "Workspace cleanup complete."
