$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$skillsRoot = Join-Path $repoRoot "skills"
$manifest = Get-Content -Raw -Encoding UTF8 -LiteralPath (Join-Path $repoRoot "manifest.json") | ConvertFrom-Json
$packageScript = Join-Path $repoRoot "scripts\package.ps1"
$tempRoot = Join-Path ([IO.Path]::GetTempPath()) ("luming-skills-package-contract-" + [guid]::NewGuid().ToString("N"))

function Assert-OneUnifiedSkill {
  param(
    [string[]]$SkillEntries,
    [string]$Location
  )

  if ($SkillEntries.Count -ne 1 -or $SkillEntries[0] -cne "skills/luming-phone-agent/SKILL.md") {
    throw "$Location must contain exactly one triggerable Luming Skill"
  }
}

function Assert-NoLegacySkillNames {
  param(
    [string[]]$EntryNames,
    [string]$Location
  )

  foreach ($legacyName in @($manifest.replaces)) {
    if (@($EntryNames | Where-Object { $_ -match "^skills/$([regex]::Escape($legacyName))(/|$)" }).Count -ne 0) {
      throw "$Location contains retired Skill name: $legacyName"
    }
  }
}

$sourceEntries = @(
  Get-ChildItem -LiteralPath $skillsRoot -Recurse -File |
    ForEach-Object { $_.FullName.Substring($repoRoot.Length).TrimStart([char[]]@('\', '/')).Replace('\', '/') }
)
$sourceSkillEntries = @($sourceEntries | Where-Object { $_ -match '^skills/[^/]+/SKILL\.md$' })
Assert-OneUnifiedSkill -SkillEntries $sourceSkillEntries -Location "Source tree"
Assert-NoLegacySkillNames -EntryNames $sourceEntries -Location "Source tree"

function Assert-PackageRejectsArtifact {
  param([string]$RelativePath)

  $artifactPath = Join-Path $repoRoot $RelativePath
  $artifactParent = Split-Path -Parent $artifactPath
  New-Item -ItemType Directory -Force -Path $artifactParent | Out-Null
  if ([IO.Path]::GetExtension($artifactPath)) {
    [IO.File]::WriteAllText($artifactPath, "package contract probe", [Text.UTF8Encoding]::new($false))
  } else {
    New-Item -ItemType Directory -Force -Path $artifactPath | Out-Null
  }
  try {
    $probeSucceeded = $true
    try {
      $probeOutput = @(& $packageScript -OutputDir $tempRoot 2>&1)
      $probeSucceeded = $?
      $probeExitCode = $LASTEXITCODE
    } catch {
      $probeOutput = @($_)
      $probeSucceeded = $false
      $probeExitCode = $LASTEXITCODE
    }
    if ($probeSucceeded -and ($null -eq $probeExitCode -or $probeExitCode -eq 0)) {
      throw "Package accepted forbidden artifact: $RelativePath"
    }
  } finally {
    if (Test-Path -LiteralPath $artifactPath) {
      Remove-Item -LiteralPath $artifactPath -Recurse -Force
    }
  }
}

foreach ($artifactRoot in @(
  "scripts",
  "skills\luming-phone-agent"
)) {
  foreach ($artifact in @(
    "__pycache__",
    "package-contract-probe.pyc",
    "package-contract-probe.pyo",
    "package-contract-probe.zip"
  )) {
    Assert-PackageRejectsArtifact -RelativePath (Join-Path $artifactRoot $artifact)
  }
}

try {
  New-Item -ItemType Directory -Force -Path $tempRoot | Out-Null
  & $packageScript -OutputDir $tempRoot | Out-Null

  $zipFiles = @(Get-ChildItem -LiteralPath $tempRoot -File -Filter "*.zip")
  if ($zipFiles.Count -ne 1) {
    throw "Expected exactly one package ZIP, found $($zipFiles.Count)"
  }

  Add-Type -AssemblyName System.IO.Compression.FileSystem
  $archive = [System.IO.Compression.ZipFile]::OpenRead($zipFiles[0].FullName)
  try {
    $entryNames = @($archive.Entries | ForEach-Object { $_.FullName })
    $backslashEntries = @($entryNames | Where-Object { $_.Contains("\") })
    if ($backslashEntries.Count -ne 0) {
      throw "ZIP entries must use forward slashes; found: $($backslashEntries -join ', ')"
    }

    $skillEntries = @($entryNames | Where-Object { $_ -match '^skills/[^/]+/SKILL\.md$' })
    Assert-OneUnifiedSkill -SkillEntries $skillEntries -Location "Package"
    Assert-NoLegacySkillNames -EntryNames $entryNames -Location "Package"

    if (@($entryNames | Where-Object { $_ -match '\.zip$' }).Count -ne 0) {
      throw "Nested ZIP artifacts are forbidden"
    }

    $unifiedFiles = @(
      Get-ChildItem -LiteralPath (Join-Path $skillsRoot "luming-phone-agent") -Recurse -File |
        ForEach-Object { $_.FullName.Substring($repoRoot.Length).TrimStart([char[]]@('\', '/')).Replace('\', '/') }
    )
    foreach ($unifiedFile in $unifiedFiles) {
      if ($entryNames -cnotcontains $unifiedFile) {
        throw "ZIP is missing unified Skill file: $unifiedFile"
      }
    }
  } finally {
    $archive.Dispose()
  }
} finally {
  if (Test-Path -LiteralPath $tempRoot) {
    Remove-Item -LiteralPath $tempRoot -Recurse -Force
  }
}

Write-Output "luming skills package contract ok"
