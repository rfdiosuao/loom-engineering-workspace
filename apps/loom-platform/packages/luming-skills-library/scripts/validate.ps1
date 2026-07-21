param(
  [string]$Validator
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$skillsRoot = Join-Path $repoRoot "skills"

function Get-NormalizedPath {
  param([string]$Path)

  return [IO.Path]::GetFullPath($Path).TrimEnd([char[]]@('\', '/'))
}

function Get-UnifiedManifestSkill {
  param([object]$Manifest)

  $skills = @($Manifest.skills)
  if ($skills.Count -ne 1 -or $skills[0].name -cne "luming-phone-agent" -or
      $skills[0].path -cne "skills/luming-phone-agent") {
    throw "Manifest must declare exactly the luming-phone-agent Skill"
  }

  $skillPath = Get-NormalizedPath -Path (Join-Path $repoRoot $skills[0].path)
  $skillsRootPath = Get-NormalizedPath -Path $skillsRoot
  if ((Get-NormalizedPath -Path (Split-Path -Parent $skillPath)) -cne $skillsRootPath -or
      (Split-Path -Leaf $skillPath) -cne $skills[0].name) {
    throw "Manifest Skill path must be the direct skills/luming-phone-agent directory"
  }
  if (-not (Test-Path -LiteralPath $skillPath -PathType Container)) {
    throw "Manifest Skill directory is missing: $($skills[0].path)"
  }

  return [pscustomobject]@{ Name = [string]$skills[0].name; FullName = $skillPath }
}

if (-not $Validator) {
  $codexHome = $env:CODEX_HOME
  if (-not $codexHome) {
    $codexHome = Join-Path $env:USERPROFILE ".codex"
  }
  $Validator = Join-Path $codexHome "skills\.system\skill-creator\scripts\quick_validate.py"
}

if (-not (Test-Path -LiteralPath $Validator)) {
  throw "Skill validator not found: $Validator"
}

$manifest = Get-Content -Raw -Encoding UTF8 -LiteralPath (Join-Path $repoRoot "manifest.json") | ConvertFrom-Json
$unifiedSkill = Get-UnifiedManifestSkill -Manifest $manifest
$sourceDirectories = @(Get-ChildItem -LiteralPath $skillsRoot -Directory | Select-Object -ExpandProperty Name)
if ($sourceDirectories.Count -ne 1 -or $sourceDirectories[0] -cne $unifiedSkill.Name) {
  throw "Skills directory must contain exactly the manifest-declared luming-phone-agent Skill"
}

$forbiddenArtifacts = @(
  Get-ChildItem -LiteralPath $unifiedSkill.FullName -Recurse -Force | Where-Object {
    $_.Name -ceq "__pycache__" -or $_.Extension -in @(".pyc", ".pyo", ".zip")
  }
)
if ($forbiddenArtifacts.Count -ne 0) {
  throw "Unified Skill contains generated or nested package artifacts: $($forbiddenArtifacts.FullName -join ', ')"
}

$env:PYTHONUTF8 = "1"
$env:PYTHONDONTWRITEBYTECODE = "1"
$results = @()

function Invoke-NativeChild {
  param(
    [string]$Command,
    [string[]]$Arguments
  )

  $previousErrorActionPreference = $ErrorActionPreference
  try {
    $ErrorActionPreference = "Continue"
    $output = @(& $Command @Arguments 2>&1)
    $exitCode = $LASTEXITCODE
  } finally {
    $ErrorActionPreference = $previousErrorActionPreference
  }
  return [pscustomobject]@{ Output = $output; ExitCode = $exitCode }
}

function Exit-ChildFailure {
  param([string]$Stage, [object]$Child)

  [Console]::Error.WriteLine("$Stage failed with exit code $($Child.ExitCode): $($Child.Output -join "`n")")
  exit $Child.ExitCode
}

$validatorResult = Invoke-NativeChild -Command "python" -Arguments @($Validator, $unifiedSkill.FullName)
if ($validatorResult.ExitCode -ne 0) {
  Exit-ChildFailure -Stage "Skill validator for $($unifiedSkill.Name)" -Child $validatorResult
}
$results += [pscustomobject]@{
  skill = $unifiedSkill.Name
  output = ($validatorResult.Output -join "`n")
}

Get-ChildItem -LiteralPath $unifiedSkill.FullName -Recurse -File -Filter "*.json" | ForEach-Object {
  try {
    Get-Content -Raw -Encoding UTF8 -LiteralPath $_.FullName | ConvertFrom-Json | Out-Null
  } catch {
    throw "Invalid unified Skill JSON document $($_.FullName): $($_.Exception.Message)"
  }
  $results += [pscustomobject]@{
    skill = $unifiedSkill.Name
    output = "JSON document is valid: $($_.FullName.Substring($unifiedSkill.FullName.Length).TrimStart([char[]]@('\', '/')))"
  }
}

$syncScript = Join-Path $unifiedSkill.FullName "scripts\sync_recipe.py"
$syncEnvironmentResult = Invoke-NativeChild -Command "python" -Arguments @($syncScript, "--check-environment")
if ($syncEnvironmentResult.ExitCode -ne 0) {
  Exit-ChildFailure -Stage "Recipe sync environment check" -Child $syncEnvironmentResult
}
$results += [pscustomobject]@{
  skill = $unifiedSkill.Name
  output = ($syncEnvironmentResult.Output -join "`n")
}

$testsRoot = Join-Path $repoRoot "tests"
if (Test-Path -LiteralPath $testsRoot) {
  Get-ChildItem -LiteralPath $testsRoot -File -Filter "*-contract.ps1" | Sort-Object Name | ForEach-Object {
    $contractResult = Invoke-NativeChild -Command "powershell" -Arguments @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $_.FullName)
    if ($contractResult.ExitCode -ne 0) {
      Exit-ChildFailure -Stage "Contract test $($_.Name)" -Child $contractResult
    }
    $results += [pscustomobject]@{
      skill = $_.BaseName
      output = ($contractResult.Output -join "`n")
    }
  }
}

$results | ConvertTo-Json -Depth 4
exit 0
