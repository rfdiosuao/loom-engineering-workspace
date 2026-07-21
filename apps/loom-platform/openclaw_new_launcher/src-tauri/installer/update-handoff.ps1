param(
    [Parameter(Mandatory = $true)][string]$Installer,
    [Parameter(Mandatory = $true)][string]$InstallRoot,
    [Parameter(Mandatory = $true)][string]$AppExe,
    [Parameter(Mandatory = $true)][string]$RecoveryRoot,
    [Parameter(Mandatory = $true)][string]$MarkerPath,
    [Parameter(Mandatory = $true)][int]$ParentPid,
    [Parameter(Mandatory = $true)][string]$Version,
    [switch]$RecoveryOnly,
    [switch]$TestMode
)

$ErrorActionPreference = "Stop"
$backupData = Join-Path $RecoveryRoot "data"
$backupApplication = Join-Path $RecoveryRoot "application"
$logPath = Join-Path $RecoveryRoot "update-handoff.log"
$markerDirectory = Split-Path -Parent $MarkerPath
$failureMarkerPath = Join-Path $markerDirectory "update-failed.json"
$healthMarkerPath = Join-Path $RecoveryRoot "new-version-health.txt"
$successMarkerPath = Join-Path $RecoveryRoot "update-success.json"
$registryBackup = Join-Path $RecoveryRoot "registry"
$runOncePath = "HKCU:\Software\Microsoft\Windows\CurrentVersion\RunOnce"
$runOnceName = "!LOOMUpdateRecovery"
$dataBackupComplete = $false
$originalDataPresent = $false
$applicationBackupComplete = $false
$registryBackupComplete = $false
$newProcess = $null
$updateMutex = $null
$updateMutexOwned = $false

function Write-UpdateLog([string]$Message) {
    try {
        Add-Content -LiteralPath $logPath -Encoding UTF8 -Value ((Get-Date -Format o) + " " + $Message) -ErrorAction Stop
    } catch {
        # Logging must never prevent rollback or recovery metadata from being written.
    }
}

