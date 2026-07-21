param(
  [string]$Root = "$PSScriptRoot\..\build\protected-resources"
)

$ErrorActionPreference = "Stop"
$resolved = Resolve-Path $Root
$pythonRoot = Join-Path $resolved "python"
$scriptsRoot = Join-Path $resolved "scripts"

if (!(Test-Path (Join-Path $pythonRoot "loom_cli.py"))) {
  throw "protected python loader missing"
}
if (!(Test-Path (Join-Path $scriptsRoot "openclaw-image-phone.mjs"))) {
  throw "protected scripts missing"
}

$allowedPy = @("bridge.py", "loom_cli.py", "loom_mcp.py", "__init__.py")
$businessPy = Get-ChildItem $pythonRoot -Recurse -Filter *.py | Where-Object { $allowedPy -notcontains $_.Name }
if ($businessPy) {
  throw "business Python source leaked into protected resources: $($businessPy[0].FullName)"
}

$debugFiles = Get-ChildItem $resolved -Recurse -Include *.map,*.ts,*.tsx -File
if ($debugFiles) {
  throw "debug/source frontend files leaked into protected resources: $($debugFiles[0].FullName)"
}

# Use the same Python interpreter that staged the protected bytecode
# ($env:PYTHON, falling back to PATH `python`). The smoke test must run
# under the same minor version that compiled the .pyc files, otherwise
# Python refuses to load them with "bad magic number". The packaged app
# ships its own Python 3.11 runtime; stage-protected-release.mjs compiles
# with $env:PYTHON, so we honor the same selection here.
$pythonExe = if ($env:PYTHON) { $env:PYTHON } else { "python" }
$json = & $pythonExe (Join-Path $pythonRoot "loom_cli.py") status --json
if ($LASTEXITCODE -ne 0) {
  throw "protected loom_cli.py smoke failed"
}
$payload = $json | ConvertFrom-Json
if (!$payload.ok) {
  throw "protected loom_cli.py returned ok=false"
}

Write-Host "protected release resources verified: $resolved"
