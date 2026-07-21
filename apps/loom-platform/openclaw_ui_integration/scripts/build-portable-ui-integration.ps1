param(
    [string]$Version = "",
    [string]$PackageName = "",
    [string]$OpenClawRuntimeVersion = "2026.6.5",
    [string]$SeedPortableDir = "",
    [string]$BrandProfile = "openclaw",
    [string]$DesktopAgentSourceRoot = "",
    [string]$PhoneAgentVerifiedVersion = "",
    [int]$PhoneAgentVerifiedVersionCode = 0,
    [switch]$SkipBuild,
    [switch]$NoZip,
    [switch]$IncludePhoneAgentApk
)

$ErrorActionPreference = "Stop"

$SandboxDir = Split-Path -Parent $PSScriptRoot
$Root = Split-Path -Parent $SandboxDir
$LauncherDir = $SandboxDir
$TauriDir = Join-Path $LauncherDir "src-tauri"
$ReleaseDir = Join-Path $Root "release"
$ToolScriptsDir = Join-Path $Root "scripts"
$VerifyScript = Join-Path $ToolScriptsDir "verify-release.ps1"
$SmokeVerifyScript = Join-Path $ToolScriptsDir "verify-portable-smoke.ps1"

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

function Get-ResolvedPathOrNull {
    param([string]$Path)

    if ([string]::IsNullOrWhiteSpace($Path) -or -not (Test-Path -LiteralPath $Path)) {
        return $null
    }

    return (Resolve-Path -LiteralPath $Path).Path
}

function Get-LauncherVersion {
    $packageJsonPath = Join-Path $LauncherDir "package.json"
    if (Test-Path -LiteralPath $packageJsonPath) {
        $packageJson = Get-Content -LiteralPath $packageJsonPath -Raw | ConvertFrom-Json
        if (-not [string]::IsNullOrWhiteSpace([string]$packageJson.version)) {
            return [string]$packageJson.version
        }
    }

    $tauriConfigPath = Join-Path $TauriDir "tauri.conf.json"
    if (Test-Path -LiteralPath $tauriConfigPath) {
        $tauriConfig = Get-Content -LiteralPath $tauriConfigPath -Raw | ConvertFrom-Json
        if (-not [string]::IsNullOrWhiteSpace([string]$tauriConfig.version)) {
            return [string]$tauriConfig.version
        }
    }

    throw "Unable to determine launcher version from package.json or tauri.conf.json."
}

function Assert-SourceVersionConsistency {
    $packageJsonPath = Join-Path $LauncherDir "package.json"
    $tauriConfigPath = Join-Path $TauriDir "tauri.conf.json"
    $packageVersion = $null
    $tauriVersion = $null

    if (Test-Path -LiteralPath $packageJsonPath) {
        $packageJson = Get-Content -LiteralPath $packageJsonPath -Raw | ConvertFrom-Json
        $packageVersion = [string]$packageJson.version
    }
    if (Test-Path -LiteralPath $tauriConfigPath) {
        $tauriConfig = Get-Content -LiteralPath $tauriConfigPath -Raw | ConvertFrom-Json
        $tauriVersion = [string]$tauriConfig.version
    }

    if ([string]::IsNullOrWhiteSpace($packageVersion)) {
        throw "package.json version is missing: $packageJsonPath"
    }
    if ([string]::IsNullOrWhiteSpace($tauriVersion)) {
        throw "tauri.conf.json version is missing: $tauriConfigPath"
    }
    if ($packageVersion -ne $tauriVersion) {
        throw "Launcher version mismatch: package.json=$packageVersion, tauri.conf.json=$tauriVersion"
    }

    return $packageVersion
}

function Assert-PackageNameVersionConsistency {
    param(
        [string]$ResolvedVersion,
        [string]$ResolvedPackageName
    )

    if ([string]::IsNullOrWhiteSpace($ResolvedPackageName)) {
        throw "PackageName is empty"
    }

    if ($ResolvedPackageName -notmatch '^OpenClaw-Portable-v(?<version>\d+(?:\.\d+){1,3})-') {
        throw "PackageName must encode the launcher version: $ResolvedPackageName"
    }

    $packageVersion = [string]$Matches.version
    if ($packageVersion -ne $ResolvedVersion) {
        throw "Package name version mismatch: packageName=$ResolvedPackageName, launcherVersion=$ResolvedVersion"
    }
}

