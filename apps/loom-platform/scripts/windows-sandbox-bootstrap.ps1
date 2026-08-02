param(
    [Parameter(Mandatory = $true)]
    [string]$CandidateRoot,
    [Parameter(Mandatory = $true)]
    [string]$EvidenceRoot,
    [Parameter(Mandatory = $true)]
    [string]$InstallerName,
    [Parameter(Mandatory = $true)]
    [ValidatePattern("^[A-Fa-f0-9]{64}$")]
    [string]$ExpectedSha256
)

$ErrorActionPreference = "Stop"

function Get-Sha256Hash {
    param([string]$Path)
    $stream = [System.IO.File]::OpenRead($Path)
    $sha256 = [System.Security.Cryptography.SHA256]::Create()
    try {
        return ([System.BitConverter]::ToString(
            $sha256.ComputeHash($stream)
        )).Replace("-", "")
    }
    finally {
        $sha256.Dispose()
        $stream.Dispose()
    }
}

if ($InstallerName -ne [System.IO.Path]::GetFileName($InstallerName)) {
    throw "InstallerName must be a file name without path segments"
}
if (-not (Test-Path -LiteralPath $CandidateRoot -PathType Container)) {
    throw "CandidateRoot is unavailable: $CandidateRoot"
}
if (-not (Test-Path -LiteralPath $EvidenceRoot -PathType Container)) {
    throw "EvidenceRoot is unavailable: $EvidenceRoot"
}

$sourceInstaller = Join-Path $CandidateRoot $InstallerName
if (-not (Test-Path -LiteralPath $sourceInstaller -PathType Leaf)) {
    throw "Installer is missing inside the read-only candidate mapping"
}

$sessionId = [DateTimeOffset]::UtcNow.ToString("yyyyMMddTHHmmssZ") + "-$PID"
$sessionDirectory = Join-Path $EvidenceRoot $sessionId
New-Item -ItemType Directory -Path $sessionDirectory | Out-Null
$transcriptPath = Join-Path $sessionDirectory "bootstrap-transcript.txt"
Start-Transcript -LiteralPath $transcriptPath -Force | Out-Null

