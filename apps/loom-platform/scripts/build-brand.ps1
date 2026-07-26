param(
    [Parameter(Mandatory = $true)]
    [string]$BrandPath,
    [Parameter(Mandatory = $true)]
    [string]$OutputPath,
    [ValidateSet("Release", "Debug")]
    [string]$Configuration = "Release",
    [string]$FactoryCommit = "",
    [switch]$AllowDemo,
    [switch]$PlanOnly
)

$ErrorActionPreference = "Stop"
if ($Configuration -ne "Release" -and -not $PlanOnly) {
    throw "Complete OEM artifact builds require -Configuration Release"
}
$PlatformRoot = Split-Path -Parent $PSScriptRoot
$AppsRoot = Split-Path -Parent $PlatformRoot
$WorkspaceRoot = Split-Path -Parent $AppsRoot
$LauncherDir = Join-Path $PlatformRoot "openclaw_new_launcher"
$PhoneAgentDir = Join-Path $AppsRoot "loom-phone-agent"
$Compiler = Join-Path $PSScriptRoot "brand_build.py"
$PortableBuilder = Join-Path $PSScriptRoot "build-portable.ps1"
$ProtectedTauriConfig = Join-Path $LauncherDir "src-tauri\tauri.protected.conf.json"
$PrepareUpdateScript = Join-Path $LauncherDir "scripts\prepare-desktop-update-release.ps1"
$PrepareUpdateConfigScript = Join-Path $LauncherDir "scripts\prepare-brand-update-config.py"
$Python = (Get-Command python -ErrorAction Stop).Source

function Invoke-Checked {
    param(
        [string]$Name,
        [scriptblock]$Action
    )

    Write-Host ""
    Write-Host "==> $Name" -ForegroundColor Cyan
    $global:LASTEXITCODE = 0
    & $Action
    if ($global:LASTEXITCODE -ne 0) {
        throw "$Name failed with exit code $global:LASTEXITCODE"
    }
    Write-Host "OK: $Name" -ForegroundColor Green
}

function Resolve-FullPath {
    param(
        [string]$Path,
        [switch]$RequireDirectory
    )

    $fullPath = [System.IO.Path]::GetFullPath($Path)
    if ($RequireDirectory -and -not (Test-Path -LiteralPath $fullPath -PathType Container)) {
        throw "Directory does not exist: $fullPath"
    }
    return $fullPath
}

function Get-GitCommit {
    param([string]$Repository)

    $commit = (& git -C $Repository rev-parse HEAD).Trim()
    if ($LASTEXITCODE -ne 0 -or $commit -notmatch '^[0-9a-fA-F]{40}$') {
        throw "Unable to resolve a full Git commit for $Repository"
    }
    return $commit.ToLowerInvariant()
}

function Assert-GitWorktreeClean {
    param([string]$Repository)

    $trackedChanges = @(& git -C $Repository status --porcelain --untracked-files=no)
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to inspect Git worktree state for $Repository"
    }
    if ($trackedChanges.Count -gt 0) {
        throw "Complete OEM builds require a clean tracked core worktree"
    }
}

function Resolve-FactoryCommit {
    param([string]$ExplicitCommit)

    $candidates = @(
        $ExplicitCommit,
        $env:LOOM_OEM_FACTORY_COMMIT
    )
    foreach ($candidate in $candidates) {
        $normalized = [string]$candidate
        if (-not [string]::IsNullOrWhiteSpace($normalized)) {
            $normalized = $normalized.Trim().ToLowerInvariant()
            if ($normalized -notmatch '^[0-9a-f]{40}$') {
                throw "FactoryCommit must be a full 40-character Git SHA"
            }
            return $normalized
        }
    }
    throw "FactoryCommit or LOOM_OEM_FACTORY_COMMIT is required for reproducible OEM builds"
}

function Assert-OutputIsFresh {
    param([string]$Root)

    New-Item -ItemType Directory -Path $Root -Force | Out-Null
    foreach ($name in @(".brand-build", "windows", "android", "update", "metadata")) {
        $candidate = Join-Path $Root $name
        if (Test-Path -LiteralPath $candidate) {
            throw "Output contains a previous build directory: $candidate"
        }
    }
}

