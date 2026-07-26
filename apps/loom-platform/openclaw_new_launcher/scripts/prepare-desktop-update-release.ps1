param(
    [Parameter(Mandatory = $true)][string]$InstallerPath,
    [Parameter(Mandatory = $true)][string]$Version,
    [string]$OutputDirectory = "",
    [string]$ReleaseNotesPath = "",
    [string]$Product = "LOOM",
    [string]$Channel = "stable",
    [string]$ChannelId = "loom-stable",
    [string]$FilePrefix = "LOOM",
    [string]$DownloadUrl = "",
    [string]$MirrorBaseUrl = "",
    [long]$MirrorPartSizeBytes = 67108864,
    [string]$PublicKeyPath = ""
)

$ErrorActionPreference = "Stop"

if ($Version -notmatch '^\d+\.\d+\.\d+$') {
    throw "Version must use MAJOR.MINOR.PATCH format: $Version"
}
if (-not (Test-Path -LiteralPath $InstallerPath -PathType Leaf)) {
    throw "Installer does not exist: $InstallerPath"
}
if ([string]::IsNullOrWhiteSpace($PublicKeyPath)) {
    $PublicKeyPath = Join-Path (Split-Path -Parent $PSScriptRoot) "desktop-update-public-key.txt"
}
if (-not (Test-Path -LiteralPath $PublicKeyPath -PathType Leaf)) {
    throw "Desktop update public key does not exist: $PublicKeyPath"
}
$PublicKeyPath = (Resolve-Path -LiteralPath $PublicKeyPath).Path

$installer = (Resolve-Path -LiteralPath $InstallerPath).Path
if ([string]::IsNullOrWhiteSpace($OutputDirectory)) {
    $OutputDirectory = Join-Path (Split-Path -Parent $PSScriptRoot) "artifacts\desktop-update\$Version"
}
$outputRoot = [System.IO.Path]::GetFullPath($OutputDirectory)
New-Item -ItemType Directory -Force -Path $outputRoot | Out-Null

$signature = Get-AuthenticodeSignature -LiteralPath $installer
if ($signature.Status -ne "Valid" -and $signature.Status -ne "NotSigned") {
    throw "Installer signature is not valid: $($signature.Status) $($signature.StatusMessage)"
}

$canonicalName = "$FilePrefix-$Version-setup.exe"
$canonicalInstaller = Join-Path $outputRoot $canonicalName
Copy-Item -LiteralPath $installer -Destination $canonicalInstaller -Force

$hash = (Get-FileHash -LiteralPath $canonicalInstaller -Algorithm SHA256).Hash.ToLowerInvariant()
$sidecar = "$canonicalInstaller.sha256.txt"
$utf8NoBom = [System.Text.UTF8Encoding]::new($false)
[System.IO.File]::WriteAllText($sidecar, "$hash *$canonicalName`n", $utf8NoBom)

