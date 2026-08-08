[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$InstallRoot
)

$ErrorActionPreference = "Stop"
$legacyDirectoryName = "Luming AI Matrix Acquisition Workbench"
$logPath = Join-Path $env:TEMP "loom-legacy-data-migration.log"
$copied = 0
$preserved = 0
$skippedLinks = 0

function Write-MigrationLog {
    param([string]$Message)
    $line = "{0} {1}" -f (Get-Date).ToUniversalTime().ToString("o"), $Message
    Add-Content -LiteralPath $logPath -Value $line -Encoding UTF8
}

function Test-ReparsePoint {
    param([System.IO.FileSystemInfo]$Item)
    return (($Item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0)
}

function Get-SafeDestinationDirectory {
    param(
        [string]$DataRoot,
        [string]$RelativeDirectory
    )
    $current = [System.IO.Path]::GetFullPath($DataRoot)
    if (-not [System.IO.Directory]::Exists($current)) {
        [System.IO.Directory]::CreateDirectory($current) | Out-Null
    }
    $rootInfo = [System.IO.DirectoryInfo]::new($current)
    if (Test-ReparsePoint $rootInfo) {
        throw "Destination data root is a reparse point."
    }
    foreach ($segment in @($RelativeDirectory -split '[\\/]' | Where-Object { $_ })) {
        if ($segment -eq "." -or $segment -eq "..") {
            throw "Unsafe relative destination path."
        }
        $current = [System.IO.Path]::Combine($current, $segment)
        if ([System.IO.Directory]::Exists($current)) {
            $directoryInfo = [System.IO.DirectoryInfo]::new($current)
            if (Test-ReparsePoint $directoryInfo) {
                throw "Destination directory is a reparse point."
            }
        }
        else {
            [System.IO.Directory]::CreateDirectory($current) | Out-Null
        }
    }
    return $current
}

try {
    $installRootFull = [System.IO.Path]::GetFullPath($InstallRoot).TrimEnd('\', '/')
    $installParent = [System.IO.Directory]::GetParent($installRootFull)
    if ($null -eq $installParent) {
        throw "Install root has no parent directory."
    }
    $legacyRoot = [System.IO.Path]::GetFullPath(
        [System.IO.Path]::Combine($installParent.FullName, $legacyDirectoryName)
    )
    $legacyData = [System.IO.Path]::Combine($legacyRoot, "data")
    $targetData = [System.IO.Path]::Combine($installRootFull, "data")

    if (-not [System.IO.Directory]::Exists($legacyData)) {
        Write-MigrationLog "No exact legacy product data directory was found."
        Write-Output "copied=0 preserved=0 skippedLinks=0"
        exit 0
    }
    $legacyDataInfo = [System.IO.DirectoryInfo]::new($legacyData)
    if (Test-ReparsePoint $legacyDataInfo) {
        throw "Legacy data root is a reparse point."
    }
    Get-SafeDestinationDirectory -DataRoot $targetData -RelativeDirectory "" | Out-Null

    $queue = [System.Collections.Generic.Queue[System.IO.DirectoryInfo]]::new()
    $queue.Enqueue($legacyDataInfo)
    while ($queue.Count -gt 0) {
        $directory = $queue.Dequeue()
        foreach ($entry in $directory.GetFileSystemInfos()) {
            if (Test-ReparsePoint $entry) {
                $skippedLinks += 1
                continue
            }
            if ($entry -is [System.IO.DirectoryInfo]) {
                $queue.Enqueue($entry)
                continue
            }
            if (-not ($entry -is [System.IO.FileInfo])) {
                continue
            }

            $relativePath = $entry.FullName.Substring($legacyData.Length).TrimStart('\', '/')
            $relativeDirectory = [System.IO.Path]::GetDirectoryName($relativePath)
            $destinationDirectory = Get-SafeDestinationDirectory `
                -DataRoot $targetData `
                -RelativeDirectory $relativeDirectory
            $destinationPath = [System.IO.Path]::Combine(
                $destinationDirectory,
                [System.IO.Path]::GetFileName($relativePath)
            )
            if ([System.IO.File]::Exists($destinationPath) -or [System.IO.Directory]::Exists($destinationPath)) {
                $preserved += 1
                continue
            }

            $sourceStream = $null
            $destinationStream = $null
            $createdDestination = $false
            $copyError = $null
            try {
                $sourceStream = [System.IO.File]::Open(
                    $entry.FullName,
                    [System.IO.FileMode]::Open,
                    [System.IO.FileAccess]::Read,
                    [System.IO.FileShare]::Read
                )
                $destinationStream = [System.IO.File]::Open(
                    $destinationPath,
                    [System.IO.FileMode]::CreateNew,
                    [System.IO.FileAccess]::Write,
                    [System.IO.FileShare]::None
                )
                $createdDestination = $true
                $sourceStream.CopyTo($destinationStream)
                $destinationStream.Flush()
                $copied += 1
            }
            catch [System.IO.IOException] {
                $copyError = $_
            }
            finally {
                if ($null -ne $destinationStream) { $destinationStream.Dispose() }
                if ($null -ne $sourceStream) { $sourceStream.Dispose() }
            }
            if ($null -ne $copyError) {
                if ($createdDestination) {
                    [System.IO.File]::Delete($destinationPath)
                    throw $copyError
                }
                if ([System.IO.File]::Exists($destinationPath)) {
                    $preserved += 1
                    continue
                }
                throw $copyError
            }
        }
    }

    Write-MigrationLog "Migration completed: copied=$copied preserved=$preserved skippedLinks=$skippedLinks"
    Write-Output "copied=$copied preserved=$preserved skippedLinks=$skippedLinks"
    exit 0
}
catch {
    Write-MigrationLog ("Migration failed: " + $_.Exception.Message)
    Write-Error "Legacy product data migration failed. See $logPath"
    exit 1
}
