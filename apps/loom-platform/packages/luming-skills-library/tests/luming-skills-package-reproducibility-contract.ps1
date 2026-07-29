$ErrorActionPreference = "Stop"

$packageRoot = Split-Path -Parent $PSScriptRoot
$packageScript = Join-Path $packageRoot "scripts\package.ps1"
$manifest = Get-Content -Raw -Encoding UTF8 -LiteralPath (Join-Path $packageRoot "manifest.json") |
  ConvertFrom-Json
$stamp = ([string]$manifest.version) -replace '[^0-9]', ''
$archiveName = "luming-skills-library-$stamp.zip"
$testRoot = Join-Path ([IO.Path]::GetTempPath()) ("loom-skill-package-repro-" + [Guid]::NewGuid().ToString("N"))

function Get-ArchiveHash {
  param(
    [string]$Shell,
    [string]$OutputDir
  )

  New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
  & $Shell -NoProfile -ExecutionPolicy Bypass -File $packageScript -OutputDir $OutputDir | Out-Null
  if ($LASTEXITCODE -ne 0) {
    throw "Skill package failed under $Shell with exit code $LASTEXITCODE"
  }

  $archivePath = Join-Path $OutputDir $archiveName
  if (-not (Test-Path -LiteralPath $archivePath -PathType Leaf)) {
    throw "Skill package is missing under $Shell`: $archivePath"
  }
  return (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash
}

try {
  $shells = @(
    (Get-Command powershell.exe -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty Source),
    (Get-Command pwsh.exe -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty Source)
  ) | Where-Object { $_ } | Select-Object -Unique

  if ($shells.Count -eq 0) {
    throw "No PowerShell host is available for reproducibility verification"
  }

  $results = @(
    for ($index = 0; $index -lt $shells.Count; $index += 1) {
      [pscustomobject]@{
        Shell = $shells[$index]
        Hash = Get-ArchiveHash -Shell $shells[$index] -OutputDir (Join-Path $testRoot "run-$index")
      }
    }
  )
  $uniqueHashes = @($results.Hash | Select-Object -Unique)
  if ($uniqueHashes.Count -ne 1) {
    throw "Skill package is not reproducible across PowerShell hosts: $($results | ConvertTo-Json -Compress)"
  }

  Write-Output "luming skills package reproducibility contract ok: $($uniqueHashes[0])"
} finally {
  if (Test-Path -LiteralPath $testRoot -PathType Container) {
    Remove-Item -LiteralPath $testRoot -Recurse -Force
  }
}
