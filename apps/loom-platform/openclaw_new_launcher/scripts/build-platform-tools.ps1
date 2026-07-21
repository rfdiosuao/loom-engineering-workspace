param(
  [string]$SourceDirectory = ""
)

$ErrorActionPreference = "Stop"

$launcherRoot = Split-Path -Parent $PSScriptRoot
$resolvedLauncherRoot = [IO.Path]::GetFullPath($launcherRoot).TrimEnd('\', '/')
$targetDirectory = Join-Path $resolvedLauncherRoot "redist\platform-tools"
$requiredFiles = @("adb.exe", "AdbWinApi.dll", "AdbWinUsbApi.dll", "NOTICE.txt")

function Test-CompletePlatformTools {
  param([string]$Directory)

  if ([string]::IsNullOrWhiteSpace($Directory) -or -not (Test-Path -LiteralPath $Directory -PathType Container)) {
    return $false
  }
  foreach ($fileName in $requiredFiles) {
    if (-not (Test-Path -LiteralPath (Join-Path $Directory $fileName) -PathType Leaf)) {
      return $false
    }
  }
  return $true
}

function Add-Candidate {
  param(
    [Collections.Generic.List[string]]$Candidates,
    [string]$Path
  )

  if ([string]::IsNullOrWhiteSpace($Path)) { return }
  $candidate = $Path.Trim().Trim('"')
  if ([IO.Path]::GetFileName($candidate) -ieq "adb.exe") {
    $candidate = Split-Path -Parent $candidate
  }
  if (-not [string]::IsNullOrWhiteSpace($candidate) -and -not $Candidates.Contains($candidate)) {
    $Candidates.Add($candidate)
  }
}

if (Test-CompletePlatformTools -Directory $targetDirectory) {
  Write-Host "Bundled Android platform-tools already staged: $targetDirectory"
  exit 0
}

$candidates = [Collections.Generic.List[string]]::new()
Add-Candidate -Candidates $candidates -Path $SourceDirectory
Add-Candidate -Candidates $candidates -Path $env:LOOM_ADB
if ($env:ANDROID_SDK_ROOT) { Add-Candidate -Candidates $candidates -Path (Join-Path $env:ANDROID_SDK_ROOT "platform-tools") }
if ($env:ANDROID_HOME) { Add-Candidate -Candidates $candidates -Path (Join-Path $env:ANDROID_HOME "platform-tools") }
if ($env:LOCALAPPDATA) { Add-Candidate -Candidates $candidates -Path (Join-Path $env:LOCALAPPDATA "Android\Sdk\platform-tools") }

$adbCommand = Get-Command adb.exe -ErrorAction SilentlyContinue
if ($adbCommand) { Add-Candidate -Candidates $candidates -Path $adbCommand.Source }

$uninstallRoots = @(
  "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*",
  "HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*",
  "HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*"
)
foreach ($entry in @(Get-ItemProperty $uninstallRoots -ErrorAction SilentlyContinue)) {
  if ($entry.DisplayName -notlike "*Luming AI Matrix Acquisition Workbench*" -and $entry.DisplayName -notlike "*麓鸣AI矩阵获客工作台*") {
    continue
  }
  $installLocation = [string]$entry.InstallLocation
  if (-not [string]::IsNullOrWhiteSpace($installLocation)) {
    Add-Candidate -Candidates $candidates -Path (Join-Path $installLocation.Trim().Trim('"') "_up_\redist\platform-tools")
  }
}

$source = $candidates | Where-Object { Test-CompletePlatformTools -Directory $_ } | Select-Object -First 1
if (-not $source) {
  throw "Refusing to package LOOM without a complete bundled Android platform-tools directory. Set LOOM_ADB to adb.exe, set ANDROID_SDK_ROOT/ANDROID_HOME, add adb.exe to PATH, or pass -SourceDirectory. Required files: $($requiredFiles -join ', ')."
}

$resolvedTarget = [IO.Path]::GetFullPath($targetDirectory)
$allowedPrefix = $resolvedLauncherRoot + [IO.Path]::DirectorySeparatorChar
if (-not $resolvedTarget.StartsWith($allowedPrefix, [StringComparison]::OrdinalIgnoreCase)) {
  throw "Unsafe platform-tools target outside launcher workspace: $resolvedTarget"
}

$stageDirectory = Join-Path $resolvedLauncherRoot "redist\.platform-tools-stage-$PID"
try {
  New-Item -ItemType Directory -Path $stageDirectory -Force | Out-Null
  Copy-Item -Path (Join-Path $source "*") -Destination $stageDirectory -Recurse -Force
  if (-not (Test-CompletePlatformTools -Directory $stageDirectory)) {
    throw "Discovered platform-tools source is incomplete after staging: $source"
  }
  if (Test-Path -LiteralPath $targetDirectory) {
    Remove-Item -LiteralPath $targetDirectory -Recurse -Force
  }
  Move-Item -LiteralPath $stageDirectory -Destination $targetDirectory
  Write-Host "Staged bundled Android platform-tools from $source"
} finally {
  if (Test-Path -LiteralPath $stageDirectory) {
    Remove-Item -LiteralPath $stageDirectory -Recurse -Force
  }
}
