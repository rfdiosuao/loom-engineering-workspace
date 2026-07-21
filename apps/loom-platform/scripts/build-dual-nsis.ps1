param(
    [Parameter(Mandatory = $true)]
    [string]$CodexPackagePath,
    [Parameter(Mandatory = $true)]
    [string]$OutputRoot,
    [string]$CertificateThumbprint = "",
    [string]$TimestampUrl = "http://timestamp.digicert.com",
    [switch]$RequireCodeSignature,
    [switch]$ValidateOnly
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$LauncherDir = Join-Path $Root "openclaw_new_launcher"
$TauriDir = Join-Path $LauncherDir "src-tauri"
$ManifestPath = Join-Path $Root "release-manifest.json"
$BundleDir = Join-Path $TauriDir "target\release\bundle\nsis"
$RedistComponentsDir = Join-Path $LauncherDir "redist\components"
$CodexSeedDir = Join-Path $LauncherDir "redist\components\codex-desktop"
$tauriBuildConfigPath = ""

function Resolve-ExistingPath {
    param([string]$Path)

    if ([string]::IsNullOrWhiteSpace($Path)) {
        throw "Path is required."
    }
    if (-not (Test-Path -LiteralPath $Path)) {
        throw "Path not found: $Path"
    }
    return (Resolve-Path -LiteralPath $Path).Path
}

function Test-PathEquals {
    param(
        [string]$Left,
        [string]$Right
    )

    return [string]::Equals(
        [System.IO.Path]::GetFullPath($Left),
        [System.IO.Path]::GetFullPath($Right),
        [System.StringComparison]::OrdinalIgnoreCase
    )
}

function Assert-SafeOutputRoot {
    param([string]$Path)

    if ([string]::IsNullOrWhiteSpace($Path)) {
        throw "OutputRoot is required."
    }

    $resolvedPath = [System.IO.Path]::GetFullPath($Path)
    $blockedPaths = @(
        $Root,
        $LauncherDir,
        (Join-Path $Root "release")
    )

    foreach ($blockedPath in $blockedPaths) {
        if (Test-PathEquals -Left $resolvedPath -Right $blockedPath) {
            throw "Refusing unsafe OutputRoot '$resolvedPath'. Use a dedicated output subdirectory instead."
        }
    }

    return $resolvedPath
}

function Assert-OutputPathAvailable {
    param([string]$Path)

    if (Test-Path -LiteralPath $Path) {
        throw "Installer output already exists: $Path"
    }
}

function Initialize-MsvcBuildEnvironment {
    if (Get-Command "link.exe" -ErrorAction SilentlyContinue) {
        return
    }

    $candidateScripts = @(
        (Join-Path ${env:ProgramFiles(x86)} "Microsoft Visual Studio\2022\BuildTools\Common7\Tools\VsDevCmd.bat"),
        (Join-Path $env:ProgramFiles "Microsoft Visual Studio\2022\BuildTools\Common7\Tools\VsDevCmd.bat")
    ) | Where-Object { -not [string]::IsNullOrWhiteSpace($_) -and (Test-Path -LiteralPath $_) }

    foreach ($candidate in $candidateScripts) {
        $environmentLines = & $env:ComSpec /d /c "call `"$candidate`" -arch=x64 -host_arch=x64 >nul && set"
        foreach ($line in $environmentLines) {
            if ($line -match '^([^=]+)=(.*)$') {
                [Environment]::SetEnvironmentVariable($matches[1], $matches[2], "Process")
            }
        }
        if (Get-Command "link.exe" -ErrorAction SilentlyContinue) {
            return
        }
    }

    throw "MSVC linker link.exe was not found. Install Visual Studio 2022 Build Tools with the Desktop development with C++ workload."
}

function Assert-SourceVersionConsistency {
    $packageJsonPath = Join-Path $LauncherDir "package.json"
    $tauriConfigPath = Join-Path $TauriDir "tauri.conf.json"
    $packageJson = Get-Content -LiteralPath $packageJsonPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $tauriConfig = Get-Content -LiteralPath $tauriConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $packageVersion = [string]$packageJson.version
    $tauriVersion = [string]$tauriConfig.version
    if ([string]::IsNullOrWhiteSpace($packageVersion) -or [string]::IsNullOrWhiteSpace($tauriVersion)) {
        throw "Launcher version is missing from package.json or tauri.conf.json."
    }
    if ($packageVersion -ne $tauriVersion) {
        throw "Launcher version mismatch: package.json=$packageVersion tauri.conf.json=$tauriVersion"
    }
    return $packageVersion
}

function Get-TauriConfig {
    return Get-Content -LiteralPath (Join-Path $TauriDir "tauri.conf.json") -Raw -Encoding UTF8 | ConvertFrom-Json
}

function Get-CodexManifestComponent {
    if (-not (Test-Path -LiteralPath $ManifestPath)) {
        throw "Missing release manifest: $ManifestPath"
    }
    $manifestText = Get-Content -LiteralPath $ManifestPath -Raw -Encoding UTF8
    $codexComponent = $null
    try {
        $manifest = $manifestText | ConvertFrom-Json
        $codexComponent = @($manifest.components | Where-Object {
            $component = $_
            $component.id -eq "codex-desktop"
        }) | Select-Object -First 1
    }
    catch {
        $componentMatch = [regex]::Match(
            $manifestText,
            '(?s)\{[^{}]*"id"\s*:\s*"codex-desktop"[^{}]*"urls"\s*:\s*\[(?<urls>.*?)\][^{}]*"size"\s*:\s*(?<size>\d+)[^{}]*"sha256"\s*:\s*"(?<sha>[0-9a-fA-F]{64})"[^{}]*\}'
        )
        if ($componentMatch.Success) {
            $urlMatch = [regex]::Match($componentMatch.Groups["urls"].Value, '"(?<url>https?://[^"]+)"')
            if ($urlMatch.Success) {
                $codexComponent = [pscustomobject]@{
                    id = "codex-desktop"
                    urls = @($urlMatch.Groups["url"].Value)
                    size = [int64]$componentMatch.Groups["size"].Value
                    sha256 = $componentMatch.Groups["sha"].Value.ToLowerInvariant()
                }
            }
        }
    }
    if (-not $codexComponent) {
        throw "release-manifest.json does not contain a parseable codex-desktop component"
    }
    if (-not $codexComponent.urls -or $codexComponent.urls.Count -lt 1) {
        throw "codex-desktop must declare at least one package URL"
    }
    return $codexComponent
}

function Assert-VerifiedCodexPackage {
    param(
        [string]$PackagePath,
        [object]$codexComponent
    )

    $resolvedCodexPackagePath = Resolve-ExistingPath $PackagePath
    $actualSize = (Get-Item -LiteralPath $resolvedCodexPackagePath).Length
    if ([int64]$actualSize -ne [int64]$codexComponent.size) {
        throw "Codex package size mismatch: expected $($codexComponent.size), got $actualSize"
    }
    $actualSha = (Get-FileHash -LiteralPath $resolvedCodexPackagePath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actualSha -ne [string]$codexComponent.sha256) {
        throw "Codex package sha256 mismatch: expected $($codexComponent.sha256), got $actualSha"
    }
    return $resolvedCodexPackagePath
}

function Write-InstallerHash {
    param([string]$Path)

    $hash = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
    Set-Content -LiteralPath ($Path + ".sha256.txt") -Value "$hash *$(Split-Path -Leaf $Path)" -Encoding ASCII
}

function Assert-CodeSignature {
    param([string]$Path)

    $signature = Get-AuthenticodeSignature -FilePath $Path
    if ($signature.Status -ne "Valid") {
        throw "Installer Authenticode signature is not valid: $Path status=$($signature.Status)"
    }
}

function Find-BuiltInstaller {
    param(
        [datetime]$StartedAtUtc,
        [string]$ExpectedVersion
    )

    if (-not (Test-Path -LiteralPath $BundleDir)) {
        throw "NSIS bundle directory not found: $BundleDir"
    }
    $builtInstaller = Get-ChildItem -LiteralPath $BundleDir -Filter "*-setup.exe" -File |
        Where-Object { $_.LastWriteTimeUtc -ge $StartedAtUtc.AddSeconds(-2) } |
        Sort-Object LastWriteTimeUtc -Descending |
        Select-Object -First 1
    if (-not $builtInstaller) {
        $builtInstaller = Get-ChildItem -LiteralPath $BundleDir -Filter "*$ExpectedVersion*_x64-setup.exe" -File |
            Sort-Object LastWriteTimeUtc -Descending |
            Select-Object -First 1
    }
    if (-not $builtInstaller) {
        throw "Could not locate the freshly built NSIS installer in $BundleDir"
    }
    return $builtInstaller
}

function Build-InstallerVariant {
    param(
        [string]$VariantName,
        [string]$ExpectedVersion,
        [string]$VariantOutputPath
    )

    if ($ValidateOnly) {
        Write-Host "ValidateOnly: skipping Tauri NSIS build for $VariantName"
        return [pscustomobject]@{
            Variant = $VariantName
            OutputPath = $VariantOutputPath
        }
    }

    Initialize-MsvcBuildEnvironment
    $startedAtUtc = [datetime]::UtcNow
    Push-Location $LauncherDir
    try {
        $tauriArgs = @("run", "tauri", "--", "build", "--bundles", "nsis")
        if (-not [string]::IsNullOrWhiteSpace($tauriBuildConfigPath)) {
            $tauriArgs += @("--config", $tauriBuildConfigPath)
        }
        & npm @tauriArgs
        if ($LASTEXITCODE -ne 0) {
            throw "Tauri NSIS build failed for $VariantName with exit code $LASTEXITCODE"
        }
    }
    finally {
        Pop-Location
    }

    $builtInstaller = Find-BuiltInstaller -StartedAtUtc $startedAtUtc -ExpectedVersion $ExpectedVersion
    Assert-OutputPathAvailable -Path $VariantOutputPath
    Copy-Item -LiteralPath $builtInstaller.FullName -Destination $variantOutputPath
    if ($RequireCodeSignature) {
        Assert-CodeSignature -Path $variantOutputPath
    }
    Write-InstallerHash -Path $variantOutputPath
    return $builtInstaller
}

$launcherVersion = Assert-SourceVersionConsistency
$tauriConfig = Get-TauriConfig
$codexComponent = Get-CodexManifestComponent
$resolvedCodexPackagePath = Assert-VerifiedCodexPackage -PackagePath $CodexPackagePath -codexComponent $codexComponent
$resolvedOutputRoot = Assert-SafeOutputRoot -Path $OutputRoot
if ($RequireCodeSignature -and [string]::IsNullOrWhiteSpace($CertificateThumbprint)) {
    throw "RequireCodeSignature needs CertificateThumbprint. Import a trusted code-signing certificate before release."
}
$packagePrefix = [string]$tauriConfig.mainBinaryName
if ([string]::IsNullOrWhiteSpace($packagePrefix)) {
    $packagePrefix = "LOOM"
}
$onlineOutputPath = Join-Path $resolvedOutputRoot "$packagePrefix-$launcherVersion-online-setup.exe"
$completeOutputPath = Join-Path $resolvedOutputRoot "$packagePrefix-$launcherVersion-complete-setup.exe"
$recommendedOutputPath = Join-Path $resolvedOutputRoot "$packagePrefix-$launcherVersion-setup.exe"
$seedPackagePath = Join-Path $CodexSeedDir (Split-Path -Leaf $resolvedCodexPackagePath)
$seedDirExisted = Test-Path -LiteralPath $CodexSeedDir
$seedDirBackupPath = ""
$outputRootExists = Test-Path -LiteralPath $resolvedOutputRoot

if ($outputRootExists -and -not (Get-Item -LiteralPath $resolvedOutputRoot).PSIsContainer) {
    throw "OutputRoot must be a directory path: $resolvedOutputRoot"
}

Assert-OutputPathAvailable -Path $onlineOutputPath
Assert-OutputPathAvailable -Path $completeOutputPath
Assert-OutputPathAvailable -Path $recommendedOutputPath

if ($ValidateOnly) {
    Write-Host "Validated Codex package and dual NSIS build inputs."
    Write-Host "Online output: $onlineOutputPath"
    Write-Host "Complete output: $completeOutputPath"
    Write-Host "Recommended output: $recommendedOutputPath"
    return
}

if (-not [string]::IsNullOrWhiteSpace($CertificateThumbprint)) {
    $certificate = Get-ChildItem Cert:\CurrentUser\My,Cert:\LocalMachine\My -ErrorAction SilentlyContinue |
        Where-Object { $_.Thumbprint -eq $CertificateThumbprint -and $_.HasPrivateKey } |
        Select-Object -First 1
    if (-not $certificate) {
        throw "Code-signing certificate not found or has no private key: $CertificateThumbprint"
    }
    $tauriBuildConfigPath = Join-Path ([System.IO.Path]::GetTempPath()) ("loom-tauri-signing-" + [guid]::NewGuid().ToString("N") + ".json")
    @{
        bundle = @{
            windows = @{
                certificateThumbprint = $CertificateThumbprint
                digestAlgorithm = "sha256"
                timestampUrl = $TimestampUrl
            }
        }
    } | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $tauriBuildConfigPath -Encoding UTF8
}

New-Item -ItemType Directory -Path $resolvedOutputRoot -Force | Out-Null

try {
    if ($seedDirExisted) {
        $seedDirBackupPath = Join-Path ([System.IO.Path]::GetTempPath()) ("loom-dual-nsis-seed-" + [guid]::NewGuid().ToString("N"))
        Move-Item -LiteralPath $CodexSeedDir -Destination $seedDirBackupPath
    }

    Build-InstallerVariant -VariantName "online" -ExpectedVersion $launcherVersion -VariantOutputPath $onlineOutputPath | Out-Null

    New-Item -ItemType Directory -Path $CodexSeedDir -Force | Out-Null
    Copy-Item -LiteralPath $resolvedCodexPackagePath -Destination $seedPackagePath -Force

    Build-InstallerVariant -VariantName "complete" -ExpectedVersion $launcherVersion -VariantOutputPath $completeOutputPath | Out-Null
    Copy-Item -LiteralPath $completeOutputPath -Destination $recommendedOutputPath
    Write-InstallerHash -Path $recommendedOutputPath
}
finally {
    if (Test-Path -LiteralPath $seedPackagePath) {
        Remove-Item -LiteralPath $seedPackagePath -Force
    }
    if ((Test-Path -LiteralPath $CodexSeedDir) -and -not $seedDirExisted) {
        $remaining = @(Get-ChildItem -LiteralPath $CodexSeedDir -Force)
        if ($remaining.Count -eq 0) {
            Remove-Item -LiteralPath $CodexSeedDir -Force
        }
    }
    if ($seedDirBackupPath) {
        if (Test-Path -LiteralPath $CodexSeedDir) {
            Remove-Item -LiteralPath $CodexSeedDir -Recurse -Force
        }
        Move-Item -LiteralPath $seedDirBackupPath -Destination $CodexSeedDir
    }
    if ($tauriBuildConfigPath -and (Test-Path -LiteralPath $tauriBuildConfigPath)) {
        Remove-Item -LiteralPath $tauriBuildConfigPath -Force
    }
}
