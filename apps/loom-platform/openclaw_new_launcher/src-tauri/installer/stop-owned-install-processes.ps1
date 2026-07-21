param(
    [Parameter(Mandatory = $true)]
    [string]$InstallRoot
)

$ErrorActionPreference = "Stop"
$logPath = Join-Path $env:TEMP "LOOM-installer-process-cleanup.log"

function Write-CleanupLog([string]$Message) {
    try {
        Add-Content -LiteralPath $logPath -Encoding UTF8 -Value (
            "[{0}] pid={1} {2}" -f (Get-Date -Format o), $PID, $Message
        )
    }
    catch {
        # Logging must never prevent an otherwise safe upgrade.
    }
}

function Resolve-NormalizedPath([string]$Path) {
    return [System.IO.Path]::GetFullPath($Path).TrimEnd(
        [System.IO.Path]::DirectorySeparatorChar,
        [System.IO.Path]::AltDirectorySeparatorChar
    )
}

$resolvedRoot = Resolve-NormalizedPath $InstallRoot
if (-not (Test-Path -LiteralPath $resolvedRoot -PathType Container)) {
    Write-CleanupLog "install root does not exist; no cleanup required root=$resolvedRoot"
    exit 0
}
$ownedPrefix = $resolvedRoot + [System.IO.Path]::DirectorySeparatorChar

function Get-ProcessExecutablePath($Process) {
    $executablePath = ""
    try {
        $executablePath = [string]$Process.Path
    }
    catch {
        $executablePath = ""
    }
    if ([string]::IsNullOrWhiteSpace($executablePath)) {
        try {
            $executablePath = [string]$Process.MainModule.FileName
        }
        catch {
            $executablePath = ""
        }
    }
    return $executablePath
}

function Get-OwnedInstallProcesses {
    # Direct process inspection is intentionally primary. CIM/WMI can fail with
    # ERROR_COMMITMENT_LIMIT on memory-constrained customer machines.
    $rows = @(Get-Process -ErrorAction SilentlyContinue | ForEach-Object {
        [pscustomobject]@{
            ProcessId = [int]$_.Id
            Name = [string]$_.ProcessName
            ExecutablePath = Get-ProcessExecutablePath -Process $_
        }
    })

    return @($rows | Where-Object {
        $processId = [int]$_.ProcessId
        $executablePath = [string]$_.ExecutablePath
        if ($processId -eq $PID -or [string]::IsNullOrWhiteSpace($executablePath)) {
            return $false
        }
        try {
            $candidate = Resolve-NormalizedPath $executablePath
            return $candidate.StartsWith($ownedPrefix, [System.StringComparison]::OrdinalIgnoreCase)
        }
        catch {
            return $false
        }
    })
}

function Test-ProcessExited([int]$ProcessId) {
    return $null -eq (Get-Process -Id $ProcessId -ErrorAction SilentlyContinue)
}

function Invoke-TaskKillProcessTree([int]$ProcessId) {
    $taskkill = Join-Path $env:WINDIR "System32\taskkill.exe"
    try {
        & $taskkill /F /T /PID ([string]$ProcessId) 2>&1 | Out-Null
    }
    catch {
        Write-CleanupLog "taskkill threw pid=$ProcessId error=$($_.Exception.Message)"
    }
    if (Test-ProcessExited -ProcessId $ProcessId) {
        return $true
    }

    try {
        Stop-Process -Id $ProcessId -Force -ErrorAction Stop
    }
    catch {
        if (-not (Test-ProcessExited -ProcessId $ProcessId)) {
            Write-CleanupLog "direct stop failed pid=$ProcessId error=$($_.Exception.Message)"
            return $false
        }
    }
    return (Test-ProcessExited -ProcessId $ProcessId)
}

function Test-OwnedRuntimeFilesUnlocked {
    $runtimeFiles = @(
        (Join-Path $resolvedRoot "LOOM.exe"),
        (Join-Path $resolvedRoot "_up_\node-runtime\node.exe"),
        (Join-Path $resolvedRoot "_up_\python-runtime\python.exe"),
        (Join-Path $resolvedRoot "node-runtime\node.exe"),
        (Join-Path $resolvedRoot "python-runtime\python.exe")
    )
    foreach ($runtimeFile in $runtimeFiles) {
        if (-not (Test-Path -LiteralPath $runtimeFile -PathType Leaf)) {
            continue
        }
        $stream = $null
        try {
            $stream = [System.IO.File]::Open(
                $runtimeFile,
                [System.IO.FileMode]::Open,
                [System.IO.FileAccess]::Read,
                [System.IO.FileShare]::None
            )
        }
        catch {
            Write-CleanupLog "runtime remains locked path=$runtimeFile error=$($_.Exception.Message)"
            return $false
        }
        finally {
            if ($null -ne $stream) {
                $stream.Dispose()
            }
        }
    }
    return $true
}

Write-CleanupLog "cleanup started root=$resolvedRoot is64bit=$([Environment]::Is64BitProcess)"
$deadline = [DateTime]::UtcNow.AddSeconds(20)
$loggedPids = @{}
$emptyScans = 0
do {
    $owned = @(Get-OwnedInstallProcesses)
    if ($owned.Count -gt 0) {
        $emptyScans = 0
        # Stop the top-level launcher first so it cannot respawn its runtimes.
        $ordered = @($owned | Sort-Object {
            if ([string]$_.ExecutablePath -like ($ownedPrefix + "_up_*")) { 1 } else { 0 }
        })
        foreach ($process in $ordered) {
            $processId = [int]$process.ProcessId
            if (-not $loggedPids.ContainsKey([string]$processId)) {
                Write-CleanupLog (
                    "stopping owned process pid={0} name={1} path={2}" -f
                    $processId,
                    $process.Name,
                    $process.ExecutablePath
                )
                $loggedPids[[string]$processId] = $true
            }
            [void](Invoke-TaskKillProcessTree -ProcessId $processId)
        }
    }
    elseif (Test-OwnedRuntimeFilesUnlocked) {
        $emptyScans += 1
        if ($emptyScans -ge 5) {
            Write-CleanupLog "cleanup completed after five stable scans"
            exit 0
        }
    }
    else {
        $emptyScans = 0
    }
    Start-Sleep -Milliseconds 400
} while ([DateTime]::UtcNow -lt $deadline)

$remaining = @(Get-OwnedInstallProcesses)
$remainingIds = ($remaining | ForEach-Object { [string]$_.ProcessId }) -join ","
Write-CleanupLog "cleanup timed out remaining=$remainingIds"
throw "LOOM-owned processes or runtime file locks did not clear before installation: $remainingIds"
