param(
  [string]$OutputDir
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$skillsRoot = Join-Path $repoRoot "skills"
if (-not $OutputDir) {
  $OutputDir = Join-Path $repoRoot "dist"
}

function Get-NormalizedPath {
  param([string]$Path)

  return [IO.Path]::GetFullPath($Path).TrimEnd([char[]]@('\', '/'))
}

function Get-ManifestSkills {
  param([object]$Manifest)

  $skillsRootPath = Get-NormalizedPath -Path $skillsRoot
  $skills = @(
    foreach ($manifestSkill in @($Manifest.skills)) {
      $name = [string]$manifestSkill.name
      $relativePath = [string]$manifestSkill.path
      if (-not $name -or $relativePath -cne "skills/$name") {
        throw "Manifest Skill must name its direct skills directory: $name"
      }

      $fullPath = Get-NormalizedPath -Path (Join-Path $repoRoot $relativePath)
      if ((Get-NormalizedPath -Path (Split-Path -Parent $fullPath)) -cne $skillsRootPath -or
          (Split-Path -Leaf $fullPath) -cne $name) {
        throw "Manifest Skill path is outside its direct skills directory: $relativePath"
      }
      if (-not (Test-Path -LiteralPath $fullPath -PathType Container)) {
        throw "Manifest Skill source directory is missing: $relativePath"
      }

      [pscustomobject]@{ Name = $name; FullName = $fullPath }
    }
  )

  if ($skills.Count -eq 0) {
    throw "Manifest does not declare any Skills"
  }
  if (@($skills.Name | Select-Object -Unique).Count -ne $skills.Count) {
    throw "Manifest declares duplicate Skill names"
  }
  return $skills
}

$manifest = Get-Content -Raw -Encoding UTF8 -LiteralPath (Join-Path $repoRoot "manifest.json") | ConvertFrom-Json
$manifestSkills = Get-ManifestSkills -Manifest $manifest
$scriptsRoot = Join-Path $repoRoot "scripts"
$candidateRoots = @($scriptsRoot) + @($manifestSkills | ForEach-Object { $_.FullName })
$forbiddenArtifacts = @(
  foreach ($candidateRoot in $candidateRoots) {
    Get-ChildItem -LiteralPath $candidateRoot -Recurse -Force | Where-Object {
      $_.Name -ceq "__pycache__" -or $_.Extension -in @(".pyc", ".pyo", ".zip")
    }
  }
)
if ($forbiddenArtifacts.Count -ne 0) {
  throw "Package input contains generated or nested package artifacts: $($forbiddenArtifacts.FullName -join ', ')"
}

New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
$stamp = Get-Date -Format "yyyyMMdd"
$zipPath = Join-Path $OutputDir "luming-skills-library-$stamp.zip"
if (Test-Path -LiteralPath $zipPath) {
  Remove-Item -LiteralPath $zipPath -Force
}

$repoRootPath = Get-NormalizedPath -Path $repoRoot
$files = @(
  Get-Item -LiteralPath (Join-Path $repoRoot "README.md")
  Get-Item -LiteralPath (Join-Path $repoRoot "manifest.json")
  Get-ChildItem -LiteralPath $scriptsRoot -Recurse -File
  foreach ($manifestSkill in $manifestSkills) {
    Get-ChildItem -LiteralPath $manifestSkill.FullName -Recurse -File
  }
) | Sort-Object FullName

$zipWriter = Join-Path $scriptsRoot "deterministic_zip.py"
if (-not (Test-Path -LiteralPath $zipWriter -PathType Leaf)) {
  throw "Deterministic ZIP writer is missing: $zipWriter"
}
$entryManifestPath = Join-Path $OutputDir (".luming-skills-package-" + [Guid]::NewGuid().ToString("N") + ".json")
try {
  $entryManifest = @(
    foreach ($file in $files) {
      $relativePath = $file.FullName.Substring($repoRootPath.Length).TrimStart([char[]]@('\', '/'))
      [pscustomobject]@{
        source = $file.FullName
        entry = $relativePath.Replace('\', '/')
        timestamp = $file.LastWriteTime.ToString(
          "yyyy-MM-ddTHH:mm:ss",
          [Globalization.CultureInfo]::InvariantCulture
        )
      }
    }
  )
  [IO.File]::WriteAllText(
    $entryManifestPath,
    ($entryManifest | ConvertTo-Json -Depth 3),
    [Text.UTF8Encoding]::new($false)
  )

  & python $zipWriter --entries $entryManifestPath --output $zipPath
  if ($LASTEXITCODE -ne 0) {
    throw "Deterministic Skill package writer failed with exit code $LASTEXITCODE"
  }
} finally {
  if (Test-Path -LiteralPath $entryManifestPath -PathType Leaf) {
    Remove-Item -LiteralPath $entryManifestPath -Force
  }
}

Get-Item -LiteralPath $zipPath | Select-Object FullName, Length, LastWriteTime
