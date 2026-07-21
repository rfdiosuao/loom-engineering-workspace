param(
    [Parameter(Mandatory = $true)]
    [string]$SourcePortableDir,
    [string]$PackageName = "",
    [string]$DistributionManifestUrl = "",
    [string]$DistributionManifestPath = "",
    [string]$OutputRoot = "",
    [switch]$NoZip
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$ReleaseDir = if ([string]::IsNullOrWhiteSpace($OutputRoot)) {
    Join-Path $Root "release"
} else {
    [System.IO.Path]::GetFullPath($OutputRoot)
}
$PrimaryPayloadDirName = "LOOMFiles"
$LauncherExeName = "LOOM.exe"

$DefaultStableManifestUrl = "https://raw.githubusercontent.com/rfdiosuao/loom-release-channel/main/stable/release-manifest.json"
$DefaultRcManifestUrl = "https://raw.githubusercontent.com/rfdiosuao/loom-release-channel/main/rc/release-manifest.json"

$RemoveLayers = @(
    "LOOMFiles\node",
    "LOOMFiles\node_modules",
    "LOOMFiles\agents\luminode-desktop",
    "LOOMFiles\releases\agent-phone"
)

function Get-ResolvedPathOrNull {
    param([string]$Path)
    if ([string]::IsNullOrWhiteSpace($Path) -or -not (Test-Path -LiteralPath $Path)) {
        return $null
    }
    return (Resolve-Path -LiteralPath $Path).Path
}

function Assert-InWorkspace {
    param([string]$ResolvedPath)
    $resolvedRoot = (Resolve-Path -LiteralPath $ReleaseDir).Path
    if (-not $ResolvedPath.StartsWith($resolvedRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to operate outside output root: $ResolvedPath"
    }
}

function Remove-SafePath {
    param([string]$Path)
    $resolved = Get-ResolvedPathOrNull $Path
    if (-not $resolved) {
        return
    }
    Assert-InWorkspace $resolved
    Remove-Item -LiteralPath $resolved -Recurse -Force
}

function Invoke-Step {
    param(
        [string]$Name,
        [scriptblock]$Script
    )
    Write-Host ""
    Write-Host "==> $Name" -ForegroundColor Cyan
    $global:LASTEXITCODE = 0
    & $Script
    if ($global:LASTEXITCODE -ne 0) {
        throw "Step failed with exit code $global:LASTEXITCODE: $Name"
    }
    Write-Host "OK: $Name" -ForegroundColor Green
}

function Get-SourcePortableDir {
    $resolved = Get-ResolvedPathOrNull $SourcePortableDir
    if (-not $resolved) {
        throw "Source portable directory is missing: $SourcePortableDir"
    }
    if (-not (Test-Path -LiteralPath (Join-Path $resolved $LauncherExeName) -PathType Leaf)) {
        throw "Source portable directory missing ${LauncherExeName}: $resolved"
    }
    if (-not (Test-Path -LiteralPath (Join-Path $resolved $PrimaryPayloadDirName) -PathType Container)) {
        throw "Source portable directory missing ${PrimaryPayloadDirName}: $resolved"
    }
    if (Test-Path -LiteralPath (Join-Path $resolved "OpenClawFiles")) {
        throw "Legacy OpenClawFiles payload is not allowed as online source: $resolved"
    }
    return $resolved
}

function Get-PackageVersion {
    param([string]$SourceDir)
    $runtimePath = Join-Path $SourceDir "$PrimaryPayloadDirName\data\launcher_runtime.json"
    if (Test-Path -LiteralPath $runtimePath) {
        $runtime = Get-Content -LiteralPath $runtimePath -Raw -Encoding UTF8 | ConvertFrom-Json
        if (-not [string]::IsNullOrWhiteSpace([string]$runtime.version)) {
            return [string]$runtime.version
        }
    }
    $packageJsonPath = Join-Path $SourceDir "$PrimaryPayloadDirName\package.json"
    if (Test-Path -LiteralPath $packageJsonPath) {
        $packageJson = Get-Content -LiteralPath $packageJsonPath -Raw -Encoding UTF8 | ConvertFrom-Json
        if (-not [string]::IsNullOrWhiteSpace([string]$packageJson.version)) {
            return [string]$packageJson.version
        }
    }
    throw "Unable to determine package version from launcher_runtime.json or package.json."
}

function Get-ManifestJson {
    if (-not [string]::IsNullOrWhiteSpace($DistributionManifestPath)) {
        $resolved = Get-ResolvedPathOrNull $DistributionManifestPath
        if (-not $resolved) {
            throw "Distribution manifest file is missing: $DistributionManifestPath"
        }
        return Get-Content -LiteralPath $resolved -Raw -Encoding UTF8
    }

    $url = if ([string]::IsNullOrWhiteSpace($DistributionManifestUrl)) { $DefaultStableManifestUrl } else { $DistributionManifestUrl }
    try {
        return (Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 20).Content
    } catch {
        if ([string]::IsNullOrWhiteSpace($DistributionManifestUrl) -or $DistributionManifestUrl -eq $DefaultStableManifestUrl) {
            try {
                return (Invoke-WebRequest -Uri $DefaultRcManifestUrl -UseBasicParsing -TimeoutSec 20).Content
            } catch {
                throw "Unable to fetch distribution manifest from $DefaultStableManifestUrl or $DefaultRcManifestUrl. $($_.Exception.Message)"
            }
        }
        throw "Unable to fetch distribution manifest from $url. $($_.Exception.Message)"
    }
}

function Assert-DistributionManifest {
    param([object]$Manifest)
    if (-not $Manifest.mirrors -or $Manifest.mirrors.Count -lt 1) {
        throw "Distribution manifest must include mirrors for online runtime layers."
    }
    if (-not $Manifest.layers -or $Manifest.layers.Count -lt 1) {
        throw "Distribution manifest must include layers for online runtime bootstrap."
    }
    $required = @($Manifest.layers | Where-Object { $_.required -eq $true })
    foreach ($id in @("node", "openclaw-deps", "python-runtime")) {
        if (-not (@($required | Where-Object { $_.id -eq $id }).Count)) {
            throw "Distribution manifest missing required layer: $id"
        }
    }
    foreach ($layer in $Manifest.layers) {
        $installPath = [string]$layer.installPath
        if (-not $installPath.StartsWith("LOOMFiles/", [System.StringComparison]::OrdinalIgnoreCase) -and -not $installPath.StartsWith("LOOMFiles\", [System.StringComparison]::OrdinalIgnoreCase)) {
            throw "Distribution layer installPath must target LOOMFiles, got: $installPath"
        }
        if ([string]::IsNullOrWhiteSpace([string]$layer.file) -or [string]::IsNullOrWhiteSpace([string]$layer.sha256)) {
            throw "Distribution layer is missing file or sha256: $($layer.id)"
        }
    }
}

function Get-DistributionManifest {
    param([object]$Manifest)
    if ($Manifest.schemaVersion -ne 1) {
        throw "Release manifest schemaVersion must be 1."
    }
    if ([string]$Manifest.product -cne "LOOM") {
        throw "Release manifest product must be LOOM."
    }
    if ($null -eq $Manifest.signature -or [string]$Manifest.signature.algorithm -cne "ed25519" -or [string]::IsNullOrWhiteSpace([string]$Manifest.signature.value)) {
        throw "Release manifest must include an Ed25519 signature."
    }
    try {
        $signatureBytes = [Convert]::FromBase64String([string]$Manifest.signature.value)
    } catch {
        throw "Release manifest Ed25519 signature must be base64."
    }
    if ($signatureBytes.Length -ne 64) {
        throw "Release manifest Ed25519 signature must contain 64 bytes."
    }
    if (-not ($Manifest.PSObject.Properties.Name -contains "distribution") -or $null -eq $Manifest.distribution) {
        throw "Signed release manifest must include distribution."
    }
    return $Manifest.distribution
}

function Copy-OnlineTree {
    param(
        [string]$SourceDir,
        [string]$TargetDir
    )
    $excludeDirs = $RemoveLayers | ForEach-Object { Join-Path $SourceDir $_ }
    & robocopy $SourceDir $TargetDir /E /XD @excludeDirs /NFL /NDL /NJH /NJS /NP | Out-Null
    if ($LASTEXITCODE -ge 8) {
        throw "robocopy failed with code $LASTEXITCODE"
    }
    $global:LASTEXITCODE = 0
    foreach ($rel in $RemoveLayers) {
        Remove-SafePath (Join-Path $TargetDir $rel)
    }
}

function Remove-OnlinePackageNoise {
    param([string]$PackageDir)

    # Some Python dependencies ship editor/agent helper docs under ".agents".
    # They are not runtime code and make release payload scans look like LOOM
    # bundled third-party agents, so strip them from the online package.
    Get-ChildItem -LiteralPath $PackageDir -Recurse -Directory -Force -Filter ".agents" -ErrorAction SilentlyContinue |
        ForEach-Object {
            Remove-SafePath $_.FullName
        }

    $openClawAgentsDir = Join-Path $PackageDir "$PrimaryPayloadDirName\data\.openclaw\agents"
    if (Test-Path -LiteralPath $openClawAgentsDir -PathType Container) {
        $agentFiles = @(Get-ChildItem -LiteralPath $openClawAgentsDir -Recurse -File -Force -ErrorAction SilentlyContinue)
        if ($agentFiles.Count -gt 0) {
            throw "Online package must not bundle agent payload files: $openClawAgentsDir"
        }
        Remove-SafePath $openClawAgentsDir
    }
}

function Write-CachedReleaseManifest {
    param(
        [string]$PackageDir,
        [string]$ManifestJson
    )
    $target = Join-Path $PackageDir "$PrimaryPayloadDirName\data\.openclaw\dist-cache\manifest.json"
    New-Item -ItemType Directory -Path (Split-Path -Parent $target) -Force | Out-Null
    $utf8NoBom = [System.Text.UTF8Encoding]::new($false)
    [System.IO.File]::WriteAllText($target, $ManifestJson, $utf8NoBom)
}

function Write-OnlineReadme {
    param([string]$PackageDir)
    $content = @(
        "LOOM online portable package",
        "",
        "Usage:",
        "1. Extract the package and keep LOOM.exe and LOOMFiles in the same directory.",
        "2. Launch LOOM.exe. The package includes the Python bridge runtime; first run downloads and verifies Node and runtime dependencies from the release-channel manifest.",
        "3. Downloaded layers are written into LOOMFiles. Later launches reuse the local layers.",
        "",
        "Notes:",
        "- This package does not contain real accounts, passwords, API keys, or private keys.",
        "- The online package requires access to release-channel mirrors/layers.",
        "- Use the full offline package when the distribution manifest is unavailable."
    ) -join [Environment]::NewLine
    Set-Content -LiteralPath (Join-Path $PackageDir "README-ONLINE.txt") -Value $content -Encoding UTF8
}

function Update-LauncherRuntimePackageName {
    param(
        [string]$PackageDir,
        [string]$Name
    )
    $runtimePath = Join-Path $PackageDir "$PrimaryPayloadDirName\data\launcher_runtime.json"
    if (-not (Test-Path -LiteralPath $runtimePath -PathType Leaf)) {
        return
    }
    $runtime = Get-Content -LiteralPath $runtimePath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($runtime.PSObject.Properties.Name -contains "packageName") {
        $runtime.packageName = $Name
    } else {
        $runtime | Add-Member -NotePropertyName "packageName" -NotePropertyValue $Name
    }
    if ($runtime.PSObject.Properties.Name -contains "packageKind") {
        $runtime.packageKind = "online"
    } else {
        $runtime | Add-Member -NotePropertyName "packageKind" -NotePropertyValue "online"
    }
    $utf8NoBom = [System.Text.UTF8Encoding]::new($false)
    [System.IO.File]::WriteAllText($runtimePath, ($runtime | ConvertTo-Json -Depth 24), $utf8NoBom)
}

$sourceDir = Get-SourcePortableDir
$version = Get-PackageVersion -SourceDir $sourceDir
if ([string]::IsNullOrWhiteSpace($PackageName)) {
    $date = Get-Date -Format "yyyy.MM.dd"
    $PackageName = "LOOM-Online-v$version-$date"
}
if ($PackageName -notmatch '^LOOM-Online-v') {
    throw "Online package name must start with LOOM-Online-v: $PackageName"
}

New-Item -ItemType Directory -Path $ReleaseDir -Force | Out-Null
$packageDir = Join-Path $ReleaseDir $PackageName
$zipPath = Join-Path $ReleaseDir "$PackageName.zip"
$hashPath = Join-Path $ReleaseDir "$PackageName.zip.sha256.txt"

$manifestJson = Get-ManifestJson
if ($manifestJson.Length -gt 0 -and $manifestJson[0] -eq [char]0xFEFF) {
    $manifestJson = $manifestJson.Substring(1)
}
$manifest = $manifestJson | ConvertFrom-Json
$distributionManifest = Get-DistributionManifest -Manifest $manifest
Assert-DistributionManifest -Manifest $distributionManifest

Write-Host "Package name: $PackageName"
Write-Host "Source portable: $sourceDir"
Write-Host "Output root: $ReleaseDir"

Invoke-Step "Create online portable directory" {
    Remove-SafePath $packageDir
    Remove-SafePath $zipPath
    Remove-SafePath $hashPath
    New-Item -ItemType Directory -Path $packageDir -Force | Out-Null
    Copy-OnlineTree -SourceDir $sourceDir -TargetDir $packageDir
    Remove-OnlinePackageNoise -PackageDir $packageDir
    Update-LauncherRuntimePackageName -PackageDir $packageDir -Name $PackageName
    Write-CachedReleaseManifest -PackageDir $packageDir -ManifestJson $manifestJson
    Write-OnlineReadme -PackageDir $packageDir
}

Invoke-Step "Verify online portable shape" {
    if (-not (Test-Path -LiteralPath (Join-Path $packageDir $LauncherExeName) -PathType Leaf)) {
        throw "Missing $LauncherExeName"
    }
    if (-not (Test-Path -LiteralPath (Join-Path $packageDir $PrimaryPayloadDirName) -PathType Container)) {
        throw "Missing $PrimaryPayloadDirName"
    }
    if (Test-Path -LiteralPath (Join-Path $packageDir "OpenClawFiles")) {
        throw "Legacy OpenClawFiles payload is not allowed."
    }
    foreach ($rel in @("node", "node_modules")) {
        if (Test-Path -LiteralPath (Join-Path $packageDir "$PrimaryPayloadDirName\$rel")) {
            throw "Heavy runtime layer was not removed: $rel"
        }
    }
    foreach ($rel in @("_up_\python-runtime\python.exe", "_up_\python\bridge.py", "scripts\openclaw-context.mjs", "data\.openclaw\workspace\runtime-context.json", "release-manifest.json", "release-public-key.txt")) {
        if (-not (Test-Path -LiteralPath (Join-Path $packageDir "$PrimaryPayloadDirName\$rel") -PathType Leaf)) {
            throw "Missing online package file: $rel"
        }
    }
}

if (-not $NoZip) {
    Invoke-Step "Create online zip" {
        Compress-Archive -LiteralPath $packageDir -DestinationPath $zipPath -CompressionLevel Optimal
    }
    $hash = Get-FileHash -Algorithm SHA256 -LiteralPath $zipPath
    "$($hash.Hash)  $(Split-Path -Leaf $zipPath)" | Set-Content -LiteralPath $hashPath -Encoding ASCII
    Write-Host ""
    Write-Host "Online package: $zipPath" -ForegroundColor Green
    Write-Host "SHA256: $($hash.Hash)" -ForegroundColor Green
} else {
    Write-Host ""
    Write-Host "Online package directory: $packageDir" -ForegroundColor Green
}