function Test-DesktopSigningKey {
    if (-not [string]::IsNullOrWhiteSpace($env:LOOM_DESKTOP_UPDATE_PRIVATE_KEY)) {
        return $true
    }
    $keyPath = [string]$env:LOOM_DESKTOP_UPDATE_PRIVATE_KEY_PATH
    return -not [string]::IsNullOrWhiteSpace($keyPath) -and
        (Test-Path -LiteralPath $keyPath -PathType Leaf)
}

function Assert-AndroidSigning {
    foreach ($name in @("KEYSTORE_FILE", "KEYSTORE_PASSWORD", "KEY_ALIAS", "KEY_PASSWORD")) {
        if ([string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($name, "Process"))) {
            throw "$name is required for an OEM Android release build"
        }
    }
    if (-not (Test-Path -LiteralPath $env:KEYSTORE_FILE -PathType Leaf)) {
        throw "Android keystore does not exist: $($env:KEYSTORE_FILE)"
    }
}

function Set-CompiledEnvironment {
    param(
        [string]$EnvironmentPath,
        [hashtable]$Previous
    )

    $values = Get-Content -LiteralPath $EnvironmentPath -Raw -Encoding UTF8 | ConvertFrom-Json
    foreach ($property in $values.PSObject.Properties) {
        $name = [string]$property.Name
        $Previous[$name] = [Environment]::GetEnvironmentVariable($name, "Process")
        [Environment]::SetEnvironmentVariable($name, [string]$property.Value, "Process")
    }
}

function Restore-Environment {
    param([hashtable]$Previous)

    foreach ($entry in $Previous.GetEnumerator()) {
        $value = if ($null -eq $entry.Value) { $null } else { [string]$entry.Value }
        [Environment]::SetEnvironmentVariable(
            [string]$entry.Key,
            $value,
            "Process"
        )
    }
}