function Assert-InWorkspace {
    param([string]$ResolvedPath)

    $resolvedRoot = (Resolve-Path -LiteralPath $Root).Path
    if (-not $ResolvedPath.StartsWith($resolvedRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to operate outside workspace: $ResolvedPath"
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

function Copy-Directory {
    param(
        [string]$Source,
        [string]$Destination,
        [string[]]$ExcludeDirs = @(),
        [string[]]$ExcludeFiles = @()
    )

    if (-not (Test-Path -LiteralPath $Source)) {
        throw "Directory not found: $Source"
    }

    $destinationParent = Split-Path -Parent $Destination
    New-Item -ItemType Directory -Path $destinationParent -Force | Out-Null

    $args = @(
        $Source,
        $Destination,
        "/MIR",
        "/R:2",
        "/W:1",
        "/NFL",
        "/NDL",
        "/NJH",
        "/NJS",
        "/NP"
    )
    if ($ExcludeDirs.Count -gt 0) {
        $args += "/XD"
        $args += $ExcludeDirs
    }
    if ($ExcludeFiles.Count -gt 0) {
        $args += "/XF"
        $args += $ExcludeFiles
    }

    & robocopy @args | Out-Host
    $code = $LASTEXITCODE
    if ($code -ge 8) {
        throw "robocopy failed with exit code $code from $Source to $Destination"
    }
    $global:LASTEXITCODE = 0
}

function Test-SeedPortableDir {
    param([string]$Path)

    $required = @(
        "node\node.exe",
        "node_modules\openclaw\openclaw.mjs",
        "_up_\python-runtime\python.exe",
        "start.js",
        "package.json",
        "package-lock.json"
    )

    $candidateRoots = @(
        $Path,
        (Join-Path $Path "OpenClawFiles")
    )

    foreach ($rootPath in $candidateRoots) {
        $valid = $true
        foreach ($item in $required) {
            if (-not (Test-Path -LiteralPath (Join-Path $rootPath $item))) {
                $valid = $false
                break
            }
        }
        if ($valid) {
            return $true
        }
    }
    return $false
}

function Find-SeedPortableDir {
    $targetPortableDir = Join-Path $ReleaseDir $PackageName

    if (-not [string]::IsNullOrWhiteSpace($SeedPortableDir)) {
        $resolved = Get-ResolvedPathOrNull $SeedPortableDir
        if (-not $resolved -or -not (Test-SeedPortableDir $resolved)) {
            throw "Seed portable directory is invalid: $SeedPortableDir"
        }
        if ($resolved.Equals($targetPortableDir, [System.StringComparison]::OrdinalIgnoreCase)) {
            throw "Seed portable directory cannot be the same as output directory: $resolved"
        }
        return $resolved
    }

    if (-not (Test-Path -LiteralPath $ReleaseDir)) {
        throw "Release directory not found: $ReleaseDir"
    }

    $candidates = Get-ChildItem -LiteralPath $ReleaseDir -Directory |
        Where-Object {
            -not $_.FullName.Equals($targetPortableDir, [System.StringComparison]::OrdinalIgnoreCase) -and
            (Test-SeedPortableDir $_.FullName)
        } |
        Sort-Object LastWriteTime -Descending

    $seed = $candidates | Select-Object -First 1
    if (-not $seed) {
        Write-Warning "No usable seed portable directory found under $ReleaseDir; falling back to bootstrap package layout."
        return $null
    }

    return $seed.FullName
}

function Get-NodeRuntimeDir {
    $nodeCommand = Get-Command node -ErrorAction Stop
    if ([string]::IsNullOrWhiteSpace($nodeCommand.Source)) {
        throw "Unable to resolve node runtime path from PATH."
    }

    $nodeExe = Get-Item -LiteralPath $nodeCommand.Source
    return $nodeExe.Directory.FullName
}

function Get-PythonRuntimeDir {
    $pythonCommand = Get-Command python -ErrorAction Stop
    if ([string]::IsNullOrWhiteSpace($pythonCommand.Source)) {
        throw "Unable to resolve python runtime path from PATH."
    }

    $pythonExe = Get-Item -LiteralPath $pythonCommand.Source
    return $pythonExe.Directory.FullName
}

function Copy-PythonRuntime {
    param([string]$PackageDir)

    $target = Join-Path $PackageDir "_up_\python-runtime"
    if (Test-Path -LiteralPath (Join-Path $target "python.exe")) {
        return
    }

    Remove-SafePath $target
    Copy-Directory `
        -Source (Get-PythonRuntimeDir) `
        -Destination $target `
        -ExcludeDirs @("__pycache__", "site-packages") `
        -ExcludeFiles @("*.pyc", "*.pyo")

    if (-not (Test-Path -LiteralPath (Join-Path $target "python.exe"))) {
        throw "Python runtime bootstrap did not create required file: $target\python.exe"
    }
}

function Write-PortableStartJs {
    param([string]$PackageDir)

    $content = @'
import { spawn } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const openclaw = path.join(__dirname, 'node_modules', 'openclaw', 'openclaw.mjs');
const port = process.env.OPENCLAW_GATEWAY_PORT || '18790';
const child = spawn(process.execPath, [
  openclaw,
  'gateway',
  '--port',
  port,
  '--bind',
  'loopback',
  '--auth',
  'none',
  '--allow-unconfigured',
], {
  cwd: __dirname,
  env: process.env,
  stdio: 'inherit',
  windowsHide: true,
});

child.on('exit', (code, signal) => {
  if (signal) {
    console.log(`[OpenClaw] gateway stopped by ${signal}`);
  }
  process.exit(code ?? 0);
});

child.on('error', (error) => {
  console.error('[OpenClaw] failed to start gateway:', error);
  process.exit(1);
});
'@

    Set-Content -LiteralPath (Join-Path $PackageDir "start.js") -Value $content -Encoding UTF8
}

function Write-PortableRuntimePackageJson {
    param([string]$PackageDir)

    $packageJson = [ordered]@{
        type = "module"
        version = $Version
        scripts = [ordered]@{
            start = "node start.js"
            "verify:phone" = "powershell -ExecutionPolicy Bypass -File scripts/verify-phone-agent.ps1"
            "phone:image" = "node scripts/openclaw-image-phone.mjs"
            "phone:image:edit" = "node scripts/openclaw-image-phone.mjs --mode edit"
            "phone:agent" = "node scripts/openclaw-phone-agent.mjs"
            "phone:fleet" = "node scripts/openclaw-phone-fleet.mjs"
            "phone:video" = "node scripts/openclaw-phone-video.mjs"
            "phone:vision" = "node scripts/openclaw-phone-vision.mjs"
            "phone:game" = "node scripts/openclaw-phone-game.mjs"
            "phone:publish" = "node scripts/openclaw-publish-phone.mjs"
            "phone:relay" = "node scripts/openclaw-publish-relay.mjs"
            "phone:relay:check" = "node scripts/openclaw-publish-relay-check.mjs"
            "phone:relay:smoke" = "node scripts/openclaw-publish-relay-smoke.mjs"
            "openclaw:context" = "node scripts/openclaw-context.mjs"
        }
        dependencies = [ordered]@{
            "@dingtalk-real-ai/dingtalk-connector" = "0.8.23"
            "@larksuite/openclaw-lark" = "2026.5.20"
            "@tencent-weixin/openclaw-weixin" = "2.4.4"
            openclaw = $OpenClawRuntimeVersion
        }
    }

    $packageJson |
        ConvertTo-Json -Depth 10 |
        Set-Content -LiteralPath (Join-Path $PackageDir "package.json") -Encoding UTF8
}

function Install-PortableRuntimeNodeModules {
    param([string]$PackageDir)

    Push-Location $PackageDir
    try {
        npm install --omit=dev --ignore-scripts --no-audit --fund=false
    } finally {
        Pop-Location
    }

    foreach ($required in @(
        "node_modules\openclaw\openclaw.mjs",
        "node_modules\@larksuite\openclaw-lark\package.json",
        "node_modules\@tencent-weixin\openclaw-weixin\package.json",
        "package-lock.json"
    )) {
        $path = Join-Path $PackageDir $required
        if (-not (Test-Path -LiteralPath $path)) {
            throw "Portable runtime bootstrap did not create required file: $path"
        }
    }
}

function Initialize-PortableBootstrap {
    param([string]$PackageDir)

    New-Item -ItemType Directory -Path $PackageDir -Force | Out-Null

    Copy-Directory -Source (Get-NodeRuntimeDir) -Destination (Join-Path $PackageDir "node")

    if (-not (Test-Path -LiteralPath (Join-Path $PackageDir ".npmrc"))) {
        Set-Content -LiteralPath (Join-Path $PackageDir ".npmrc") -Value @("fund=false", "audit=false") -Encoding ASCII
    }

    Write-PortableRuntimePackageJson -PackageDir $PackageDir
    Write-PortableStartJs -PackageDir $PackageDir
    Install-PortableRuntimeNodeModules -PackageDir $PackageDir
}

function Find-TauriExe {
    $candidatePaths = @(
        (Join-Path $TauriDir "target\release\app.exe"),
        (Join-Path $TauriDir "target\release\OpenClaw.exe")
    )

    $candidateExe = $candidatePaths |
        Where-Object { Test-Path -LiteralPath $_ } |
        ForEach-Object { Get-Item -LiteralPath $_ } |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1

    if ($candidateExe) {
        return $candidateExe.FullName
    }

    $exe = Get-ChildItem -LiteralPath (Join-Path $TauriDir "target\release") -Filter "*.exe" -File -ErrorAction SilentlyContinue |
        Where-Object { $_.DirectoryName -eq (Join-Path $TauriDir "target\release") } |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1

    if (-not $exe) {
        throw "Could not find built Tauri exe under src-tauri\target\release"
    }

    return $exe.FullName
}

function Get-PhoneAgentVersionCodeFromVersion {
    param([string]$VersionName)

    if ($VersionName -match "^(\d+)\.(\d+)$") {
        $major = [int]$Matches[1]
        $minor = [int]$Matches[2]
        if ($major -eq 6) {
            return 600 + ($minor * 10)
        }
    }

    return 0
}

function Resolve-PhoneAgentVersionInfo {
    $resolvedVersion = $PhoneAgentVerifiedVersion.Trim()
    $resolvedCode = $PhoneAgentVerifiedVersionCode
    $latestApk = Join-Path $LauncherDir "AgentPhone_latest.apk"
    $sourceRuntimeContext = Join-Path $LauncherDir "openclaw-workspace\runtime-context.json"

    if (Test-Path -LiteralPath $latestApk) {
        $latestHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $latestApk).Hash
        $matchingVersionedApk = Get-ChildItem -LiteralPath $LauncherDir -File -Filter "AgentPhone_v*.apk" -ErrorAction SilentlyContinue |
            Where-Object { (Get-FileHash -Algorithm SHA256 -LiteralPath $_.FullName).Hash -eq $latestHash } |
            Sort-Object LastWriteTime -Descending |
            Select-Object -First 1

        if (-not $matchingVersionedApk) {
            throw "AgentPhone_latest.apk hash does not match any versioned AgentPhone APK under $LauncherDir"
        }

        if ($matchingVersionedApk.Name -match "AgentPhone_v(?<version>\d+\.\d+)_") {
            if ([string]::IsNullOrWhiteSpace($resolvedVersion)) {
                $resolvedVersion = $Matches["version"]
            }
        }
        else {
            throw "Matched AgentPhone APK name does not encode version: $($matchingVersionedApk.Name)"
        }
    }

    if ([string]::IsNullOrWhiteSpace($resolvedVersion)) {
        if (Test-Path -LiteralPath $sourceRuntimeContext) {
            $sourceContext = Get-Content -LiteralPath $sourceRuntimeContext -Raw | ConvertFrom-Json
            $sourcePhoneAgent = $sourceContext.capabilities.phoneAgent
            $resolvedVersion = [string]$sourcePhoneAgent.verifiedVersion
            if ($resolvedCode -le 0) {
                try {
                    $resolvedCode = [int]$sourcePhoneAgent.verifiedVersionCode
                } catch {
                    $resolvedCode = 0
                }
            }
        }
    }

    if ([string]::IsNullOrWhiteSpace($resolvedVersion) -or $resolvedVersion -eq "unknown") {
        throw "Unable to resolve phone agent verified version. Pass -PhoneAgentVerifiedVersion or update openclaw-workspace\runtime-context.json."
    }

    if ($resolvedCode -le 0) {
        $resolvedCode = Get-PhoneAgentVersionCodeFromVersion -VersionName $resolvedVersion
    }

    if ($resolvedCode -le 0) {
        throw "Unable to resolve phone agent verified versionCode. Pass -PhoneAgentVerifiedVersionCode or update openclaw-workspace\runtime-context.json."
    }

    return [pscustomobject]@{
        Version = $resolvedVersion
        VersionCode = $resolvedCode
    }
}

function Write-CleanRuntimeConfig {
    param(
        [string]$PackageDir,
        [string]$ProfileName,
        [string]$ThemeId,
        [string]$Edition
    )

    $dataDir = Join-Path $PackageDir "data"
    $stateDir = Join-Path $dataDir ".openclaw"
    $agentDir = Join-Path $stateDir "agents\main\agent"
    $launcherStateDir = Join-Path $stateDir "launcher"
    $workspaceDir = Join-Path $stateDir "workspace"
    $storyboardAssets = Join-Path $dataDir "storyboards\assets"

    New-Item -ItemType Directory -Path $agentDir -Force | Out-Null
    New-Item -ItemType Directory -Path $launcherStateDir -Force | Out-Null
    New-Item -ItemType Directory -Path $workspaceDir -Force | Out-Null
    New-Item -ItemType Directory -Path $storyboardAssets -Force | Out-Null

    $openclawConfig = [ordered]@{
        gateway = [ordered]@{
            auth = [ordered]@{
                mode = "none"
            }
            bind = "loopback"
        }
        agents = [ordered]@{
            defaults = [ordered]@{
                workspace = "data/.openclaw/workspace"
                contextInjection = "always"
                bootstrapPromptTruncationWarning = "once"
            }
        }
        plugins = [ordered]@{
            entries = [ordered]@{
                workboard = [ordered]@{
                    enabled = $true
                }
            }
        }
    }
    $openclawConfig | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath (Join-Path $stateDir "openclaw.json") -Encoding UTF8

    $brandProfile = [ordered]@{
        profile = $ProfileName
        themeId = $ThemeId
        edition = $Edition
    }
    $brandProfile | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath (Join-Path $dataDir "brand_profile.json") -Encoding UTF8

    $launcherRuntime = [ordered]@{
        name = "OpenClaw Portable Launcher"
        version = $Version
        packageName = $PackageName
    }
    $launcherRuntime | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath (Join-Path $dataDir "launcher_runtime.json") -Encoding UTF8

    "{}" | Set-Content -LiteralPath (Join-Path $PackageDir "imgapi_config.json") -Encoding UTF8
    "{}" | Set-Content -LiteralPath (Join-Path $PackageDir "video_config.json") -Encoding UTF8

    $phoneAgentVersionInfo = Resolve-PhoneAgentVersionInfo

    $runtimeContext = [ordered]@{
        schema = "openclaw.launcher.runtime-context.v1"
        updatedAt = $null
        launcher = [ordered]@{
            name = "OpenClaw Portable Launcher"
            version = $Version
            mode = "usb-portable"
            root = "."
        }
        workspace = [ordered]@{
            path = "data/.openclaw/workspace"
            bootstrapFiles = @("AGENTS.md", "SOUL.md", "TOOLS.md", "CAPABILITIES.md")
            skillsPath = "data/.openclaw/workspace/skills"
        }
        paths = [ordered]@{
            generatedImages = "data/generated-images"
            phoneVideos = "data/phone-videos"
            scripts = "scripts"
            imageToPhoneCli = "scripts/openclaw-image-phone.mjs"
            phoneAgentCli = "scripts/openclaw-phone-agent.mjs"
            phoneFleetCli = "scripts/openclaw-phone-fleet.mjs"
            phoneVideoCli = "scripts/openclaw-phone-video.mjs"
            phoneVisionCli = "scripts/openclaw-phone-vision.mjs"
            phoneGameCli = "scripts/openclaw-phone-game.mjs"
            phoneVerifier = "scripts/verify-phone-agent.ps1"
        }
        capabilities = [ordered]@{
            imageGeneration = [ordered]@{
                available = $true
                localOutputDir = "data/generated-images"
                cli = "npm run phone:image"
                editCli = "npm run phone:image:edit -- --reference-image <path> --prompt `"<edit instruction>`""
            }
            phoneAgent = [ordered]@{
                available = $true
                controlPolicy = "wrapper-only"
                agentCli = "npm run phone:agent"
                fleetCli = "npm run phone:fleet"
                multiDevice = $true
                defaultDeviceId = $null
                deviceCliArg = "--device-id <device-id>"
                imageCli = "npm run phone:image"
                imageEditCli = "npm run phone:image:edit -- --reference-image <path> --prompt `"<edit instruction>`""
                visionCli = "npm run phone:vision"
                videoDownloadDir = "data/phone-videos"
                videoCli = "npm run phone:video"
                gameModeCli = "npm run phone:game"
                defaultAlbum = "OpenClaw"
                galleryPath = "Pictures/OpenClaw"
                verifiedVersion = $phoneAgentVersionInfo.Version
                verifiedVersionCode = $phoneAgentVersionInfo.VersionCode
                maxRoundsPerTask = 60
                tokenSource = "data/.openclaw/launcher/phone-agent.json"
                fleetTokenSource = "data/.openclaw/launcher/phone-agents.json"
                tokenPolicy = "never expose token; use launcher CLI helpers only"
            }
            portableRuntime = [ordered]@{
                available = $true
                preferRelativePaths = $true
            }
            officeSkills = [ordered]@{
                available = $true
                skills = @(
                    "openclaw-meeting-notes",
                    "openclaw-weekly-report",
                    "openclaw-pdf-ocr",
                    "openclaw-excel-analysis",
                    "openclaw-presentation-builder",
                    "openclaw-file-organizer"
                )
                skillsPath = "data/.openclaw/workspace/skills"
            }
        }
        phone = [ordered]@{
            configured = $false
            connected = $false
            endpoint = "launcher-cli-wrapper"
            baseUrl = $null
            tokenAvailable = $false
            configPath = "data/.openclaw/launcher/phone-agent.json"
            fleetConfigPath = "data/.openclaw/launcher/phone-agents.json"
            devices = @()
            defaultDeviceId = $null
            lastStatus = $null
        }
        policies = [ordered]@{
            autoSendGeneratedImagesToPhone = "enabled_when_phone_configured"
            autoUploadPersonalFiles = $false
            screenRecordingRequiresExplicitIntent = $true
            neverExposeSecrets = $true
        }
    }
    $runtimeContext | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath (Join-Path $workspaceDir "runtime-context.json") -Encoding UTF8
}

function Resolve-BrandProfile {
    param([string]$Profile)

    $normalized = if ([string]::IsNullOrWhiteSpace($Profile)) { "openclaw" } else { $Profile.Trim() }
    switch -Regex ($normalized.ToLowerInvariant()) {
        "^(openclaw|launcher|default)$" {
            return [pscustomobject]@{ Profile = "openclaw"; ThemeId = "default"; Edition = "openclaw" }
        }
        "^(lumi|personal|private)$" {
            return [pscustomobject]@{ Profile = "lumi"; ThemeId = "lumi"; Edition = "personal" }
        }
        "^(customer|delivery|yonghao|yonghao_tech)$" {
            return [pscustomobject]@{ Profile = "customer"; ThemeId = "yonghao_tech"; Edition = "delivery" }
        }
        default {
            return [pscustomobject]@{ Profile = $normalized; ThemeId = $normalized; Edition = "custom" }
        }
    }
}

function Copy-ThemeBundle {
    param(
        [string]$PackageDir,
        [string]$ThemeId
    )

    $themeRoot = Join-Path $LauncherDir "data\themes"
    $normalizedThemeId = if ([string]::IsNullOrWhiteSpace($ThemeId)) { "default" } else { $ThemeId.Trim() }
    $themeIds = New-Object System.Collections.Generic.List[string]
    $themeIds.Add("default")
    if ($normalizedThemeId -ne "default") {
        $themeIds.Add($normalizedThemeId)
    }

    $destinations = @(
        (Join-Path $PackageDir "data\themes"),
        (Join-Path $PackageDir "_up_\data\themes")
    )

    foreach ($destinationRoot in $destinations) {
        New-Item -ItemType Directory -Path $destinationRoot -Force | Out-Null
        foreach ($themeId in $themeIds) {
            $sourceTheme = Join-Path $themeRoot $themeId
            if (-not (Test-Path -LiteralPath $sourceTheme)) {
                throw "Theme not found: $sourceTheme"
            }
            Copy-Directory -Source $sourceTheme -Destination (Join-Path $destinationRoot $themeId)
        }
    }
}

function Remove-PythonCacheFiles {
    param([string]$PackageDir)

    Get-ChildItem -LiteralPath $PackageDir -Recurse -Directory -Filter "__pycache__" -ErrorAction SilentlyContinue |
        Remove-Item -Recurse -Force
    Get-ChildItem -LiteralPath $PackageDir -Recurse -File -ErrorAction SilentlyContinue |
        Where-Object { $_.Extension -in @(".pyc", ".pyo") } |
        Remove-Item -Force
}

function Remove-NodeCacheDirectories {
    param([string]$PackageDir)

    @(
        Get-ChildItem -LiteralPath $PackageDir -Recurse -Directory -Filter ".cache" -ErrorAction SilentlyContinue
    ) |
        Sort-Object { $_.FullName.Length } -Descending |
        ForEach-Object {
            Remove-SafePath $_.FullName
        }
}

function Install-PythonBridgeDependencies {
    param([string]$PackageDir)

    $requirements = Join-Path $LauncherDir "python\requirements.txt"
    $target = Join-Path $PackageDir "_up_\python"

    if (-not (Test-Path -LiteralPath $requirements)) {
        return
    }
    if (-not (Test-Path -LiteralPath $target)) {
        throw "Python bridge target not found: $target"
    }

    for ($attempt = 1; $attempt -le 2; $attempt++) {
        & python -m pip install `
            --disable-pip-version-check `
            --no-warn-script-location `
            --upgrade `
            --target $target `
            -r $requirements
        if ($LASTEXITCODE -eq 0) {
            return
        }
        if ($attempt -lt 2) {
            Write-Warning "pip install Python bridge dependencies failed with exit code $LASTEXITCODE; retrying..."
            Start-Sleep -Seconds 2
        }
    }
    if ($LASTEXITCODE -ne 0) {
        throw "pip install Python bridge dependencies failed with exit code $LASTEXITCODE"
    }
}

function Remove-MemoryToolArtifacts {
    param([string]$PackageDir)

    $scriptRoots = @(
        (Join-Path $PackageDir "_up_\python-runtime\Scripts"),
        (Join-Path $PackageDir "_up_\python\Scripts")
    )
    $scriptNames = @(
        "omega.exe",
        "omega-script.py",
        "omega-obsidian.exe",
        "omega-obsidian-script.py",
        "clawvault.exe",
        "clawvault-script.py"
    )
    foreach ($root in $scriptRoots) {
        foreach ($name in $scriptNames) {
            Remove-SafePath (Join-Path $root $name)
        }
    }

    $packageRoots = @(
        (Join-Path $PackageDir "_up_\python"),
        (Join-Path $PackageDir "_up_\python-runtime\Lib\site-packages")
    )
    foreach ($root in $packageRoots) {
        if (-not (Test-Path -LiteralPath $root)) {
            continue
        }
        Get-ChildItem -LiteralPath $root -Force -ErrorAction SilentlyContinue |
            Where-Object {
                $_.Name -like "omega_obsidian*" -or
                $_.Name -like "omega-obsidian*" -or
                $_.Name -like "clawvault*" -or
                $_.Name -eq "omega"
            } |
            ForEach-Object { Remove-SafePath $_.FullName }
    }
}

function Remove-OpenClawKnowledgeArtifacts {
    param([string]$PackageDir)

    $openclawRoot = Join-Path $PackageDir "node_modules\openclaw"
    if (-not (Test-Path -LiteralPath $openclawRoot)) {
        return
    }

    @(
        "dist\extensions\memory-wiki",
        "skills\obsidian",
        "docs",
        "CHANGELOG.md"
    ) | ForEach-Object {
        Remove-SafePath (Join-Path $openclawRoot $_)
    }
}

function Copy-PhoneAgentApks {
    param([string]$PackageDir)

    $targetDir = Join-Path $PackageDir "releases\agent-phone"
    Remove-SafePath $targetDir

    if (-not $IncludePhoneAgentApk) {
        Write-Host "Skipping bundled AgentPhone APK. Use -IncludePhoneAgentApk only for internal test packages." -ForegroundColor Yellow
        return
    }

    $latestApk = Join-Path $LauncherDir "AgentPhone_latest.apk"
    if (-not (Test-Path -LiteralPath $latestApk)) {
        Write-Warning "AgentPhone_latest.apk not found; portable package will not include phone agent APK."
        return
    }

    New-Item -ItemType Directory -Path $targetDir -Force | Out-Null

    Copy-Item -LiteralPath $latestApk -Destination (Join-Path $targetDir "AgentPhone_latest.apk") -Force

    $latestHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $latestApk).Hash
    Get-ChildItem -LiteralPath $LauncherDir -File -Filter "AgentPhone_v*.apk" -ErrorAction SilentlyContinue |
        ForEach-Object {
            $candidateHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $_.FullName).Hash
            if ($candidateHash -eq $latestHash) {
                Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $targetDir $_.Name) -Force
            }
        }
}

function Copy-WebView2Redist {
    param([string]$PackageDir)

    $source = Join-Path $LauncherDir "redist\MicrosoftEdgeWebView2RuntimeInstallerX64.exe"
    if (-not (Test-Path -LiteralPath $source)) {
        throw "WebView2 offline installer is missing: $source. Run scripts\download-webview2-runtime.ps1 before packaging."
    }

    $targetDir = Join-Path $PackageDir "redist"
    New-Item -ItemType Directory -Path $targetDir -Force | Out-Null
    Copy-Item -LiteralPath $source -Destination (Join-Path $targetDir "MicrosoftEdgeWebView2RuntimeInstallerX64.exe") -Force
}

function Copy-DesktopAgentSidecar {
    param([string]$PackageDir)

    $sourceRoots = @()
    if (-not [string]::IsNullOrWhiteSpace($DesktopAgentSourceRoot)) {
        $sourceRoots += $DesktopAgentSourceRoot
    }
    $sourceRoots += @(
        # sightflow-desktop-agent-main 是集成版:-main 更全的自动回复能力(多渠道/更可配置)
        # + 移植进来的 http-api-server/sidecar(路由与启动器 desktop_agent.py 的
        # ALLOWED_PROXY_PATHS 对应)。优先取它;sightflow-desktop-agent 为回退。
        (Join-Path $Root "sightflow-desktop-agent-main\sightflow-desktop-agent-main"),
        (Join-Path $Root "sightflow-desktop-agent-main"),
        (Join-Path $Root "sightflow-desktop-agent")
    )
    $sourceRoot = $sourceRoots |
        Where-Object { Test-Path -LiteralPath (Join-Path $_ "package.json") } |
        Select-Object -First 1

    if (-not $sourceRoot) {
        Write-Warning "Luminode Desktop Agent source not found; portable package will not include desktop sidecar."
        return
    }

    $unpackedCandidates = @(
        (Join-Path $sourceRoot "dist\win-unpacked"),
        (Join-Path $sourceRoot "build\win-unpacked")
    )
    $source = $unpackedCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    if (-not $source) {
        Write-Warning "Luminode win-unpacked output not found. Run npm run build:unpack in $sourceRoot before packaging."
        return
    }
    Write-Host "Using Luminode sidecar source: $source"

    foreach ($stale in @(
        "agents\luminode-desktop",
        "agents\sightflow-desktop",
        "agents\sightflow-desktop-agent",
        "sightflow-desktop-agent"
    )) {
        Remove-SafePath (Join-Path $PackageDir $stale)
    }

    $target = Join-Path $PackageDir "agents\luminode-desktop"
    Copy-Directory -Source $source -Destination $target

    $lumiNodeExe = Join-Path $target "LumiNode.exe"
    $luminodeExe = Join-Path $target "Luminode.exe"
    if ((Test-Path -LiteralPath $lumiNodeExe) -and -not (Test-Path -LiteralPath $luminodeExe)) {
        Copy-Item -LiteralPath $lumiNodeExe -Destination $luminodeExe
    }
    $sightFlowExe = Join-Path $target "SightFlow.exe"
    if ((Test-Path -LiteralPath $sightFlowExe) -and -not (Test-Path -LiteralPath $luminodeExe)) {
        Copy-Item -LiteralPath $sightFlowExe -Destination $luminodeExe
    }
}

function Expand-PortablePayloadForBuild {
    param([string]$PackageDir)

    $payloadDir = Join-Path $PackageDir "OpenClawFiles"
    if (-not (Test-Path -LiteralPath $payloadDir)) {
        return
    }
    if (Test-Path -LiteralPath (Join-Path $PackageDir "node\node.exe")) {
        return
    }

    Get-ChildItem -LiteralPath $payloadDir -Force |
        ForEach-Object {
            Move-Item -LiteralPath $_.FullName -Destination $PackageDir -Force
        }
    Remove-SafePath $payloadDir
}

function Remove-LegacyNestedLaunchers {
    param([string]$PackageDir)

    Get-ChildItem -LiteralPath $PackageDir -Directory -ErrorAction SilentlyContinue |
        Where-Object {
            $_.Name -notin @("data", "_up_", "node", "node_modules", "scripts", "releases") -and
            (Test-Path -LiteralPath (Join-Path $_.FullName "app.exe")) -and
            (Test-Path -LiteralPath (Join-Path $_.FullName "data")) -and
            (Test-Path -LiteralPath (Join-Path $_.FullName "_up_"))
        } |
        ForEach-Object {
            Write-Host "Removing legacy nested launcher payload: $($_.FullName)" -ForegroundColor Yellow
            Remove-SafePath $_.FullName
        }
}

function Move-PortablePayload {
    param([string]$PackageDir)

    $payloadDir = Join-Path $PackageDir "OpenClawFiles"
    Remove-SafePath $payloadDir
    New-Item -ItemType Directory -Path $payloadDir -Force | Out-Null

    Get-ChildItem -LiteralPath $PackageDir -Force |
        Where-Object { $_.Name -ne "OpenClaw.exe" -and $_.Name -ne "OpenClawFiles" } |
        ForEach-Object {
            Move-Item -LiteralPath $_.FullName -Destination $payloadDir -Force
        }
}

function Write-PortableReadme {
    param(
        [string]$PackageDir,
        [string]$NodeVersion,
        [string]$OpenClawVersion,
        [switch]$IncludePhoneAgentApk
    )

    $phoneAgentLine = if ($IncludePhoneAgentApk) {
        "6. Phone Agent APK is bundled in this internal package under releases/agent-phone/."
    } else {
        "6. Phone Agent APK is not bundled in public portable packages; install APKClaw separately from the release channel before using phone control."
    }

    $content = @"
OpenClaw offline portable package

1. Copy this whole folder to a USB drive or local disk.
2. Run OpenClaw.exe.
3. Activate with a valid license code on first use.
4. Configure API settings in the launcher before using image/video features.
$phoneAgentLine
This package includes the launcher, bundled Node.js, OpenClaw runtime, Python bridge, workspace, themes, and scripts.

Bundled Node.js: $NodeVersion
Bundled OpenClaw: $OpenClawVersion
"@

    Set-Content -LiteralPath (Join-Path $PackageDir "README-PORTABLE.txt") -Value $content -Encoding UTF8
}

function Get-NodeVersion {
    param([string]$PackageDir)

    $nodeExe = Join-Path $PackageDir "node\node.exe"
    if (Test-Path -LiteralPath $nodeExe) {
        return (& $nodeExe --version).Trim()
    }
    return "unknown"
}

function Get-OpenClawVersion {
    param([string]$PackageDir)

    $pkgPath = Join-Path $PackageDir "node_modules\openclaw\package.json"
    if (Test-Path -LiteralPath $pkgPath) {
        try {
            $pkg = Get-Content -LiteralPath $pkgPath -Raw | ConvertFrom-Json
            if ($pkg.version) {
                return [string]$pkg.version
            }
        } catch {
            return "unknown"
        }
    }
    return "unknown"
}

function Set-JsonProperty {
    param(
        [object]$Object,
        [string]$Name,
        [object]$Value
    )

    if ($Object.PSObject.Properties.Name -contains $Name) {
        $Object.$Name = $Value
    } else {
        $Object | Add-Member -MemberType NoteProperty -Name $Name -Value $Value
    }
}

function Install-BundledBotPlugins {
    param([string]$PackageDir)

    $nodeDir = Join-Path $PackageDir "node"
    $npmCmd = Join-Path $nodeDir "npm.cmd"
    $pkgJsonPath = Join-Path $PackageDir "package.json"
    $openclawVersion = $OpenClawRuntimeVersion

    if (-not (Test-Path -LiteralPath $npmCmd)) {
        throw "Bundled npm not found: $npmCmd"
    }
    if ($openclawVersion -eq "unknown") {
        throw "Cannot read bundled OpenClaw version before installing bot plugins."
    }

    $pkg = Get-Content -LiteralPath $pkgJsonPath -Raw | ConvertFrom-Json
    Set-JsonProperty -Object $pkg -Name "version" -Value $Version
    if (-not $pkg.dependencies) {
        Set-JsonProperty -Object $pkg -Name "dependencies" -Value ([pscustomobject]@{})
    }
    Set-JsonProperty -Object $pkg.dependencies -Name "openclaw" -Value $openclawVersion
    $pkg | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $pkgJsonPath -Encoding UTF8

    $oldPath = $env:Path
    Push-Location $PackageDir
    try {
        $env:Path = "$nodeDir;$oldPath"
        & $npmCmd install --omit=dev --ignore-scripts --no-audit --no-fund --save-exact "openclaw@$OpenClawRuntimeVersion" "@larksuite/openclaw-lark@latest" "@tencent-weixin/openclaw-weixin@latest" "@dingtalk-real-ai/dingtalk-connector@0.8.23"
        if ($LASTEXITCODE -ne 0) {
            throw "npm install bot plugins failed with exit code $LASTEXITCODE"
        }
    } finally {
        Pop-Location
        $env:Path = $oldPath
    }

    $required = @(
        "node_modules\@larksuite\openclaw-lark\package.json",
        "node_modules\@dingtalk-real-ai\dingtalk-connector\package.json",
        "node_modules\@tencent-weixin\openclaw-weixin\package.json"
    )
    foreach ($item in $required) {
        if (-not (Test-Path -LiteralPath (Join-Path $PackageDir $item))) {
            throw "Bundled bot plugin missing after install: $item"
        }
    }
}

function Patch-OpenClawPortableRuntime {
    param([string]$PackageDir)

    $openclawRoot = Join-Path $PackageDir "node_modules\openclaw"
    $distDir = Join-Path $openclawRoot "dist"
    if (-not (Test-Path -LiteralPath $distDir)) {
        throw "OpenClaw dist directory missing after install: $distDir"
    }

    $runtimeFiles = @(Get-ChildItem -LiteralPath $distDir -File -Filter "openai-chatgpt-oauth.runtime-*.js")
    if ($runtimeFiles.Count -eq 0) {
        throw "OpenAI Codex OAuth runtime file missing under $distDir"
    }
    foreach ($file in $runtimeFiles) {
        $content = Get-Content -LiteralPath $file.FullName -Raw
        $delaySource = "const localManualFallbackDelayMs = 15e3;"
        $delayTarget = "const localManualFallbackDelayMs = Number(process.env.OPENCLAW_OAUTH_MANUAL_FALLBACK_MS || 120000);"
        $proxySource = "If you normally use a proxy, verify HTTPS_PROXY, HTTP_PROXY, or ALL_PROXY is set for the OpenClaw process and then retry ``openclaw models auth login --provider openai``."
        $proxyTarget = "If you normally use a proxy, set the OpenAI OAuth proxy in OpenClaw Settings or verify HTTPS_PROXY, HTTP_PROXY, or ALL_PROXY is set for the OpenClaw process, then retry ``openclaw models auth login --provider openai``."
        $patched = $content

        if ($patched.Contains($delaySource)) {
            $patched = $patched.Replace($delaySource, $delayTarget)
        } elseif (-not $patched.Contains($delayTarget)) {
            throw "OpenAI Codex OAuth runtime delay patch did not match expected content: $($file.FullName)"
        }

        if ($patched.Contains($proxySource)) {
            $patched = $patched.Replace($proxySource, $proxyTarget)
        } elseif (-not $patched.Contains($proxyTarget)) {
            throw "OpenAI Codex OAuth runtime proxy hint patch did not match expected content: $($file.FullName)"
        }

        if ($patched -ne $content) {
            Set-Content -LiteralPath $file.FullName -Value $patched -Encoding UTF8
        }
    }

    $flowFiles = @(Get-ChildItem -LiteralPath $distDir -File -Filter "openai-chatgpt-oauth-flow.runtime-*.js")
    if ($flowFiles.Count -eq 0) {
        throw "OpenAI Codex OAuth flow runtime file missing under $distDir"
    }
    foreach ($file in $flowFiles) {
        $content = Get-Content -LiteralPath $file.FullName -Raw
        $delaySource = "const MANUAL_PROMPT_FALLBACK_MS = 15e3;"
        $delayTarget = "const MANUAL_PROMPT_FALLBACK_MS = Number(process.env.OPENCLAW_OAUTH_MANUAL_FALLBACK_MS || 120000);"
        $patched = $content

        if ($patched.Contains($delaySource)) {
            $patched = $patched.Replace($delaySource, $delayTarget)
        } elseif (-not $patched.Contains($delayTarget)) {
            throw "OpenAI Codex OAuth flow patch did not match expected content: $($file.FullName)"
        }

        if ($patched -ne $content) {
            Set-Content -LiteralPath $file.FullName -Value $patched -Encoding UTF8
        }
    }

    Ensure-OpenClawWorkspaceTemplates -OpenClawRoot $openclawRoot

    Write-Host "Patched OpenClaw OAuth runtime fallback to OPENCLAW_OAUTH_MANUAL_FALLBACK_MS (default 120000ms)." -ForegroundColor DarkGray
}

function Get-OpenClawTemplateRawContent {
    param(
        [string]$RelativePath,
        [string]$TemplateName
    )

    $versionTag = "v$OpenClawRuntimeVersion"
    $urls = @(
        "https://raw.githubusercontent.com/openclaw/openclaw/$versionTag/$RelativePath/$TemplateName",
        "https://raw.githubusercontent.com/openclaw/openclaw/main/$RelativePath/$TemplateName"
    )

    foreach ($url in $urls) {
        try {
            $response = Invoke-WebRequest -Uri $url -Headers @{ "User-Agent" = "OpenClaw-Portable-Packager" } -TimeoutSec 30 -UseBasicParsing
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 300 -and -not [string]::IsNullOrWhiteSpace([string]$response.Content)) {
                return [string]$response.Content
            }
        } catch {
            # Try the next source URL.
        }
    }

    throw "Unable to fetch OpenClaw workspace template: $RelativePath/$TemplateName"
}

function Write-Utf8NoBomFile {
    param(
        [string]$Path,
        [string]$Content
    )

    $parent = Split-Path -Parent $Path
    if (-not (Test-Path -LiteralPath $parent)) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }
    $utf8NoBom = [System.Text.UTF8Encoding]::new($false)
    [System.IO.File]::WriteAllText($Path, $Content, $utf8NoBom)
}

function Ensure-OpenClawWorkspaceTemplates {
    param([string]$OpenClawRoot)

    $primaryTemplateDir = Join-Path $OpenClawRoot "src\agents\templates"
    $docsTemplateNames = @(
        "AGENTS.md",
        "SOUL.md",
        "TOOLS.md",
        "USER.md",
        "IDENTITY.md",
        "BOOTSTRAP.md",
        "HEARTBEAT.md"
    )
    $primaryTemplateNamesFromDocs = @(
        "AGENTS.md",
        "SOUL.md",
        "TOOLS.md",
        "USER.md",
        "IDENTITY.md",
        "BOOTSTRAP.md"
    )

    foreach ($templateName in $docsTemplateNames) {
        $content = Get-OpenClawTemplateRawContent -RelativePath "docs/reference/templates" -TemplateName $templateName
        if ($primaryTemplateNamesFromDocs -contains $templateName) {
            Write-Utf8NoBomFile -Path (Join-Path $primaryTemplateDir $templateName) -Content $content
        }
    }

    $heartbeatContent = Get-OpenClawTemplateRawContent -RelativePath "src/agents/templates" -TemplateName "HEARTBEAT.md"
    Write-Utf8NoBomFile -Path (Join-Path $primaryTemplateDir "HEARTBEAT.md") -Content $heartbeatContent

    $requiredPrimaryTemplates = @(
        "AGENTS.md",
        "SOUL.md",
        "TOOLS.md",
        "USER.md",
        "IDENTITY.md",
        "BOOTSTRAP.md",
        "HEARTBEAT.md"
    )
    foreach ($templateName in $requiredPrimaryTemplates) {
        $path = Join-Path $primaryTemplateDir $templateName
        if (-not (Test-Path -LiteralPath $path)) {
            throw "OpenClaw agent template missing after repair: $path"
        }
    }

    Write-Host "Verified OpenClaw workspace templates: $primaryTemplateDir" -ForegroundColor DarkGray
}

if ([string]::IsNullOrWhiteSpace($Version)) {
    $Version = Assert-SourceVersionConsistency
}
else {
    $sourceVersion = Assert-SourceVersionConsistency
    if ($Version -ne $sourceVersion) {
        throw "Requested version does not match launcher source versions: requested=$Version, source=$sourceVersion"
    }
}

if ([string]::IsNullOrWhiteSpace($PackageName)) {
    $date = Get-Date -Format "yyyy.MM.dd"
    $PackageName = "OpenClaw-Portable-v$Version-$date"
}
else {
    Assert-PackageNameVersionConsistency -ResolvedVersion $Version -ResolvedPackageName $PackageName
}

New-Item -ItemType Directory -Path $ReleaseDir -Force | Out-Null

$seedDir = Find-SeedPortableDir
$brand = Resolve-BrandProfile -Profile $BrandProfile
$brandThemeDir = Join-Path $LauncherDir "data\themes\$($brand.ThemeId)"
if (-not (Test-Path -LiteralPath (Join-Path $brandThemeDir "theme.json"))) {
    throw "Brand profile theme not found: $($brand.ThemeId) ($brandThemeDir)"
}
$packageDir = Join-Path $ReleaseDir $PackageName
$zipPath = Join-Path $ReleaseDir "$PackageName.zip"
$hashPath = Join-Path $ReleaseDir "$PackageName.zip.sha256.txt"

Write-Host "Package name: $PackageName"
Write-Host "Seed portable dir: $seedDir"
Write-Host "Brand profile: $($brand.Profile) -> theme $($brand.ThemeId) [$($brand.Edition)]"

Invoke-Step "Clean integration sandbox runtime artifacts" {
    Remove-SafePath (Join-Path $LauncherDir "dist")
    Remove-SafePath (Join-Path $LauncherDir "data\.openclaw")
    Remove-SafePath (Join-Path $LauncherDir "data\logs")
    Remove-PythonCacheFiles -PackageDir $LauncherDir
}

if (-not $SkipBuild) {
    Invoke-Step "Install frontend dependencies" {
        Push-Location $LauncherDir
        try {
            npm install
        } finally {
            Pop-Location
        }
    }

    Invoke-Step "Clean Tauri target for icon resources" {
        Push-Location $TauriDir
        try {
            cargo clean
        } finally {
            Pop-Location
        }
    }

    Invoke-Step "Build Tauri application" {
        Push-Location $LauncherDir
        try {
            npm run tauri -- build
        } finally {
            Pop-Location
        }
    }
}

$tauriExe = Find-TauriExe

Invoke-Step "Create portable directory" {
    Remove-SafePath $packageDir
    Remove-SafePath $zipPath
    Remove-SafePath $hashPath

    if ($seedDir) {
        Copy-Directory -Source $seedDir -Destination $packageDir
    } else {
        Initialize-PortableBootstrap -PackageDir $packageDir
    }
    Write-PortableRuntimePackageJson -PackageDir $packageDir
    Write-PortableStartJs -PackageDir $packageDir
    Expand-PortablePayloadForBuild -PackageDir $packageDir
    Write-PortableRuntimePackageJson -PackageDir $packageDir
    Write-PortableStartJs -PackageDir $packageDir
    Remove-LegacyNestedLaunchers -PackageDir $packageDir
    Copy-Item -LiteralPath $tauriExe -Destination (Join-Path $packageDir "OpenClaw.exe") -Force

    Remove-SafePath (Join-Path $packageDir "data")
    Remove-SafePath (Join-Path $packageDir "_up_\python")
    Remove-SafePath (Join-Path $packageDir "_up_\data")
    Remove-SafePath (Join-Path $packageDir "_up_\python-runtime")

    Copy-Directory `
        -Source (Join-Path $LauncherDir "python") `
        -Destination (Join-Path $packageDir "_up_\python") `
        -ExcludeDirs @("__pycache__") `
        -ExcludeFiles @("*.pyc", "*.pyo")

    Copy-PythonRuntime -PackageDir $packageDir
    Install-PythonBridgeDependencies -PackageDir $packageDir
    Remove-MemoryToolArtifacts -PackageDir $packageDir

    Copy-ThemeBundle -PackageDir $packageDir -ThemeId $brand.ThemeId

    Copy-Directory `
        -Source (Join-Path $LauncherDir "openclaw-workspace") `
        -Destination (Join-Path $packageDir "data\.openclaw\workspace")

    Copy-Directory `
        -Source (Join-Path $LauncherDir "scripts") `
        -Destination (Join-Path $packageDir "scripts") `
        -ExcludeFiles @("build-portable-ui-integration.ps1", "packaged-bridge-contract-smoke.ps1", "packaged-settings-write-smoke.ps1")

    Copy-PhoneAgentApks -PackageDir $packageDir
    Copy-WebView2Redist -PackageDir $packageDir
    Copy-DesktopAgentSidecar -PackageDir $packageDir

    Install-BundledBotPlugins -PackageDir $packageDir
    Patch-OpenClawPortableRuntime -PackageDir $packageDir
    Remove-OpenClawKnowledgeArtifacts -PackageDir $packageDir
    Remove-NodeCacheDirectories -PackageDir $packageDir

    Write-CleanRuntimeConfig -PackageDir $packageDir -ProfileName $brand.Profile -ThemeId $brand.ThemeId -Edition $brand.Edition

    $nodeVersion = Get-NodeVersion -PackageDir $packageDir
    $openclawVersion = Get-OpenClawVersion -PackageDir $packageDir
    Write-PortableReadme -PackageDir $packageDir -NodeVersion $nodeVersion -OpenClawVersion $openclawVersion -IncludePhoneAgentApk:$IncludePhoneAgentApk

    Get-ChildItem -LiteralPath $packageDir -File -Filter "README-*.txt" |
        Where-Object { $_.Name -ne "README-PORTABLE.txt" } |
        Remove-Item -Force

    Remove-PythonCacheFiles -PackageDir $packageDir
    Move-PortablePayload -PackageDir $packageDir
}

Invoke-Step "Verify portable directory" {
    $oldAllowPhoneAgentApk = $env:OPENCLAW_ALLOW_PHONE_AGENT_APK
    try {
        $env:OPENCLAW_ALLOW_PHONE_AGENT_APK = if ($IncludePhoneAgentApk) { "1" } else { "" }
        & powershell -ExecutionPolicy Bypass -File $VerifyScript -Path $packageDir
    } finally {
        $env:OPENCLAW_ALLOW_PHONE_AGENT_APK = $oldAllowPhoneAgentApk
    }
}

Invoke-Step "Smoke verify portable runtime" {
    & powershell -ExecutionPolicy Bypass -File $SmokeVerifyScript -Path $packageDir
}

Invoke-Step "Clean runtime cache after smoke" {
    $payloadDir = Join-Path $packageDir "OpenClawFiles"
    if (Test-Path -LiteralPath $payloadDir) {
        Remove-PythonCacheFiles -PackageDir $payloadDir
    } else {
        Remove-PythonCacheFiles -PackageDir $packageDir
    }
    if (Test-Path -LiteralPath $payloadDir) {
        Remove-PythonCacheFiles -PackageDir $payloadDir
    } else {
        Remove-PythonCacheFiles -PackageDir $packageDir
    }
}

Invoke-Step "Verify portable directory after smoke cleanup" {
    $oldAllowPhoneAgentApk = $env:OPENCLAW_ALLOW_PHONE_AGENT_APK
    try {
        $env:OPENCLAW_ALLOW_PHONE_AGENT_APK = if ($IncludePhoneAgentApk) { "1" } else { "" }
        & powershell -ExecutionPolicy Bypass -File $VerifyScript -Path $packageDir
    } finally {
        $env:OPENCLAW_ALLOW_PHONE_AGENT_APK = $oldAllowPhoneAgentApk
    }
}

if (-not $NoZip) {
    Invoke-Step "Create zip package" {
        Compress-Archive -LiteralPath $packageDir -DestinationPath $zipPath -CompressionLevel Optimal
    }

    Invoke-Step "Verify zip package" {
        $oldAllowPhoneAgentApk = $env:OPENCLAW_ALLOW_PHONE_AGENT_APK
        try {
            $env:OPENCLAW_ALLOW_PHONE_AGENT_APK = if ($IncludePhoneAgentApk) { "1" } else { "" }
            & powershell -ExecutionPolicy Bypass -File $VerifyScript -Path $zipPath
        } finally {
            $env:OPENCLAW_ALLOW_PHONE_AGENT_APK = $oldAllowPhoneAgentApk
        }
    }

    $hash = Get-FileHash -Algorithm SHA256 -LiteralPath $zipPath
    "$($hash.Hash)  $(Split-Path -Leaf $zipPath)" | Set-Content -LiteralPath $hashPath -Encoding ASCII

    Write-Host ""
    Write-Host "Package: $zipPath" -ForegroundColor Green
    Write-Host "SHA256:  $($hash.Hash)" -ForegroundColor Green
} else {
    Write-Host ""
    Write-Host "Package directory: $packageDir" -ForegroundColor Green
}