try {
    $operatingSystem = $null
    try {
        $operatingSystem = Get-CimInstance Win32_OperatingSystem -ErrorAction Stop
    }
    catch {
        $operatingSystem = [pscustomobject]@{
            Caption = [System.Environment]::OSVersion.VersionString
            Version = [System.Environment]::OSVersion.Version.ToString()
            BuildNumber = "unknown"
            OSArchitecture = [System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture.ToString()
        }
    }
    [pscustomobject]@{
        capturedAt = [DateTimeOffset]::UtcNow.ToString("o")
        computerName = $env:COMPUTERNAME
        userName = $env:USERNAME
        caption = $operatingSystem.Caption
        version = $operatingSystem.Version
        buildNumber = $operatingSystem.BuildNumber
        architecture = $operatingSystem.OSArchitecture
        sandbox = $true
        usbPassthrough = $false
    } | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (
        Join-Path $sessionDirectory "runtime-environment.json"
    ) -Encoding UTF8

    $sourceHash = Get-Sha256Hash -Path $sourceInstaller
    if ($sourceHash -ne $ExpectedSha256) {
        throw "Installer SHA256 does not match the host preparation record"
    }
    $signature = Get-AuthenticodeSignature -LiteralPath $sourceInstaller

    $localRoot = "C:\LumingAcceptance"
    if (-not (Test-Path -LiteralPath $localRoot)) {
        New-Item -ItemType Directory -Path $localRoot | Out-Null
    }
    $localInstaller = Join-Path $localRoot $InstallerName
    Copy-Item -LiteralPath $sourceInstaller -Destination $localInstaller
    $localHash = Get-Sha256Hash -Path $localInstaller
    if ($localHash -ne $ExpectedSha256) {
        throw "Local installer copy failed SHA256 verification"
    }

    [pscustomobject]@{
        source = $sourceInstaller
        localCopy = $localInstaller
        bytes = (Get-Item -LiteralPath $localInstaller).Length
        sha256 = $localHash
        signatureStatus = [string]$signature.Status
        signer = if ($null -ne $signature.SignerCertificate) {
            [string]$signature.SignerCertificate.Subject
        } else {
            ""
        }
    } | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (
        Join-Path $sessionDirectory "installer-manifest.json"
    ) -Encoding UTF8

    $checklist = "C:\LumingHarness\windows-sandbox-acceptance-checklist.md"
    if (Test-Path -LiteralPath $checklist -PathType Leaf) {
        Start-Process -FilePath "notepad.exe" -ArgumentList ('"' + $checklist + '"')
    }

    $installerProcess = Start-Process -FilePath $localInstaller -PassThru -Wait
    [pscustomobject]@{
        completedAt = [DateTimeOffset]::UtcNow.ToString("o")
        exitCode = $installerProcess.ExitCode
        interactive = $true
    } | ConvertTo-Json | Set-Content -LiteralPath (
        Join-Path $sessionDirectory "installer-result.json"
    ) -Encoding UTF8
    if ($installerProcess.ExitCode -ne 0) {
        throw "Interactive installer exited with code $($installerProcess.ExitCode)"
    }

    $appCandidates = [System.Collections.Generic.List[string]]::new()
    $uninstallRoots = @(
        "HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*",
        "HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*",
        "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*"
    )
    foreach ($uninstallRoot in $uninstallRoots) {
        Get-ItemProperty -Path $uninstallRoot -ErrorAction SilentlyContinue |
            Where-Object {
                [string]$_.DisplayName -match "麓鸣|LOOM|Luming"
            } |
            ForEach-Object {
                if (-not [string]::IsNullOrWhiteSpace([string]$_.DisplayIcon)) {
                    $displayIcon = ([string]$_.DisplayIcon).Split(",")[0].Trim('"')
                    $appCandidates.Add($displayIcon)
                }
                if (-not [string]::IsNullOrWhiteSpace([string]$_.InstallLocation)) {
                    $appCandidates.Add((Join-Path ([string]$_.InstallLocation) "LOOM.exe"))
                }
            }
    }
    foreach ($root in @($env:ProgramFiles, ${env:ProgramFiles(x86)}, $env:LOCALAPPDATA)) {
        if (-not [string]::IsNullOrWhiteSpace($root)) {
            $appCandidates.Add((Join-Path $root "麓鸣\LOOM.exe"))
            $appCandidates.Add((Join-Path $root "LOOM\LOOM.exe"))
        }
    }
    $appPath = $appCandidates | Where-Object {
        Test-Path -LiteralPath $_ -PathType Leaf
    } | Select-Object -First 1
    if ([string]::IsNullOrWhiteSpace([string]$appPath)) {
        throw "Installed LOOM.exe could not be located from Uninstall records or standard paths"
    }

    [pscustomobject]@{
        locatedAt = [DateTimeOffset]::UtcNow.ToString("o")
        executable = $appPath
    } | ConvertTo-Json | Set-Content -LiteralPath (
        Join-Path $sessionDirectory "application-location.json"
    ) -Encoding UTF8
    Start-Process -FilePath $appPath | Out-Null

    @(
        "麓鸣已启动，请严格按记事本中的逐按钮清单验收。",
        "截图、脱敏说明和人工结论请保存到：$sessionDirectory",
        "关闭 Windows Sandbox 会清空客体；映射到 LumingEvidence 的文件会保留。"
    ) | Set-Content -LiteralPath (
        Join-Path $sessionDirectory "manual-acceptance-required.txt"
    ) -Encoding UTF8
    Start-Process -FilePath "explorer.exe" -ArgumentList ('"' + $sessionDirectory + '"')
}
catch {
    [pscustomobject]@{
        failedAt = [DateTimeOffset]::UtcNow.ToString("o")
        errorType = $_.Exception.GetType().FullName
        message = $_.Exception.Message
    } | ConvertTo-Json | Set-Content -LiteralPath (
        Join-Path $sessionDirectory "bootstrap-failure.json"
    ) -Encoding UTF8
    throw
}
finally {
    Stop-Transcript | Out-Null
}
