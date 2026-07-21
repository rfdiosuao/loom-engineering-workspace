$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectDir = Split-Path -Parent $scriptDir
$runtimeDir = Join-Path $projectDir "node-runtime"

function Test-NodeRuntimeReady {
  param([string]$Path)
  $nodeExe = Join-Path $Path "node.exe"
  $npmCli = Join-Path $Path "node_modules\npm\bin\npm-cli.js"
  return (Test-Path -LiteralPath $nodeExe) -and (Test-Path -LiteralPath $npmCli)
}

if (Test-NodeRuntimeReady -Path $runtimeDir) {
  Write-Host "node-runtime already ready: $runtimeDir"
  exit 0
}

$nodeCommand = Get-Command node -ErrorAction SilentlyContinue
if (-not $nodeCommand) {
  throw "Cannot build node-runtime: node.exe was not found in PATH."
}

$nodeSourceDir = Split-Path -Parent $nodeCommand.Source
$sourceNode = Join-Path $nodeSourceDir "node.exe"
$sourceNpm = Join-Path $nodeSourceDir "node_modules\npm"
if (-not (Test-Path -LiteralPath $sourceNode)) {
  throw "Cannot build node-runtime: missing $sourceNode"
}
if (-not (Test-Path -LiteralPath $sourceNpm)) {
  throw "Cannot build node-runtime: missing npm package at $sourceNpm"
}

if (Test-Path -LiteralPath $runtimeDir) {
  Remove-Item -LiteralPath $runtimeDir -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $runtimeDir | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $runtimeDir "node_modules") | Out-Null

Copy-Item -LiteralPath $sourceNode -Destination (Join-Path $runtimeDir "node.exe") -Force
foreach ($name in @("npm", "npm.cmd", "npm.ps1", "npx", "npx.cmd", "npx.ps1", "corepack", "corepack.cmd")) {
  $source = Join-Path $nodeSourceDir $name
  if (Test-Path -LiteralPath $source) {
    Copy-Item -LiteralPath $source -Destination (Join-Path $runtimeDir $name) -Force
  }
}
Copy-Item -LiteralPath $sourceNpm -Destination (Join-Path $runtimeDir "node_modules\npm") -Recurse -Force

$nodeVersion = & (Join-Path $runtimeDir "node.exe") --version
if ($LASTEXITCODE -ne 0 -or -not $nodeVersion) {
  throw "node-runtime verification failed: node.exe cannot run."
}

$npmVersion = & (Join-Path $runtimeDir "node.exe") (Join-Path $runtimeDir "node_modules\npm\bin\npm-cli.js") --version
if ($LASTEXITCODE -ne 0 -or -not $npmVersion) {
  throw "node-runtime verification failed: npm-cli.js cannot run."
}

Write-Host "node-runtime ready: $runtimeDir ($nodeVersion, npm $npmVersion)"
