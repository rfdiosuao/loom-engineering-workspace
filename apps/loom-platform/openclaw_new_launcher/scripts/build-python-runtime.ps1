param(
  [string]$PythonVersion = "3.11.9",
  [switch]$Force
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectDir = Split-Path -Parent $scriptDir
$runtimeDir = Join-Path $projectDir "python-runtime"
$requirements = Join-Path $projectDir "python\requirements.txt"
$cacheDir = Join-Path $projectDir ".cache\python-runtime"

function Test-RuntimeReady {
  param([string]$Dir)
  $python = Join-Path $Dir "python.exe"
  if (!(Test-Path -LiteralPath $python)) { return $false }
  $code = "import fastapi, uvicorn, pydantic, cryptography, httpx2; from fastapi.testclient import TestClient; from PIL import Image; from core.paths import AppPaths; from python.core.paths import AppPaths as PackageAppPaths; print('ok')"
  $result = & $python -c $code 2>$null
  return ($LASTEXITCODE -eq 0 -and ($result -join "`n").Trim() -eq "ok")
}

function Get-PythonInstaller {
  $targetMajorMinor = (($PythonVersion -split "\.")[0..1] -join ".")
  $candidates = New-Object System.Collections.Generic.List[object]
  if ($env:PYTHON -and (Test-Path -LiteralPath $env:PYTHON)) {
    $candidates.Add([pscustomobject]@{ Exe = $env:PYTHON; Args = @() })
  }
  foreach ($name in @("python", "python3")) {
    $cmd = Get-Command $name -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($cmd) {
      $candidates.Add([pscustomobject]@{ Exe = $cmd.Source; Args = @() })
    }
  }
  $py = Get-Command "py" -ErrorAction SilentlyContinue | Select-Object -First 1
  if ($py) {
    $candidates.Add([pscustomobject]@{ Exe = $py.Source; Args = @("-$targetMajorMinor") })
    $candidates.Add([pscustomobject]@{ Exe = $py.Source; Args = @("-3") })
  }

  foreach ($candidate in $candidates) {
    $probeArgs = @($candidate.Args) + @("-c", "import sys; print(f'{sys.version_info[0]}.{sys.version_info[1]}|{sys.executable}')")
    $probe = & $candidate.Exe @probeArgs 2>$null
    $probeText = ($probe -join "`n").Trim()
    if ($LASTEXITCODE -eq 0 -and $probeText.StartsWith("$targetMajorMinor|")) {
      return $candidate
    }
  }
  throw "No working Python $targetMajorMinor installer found. Set PYTHON to a Python $targetMajorMinor executable with pip."
}

if (!$Force -and (Test-RuntimeReady $runtimeDir)) {
  Write-Host "python-runtime already ready: $runtimeDir"
  exit 0
}

if ($env:PROCESSOR_ARCHITECTURE -notmatch "64" -and $env:PROCESSOR_ARCHITEW6432 -notmatch "64") {
  throw "Only Windows x64 python-runtime packaging is supported."
}

New-Item -ItemType Directory -Force -Path $cacheDir | Out-Null

$zipName = "python-$PythonVersion-embed-amd64.zip"
$zipPath = Join-Path $cacheDir $zipName
$url = "https://www.python.org/ftp/python/$PythonVersion/$zipName"

if (!(Test-Path -LiteralPath $zipPath)) {
  Write-Host "Downloading $url"
  Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $zipPath
}

$stage = Join-Path $cacheDir "stage"
if (Test-Path -LiteralPath $stage) {
  Remove-Item -LiteralPath $stage -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $stage | Out-Null
Expand-Archive -LiteralPath $zipPath -DestinationPath $stage -Force

$pth = Get-ChildItem -LiteralPath $stage -Filter "python*._pth" | Select-Object -First 1
if (!$pth) {
  throw "Embedded Python ._pth file not found in $stage"
}

$pthLines = Get-Content -LiteralPath $pth.FullName
$next = New-Object System.Collections.Generic.List[string]
$hasProjectPython = $false
$hasProjectRoot = $false
$hasSitePackages = $false
$hasImportSite = $false
foreach ($line in $pthLines) {
  if ($line.Trim() -eq "../python") { $hasProjectPython = $true }
  if ($line.Trim() -eq "..") { $hasProjectRoot = $true }
  if ($line.Trim() -eq "Lib/site-packages") { $hasSitePackages = $true }
  if ($line.Trim() -eq "import site") {
    $next.Add("import site")
    $hasImportSite = $true
    continue
  }
  if ($line.Trim() -eq "#import site") {
    $next.Add("import site")
    $hasImportSite = $true
    continue
  }
  $next.Add($line)
}
if (!$hasProjectPython) {
  $insertAt = [Math]::Max(0, $next.Count - 1)
  $next.Insert($insertAt, "../python")
}
if (!$hasProjectRoot) {
  $next.Insert([Math]::Max(0, $next.Count - 1), "..")
}
if (!$hasSitePackages) {
  $next.Insert([Math]::Max(0, $next.Count - 1), "Lib/site-packages")
}
if (!$hasImportSite) {
  $next.Add("import site")
}
Set-Content -LiteralPath $pth.FullName -Value $next -Encoding ASCII

$sitePackages = Join-Path $stage "Lib\site-packages"
New-Item -ItemType Directory -Force -Path $sitePackages | Out-Null

Write-Host "Installing Bridge dependencies into embedded runtime..."
$installer = Get-PythonInstaller
$pipArgs = @($installer.Args) + @("-m", "pip", "install", "--disable-pip-version-check", "--upgrade", "--target", $sitePackages, "-r", $requirements)
& $installer.Exe @pipArgs
if ($LASTEXITCODE -ne 0) {
  throw "pip install failed with exit code $LASTEXITCODE"
}

if (Test-Path -LiteralPath $runtimeDir) {
  Remove-Item -LiteralPath $runtimeDir -Recurse -Force
}
Move-Item -LiteralPath $stage -Destination $runtimeDir

if (!(Test-RuntimeReady $runtimeDir)) {
  throw "python-runtime verification failed: required Bridge dependencies cannot be imported."
}

Write-Host "python-runtime ready: $runtimeDir"
