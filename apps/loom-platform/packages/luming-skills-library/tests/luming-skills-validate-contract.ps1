$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$validateScript = Join-Path $repoRoot "scripts\validate.ps1"
$tempRoot = Join-Path ([IO.Path]::GetTempPath()) ("luming-skills-validate-contract-" + [guid]::NewGuid().ToString("N"))

New-Item -ItemType Directory -Force -Path $tempRoot | Out-Null
try {
  $validator = Join-Path $tempRoot "exit-two-validator.py"
  [IO.File]::WriteAllText($validator, "import sys`nsys.exit(2)`n", [Text.UTF8Encoding]::new($false))
  $previousErrorActionPreference = $ErrorActionPreference
  $ErrorActionPreference = "Continue"
  $output = @(& powershell -NoProfile -ExecutionPolicy Bypass -File $validateScript -Validator $validator 2>&1)
  $validateExitCode = $LASTEXITCODE
  $ErrorActionPreference = $previousErrorActionPreference
  if ($validateExitCode -ne 2) {
    throw "validate.ps1 must propagate validator exit 2, got ${validateExitCode}: $($output -join "`n")"
  }
} finally {
  if (Test-Path -LiteralPath $tempRoot) {
    Remove-Item -LiteralPath $tempRoot -Recurse -Force
  }
}

Write-Output "luming skills validate contract ok"
