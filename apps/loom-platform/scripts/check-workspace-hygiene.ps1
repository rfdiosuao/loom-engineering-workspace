param(
    [switch]$StrictTracked
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
Push-Location $Root
try {
    $status = @(git status --porcelain --untracked-files=all)
} finally {
    Pop-Location
}

$tracked = @()
$untracked = @()
foreach ($line in $status) {
    if ($line.Length -lt 4) {
        continue
    }
    $code = $line.Substring(0, 2)
    $path = $line.Substring(3).Trim()
    if ($code -eq "??") {
        $untracked += $path
    } else {
        $tracked += $line
    }
}

$scratchPatterns = @(
    'electron*.zip',
    'electron-extract*/*',
    'tmp_license_admin_*/*',
    '*.log',
    'check_electron.ps1',
    'copy_electron*',
    'copy_utils.js',
    'cp_ps1.ps1',
    'create_electron_*.js',
    'debug_electron_start.ps1',
    'dl_electron*',
    'download_electron*',
    'find_node*.ps1',
    'find_python.ps1',
    'fix_electron*.ps1',
    'fix_path_txt*.js',
    'install_e*',
    'install_missing_deps.js',
    'launch_electron*.ps1',
    'launch_luminode_final.ps1',
    'link_electron_toolkit.js',
    'list_d.ps1',
    'npm_install*.ps1',
    'pack_electron.bat',
    'run_copy.ps1',
    'shortpath.ps1',
    'start_luminode*.ps1',
    'test_electron*.ps1',
    'test_luminode_final.ps1',
    'test_require_utils.js',
    'test_utils_detailed.js',
    'tmp_pack*.js',
    'lumiu-official-site/*',
    'lumiu-partner-film/*',
    'sightflow-desktop-agent/*',
    'sightflow-desktop-agent-main/*',
    'openclaw_new_launcher/docs/*.bak-*'
)

$scratch = @()
foreach ($path in $untracked) {
    foreach ($pattern in $scratchPatterns) {
        if ($path -like $pattern) {
            $scratch += $path
            break
        }
    }
}

if ($scratch.Count -gt 0) {
    throw "Workspace scratch files are not ignored or cleaned: $($scratch -join ', ')"
}

if ($StrictTracked -and $tracked.Count -gt 0) {
    throw "Tracked files have uncommitted changes:`n$($tracked -join [Environment]::NewLine)"
}

Write-Host "Workspace hygiene check passed." -ForegroundColor Green