function Assert-SafeUpdatePaths {
    $normalizedInstall = [System.IO.Path]::GetFullPath($InstallRoot).TrimEnd(
        [System.IO.Path]::DirectorySeparatorChar,
        [System.IO.Path]::AltDirectorySeparatorChar
    )
    $installVolumeRoot = [System.IO.Path]::GetPathRoot($normalizedInstall).TrimEnd(
        [System.IO.Path]::DirectorySeparatorChar,
        [System.IO.Path]::AltDirectorySeparatorChar
    )
    if ($normalizedInstall.Equals($installVolumeRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "refusing to update a volume root: $normalizedInstall"
    }
    $installPrefix = $normalizedInstall + [System.IO.Path]::DirectorySeparatorChar
    $normalizedApp = [System.IO.Path]::GetFullPath($AppExe)
    if (-not $normalizedApp.StartsWith($installPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "application executable is outside install root: $normalizedApp"
    }

    $normalizedRecovery = [System.IO.Path]::GetFullPath($RecoveryRoot).TrimEnd(
        [System.IO.Path]::DirectorySeparatorChar,
        [System.IO.Path]::AltDirectorySeparatorChar
    )
    $recoveryPrefix = $normalizedRecovery + [System.IO.Path]::DirectorySeparatorChar
    if (
        $normalizedRecovery.Equals($normalizedInstall, [System.StringComparison]::OrdinalIgnoreCase) -or
        $normalizedRecovery.StartsWith($installPrefix, [System.StringComparison]::OrdinalIgnoreCase) -or
        $normalizedInstall.StartsWith($recoveryPrefix, [System.StringComparison]::OrdinalIgnoreCase)
    ) {
        throw "recovery root must be external to install root: $normalizedRecovery"
    }

    $normalizedMarker = [System.IO.Path]::GetFullPath($MarkerPath)
    if ($normalizedMarker.StartsWith($installPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "update marker must be external to install root: $normalizedMarker"
    }
    $normalizedInstaller = [System.IO.Path]::GetFullPath($Installer)
    if ($normalizedInstaller.StartsWith($installPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "update installer must be external to install root: $normalizedInstaller"
    }
}

function Copy-DataTree([string]$Source, [string]$Destination) {
    if (-not (Test-Path -LiteralPath $Source)) {
        return
    }
    New-Item -ItemType Directory -Force -Path $Destination | Out-Null
    & "$env:WINDIR\System32\robocopy.exe" $Source $Destination /E /COPY:DAT /DCOPY:DAT /R:2 /W:1 /NFL /NDL /NJH /NJS | Out-Null
    if ($LASTEXITCODE -gt 7) {
        throw "robocopy failed: exit=$LASTEXITCODE source=$Source destination=$Destination"
    }
}

function Get-CommandExecutablePath([string]$CommandLine) {
    if (-not $CommandLine) {
        return ""
    }
    $trimmed = $CommandLine.Trim()
    if ($trimmed.StartsWith('"')) {
        $closingQuote = $trimmed.IndexOf('"', 1)
        if ($closingQuote -gt 1) {
            return $trimmed.Substring(1, $closingQuote - 1)
        }
        return ""
    }
    return ($trimmed -split '\s+', 2)[0]
}

function Get-OwnedInstallProcesses([string]$Root) {
    $normalizedRoot = [System.IO.Path]::GetFullPath($Root).TrimEnd(
        [System.IO.Path]::DirectorySeparatorChar,
        [System.IO.Path]::AltDirectorySeparatorChar
    )
    $rootPrefix = $normalizedRoot + [System.IO.Path]::DirectorySeparatorChar

    $processRows = @()
    try {
        $processRows = @(Get-CimInstance Win32_Process -ErrorAction Stop)
    } catch {
        Write-UpdateLog ("CIM process scan failed; using direct process scan: " + $_.Exception.Message)
    }
    if ($processRows.Count -eq 0) {
        try {
            $processRows = @(Get-Process -ErrorAction Stop | ForEach-Object {
                $livePath = ""
                try {
                    $livePath = [string]$_.Path
                } catch {
                    $livePath = ""
                }
                [pscustomobject]@{
                    ProcessId = $_.Id
                    Name = $_.ProcessName
                    ExecutablePath = $livePath
                    CommandLine = ""
                }
            })
        } catch {
            throw "direct process scan failed after CIM was unavailable: $($_.Exception.Message)"
        }
    }

    $processRows | Where-Object {
        if ($_.ProcessId -eq $PID) {
            return $false
        }
        $executablePath = [string]$_.ExecutablePath
        if (-not $executablePath) {
            $liveProcess = Get-Process -Id $_.ProcessId -ErrorAction SilentlyContinue
            if ($liveProcess) {
                try {
                    $executablePath = [string]$liveProcess.Path
                } catch {
                    $executablePath = ""
                }
            }
        }
        if (-not $executablePath) {
            $executablePath = Get-CommandExecutablePath -CommandLine ([string]$_.CommandLine)
        }
        if ($executablePath) {
            try {
                $executablePath = [System.IO.Path]::GetFullPath($executablePath)
            } catch {
                $executablePath = ""
            }
        }
        $executableOwned = $executablePath -and (
            $executablePath.Equals($normalizedRoot, [System.StringComparison]::OrdinalIgnoreCase) -or
            $executablePath.StartsWith($rootPrefix, [System.StringComparison]::OrdinalIgnoreCase)
        )
        $owned = $executableOwned
        if ($owned) {
            $_ | Add-Member -NotePropertyName LoomExecutablePath -NotePropertyValue $executablePath -Force
        }
        return $owned
    }
}

function Test-ProcessExited([int]$ProcessId) {
    $liveProcess = $null
    try {
        $liveProcess = [System.Diagnostics.Process]::GetProcessById($ProcessId)
        $liveProcess.Refresh()
        return $liveProcess.HasExited
    } catch [System.ArgumentException] {
        return $true
    } catch {
        Write-UpdateLog ("failed to verify process exit pid={0}: {1}" -f $ProcessId, $_.Exception.Message)
        return $false
    } finally {
        if ($null -ne $liveProcess) {
            $liveProcess.Dispose()
        }
    }
}

function Invoke-TaskKillProcessTree([int]$ProcessId) {
    $taskkillExit = $null
    $taskkillOutput = @()
    if ($TestMode -and $env:LOOM_UPDATE_TEST_TASKKILL_FAILURE -eq "1") {
        $taskkillExit = 1455
        $taskkillOutput = @("The paging file is too small for this operation to complete.")
    } else {
        $previousErrorActionPreference = $ErrorActionPreference
        try {
            $ErrorActionPreference = "Continue"
            $taskkillOutput = @(& "$env:WINDIR\System32\taskkill.exe" /F /T /PID ([string]$ProcessId) 2>&1)
            $taskkillExit = $LASTEXITCODE
        } catch {
            $taskkillOutput = @($_.Exception.Message)
        } finally {
            $ErrorActionPreference = $previousErrorActionPreference
        }
    }

    if ($null -eq $taskkillExit) {
        $taskkillExit = -1
    }
    if ($taskkillExit -eq 0 -and (Test-ProcessExited -ProcessId $ProcessId)) {
        return $true
    }

    $failureText = (($taskkillOutput | ForEach-Object { [string]$_ }) -join " ").Trim()
    if ($failureText.Length -gt 500) {
        $failureText = $failureText.Substring(0, 500)
    }
    Write-UpdateLog ("taskkill failed pid={0} exit={1} error={2}" -f $ProcessId, $taskkillExit, $failureText)
    return (Test-ProcessExited -ProcessId $ProcessId)
}

function Stop-ProcessDirect([int]$ProcessId) {
    if ($TestMode -and $env:LOOM_UPDATE_TEST_DIRECT_STOP_FAILURE -eq "1") {
        Write-UpdateLog "direct process termination failed pid=$ProcessId error=injected test failure"
        return $false
    }

    $liveProcess = $null
    try {
        $liveProcess = [System.Diagnostics.Process]::GetProcessById($ProcessId)
    } catch [System.ArgumentException] {
        return $true
    } catch {
        Write-UpdateLog ("direct process lookup failed pid={0}: {1}" -f $ProcessId, $_.Exception.Message)
        return $false
    }

    try {
        $liveProcess.Kill()
        if (-not $liveProcess.WaitForExit(5000)) {
            Write-UpdateLog "direct process termination timed out pid=$ProcessId"
            return $false
        }
        $liveProcess.Refresh()
        if (-not $liveProcess.HasExited) {
            Write-UpdateLog "direct process termination was not verified pid=$ProcessId"
            return $false
        }
        Write-UpdateLog "direct process termination verified pid=$ProcessId"
        return $true
    } catch {
        if (Test-ProcessExited -ProcessId $ProcessId) {
            Write-UpdateLog "direct process termination verified pid=$ProcessId"
            return $true
        }
        Write-UpdateLog ("direct process termination failed pid={0}: {1}" -f $ProcessId, $_.Exception.Message)
        return $false
    } finally {
        $liveProcess.Dispose()
    }
}

function Stop-ProcessWithFallback([int]$ProcessId) {
    if (Invoke-TaskKillProcessTree -ProcessId $ProcessId) {
        return $true
    }
    return (Stop-ProcessDirect -ProcessId $ProcessId)
}

function Stop-OwnedInstallProcesses([string]$Root) {
    $stopTimeoutMilliseconds = 15000
    if ($TestMode -and $env:LOOM_UPDATE_TEST_PROCESS_STOP_TIMEOUT_MS) {
        $configuredTimeout = 0
        if (
            [int]::TryParse($env:LOOM_UPDATE_TEST_PROCESS_STOP_TIMEOUT_MS, [ref]$configuredTimeout) -and
            $configuredTimeout -ge 100 -and
            $configuredTimeout -le 15000
        ) {
            $stopTimeoutMilliseconds = $configuredTimeout
        }
    }
    $deadline = [DateTime]::UtcNow.AddMilliseconds($stopTimeoutMilliseconds)
    $loggedPids = @{}
    $emptyScans = 0
    do {
        $owned = @(Get-OwnedInstallProcesses -Root $Root)
        if ($owned.Count -eq 0) {
            $emptyScans += 1
            if ($emptyScans -ge 2) {
                return
            }
        } else {
            $emptyScans = 0
            foreach ($process in $owned) {
                $ownedPid = [string]$process.ProcessId
                if (-not $loggedPids.ContainsKey($ownedPid)) {
                    Write-UpdateLog (
                        "stopping owned process pid={0} name={1} executable={2}" -f
                        $process.ProcessId,
                        $process.Name,
                        ([string]$process.LoomExecutablePath)
                    )
                    $loggedPids[$ownedPid] = $true
                }
                if (-not (Stop-ProcessWithFallback -ProcessId ([int]$ownedPid))) {
                    Write-UpdateLog "owned process remains after termination attempts pid=$ownedPid"
                }
            }
        }
        Start-Sleep -Milliseconds 200
    } while ([DateTime]::UtcNow -lt $deadline)

    $remaining = @(Get-OwnedInstallProcesses -Root $Root)
    if ($remaining.Count -eq 0) {
        return
    }
    $details = ($remaining | ForEach-Object {
        "pid={0} name={1}" -f $_.ProcessId, $_.Name
    }) -join "; "
    throw "owned processes did not exit before update: $details"
}

function Restore-DataTree([string]$Source, [string]$Destination) {
    if (Test-Path -LiteralPath $Destination) {
        Remove-Item -LiteralPath $Destination -Recurse -Force
    }
    if (-not (Test-Path -LiteralPath $Source -PathType Container)) {
        return
    }
    New-Item -ItemType Directory -Force -Path $Destination | Out-Null
    & "$env:WINDIR\System32\robocopy.exe" $Source $Destination /E /COPY:DAT /DCOPY:DAT /XJ /R:2 /W:1 /NFL /NDL /NJH /NJS | Out-Null
    if ($LASTEXITCODE -gt 7) {
        throw "data restore failed: exit=$LASTEXITCODE source=$Source destination=$Destination"
    }
}

function Copy-ApplicationTree([string]$Source, [string]$Destination) {
    if (-not (Test-Path -LiteralPath $Source -PathType Container)) {
        throw "install root does not exist: $Source"
    }
    if (Test-Path -LiteralPath $Destination) {
        Remove-Item -LiteralPath $Destination -Recurse -Force
    }
    New-Item -ItemType Directory -Force -Path $Destination | Out-Null
    $sourceData = Join-Path $Source "data"
    & "$env:WINDIR\System32\robocopy.exe" $Source $Destination /E /COPY:DAT /DCOPY:DAT /XJ /R:2 /W:1 /NFL /NDL /NJH /NJS /XD $sourceData | Out-Null
    if ($LASTEXITCODE -gt 7) {
        throw "application backup failed: exit=$LASTEXITCODE source=$Source destination=$Destination"
    }
}

function Restore-ApplicationTree([string]$Source, [string]$Destination, [string]$ExpectedExecutable) {
    if (-not (Test-Path -LiteralPath $Source -PathType Container)) {
        throw "application backup is unavailable: $Source"
    }
    New-Item -ItemType Directory -Force -Path $Destination | Out-Null
    Get-ChildItem -LiteralPath $Destination -Force | Where-Object {
        $_.Name -ne "data"
    } | ForEach-Object {
        Remove-Item -LiteralPath $_.FullName -Recurse -Force
    }
    & "$env:WINDIR\System32\robocopy.exe" $Source $Destination /E /COPY:DAT /DCOPY:DAT /XJ /R:2 /W:1 /NFL /NDL /NJH /NJS | Out-Null
    if ($LASTEXITCODE -gt 7) {
        throw "application restore failed: exit=$LASTEXITCODE source=$Source destination=$Destination"
    }
    if (-not (Test-Path -LiteralPath $ExpectedExecutable -PathType Leaf)) {
        throw "restored application executable is missing: $ExpectedExecutable"
    }
}

function ConvertTo-RegistryProviderPath([string]$NativePath) {
    if ($NativePath.StartsWith("HKCU\", [System.StringComparison]::OrdinalIgnoreCase)) {
        return "Registry::HKEY_CURRENT_USER\" + $NativePath.Substring(5)
    }
    throw "unsupported uninstall registry root: $NativePath"
}

function Get-OwnedUninstallRegistryKeys {
    if ($env:LOOM_UPDATE_TEST_PRODUCT_KEY) {
        return @($env:LOOM_UPDATE_TEST_PRODUCT_KEY)
    }
    $nativeRoot = if ($env:LOOM_UPDATE_TEST_UNINSTALL_ROOT) {
        $env:LOOM_UPDATE_TEST_UNINSTALL_ROOT.TrimEnd("\")
    } else {
        "HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall"
    }
    $providerRoot = ConvertTo-RegistryProviderPath -NativePath $nativeRoot
    if (-not (Test-Path -LiteralPath $providerRoot)) {
        return @()
    }
    $normalizedInstall = [System.IO.Path]::GetFullPath($InstallRoot).TrimEnd("\")
    $ownedKeys = @()
    Get-ChildItem -LiteralPath $providerRoot -ErrorAction SilentlyContinue | ForEach-Object {
        $properties = Get-ItemProperty -LiteralPath $_.PSPath -ErrorAction SilentlyContinue
        if (-not $properties) {
            return
        }
        $owned = @("InstallLocation", "DisplayIcon", "UninstallString", "QuietUninstallString") | Where-Object {
            $value = [string]$properties.$_
            $value -and $value.IndexOf($normalizedInstall, [System.StringComparison]::OrdinalIgnoreCase) -ge 0
        }
        if ($owned.Count -gt 0) {
            $ownedKeys += ($nativeRoot + "\" + $_.PSChildName)
        }
    }
    return @($ownedKeys)
}

function Backup-InstallerRegistryState {
    if (Test-Path -LiteralPath $registryBackup) {
        Remove-Item -LiteralPath $registryBackup -Recurse -Force
    }
    New-Item -ItemType Directory -Force -Path $registryBackup | Out-Null
    $entries = @()
    $index = 0
    $ownedKeys = @(Get-OwnedUninstallRegistryKeys)
    Write-UpdateLog "backing up installer registry keys count=$($ownedKeys.Count)"
    foreach ($nativeKey in $ownedKeys) {
        $fileName = "uninstall-$index.reg"
        $filePath = Join-Path $registryBackup $fileName
        & "$env:WINDIR\System32\reg.exe" export $nativeKey $filePath /y | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "failed to back up installer registry key: $nativeKey"
        }
        $entries += [pscustomobject]@{ key = $nativeKey; file = $fileName }
        $index += 1
    }
    [pscustomobject]@{ keys = @($entries) } | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $registryBackup "manifest.json") -Encoding UTF8
}

function Restore-InstallerRegistryState {
    $manifestPath = Join-Path $registryBackup "manifest.json"
    if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
        return
    }
    $manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $keysToDelete = @(
        @(Get-OwnedUninstallRegistryKeys)
        @($manifest.keys | ForEach-Object { [string]$_.key })
    ) | Where-Object { $_ } | Select-Object -Unique
    Write-UpdateLog "restoring installer registry keys count=$(@($manifest.keys).Count)"
    foreach ($nativeKey in $keysToDelete) {
        & "$env:WINDIR\System32\reg.exe" delete $nativeKey /f | Out-Null
        if ($LASTEXITCODE -ne 0 -and $LASTEXITCODE -ne 1) {
            throw "failed to remove replacement installer registry key: $nativeKey"
        }
    }
    foreach ($entry in @($manifest.keys)) {
        $filePath = Join-Path $registryBackup ([string]$entry.file)
        & "$env:WINDIR\System32\reg.exe" import $filePath | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "failed to restore installer registry key: $($entry.key)"
        }
        $providerPath = ConvertTo-RegistryProviderPath -NativePath ([string]$entry.key)
        if (-not (Test-Path -LiteralPath $providerPath)) {
            throw "restored installer registry key is missing: $($entry.key)"
        }
    }
}

function Quote-UpdateArgument([string]$Value) {
    if ($Value.Contains('"')) {
        throw "update recovery argument contains an unsupported quote"
    }
    return '"' + $Value + '"'
}

function Register-UpdateRecoveryRunOnce([switch]$Retry) {
    if ($TestMode) {
        return
    }
    $powershell = Join-Path $env:WINDIR "System32\WindowsPowerShell\v1.0\powershell.exe"
    $arguments = @(
        "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", $PSCommandPath,
        "-Installer", $Installer, "-InstallRoot", $InstallRoot, "-AppExe", $AppExe,
        "-RecoveryRoot", $RecoveryRoot, "-MarkerPath", $MarkerPath, "-ParentPid", "0",
        "-Version", $Version, "-RecoveryOnly"
    )
    $commandLine = (Quote-UpdateArgument $powershell) + " " + (($arguments | ForEach-Object { Quote-UpdateArgument ([string]$_) }) -join " ")
    $valueName = if ($Retry) {
        $runOnceName + "Retry-" + [guid]::NewGuid().ToString("N")
    } else {
        $runOnceName
    }
    New-Item -ItemType Directory -Force -Path $runOncePath | Out-Null
    New-ItemProperty -Path $runOncePath -Name $valueName -Value $commandLine -PropertyType String -Force | Out-Null
}

function Clear-UpdateRecoveryRunOnce {
    if ($TestMode) {
        return
    }
    $runOnce = Get-ItemProperty -Path $runOncePath -ErrorAction SilentlyContinue
    if (-not $runOnce) {
        return
    }
    $runOnce.PSObject.Properties | Where-Object {
        $_.Name.StartsWith($runOnceName, [System.StringComparison]::OrdinalIgnoreCase)
    } | ForEach-Object {
        Remove-ItemProperty -Path $runOncePath -Name $_.Name -Force -ErrorAction SilentlyContinue
    }
}

function Acquire-UpdateHandoffMutex {
    $script:updateMutex = [System.Threading.Mutex]::new($false, "Local\LOOM.Update.Handoff")
    try {
        $script:updateMutexOwned = $script:updateMutex.WaitOne([TimeSpan]::FromSeconds(45))
    } catch [System.Threading.AbandonedMutexException] {
        $script:updateMutexOwned = $true
    }
    if (-not $script:updateMutexOwned) {
        throw "another LOOM update handoff is already running"
    }
}

function Release-UpdateHandoffMutex {
    if ($script:updateMutexOwned -and $null -ne $script:updateMutex) {
        try {
            $script:updateMutex.ReleaseMutex()
        } catch {
            Write-UpdateLog ("failed to release update mutex: " + $_.Exception.Message)
        }
    }
    if ($null -ne $script:updateMutex) {
        $script:updateMutex.Dispose()
    }
    $script:updateMutexOwned = $false
    $script:updateMutex = $null
}

function Prune-SuccessfulRecoveryBackups([string]$CurrentRecoveryRoot, [string]$CurrentInstallRoot) {
    $parent = Split-Path -Parent $CurrentRecoveryRoot
    if (-not (Test-Path -LiteralPath $parent -PathType Container)) {
        return
    }
    $current = [System.IO.Path]::GetFullPath($CurrentRecoveryRoot).TrimEnd(
        [System.IO.Path]::DirectorySeparatorChar,
        [System.IO.Path]::AltDirectorySeparatorChar
    )
    Get-ChildItem -LiteralPath $parent -Directory -Force -ErrorAction SilentlyContinue | ForEach-Object {
        $candidate = [System.IO.Path]::GetFullPath($_.FullName).TrimEnd(
            [System.IO.Path]::DirectorySeparatorChar,
            [System.IO.Path]::AltDirectorySeparatorChar
        )
        $successMarker = Join-Path $candidate "update-success.json"
        if (
            -not $candidate.Equals($current, [System.StringComparison]::OrdinalIgnoreCase) -and
            (($_.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -eq 0) -and
            (Test-Path -LiteralPath $successMarker -PathType Leaf)
        ) {
            try {
                $marker = Get-Content -LiteralPath $successMarker -Raw -Encoding UTF8 | ConvertFrom-Json
                $markerInstall = [System.IO.Path]::GetFullPath([string]$marker.installRoot).TrimEnd("\")
                $expectedInstall = [System.IO.Path]::GetFullPath($CurrentInstallRoot).TrimEnd("\")
                if (
                    [string]$marker.state -eq "healthy" -and
                    $markerInstall.Equals($expectedInstall, [System.StringComparison]::OrdinalIgnoreCase)
                ) {
                    Remove-Item -LiteralPath $candidate -Recurse -Force -ErrorAction Stop
                    Write-UpdateLog "pruned successful recovery backup: $candidate"
                }
            } catch {
                Write-UpdateLog ("retained unreadable recovery backup: " + $candidate)
            }
        }
    }
}

function Wait-NewVersionHealth {
    $healthNonce = [guid]::NewGuid().ToString("N")
    Remove-Item -LiteralPath $healthMarkerPath -Force -ErrorAction SilentlyContinue

    if ($TestMode) {
        if ($env:LOOM_UPDATE_TEST_HEALTH_MODE -eq "fail") {
            throw "new LOOM health check failed in test mode"
        }
        Set-Content -LiteralPath $healthMarkerPath -Value $healthNonce -Encoding ASCII
        if ($env:LOOM_UPDATE_TEST_HEALTH_MODE -eq "late-fail") {
            throw "new LOOM exited during health stabilization in test mode"
        }
        return
    }

    $previousMarker = $env:LOOM_UPDATE_HEALTH_MARKER
    $previousNonce = $env:LOOM_UPDATE_HEALTH_NONCE
    try {
        $env:LOOM_UPDATE_HEALTH_MARKER = $healthMarkerPath
        $env:LOOM_UPDATE_HEALTH_NONCE = $healthNonce
        $script:newProcess = Start-Process -FilePath $AppExe -WorkingDirectory $InstallRoot -PassThru
    } finally {
        $env:LOOM_UPDATE_HEALTH_MARKER = $previousMarker
        $env:LOOM_UPDATE_HEALTH_NONCE = $previousNonce
    }

    $healthDeadline = [DateTime]::UtcNow.AddSeconds(120)
    while ([DateTime]::UtcNow -lt $healthDeadline) {
        if (Test-Path -LiteralPath $healthMarkerPath -PathType Leaf) {
            $acknowledgedNonce = (Get-Content -LiteralPath $healthMarkerPath -Raw -ErrorAction Stop).Trim()
            if ($acknowledgedNonce -eq $healthNonce) {
                $stabilityDeadline = [DateTime]::UtcNow.AddSeconds(3)
                while ([DateTime]::UtcNow -lt $stabilityDeadline) {
                    if (-not (Test-Path -LiteralPath $healthMarkerPath -PathType Leaf)) {
                        throw "new LOOM withdrew health confirmation during stabilization"
                    }
                    $stableNonce = (Get-Content -LiteralPath $healthMarkerPath -Raw -ErrorAction Stop).Trim()
                    if ($stableNonce -ne $healthNonce) {
                        throw "new LOOM health confirmation changed during stabilization"
                    }
                    $script:newProcess.Refresh()
                    if ($script:newProcess.HasExited) {
                        throw "new LOOM exited during health stabilization: exit=$($script:newProcess.ExitCode)"
                    }
                    Start-Sleep -Milliseconds 250
                }
                return
            }
        }
        $script:newProcess.Refresh()
        if ($script:newProcess.HasExited) {
            throw "new LOOM exited before health confirmation: exit=$($script:newProcess.ExitCode)"
        }
        Start-Sleep -Milliseconds 250
    }
    throw "new LOOM did not confirm health within 120 seconds"
}

if ($RecoveryOnly) {
    try {
        Assert-SafeUpdatePaths
        Acquire-UpdateHandoffMutex
        if (-not (Test-Path -LiteralPath $MarkerPath -PathType Leaf)) {
            Clear-UpdateRecoveryRunOnce
            Release-UpdateHandoffMutex
            exit 0
        }
        New-Item -ItemType Directory -Force -Path $markerDirectory | Out-Null
        Stop-OwnedInstallProcesses -Root $InstallRoot
        if (-not (Test-Path -LiteralPath $backupApplication -PathType Container)) {
            throw "interrupted update application backup is unavailable"
        }
        $pending = Get-Content -LiteralPath $MarkerPath -Raw -Encoding UTF8 | ConvertFrom-Json
        $pendingDataPresent = if ($null -ne $pending.originalDataPresent) {
            [bool]$pending.originalDataPresent
        } else {
            Test-Path -LiteralPath $backupData -PathType Container
        }
        if ($pendingDataPresent -and -not (Test-Path -LiteralPath $backupData -PathType Container)) {
            throw "interrupted update data backup is unavailable"
        }
        Restore-ApplicationTree -Source $backupApplication -Destination $InstallRoot -ExpectedExecutable $AppExe
        Restore-DataTree -Source $backupData -Destination (Join-Path $InstallRoot "data")
        Restore-InstallerRegistryState
        [pscustomobject]@{
            version = $Version
            installRoot = $InstallRoot
            state = "recovered_after_interruption"
            rollbackState = "restored"
            oldVersionLaunchable = $true
        } | ConvertTo-Json -Compress | Set-Content -LiteralPath $failureMarkerPath -Encoding UTF8
        Remove-Item -LiteralPath $MarkerPath -Force -ErrorAction SilentlyContinue
        Clear-UpdateRecoveryRunOnce
        Release-UpdateHandoffMutex
        Write-UpdateLog "interrupted update recovered successfully"
        if (-not $TestMode) {
            Start-Process -FilePath $AppExe -WorkingDirectory $InstallRoot | Out-Null
        }
        exit 0
    } catch {
        Write-UpdateLog ("interrupted update recovery failed: " + $_.Exception.Message)
        try {
            Register-UpdateRecoveryRunOnce -Retry
        } catch {
            Write-UpdateLog ("failed to schedule interrupted update retry: " + $_.Exception.Message)
        }
        Release-UpdateHandoffMutex
        exit 1
    }
}

try {
    Assert-SafeUpdatePaths
    New-Item -ItemType Directory -Force -Path $RecoveryRoot | Out-Null
    New-Item -ItemType Directory -Force -Path $markerDirectory | Out-Null
    Remove-Item -LiteralPath $failureMarkerPath -Force -ErrorAction SilentlyContinue
    Acquire-UpdateHandoffMutex
    $parentDeadline = [DateTime]::UtcNow.AddSeconds(30)
    while (Get-Process -Id $ParentPid -ErrorAction SilentlyContinue) {
        if ([DateTime]::UtcNow -ge $parentDeadline) {
            throw "parent process did not exit before update: pid=$ParentPid"
        }
        Start-Sleep -Milliseconds 200
    }

    Stop-OwnedInstallProcesses -Root $InstallRoot

    $sourceData = Join-Path $InstallRoot "data"
    $originalDataPresent = Test-Path -LiteralPath $sourceData -PathType Container
    Copy-DataTree -Source $sourceData -Destination $backupData
    $dataBackupComplete = $true
    Copy-ApplicationTree -Source $InstallRoot -Destination $backupApplication
    $applicationBackupComplete = $true
    Backup-InstallerRegistryState
    $registryBackupComplete = $true
    [pscustomobject]@{
        version = $Version
        installRoot = $InstallRoot
        backup = $backupData
        applicationBackup = $backupApplication
        originalDataPresent = [bool]$originalDataPresent
        dataBackupComplete = [bool]$dataBackupComplete
        registryBackupComplete = [bool]$registryBackupComplete
        state = "installing"
        rollbackState = "pending"
    } | ConvertTo-Json -Compress | Set-Content -LiteralPath $MarkerPath -Encoding UTF8
    Register-UpdateRecoveryRunOnce
    Write-UpdateLog "data and application backup complete; starting installer"

    & $Installer "/S" "/D=$InstallRoot"
    $setupExit = $LASTEXITCODE
    if ($null -eq $setupExit) {
        $setupExit = 0
    }
    if ($setupExit -ne 0) {
        throw "installer failed: exit=$setupExit"
    }
    if (-not (Test-Path -LiteralPath $AppExe -PathType Leaf)) {
        throw "installer completed without LOOM executable: $AppExe"
    }

    Restore-DataTree -Source $backupData -Destination (Join-Path $InstallRoot "data")
    Write-UpdateLog "installer complete; waiting for new LOOM health confirmation"
    Wait-NewVersionHealth

    [pscustomobject]@{
        version = $Version
        installRoot = $InstallRoot
        backup = $backupData
        applicationBackup = $backupApplication
        state = "healthy"
        confirmedAt = (Get-Date -Format o)
    } | ConvertTo-Json -Compress | Set-Content -LiteralPath $successMarkerPath -Encoding UTF8
    Remove-Item -LiteralPath $MarkerPath -Force -ErrorAction SilentlyContinue
    Clear-UpdateRecoveryRunOnce
    Prune-SuccessfulRecoveryBackups -CurrentRecoveryRoot $RecoveryRoot -CurrentInstallRoot $InstallRoot
    Release-UpdateHandoffMutex
    Write-UpdateLog "update complete; new LOOM confirmed healthy"
}
catch {
    $failureMessage = $_.Exception.Message
    $rollbackState = "not_available"
    $rollbackError = ""
    $oldVersionLaunchable = Test-Path -LiteralPath $AppExe -PathType Leaf
    Write-UpdateLog ("update failed: " + $failureMessage)
    if ($null -ne $newProcess) {
        try {
            $newProcess.Refresh()
            if (-not $newProcess.HasExited) {
                if (-not (Stop-ProcessWithFallback -ProcessId ([int]$newProcess.Id))) {
                    Write-UpdateLog "unhealthy new LOOM remains after termination attempts pid=$($newProcess.Id)"
                }
            }
        } catch {
            Write-UpdateLog ("failed to stop unhealthy new LOOM: " + $_.Exception.Message)
        }
    }
    try {
        Stop-OwnedInstallProcesses -Root $InstallRoot
    } catch {
        Write-UpdateLog ("failed to stop installer-owned processes before rollback: " + $_.Exception.Message)
    }

    $rollbackErrors = @()
    if ($dataBackupComplete) {
        try {
            Restore-DataTree -Source $backupData -Destination (Join-Path $InstallRoot "data")
        } catch {
            $rollbackErrors += ("data restore failed: " + $_.Exception.Message)
            Write-UpdateLog $rollbackErrors[-1]
        }
    }
    if ($applicationBackupComplete) {
        try {
            Restore-ApplicationTree -Source $backupApplication -Destination $InstallRoot -ExpectedExecutable $AppExe
        } catch {
            $rollbackErrors += ("application restore failed: " + $_.Exception.Message)
            Write-UpdateLog $rollbackErrors[-1]
        }
    }
    if ($registryBackupComplete) {
        try {
            Restore-InstallerRegistryState
        } catch {
            $rollbackErrors += ("registry restore failed: " + $_.Exception.Message)
            Write-UpdateLog $rollbackErrors[-1]
        }
    }

    $oldVersionLaunchable = Test-Path -LiteralPath $AppExe -PathType Leaf
    if ($applicationBackupComplete -and -not $oldVersionLaunchable) {
        $rollbackErrors += "old LOOM executable is missing after rollback"
    }
    if ($rollbackErrors.Count -gt 0) {
        $rollbackState = "failed"
        $rollbackError = $rollbackErrors -join "; "
        Write-UpdateLog ("rollback failed: " + $rollbackError)
    } elseif ($applicationBackupComplete -or $dataBackupComplete -or $registryBackupComplete) {
        $rollbackState = "restored"
    }
    Write-UpdateLog "rollback state=$rollbackState oldVersionLaunchable=$oldVersionLaunchable"

    $failureMarker = [pscustomobject]@{
        version = $Version
        installRoot = $InstallRoot
        backup = $backupData
        applicationBackup = $backupApplication
        state = "failed"
        error = $failureMessage
        rollbackState = $rollbackState
        rollbackError = $rollbackError
        oldVersionLaunchable = [bool]$oldVersionLaunchable
        recoveryActions = @(
            "Restart the previous LOOM version if it was restored.",
            "Keep the recovery directory until the update issue is resolved."
        )
    }
    try {
        New-Item -ItemType Directory -Force -Path $markerDirectory | Out-Null
        $failureMarker | ConvertTo-Json -Compress | Set-Content -LiteralPath $failureMarkerPath -Encoding UTF8 -ErrorAction Stop
    } catch {
        try {
            New-Item -ItemType Directory -Force -Path $RecoveryRoot | Out-Null
            $recoveryFailureMarkerPath = Join-Path $RecoveryRoot "update-failed.json"
            $failureMarker | ConvertTo-Json -Compress | Set-Content -LiteralPath $recoveryFailureMarkerPath -Encoding UTF8 -ErrorAction Stop
        } catch {
            Write-UpdateLog "failed to write recovery manifest"
        }
    } finally {
        Remove-Item -LiteralPath $MarkerPath -Force -ErrorAction SilentlyContinue
        Clear-UpdateRecoveryRunOnce
        Release-UpdateHandoffMutex
    }
    if (-not $TestMode -and $rollbackState -eq "restored" -and $oldVersionLaunchable) {
        try {
            Start-Process -FilePath $AppExe -WorkingDirectory $InstallRoot | Out-Null
        } catch {
            Write-UpdateLog ("failed to restart restored LOOM: " + $_.Exception.Message)
        }
    }
    exit 1
}
