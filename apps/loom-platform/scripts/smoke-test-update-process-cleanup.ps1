param(
    [Parameter(Mandatory = $true)][string]$OldInstaller,
    [Parameter(Mandatory = $true)][string]$NewInstaller,
    [Parameter(Mandatory = $true)][string]$SmokeRoot,
    [string]$ProductName = "Luming AI Matrix Acquisition Workbench"
)

$ErrorActionPreference = "Stop"

function Resolve-Leaf([string]$Path, [string]$Label) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "$Label not found: $Path"
    }
    return (Resolve-Path -LiteralPath $Path).Path
}

function Assert-ChildPath([string]$Parent, [string]$Child) {
    $parentPath = [System.IO.Path]::GetFullPath($Parent).TrimEnd([System.IO.Path]::DirectorySeparatorChar)
    $childPath = [System.IO.Path]::GetFullPath($Child).TrimEnd([System.IO.Path]::DirectorySeparatorChar)
    if (-not $childPath.StartsWith(
        $parentPath + [System.IO.Path]::DirectorySeparatorChar,
        [System.StringComparison]::OrdinalIgnoreCase
    )) {
        throw "Test install path must stay inside smoke root: $childPath"
    }
    return $childPath
}

function Invoke-Hidden([string]$FilePath, [string]$Arguments) {
    $process = Start-Process `
        -FilePath $FilePath `
        -ArgumentList $Arguments `
        -PassThru `
        -Wait `
        -WindowStyle Hidden
    if ($process.ExitCode -ne 0) {
        throw "Process failed: exit=$($process.ExitCode) file=$FilePath"
    }
}

$resolvedOldInstaller = Resolve-Leaf -Path $OldInstaller -Label "Old installer"
$resolvedNewInstaller = Resolve-Leaf -Path $NewInstaller -Label "New installer"
$resolvedSmokeRoot = [System.IO.Path]::GetFullPath($SmokeRoot)
$installRoot = Assert-ChildPath -Parent $resolvedSmokeRoot -Child (Join-Path $resolvedSmokeRoot "old-version LOOM")

if (Test-Path -LiteralPath $resolvedSmokeRoot) {
    throw "Smoke root already exists: $resolvedSmokeRoot"
}
if (Get-CimInstance Win32_Process -Filter "Name='LOOM.exe'" -ErrorAction SilentlyContinue) {
    throw "Close all existing LOOM processes before running the update cleanup smoke test"
}

$uninstallRoot = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall"
$productKey = Join-Path $uninstallRoot $ProductName
$backupName = "$ProductName.__process_cleanup_smoke_$PID"
$backupKey = Join-Path $uninstallRoot $backupName
if (Test-Path -LiteralPath $backupKey) {
    throw "Temporary uninstall backup key already exists: $backupKey"
}

$shortcutPaths = @(
    (Join-Path ([Environment]::GetFolderPath("Desktop")) "$ProductName.lnk"),
    (Join-Path ([Environment]::GetFolderPath("Programs")) "$ProductName.lnk")
)
$shortcutBackupRoot = Join-Path $resolvedSmokeRoot "shortcut-backup"
$shortcutBackups = [System.Collections.Generic.List[object]]::new()
$renamedProductKey = $false
$pythonProcess = $null
$nodeProcess = $null

try {
    New-Item -ItemType Directory -Path $shortcutBackupRoot -Force | Out-Null
    for ($index = 0; $index -lt $shortcutPaths.Count; $index += 1) {
        $shortcutPath = $shortcutPaths[$index]
        if (Test-Path -LiteralPath $shortcutPath -PathType Leaf) {
            $backupPath = Join-Path $shortcutBackupRoot "$index.lnk"
            Copy-Item -LiteralPath $shortcutPath -Destination $backupPath -Force
            $shortcutBackups.Add([pscustomobject]@{ Original = $shortcutPath; Backup = $backupPath })
        }
    }

    if (Test-Path -LiteralPath $productKey) {
        Rename-Item -LiteralPath $productKey -NewName $backupName
        $renamedProductKey = $true
    }

    Invoke-Hidden -FilePath $resolvedOldInstaller -Arguments "/S /D=$installRoot"
    $pythonExe = Join-Path $installRoot "_up_\python-runtime\python.exe"
    $nodeExe = Join-Path $installRoot "_up_\node-runtime\node.exe"
    foreach ($runtime in @($pythonExe, $nodeExe)) {
        if (-not (Test-Path -LiteralPath $runtime -PathType Leaf)) {
            throw "Old installer did not provide expected runtime: $runtime"
        }
    }

    $pythonProcess = Start-Process `
        -FilePath $pythonExe `
        -ArgumentList @("-c", '"import time; time.sleep(120)"') `
        -PassThru `
        -WindowStyle Hidden
    $nodeProcess = Start-Process `
        -FilePath $nodeExe `
        -ArgumentList @("-e", '"setTimeout(()=>{},120000)"') `
        -PassThru `
        -WindowStyle Hidden
    Start-Sleep -Seconds 2
    if ($pythonProcess.HasExited -or $nodeProcess.HasExited) {
        throw "Owned Python/Node reproduction process exited before the overlay test"
    }

    Invoke-Hidden -FilePath $resolvedNewInstaller -Arguments "/S /D=$installRoot"
    Start-Sleep -Seconds 2
    $pythonAlive = $null -ne (Get-Process -Id $pythonProcess.Id -ErrorAction SilentlyContinue)
    $nodeAlive = $null -ne (Get-Process -Id $nodeProcess.Id -ErrorAction SilentlyContinue)
    if ($pythonAlive -or $nodeAlive) {
        throw "Overlay left owned runtimes alive: python=$pythonAlive node=$nodeAlive"
    }

    foreach ($requiredPath in @(
        (Join-Path $installRoot "LOOM.exe"),
        (Join-Path $installRoot "_up_\python-runtime\python.exe"),
        (Join-Path $installRoot "_up_\node-runtime\node.exe")
    )) {
        if (-not (Test-Path -LiteralPath $requiredPath -PathType Leaf)) {
            throw "Overlay output is incomplete: $requiredPath"
        }
    }

    [pscustomobject]@{
        installPath = $installRoot
        pythonPid = $pythonProcess.Id
        nodePid = $nodeProcess.Id
        pythonStopped = -not $pythonAlive
        nodeStopped = -not $nodeAlive
        overlaySucceeded = $true
    } | ConvertTo-Json
}
finally {
    foreach ($process in @($pythonProcess, $nodeProcess)) {
        if ($process -and (Get-Process -Id $process.Id -ErrorAction SilentlyContinue)) {
            Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
        }
    }

    $uninstaller = Join-Path $installRoot "uninstall.exe"
    if (Test-Path -LiteralPath $uninstaller -PathType Leaf) {
        try {
            Invoke-Hidden -FilePath $uninstaller -Arguments "/S"
        }
        catch {
            Write-Warning $_
        }
    }
    if (Test-Path -LiteralPath $installRoot) {
        $verifiedInstallRoot = Assert-ChildPath -Parent $resolvedSmokeRoot -Child $installRoot
        Remove-Item -LiteralPath $verifiedInstallRoot -Recurse -Force -ErrorAction SilentlyContinue
    }

    foreach ($shortcutPath in $shortcutPaths) {
        Remove-Item -LiteralPath $shortcutPath -Force -ErrorAction SilentlyContinue
    }
    foreach ($shortcutBackup in $shortcutBackups) {
        Copy-Item -LiteralPath $shortcutBackup.Backup -Destination $shortcutBackup.Original -Force
    }

    if (Test-Path -LiteralPath $productKey) {
        Remove-Item -LiteralPath $productKey -Recurse -Force
    }
    if ($renamedProductKey -and (Test-Path -LiteralPath $backupKey)) {
        Rename-Item -LiteralPath $backupKey -NewName $ProductName
    }
}