function Get-RelativeArtifactPath {
    param(
        [string]$Root,
        [string]$Path
    )

    $normalizedRoot = $Root.TrimEnd("\", "/") + [System.IO.Path]::DirectorySeparatorChar
    $rootUri = [Uri]::new($normalizedRoot)
    $pathUri = [Uri]::new($Path)
    return [Uri]::UnescapeDataString($rootUri.MakeRelativeUri($pathUri).ToString())
}

function New-InstallerBitmap {
    param(
        [string]$Path,
        [string]$IconPath,
        [string]$Title,
        [int]$Width,
        [int]$Height,
        [switch]$Vertical
    )

    Add-Type -AssemblyName System.Drawing
    $bitmap = [System.Drawing.Bitmap]::new($Width, $Height)
    $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
    $icon = [System.Drawing.Image]::FromFile($IconPath)
    try {
        $graphics.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::HighQuality
        $graphics.Clear([System.Drawing.Color]::FromArgb(7, 31, 39))
        if ($Vertical) {
            $iconSize = 72
            $iconX = [int](($Width - $iconSize) / 2)
            $graphics.DrawImage($icon, $iconX, 54, $iconSize, $iconSize)
            $font = [System.Drawing.Font]::new("Segoe UI", 12, [System.Drawing.FontStyle]::Bold)
            $format = [System.Drawing.StringFormat]::new()
            $format.Alignment = [System.Drawing.StringAlignment]::Center
            $brush = [System.Drawing.SolidBrush]::new([System.Drawing.Color]::White)
            try {
                $graphics.DrawString($Title, $font, $brush, [System.Drawing.RectangleF]::new(8, 148, $Width - 16, 110), $format)
            } finally {
                $brush.Dispose()
                $format.Dispose()
                $font.Dispose()
            }
        } else {
            $graphics.DrawImage($icon, 8, 8, 40, 40)
            $font = [System.Drawing.Font]::new("Segoe UI", 9, [System.Drawing.FontStyle]::Bold)
            $brush = [System.Drawing.SolidBrush]::new([System.Drawing.Color]::White)
            try {
                $graphics.DrawString($Title, $font, $brush, [System.Drawing.RectangleF]::new(54, 11, $Width - 58, 38))
            } finally {
                $brush.Dispose()
                $font.Dispose()
            }
        }
        $bitmap.Save($Path, [System.Drawing.Imaging.ImageFormat]::Bmp)
    } finally {
        $icon.Dispose()
        $graphics.Dispose()
        $bitmap.Dispose()
    }
}

function Copy-AndroidIconResources {
    param(
        [string]$IconRoot,
        [string]$Destination
    )

    $androidRoot = Join-Path $IconRoot "android"
    if (-not (Test-Path -LiteralPath $androidRoot -PathType Container)) {
        throw "Tauri icon generation did not create Android resources: $androidRoot"
    }
    New-Item -ItemType Directory -Path $Destination -Force | Out-Null
    Get-ChildItem -LiteralPath $androidRoot -Directory | ForEach-Object {
        Copy-Item -LiteralPath $_.FullName -Destination $Destination -Recurse -Force
    }
}

function Get-ManifestDownloadUrl {
    param(
        [string]$ManifestUrl,
        [string]$Filename
    )

    $manifestUri = [Uri]::new($ManifestUrl)
    $baseUri = [Uri]::new($manifestUri, ".")
    return [Uri]::new($baseUri, $Filename).AbsoluteUri
}

function Write-Provenance {
    param(
        [string]$OutputRoot,
        [pscustomobject]$Plan,
        [string]$CoreCommit,
        [string]$FactoryCommit,
        [string]$BuildConfiguration
    )

    $artifactRoots = @("windows", "android", "update")
    $artifacts = New-Object System.Collections.Generic.List[object]
    foreach ($artifactRoot in $artifactRoots) {
        $root = Join-Path $OutputRoot $artifactRoot
        if (-not (Test-Path -LiteralPath $root -PathType Container)) {
            continue
        }
        Get-ChildItem -LiteralPath $root -File -Recurse | Sort-Object FullName | ForEach-Object {
            $relative = Get-RelativeArtifactPath -Root $OutputRoot -Path $_.FullName
            $artifacts.Add([ordered]@{
                relativePath = $relative
                type = [System.IO.Path]::GetExtension($_.Name).TrimStart(".").ToLowerInvariant()
                size = $_.Length
                sha256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
            })
        }
    }
    if ($artifacts.Count -eq 0) {
        throw "No OEM artifacts were produced"
    }

    $metadataDir = Join-Path $OutputRoot "metadata"
    New-Item -ItemType Directory -Path $metadataDir -Force | Out-Null
    $provenancePath = Join-Path $metadataDir "build-provenance.json"
    $provenance = [ordered]@{
        schemaVersion = 1
        brandId = [string]$Plan.brandId
        version = [string]$Plan.version
        configuration = $BuildConfiguration
        coreCommit = $CoreCommit
        factoryCommit = $FactoryCommit
        generatedAt = [DateTime]::UtcNow.ToString("o")
        artifacts = $artifacts
    }
    $provenance | ConvertTo-Json -Depth 10 |
        Set-Content -LiteralPath $provenancePath -Encoding UTF8

    $checksumLines = New-Object System.Collections.Generic.List[string]
    foreach ($artifact in $artifacts) {
        $checksumLines.Add("$($artifact.sha256)  $($artifact.relativePath)")
    }
    $provenanceHash = (Get-FileHash -LiteralPath $provenancePath -Algorithm SHA256).Hash.ToLowerInvariant()
    $checksumLines.Add("$provenanceHash  metadata/build-provenance.json")
    $checksumLines | Set-Content -LiteralPath (Join-Path $metadataDir "artifacts.sha256.txt") -Encoding ASCII
}

$brandRoot = Resolve-FullPath -Path $BrandPath -RequireDirectory
$outputRoot = Resolve-FullPath -Path $OutputPath
if ($outputRoot.StartsWith($brandRoot + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "OutputPath must not be inside BrandPath"
}
Assert-OutputIsFresh -Root $outputRoot

$coreCommit = Get-GitCommit -Repository $WorkspaceRoot
$factoryCommitResolved = Resolve-FactoryCommit -ExplicitCommit $FactoryCommit
$packageJson = Get-Content -LiteralPath (Join-Path $LauncherDir "package.json") -Raw -Encoding UTF8 | ConvertFrom-Json
$version = [string]$packageJson.version
$compiledRoot = Join-Path $outputRoot ".brand-build"
$environmentBeforeBuild = @{}

try {
    $compilerArguments = @(
        $Compiler,
        "--brand-path", $brandRoot,
        "--output-path", $compiledRoot,
        "--version", $version,
        "--core-commit", $coreCommit,
        "--factory-commit", $factoryCommitResolved
    )
    if ($AllowDemo) {
        $compilerArguments += "--allow-demo"
    }
    Invoke-Checked "Compile and validate OEM brand pack" {
        & $Python @compilerArguments
    }

    $planPath = Join-Path $compiledRoot "brand-build-plan.json"
    $plan = Get-Content -LiteralPath $planPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $brandTauriConfig = Join-Path $compiledRoot "tauri.brand.conf.json"
    if ([System.IO.Path]::GetFullPath([string]$plan.paths.tauriConfig) -ne [System.IO.Path]::GetFullPath($brandTauriConfig)) {
        throw "Compiled Tauri brand config path is inconsistent"
    }
    Copy-Item -LiteralPath $planPath -Destination (Join-Path $outputRoot "brand-build-plan.json") -Force
    if ($PlanOnly) {
        Write-Host "Plan-only validation completed: $planPath" -ForegroundColor Green
        return
    }

    Assert-GitWorktreeClean -Repository $WorkspaceRoot
    if (-not (Test-DesktopSigningKey)) {
        throw "LOOM_DESKTOP_UPDATE_PRIVATE_KEY or LOOM_DESKTOP_UPDATE_PRIVATE_KEY_PATH is required for a complete OEM build"
    }
    if ([bool]$plan.android.enabled) {
        Assert-AndroidSigning
    }

    Set-CompiledEnvironment -EnvironmentPath $plan.paths.environment -Previous $environmentBeforeBuild
    if (-not (Test-Path -LiteralPath (Join-Path $plan.paths.frontendPublic $plan.frontend.bundledLogoRelativePath) -PathType Leaf)) {
        throw "Bundled frontend brand logo is missing"
    }

    Invoke-Checked "Install deterministic desktop dependencies" {
        Push-Location $LauncherDir
        try {
            npm ci
        } finally {
            Pop-Location
        }
    }

    Invoke-Checked "Generate desktop and Android brand icons" {
        Push-Location $LauncherDir
        try {
            npm run tauri -- icon $plan.assets.logo --output $plan.paths.icons
        } finally {
            Pop-Location
        }
    }

    $generatedIcon = Join-Path $plan.paths.icons "icon.png"
    if (-not (Test-Path -LiteralPath $generatedIcon -PathType Leaf)) {
        throw "Generated brand icon is missing: $generatedIcon"
    }
    New-InstallerBitmap `
        -Path (Join-Path $plan.paths.installer "nsis-header.bmp") `
        -IconPath $generatedIcon `
        -Title $plan.desktop.productName `
        -Width 150 `
        -Height 57
    New-InstallerBitmap `
        -Path (Join-Path $plan.paths.installer "nsis-sidebar.bmp") `
        -IconPath $generatedIcon `
        -Title $plan.desktop.productName `
        -Width 164 `
        -Height 314 `
        -Vertical
    if ([bool]$plan.android.enabled) {
        Copy-AndroidIconResources -IconRoot $plan.paths.icons -Destination $plan.paths.androidRes
    }

    Invoke-Checked "Bind OEM desktop update public key" {
        & $Python $PrepareUpdateConfigScript --config (Join-Path $plan.paths.runtime "desktop-update-brand.json")
    }

    $buildStartedAt = Get-Date
    Invoke-Checked "Build branded Windows installer" {
        Push-Location $LauncherDir
        try {
            npm run tauri -- build `
                --bundles nsis `
                --config $ProtectedTauriConfig `
                --config $plan.paths.tauriConfig
        } finally {
            Pop-Location
        }
    }

    $nsisRoot = Join-Path $LauncherDir "src-tauri\target\release\bundle\nsis"
    $nsisInstaller = Get-ChildItem -LiteralPath $nsisRoot -File -Filter "*.exe" |
        Where-Object { $_.LastWriteTime -ge $buildStartedAt.AddSeconds(-2) } |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    if (-not $nsisInstaller) {
        throw "Branded NSIS installer was not produced under $nsisRoot"
    }

    $windowsOutput = Join-Path $outputRoot "windows"
    $updateOutput = Join-Path $outputRoot "update"
    New-Item -ItemType Directory -Path $windowsOutput -Force | Out-Null
    New-Item -ItemType Directory -Path $updateOutput -Force | Out-Null
    $canonicalInstallerName = "$($plan.update.filePrefix)-$version-setup.exe"
    $canonicalInstaller = Join-Path $windowsOutput $canonicalInstallerName
    Copy-Item -LiteralPath $nsisInstaller.FullName -Destination $canonicalInstaller -Force

    $downloadUrl = Get-ManifestDownloadUrl `
        -ManifestUrl $plan.update.manifestUrl `
        -Filename $canonicalInstallerName
    Invoke-Checked "Sign branded desktop update channel" {
        & powershell -NoProfile -ExecutionPolicy Bypass -File $PrepareUpdateScript `
            -InstallerPath $canonicalInstaller `
            -Version $version `
            -OutputDirectory $updateOutput `
            -Product $plan.update.product `
            -Channel $plan.update.channel `
            -ChannelId $plan.update.channelId `
            -FilePrefix $plan.update.filePrefix `
            -DownloadUrl $downloadUrl `
            -PublicKeyPath (Join-Path $plan.paths.runtime "desktop-update-brand.json")
    }
    $signedManifest = Join-Path $updateOutput "$canonicalInstallerName.update.json"
    if (-not (Test-Path -LiteralPath $signedManifest -PathType Leaf)) {
        throw "Signed desktop update manifest is missing: $signedManifest"
    }
    Copy-Item -LiteralPath $signedManifest -Destination (Join-Path $updateOutput "latest.json") -Force

    $portablePackagePrefix = "$($plan.update.filePrefix)-Portable"
    $portablePackageName = "$portablePackagePrefix-v$version-oem"
    Invoke-Checked "Build branded portable package" {
        & powershell -NoProfile -ExecutionPolicy Bypass -File $PortableBuilder `
            -Version $version `
            -PackageName $portablePackageName `
            -BrandProfile $plan.brandId `
            -ProductName $plan.desktop.productName `
            -PackagePrefix $portablePackagePrefix `
            -LauncherExeName $plan.desktop.binaryName `
            -BrandThemeDir (Join-Path $plan.paths.runtime "themes\$($plan.brandId)") `
            -BrandProfilePath (Join-Path $plan.paths.runtime "brand_profile.json") `
            -DesktopUpdateBrandPath (Join-Path $plan.paths.runtime "desktop-update-brand.json") `
            -SkipBuild
    }
    $portableSource = Join-Path $PlatformRoot "release\$portablePackageName.zip"
    $portableHashSource = "$portableSource.sha256.txt"
    if (-not (Test-Path -LiteralPath $portableSource -PathType Leaf)) {
        throw "Branded portable package is missing: $portableSource"
    }
    Copy-Item -LiteralPath $portableSource -Destination (Join-Path $windowsOutput "$portablePackageName.zip") -Force
    Copy-Item -LiteralPath $portableHashSource -Destination (Join-Path $windowsOutput "$portablePackageName.zip.sha256.txt") -Force

    if ([bool]$plan.android.enabled) {
        $androidBuildStartedAt = Get-Date
        Invoke-Checked "Build signed branded Android APK" {
            Push-Location $PhoneAgentDir
            try {
                & .\gradlew.bat assembleRelease `
                    "-POEM_APPLICATION_ID=$($plan.android.applicationId)" `
                    "-POEM_APP_NAME=$($plan.android.appName)" `
                    "-POEM_FILE_PREFIX=$($plan.android.filePrefix)" `
                    "-POEM_RES_DIR=$($plan.android.resDir)"
            } finally {
                Pop-Location
            }
        }
        $apkSource = Get-ChildItem -LiteralPath (Join-Path $PhoneAgentDir "app\build\outputs\apk\release") -File -Filter "*.apk" |
            Where-Object { $_.LastWriteTime -ge $androidBuildStartedAt.AddSeconds(-2) } |
            Sort-Object LastWriteTime -Descending |
            Select-Object -First 1
        if (-not $apkSource) {
            throw "Branded Android release APK was not produced"
        }
        $androidOutput = Join-Path $outputRoot "android"
        New-Item -ItemType Directory -Path $androidOutput -Force | Out-Null
        Copy-Item `
            -LiteralPath $apkSource.FullName `
            -Destination (Join-Path $androidOutput "$($plan.android.filePrefix)-$version.apk") `
            -Force
    }

    Write-Provenance `
        -OutputRoot $outputRoot `
        -Plan $plan `
        -CoreCommit $coreCommit `
        -FactoryCommit $factoryCommitResolved `
        -BuildConfiguration $Configuration

    Write-Host ""
    Write-Host "OEM build completed: $outputRoot" -ForegroundColor Green
} finally {
    Restore-Environment -Previous $environmentBeforeBuild
}
