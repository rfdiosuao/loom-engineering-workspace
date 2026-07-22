param(
    [Parameter(Mandatory = $true)][string]$InstallerPath,
    [Parameter(Mandatory = $true)][string]$Version,
    [string]$OutputDirectory = "",
    [string]$ReleaseNotesPath = "",
    [switch]$AllowUnsigned
)

$ErrorActionPreference = "Stop"

if ($Version -notmatch '^\d+\.\d+\.\d+$') {
    throw "Version must use MAJOR.MINOR.PATCH format: $Version"
}
if (-not (Test-Path -LiteralPath $InstallerPath -PathType Leaf)) {
    throw "Installer does not exist: $InstallerPath"
}

$installer = (Resolve-Path -LiteralPath $InstallerPath).Path
if ([string]::IsNullOrWhiteSpace($OutputDirectory)) {
    $OutputDirectory = Join-Path (Split-Path -Parent $PSScriptRoot) "artifacts\desktop-update\$Version"
}
$outputRoot = [System.IO.Path]::GetFullPath($OutputDirectory)
New-Item -ItemType Directory -Force -Path $outputRoot | Out-Null

$signature = Get-AuthenticodeSignature -LiteralPath $installer
if (-not $AllowUnsigned -and $signature.Status -eq "NotSigned") {
    throw "Installer is NotSigned. Production auto-update assets must have a valid Authenticode signature."
}
if (-not $AllowUnsigned -and $signature.Status -ne "Valid") {
    throw "Installer signature is not valid: $($signature.Status) $($signature.StatusMessage)"
}

$canonicalName = "LOOM-$Version-setup.exe"
$canonicalInstaller = Join-Path $outputRoot $canonicalName
Copy-Item -LiteralPath $installer -Destination $canonicalInstaller -Force

$hash = (Get-FileHash -LiteralPath $canonicalInstaller -Algorithm SHA256).Hash.ToLowerInvariant()
$sidecar = "$canonicalInstaller.sha256.txt"
$utf8NoBom = [System.Text.UTF8Encoding]::new($false)
[System.IO.File]::WriteAllText($sidecar, "$hash *$canonicalName`n", $utf8NoBom)

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
    releaseNotes = $releaseNotesOutput
    signatureStatus = [string]$signature.Status
    signer = if ($signature.SignerCertificate) { [string]$signature.SignerCertificate.Subject } else { "" }
} | ConvertTo-Json -Depth 3
