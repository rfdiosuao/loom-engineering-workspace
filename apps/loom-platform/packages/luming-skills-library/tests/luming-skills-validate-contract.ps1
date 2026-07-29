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
  if ($validateExitCode -eq 0) {
    throw "validate.ps1 accepted a validator failure: $($output -join "`n")"
  }
  if (($output -join "`n") -notmatch "exit code 2") {
    throw "validate.ps1 did not preserve the validator failure detail: $($output -join "`n")"
  }

  $passingValidator = Join-Path $tempRoot "passing-validator.py"
  [IO.File]::WriteAllText($passingValidator, "print('validator ok')`n", [Text.UTF8Encoding]::new($false))
  $continuationMarker = Join-Path $tempRoot "validate-returned.txt"
  $wrapper = Join-Path $tempRoot "validate-wrapper.ps1"
  $escapedValidate = $validateScript.Replace("'", "''")
  $escapedValidator = $passingValidator.Replace("'", "''")
  $escapedMarker = $continuationMarker.Replace("'", "''")
  $wrapperSource = @"
`$ErrorActionPreference = "Stop"
& '$escapedValidate' -Validator '$escapedValidator' -SkipContracts | Out-Null
[IO.File]::WriteAllText('$escapedMarker', 'returned', [Text.UTF8Encoding]::new(`$false))
"@
  [IO.File]::WriteAllText($wrapper, $wrapperSource, [Text.UTF8Encoding]::new($false))
  $continuationOutput = @(
    & powershell -NoProfile -ExecutionPolicy Bypass -File $wrapper 2>&1
  )
  $continuationExitCode = $LASTEXITCODE
  if ($continuationExitCode -ne 0) {
    throw "validate.ps1 continuation probe failed with ${continuationExitCode}: $($continuationOutput -join "`n")"
  }
  if (-not (Test-Path -LiteralPath $continuationMarker -PathType Leaf)) {
    throw "validate.ps1 terminated its caller before the continuation marker was written"
  }
} finally {
  if (Test-Path -LiteralPath $tempRoot) {
    Remove-Item -LiteralPath $tempRoot -Recurse -Force
  }
}

Write-Output "luming skills validate contract ok"
