param(
    [Parameter(Mandatory = $true)]
    [string]$ApkPath,
    [string]$TrustedFingerprintPath = "",
    [string]$AndroidSdkPath = ""
)

$ErrorActionPreference = "Stop"

$resolvedApk = (Resolve-Path -LiteralPath $ApkPath).Path
$TrustedFingerprintPath = if ($TrustedFingerprintPath) {
    $TrustedFingerprintPath
} else {
    Join-Path $PSScriptRoot "..\release\trusted-signing-cert.sha256"
}
$resolvedFingerprint = (Resolve-Path -LiteralPath $TrustedFingerprintPath).Path
$trustedFingerprint = (Get-Content -Raw -LiteralPath $resolvedFingerprint).Trim().ToUpperInvariant()
if ($trustedFingerprint -notmatch "^[0-9A-F]{64}$") {
    throw "Trusted signing certificate fingerprint must contain exactly 64 hexadecimal characters."
}

$sdkCandidates = @(
    $AndroidSdkPath,
    $env:ANDROID_SDK_ROOT,
    $env:ANDROID_HOME,
    (Join-Path $env:LOCALAPPDATA "Android\Sdk")
) | Where-Object { $_ -and (Test-Path -LiteralPath $_) }
$sdkRoot = $sdkCandidates | Select-Object -First 1
if (-not $sdkRoot) {
    throw "Android SDK was not found. Set ANDROID_SDK_ROOT or pass -AndroidSdkPath."
}

$apkSigner = Get-ChildItem -LiteralPath (Join-Path $sdkRoot "build-tools") `
    -Recurse `
    -File `
    -Filter "apksigner*" |
    Where-Object { $_.Name -in @("apksigner", "apksigner.bat") } |
    Sort-Object { [version]$_.Directory.Name } -Descending |
    Select-Object -First 1
if (-not $apkSigner) {
    throw "apksigner was not found below $sdkRoot."
}

$verificationOutput = & $apkSigner.FullName verify --verbose --print-certs $resolvedApk 2>&1
if ($LASTEXITCODE -ne 0) {
    throw "APK signature verification failed:`n$($verificationOutput -join [Environment]::NewLine)"
}

$digestMatches = [regex]::Matches(
    ($verificationOutput -join "`n"),
    "Signer #\d+ certificate SHA-256 digest:\s*([0-9A-Fa-f]{64})"
)
$actualFingerprints = @($digestMatches | ForEach-Object { $_.Groups[1].Value.ToUpperInvariant() } | Select-Object -Unique)
if ($actualFingerprints.Count -ne 1) {
    throw "Expected exactly one APK signing certificate, found $($actualFingerprints.Count)."
}
if ($actualFingerprints[0] -ne $trustedFingerprint) {
    throw "APK signing certificate mismatch. Expected $trustedFingerprint, got $($actualFingerprints[0])."
}

Write-Output "APK signature verified: $resolvedApk"
Write-Output "Signer SHA256: $trustedFingerprint"