$mirrorParts = @()
$mirrorPartsJson = ""
if (-not [string]::IsNullOrWhiteSpace($MirrorBaseUrl)) {
    if (-not $MirrorBaseUrl.StartsWith("https://", [StringComparison]::OrdinalIgnoreCase)) {
        throw "MirrorBaseUrl must use HTTPS."
    }
    if ($MirrorPartSizeBytes -le 0 -or $MirrorPartSizeBytes -gt 100MB) {
        throw "MirrorPartSizeBytes must be between 1 byte and 100 MiB."
    }
    $normalizedMirrorBaseUrl = $MirrorBaseUrl.TrimEnd("/") + "/"
    $mirrorPartsRoot = Join-Path $outputRoot "mirror-parts"
    New-Item -ItemType Directory -Force -Path $mirrorPartsRoot | Out-Null
    Get-ChildItem -LiteralPath $mirrorPartsRoot -File -Filter "$FilePrefix-$Version-setup.part*" -ErrorAction SilentlyContinue |
        Remove-Item -Force

    $source = [System.IO.File]::OpenRead($canonicalInstaller)
    try {
        $buffer = [byte[]]::new(1MB)
        $partIndex = 1
        while ($source.Position -lt $source.Length) {
            if ($partIndex -gt 32) {
                throw "Installer requires more than 32 mirror parts."
            }
            $partName = "{0}-{1}-setup.part{2:D3}" -f $FilePrefix, $Version, $partIndex
            $partPath = Join-Path $mirrorPartsRoot $partName
            $target = [System.IO.File]::Create($partPath)
            try {
                $partWritten = 0L
                while ($partWritten -lt $MirrorPartSizeBytes -and $source.Position -lt $source.Length) {
                    $remaining = [Math]::Min(
                        [long]$buffer.Length,
                        [Math]::Min($MirrorPartSizeBytes - $partWritten, $source.Length - $source.Position)
                    )
                    $read = $source.Read($buffer, 0, [int]$remaining)
                    if ($read -le 0) {
                        break
                    }
                    $target.Write($buffer, 0, $read)
                    $partWritten += $read
                }
            } finally {
                $target.Dispose()
            }
            $partInfo = Get-Item -LiteralPath $partPath
            if ($partInfo.Length -le 0) {
                throw "Mirror part is empty: $partPath"
            }
            $mirrorParts += [pscustomobject][ordered]@{
                index = $partIndex
                url = $normalizedMirrorBaseUrl + [Uri]::EscapeDataString($partName)
                size = [long]$partInfo.Length
                sha256 = (Get-FileHash -LiteralPath $partPath -Algorithm SHA256).Hash.ToLowerInvariant()
                path = $partPath
            }
            $partIndex++
        }
    } finally {
        $source.Dispose()
    }
    if ($mirrorParts.Count -eq 0) {
        throw "No mirror parts were generated."
    }
    $mirrorTotal = ($mirrorParts | Measure-Object -Property size -Sum).Sum
    if ([long]$mirrorTotal -ne (Get-Item -LiteralPath $canonicalInstaller).Length) {
        throw "Mirror part total size does not match the installer."
    }
    $mirrorPartsJson = Join-Path $outputRoot "$FilePrefix-$Version-setup.parts.json"
    $signedPartDescriptors = @(
        $mirrorParts | ForEach-Object {
            [ordered]@{
                index = $_.index
                url = $_.url
                size = $_.size
                sha256 = $_.sha256
            }
        }
    )
    [System.IO.File]::WriteAllText(
        $mirrorPartsJson,
        ($signedPartDescriptors | ConvertTo-Json -Depth 4),
        $utf8NoBom
    )
}

$updateManifest = "$canonicalInstaller.update.json"
$signerScript = Join-Path $PSScriptRoot "sign-desktop-update.py"
if (-not (Test-Path -LiteralPath $signerScript -PathType Leaf)) {
    throw "Desktop update signer is missing: $signerScript"
}
if (
    [string]::IsNullOrWhiteSpace($env:LOOM_DESKTOP_UPDATE_PRIVATE_KEY) -and
    [string]::IsNullOrWhiteSpace($env:LOOM_DESKTOP_UPDATE_PRIVATE_KEY_PATH)
) {
    throw "LOOM_DESKTOP_UPDATE_PRIVATE_KEY or LOOM_DESKTOP_UPDATE_PRIVATE_KEY_PATH is required."
}
$python = (Get-Command python -ErrorAction Stop).Source
$signerArguments = @(
    $signerScript,
    "--installer", $canonicalInstaller,
    "--version", $Version,
    "--output", $updateManifest,
    "--product", $Product,
    "--channel", $Channel,
    "--channel-id", $ChannelId,
    "--file-prefix", $FilePrefix,
    "--public-key", $PublicKeyPath
)
if (-not [string]::IsNullOrWhiteSpace($DownloadUrl)) {
    $signerArguments += @("--download-url", $DownloadUrl)
}
if (-not [string]::IsNullOrWhiteSpace($mirrorPartsJson)) {
    $signerArguments += @("--download-parts-json", $mirrorPartsJson)
}
& $python @signerArguments
if ($LASTEXITCODE -ne 0) {
    throw "Desktop update signing failed with exit code $LASTEXITCODE"
}
if (-not (Test-Path -LiteralPath $updateManifest -PathType Leaf)) {
    throw "Desktop update signature manifest was not created: $updateManifest"
}

$releaseNotesOutput = ""
if (-not [string]::IsNullOrWhiteSpace($ReleaseNotesPath)) {
    if (-not (Test-Path -LiteralPath $ReleaseNotesPath -PathType Leaf)) {
        throw "Release notes do not exist: $ReleaseNotesPath"
    }
    $releaseNotesOutput = Join-Path $outputRoot "release-notes.md"
    Copy-Item -LiteralPath $ReleaseNotesPath -Destination $releaseNotesOutput -Force
}

[pscustomobject]@{
    ok = $true
    version = $Version
    installer = $canonicalInstaller
    sha256 = $hash
    sha256File = $sidecar
    updateManifest = $updateManifest
    mirrorParts = @($mirrorParts | ForEach-Object { $_.path })
    mirrorPartsManifest = $mirrorPartsJson
    releaseNotes = $releaseNotesOutput
    signatureStatus = [string]$signature.Status
    signer = if ($signature.SignerCertificate) { [string]$signature.SignerCertificate.Subject } else { "" }
} | ConvertTo-Json -Depth 3
