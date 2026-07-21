$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$skillsRoot = Join-Path $repoRoot "skills"
$installScript = Join-Path $repoRoot "scripts\install.ps1"
$tempRoot = Join-Path ([IO.Path]::GetTempPath()) ("luming-skills-install-contract-" + [guid]::NewGuid().ToString("N"))
$destination = Join-Path $tempRoot "installed skills"
$stateRoot = Join-Path $tempRoot "phone-agent-state"
$unifiedSkillName = "luming-phone-agent"
$reparsePaths = [Collections.Generic.List[string]]::new()
$legacyNames = @(
  "loom-adb-forward-proxy-bypass",
  "loom-command-brain",
  "luming-acquisition-agent",
  "luming-boss-resume-screening",
  "luming-matrix-supervisor-loop",
  "luming-phone-scenario-builder",
  "luming-scenario-skill-writer"
)

function Get-FileManifest {
  param([string]$Root)

  $rootPath = [IO.Path]::GetFullPath($Root).TrimEnd([char[]]@('\', '/'))
  $manifest = [Collections.Generic.Dictionary[string, string]]::new(
    [StringComparer]::Ordinal
  )

  Get-ChildItem -LiteralPath $rootPath -Recurse -File -Force | ForEach-Object {
    $relativePath = $_.FullName.Substring($rootPath.Length).TrimStart([char[]]@('\', '/')).Replace('\', '/')
    $manifest.Add($relativePath, (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash)
  }

  return $manifest
}

function Assert-StringSetEqual {
  param(
    [string[]]$Expected,
    [string[]]$Actual,
    [string]$Context
  )

  $expectedSet = [Collections.Generic.HashSet[string]]::new(
    [StringComparer]::Ordinal
  )
  $actualSet = [Collections.Generic.HashSet[string]]::new(
    [StringComparer]::Ordinal
  )
  foreach ($value in $Expected) {
    $expectedSet.Add($value) | Out-Null
  }
  foreach ($value in $Actual) {
    $actualSet.Add($value) | Out-Null
  }

  if (-not $expectedSet.SetEquals($actualSet)) {
    throw "$Context differs. Expected: $($Expected -join ', '); actual: $($Actual -join ', ')"
  }
}

function Assert-DirectoryParity {
  param(
    [string]$Source,
    [string]$Installed,
    [string]$Context
  )

  if (-not (Test-Path -LiteralPath $Installed -PathType Container)) {
    throw "$Context was not installed"
  }

  $sourceManifest = Get-FileManifest -Root $Source
  $installedManifest = Get-FileManifest -Root $Installed
  Assert-StringSetEqual `
    -Expected @($sourceManifest.Keys) `
    -Actual @($installedManifest.Keys) `
    -Context "$Context recursive file set"

  foreach ($relativePath in $sourceManifest.Keys) {
    if ($sourceManifest[$relativePath] -cne $installedManifest[$relativePath]) {
      throw "$Context SHA256 mismatch for $relativePath"
    }
  }
}

function Assert-SourceMetadata {
  param(
    [object]$Result,
    [string]$StateRoot,
    [string]$SourceSkillRoot,
    [string]$InstalledSkillRoot
  )

  $metadataPath = Join-Path $StateRoot "source.json"
  if (-not (Test-Path -LiteralPath $metadataPath -PathType Leaf)) {
    throw "Installer did not write source metadata: $metadataPath"
  }

  $metadata = Get-Content -Raw -Encoding UTF8 -LiteralPath $metadataPath | ConvertFrom-Json
  $metadataJson = Get-Content -Raw -Encoding UTF8 -LiteralPath $metadataPath
  $expectedProperties = @("schema", "sourceSkillRoot", "installedSkillRoot")
  Assert-StringSetEqual `
    -Expected $expectedProperties `
    -Actual @($metadata.PSObject.Properties.Name) `
    -Context "Source metadata properties"

  if ($metadata.schema -cne "loom.phone-agent.source.v1") {
    throw "Source metadata schema is incorrect: $($metadata.schema)"
  }
  foreach ($field in @("sourceSkillRoot", "installedSkillRoot")) {
    if (-not [IO.Path]::IsPathRooted([string]$metadata.$field)) {
      throw "Source metadata $field is not absolute: $($metadata.$field)"
    }
  }
  if ([IO.Path]::GetFullPath([string]$metadata.sourceSkillRoot) -cne [IO.Path]::GetFullPath($SourceSkillRoot)) {
    throw "Source metadata reported the wrong source root: $($metadata.sourceSkillRoot)"
  }
  if ([IO.Path]::GetFullPath([string]$metadata.installedSkillRoot) -cne [IO.Path]::GetFullPath($InstalledSkillRoot)) {
    throw "Source metadata reported the wrong installed root: $($metadata.installedSkillRoot)"
  }
  if ($metadataJson -match '(?i)password|token|secret|credential|api[_-]?key|authorization') {
    throw "Source metadata contains credentials"
  }

  $resultMetadata = $Result.sourceMetadata
  if ($null -eq $resultMetadata) {
    throw "Installer JSON omitted sourceMetadata"
  }
  foreach ($field in $expectedProperties) {
    if ([string]$resultMetadata.$field -cne [string]$metadata.$field) {
      throw "Installer JSON sourceMetadata differs from source.json for $field"
    }
  }
}

function Get-TreeSnapshot {
  param([string]$Root)

  if (-not (Test-Path -LiteralPath $Root)) {
    return "<missing>"
  }

  $rootPath = [IO.Path]::GetFullPath($Root).TrimEnd([char[]]@('\', '/'))
  $entries = Get-ChildItem -LiteralPath $Root -Recurse -Force | Sort-Object FullName
  return (($entries | ForEach-Object {
    $relativePath = $_.FullName.Substring($rootPath.Length).TrimStart([char[]]@('\', '/'))
    if ($_.PSIsContainer) {
      "D|$relativePath"
    } else {
      "F|$relativePath|$((Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash)"
    }
  }) -join "`n")
}

function Invoke-InstallerChild {
  param(
    [string]$Destination,
    [string]$StateRoot,
    [string]$FailureInjection
  )

  $startInfo = [Diagnostics.ProcessStartInfo]::new()
  $startInfo.FileName = "powershell"
  $startInfo.Arguments = @(
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", ('"' + $installScript.Replace('"', '\"') + '"'),
    "-Destination", ('"' + $Destination.Replace('"', '\"') + '"'),
    "-StateRoot", ('"' + $StateRoot.Replace('"', '\"') + '"')
  ) -join " "
  $startInfo.UseShellExecute = $false
  $startInfo.CreateNoWindow = $true
  $startInfo.RedirectStandardOutput = $true
  $startInfo.RedirectStandardError = $true
  if ($FailureInjection) {
    $startInfo.EnvironmentVariables["LUMING_SKILLS_INSTALL_FAIL_AT"] = $FailureInjection
  }

  $process = [Diagnostics.Process]::new()
  $process.StartInfo = $startInfo
  if (-not $process.Start()) {
    throw "Failed to start installer child process"
  }
  $stdout = $process.StandardOutput.ReadToEnd()
  $stderr = $process.StandardError.ReadToEnd()
  $process.WaitForExit()
  return [pscustomobject]@{
    ExitCode = $process.ExitCode
    StdOut = $stdout
    StdErr = $stderr
  }
}

function Assert-DestinationIsRequired {
  $isolatedHome = Join-Path $tempRoot "host-home"
  $isolatedStateRoot = Join-Path $tempRoot "destination-required-state"
  New-Item -ItemType Directory -Force -Path $isolatedHome | Out-Null

  $startInfo = [Diagnostics.ProcessStartInfo]::new()
  $startInfo.FileName = "powershell"
  $startInfo.Arguments = @(
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", ('"' + $installScript.Replace('"', '\"') + '"'),
    "-StateRoot", ('"' + $isolatedStateRoot.Replace('"', '\"') + '"')
  ) -join " "
  $startInfo.UseShellExecute = $false
  $startInfo.CreateNoWindow = $true
  $startInfo.RedirectStandardOutput = $true
  $startInfo.RedirectStandardError = $true
  $startInfo.EnvironmentVariables["USERPROFILE"] = $isolatedHome
  $startInfo.EnvironmentVariables["CODEX_HOME"] = ""

  $process = [Diagnostics.Process]::new()
  $process.StartInfo = $startInfo
  if (-not $process.Start()) {
    throw "Failed to start destination-required installer probe"
  }
  $stdout = $process.StandardOutput.ReadToEnd()
  $stderr = $process.StandardError.ReadToEnd()
  $process.WaitForExit()

  if ($process.ExitCode -eq 0) {
    throw "Installer accepted an omitted Destination and may have guessed the Agent host"
  }
  if (("$stdout`n$stderr") -notmatch "Destination is required") {
    throw "Installer did not explain that Destination is required"
  }
  if (Test-Path -LiteralPath (Join-Path $isolatedHome ".codex")) {
    throw "Installer created an implicit .codex directory for an unidentified Agent host"
  }
}

function Get-TriggerableSkillNames {
  param([string]$Destination)

  return @(
    Get-ChildItem -LiteralPath $Destination -Directory -Force |
      Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName "SKILL.md") -PathType Leaf } |
      Select-Object -ExpandProperty Name
  )
}

function New-TransactionalFailureDestination {
  param([string]$Name)

  $fixtureDestination = Join-Path $tempRoot $Name
  foreach ($legacyName in $legacyNames) {
    $legacyTarget = Join-Path $fixtureDestination $legacyName
    New-Item -ItemType Directory -Force -Path $legacyTarget | Out-Null
    [IO.File]::WriteAllBytes((Join-Path $legacyTarget "SKILL.md"), [byte[]](1, 2, 3, 4, 5, $legacyName.Length))
    [IO.File]::WriteAllBytes((Join-Path $legacyTarget "legacy.bin"), [byte[]](65, 66, 67, $legacyName.Length))
  }

  return $fixtureDestination
}

function Assert-TransactionalRollback {
  param(
    [string]$Name,
    [string]$FailureInjection,
    [bool]$SeedMetadata
  )

  $failureDestination = New-TransactionalFailureDestination -Name "$Name-destination"
  $failureStateRoot = Join-Path $tempRoot "$Name-state"
  if ($SeedMetadata) {
    New-Item -ItemType Directory -Force -Path $failureStateRoot | Out-Null
    [IO.File]::WriteAllBytes((Join-Path $failureStateRoot "source.json"), [byte[]](255, 0, 128, 64, 32))
  }

  $destinationBefore = Get-TreeSnapshot -Root $failureDestination
  $stateBefore = Get-TreeSnapshot -Root $failureStateRoot
  $invocation = Invoke-InstallerChild `
    -Destination $failureDestination `
    -StateRoot $failureStateRoot `
    -FailureInjection $FailureInjection
  if ($invocation.ExitCode -eq 0) {
    throw "$Name failure injection unexpectedly exited 0"
  }
  if ((Get-TreeSnapshot -Root $failureDestination) -cne $destinationBefore) {
    throw "$Name rollback did not restore the destination tree exactly"
  }
  if ((Get-TreeSnapshot -Root $failureStateRoot) -cne $stateBefore) {
    throw "$Name rollback did not restore metadata exactly"
  }
  Assert-StringSetEqual `
    -Expected $legacyNames `
    -Actual @(Get-TriggerableSkillNames -Destination $failureDestination) `
    -Context "$Name rollback triggerable Skills"
  $destinationResidue = @(
    Get-ChildItem -LiteralPath $failureDestination -Force |
      Where-Object { $_.Name -like ".luming-skills-install-*" }
  )
  if ($destinationResidue.Count -ne 0) {
    throw "$Name rollback left destination transaction residue: $($destinationResidue.Name -join ', ')"
  }
  if (Test-Path -LiteralPath $failureStateRoot) {
    $stateResidue = @(
      Get-ChildItem -LiteralPath $failureStateRoot -Force |
        Where-Object { $_.Name -like ".luming-skills-install-*" }
    )
    if ($stateResidue.Count -ne 0) {
      throw "$Name rollback left state transaction residue: $($stateResidue.Name -join ', ')"
    }
  }
}

function Assert-CleanupFailurePreservesCommittedInstall {
  $failureDestination = New-TransactionalFailureDestination -Name "cleanup-failure-destination"
  $failureStateRoot = Join-Path $tempRoot "cleanup-failure-state"
  $invocation = Invoke-InstallerChild `
    -Destination $failureDestination `
    -StateRoot $failureStateRoot `
    -FailureInjection "cleanup-state"
  if ($invocation.ExitCode -eq 0) {
    throw "Cleanup failure fixture unexpectedly exited 0"
  }
  Assert-StringSetEqual `
    -Expected @($unifiedSkillName) `
    -Actual @(Get-TriggerableSkillNames -Destination $failureDestination) `
    -Context "Cleanup failure committed triggerable Skills"
  Assert-DirectoryParity `
    -Source (Join-Path $skillsRoot $unifiedSkillName) `
    -Installed (Join-Path $failureDestination $unifiedSkillName) `
    -Context "Cleanup failure committed unified Skill"
  if (-not (Test-Path -LiteralPath (Join-Path $failureStateRoot "source.json") -PathType Leaf)) {
    throw "Cleanup failure lost committed source metadata"
  }
  if (@(Get-ChildItem -LiteralPath $failureDestination -Force | Where-Object Name -Like ".luming-skills-install-*").Count -lt 1) {
    throw "Cleanup failure did not preserve recoverable destination backups"
  }
}

function Assert-ReparseStateRootRejectedWithoutMutation {
  $aliasDestination = New-TransactionalFailureDestination -Name "reparse-destination"
  $realStateRoot = Join-Path $aliasDestination "aliased-state-target"
  $aliasParent = Join-Path $tempRoot "reparse-alias-parent"
  $stateAlias = Join-Path $aliasParent "state-alias"
  New-Item -ItemType Directory -Force -Path $realStateRoot, $aliasParent | Out-Null
  New-Item -ItemType Junction -Path $stateAlias -Target $realStateRoot | Out-Null
  $reparsePaths.Add($stateAlias)

  $destinationBefore = Get-TreeSnapshot -Root $aliasDestination
  $sourceBefore = Get-TreeSnapshot -Root $skillsRoot
  $invocation = Invoke-InstallerChild -Destination $aliasDestination -StateRoot $stateAlias
  if ($invocation.ExitCode -eq 0) {
    throw "Reparse-aliased StateRoot unexpectedly exited 0"
  }
  if ((Get-TreeSnapshot -Root $aliasDestination) -cne $destinationBefore) {
    throw "Reparse-aliased StateRoot mutated the destination before rejection"
  }
  if ((Get-TreeSnapshot -Root $skillsRoot) -cne $sourceBefore) {
    throw "Reparse-aliased StateRoot mutated the managed source before rejection"
  }
}

function Assert-StateRootRejectedWithoutMutation {
  param(
    [string]$Name,
    [string]$Destination,
    [string]$StateRoot,
    [string]$SourceRoot
  )

  $destinationBefore = Get-TreeSnapshot -Root $Destination
  $sourceBefore = Get-TreeSnapshot -Root $SourceRoot
  $invocation = Invoke-InstallerChild -Destination $Destination -StateRoot $StateRoot
  if ($invocation.ExitCode -eq 0) {
    throw "$Name StateRoot overlap unexpectedly exited 0"
  }
  if ((Get-TreeSnapshot -Root $Destination) -cne $destinationBefore) {
    throw "$Name StateRoot overlap mutated the destination before rejection"
  }
  if ((Get-TreeSnapshot -Root $SourceRoot) -cne $sourceBefore) {
    throw "$Name StateRoot overlap mutated the managed source before rejection"
  }
}

function New-StaleDestination {
  param([string]$Name)

  $fixtureDestination = Join-Path $tempRoot $Name
  foreach ($legacyName in $legacyNames) {
    $legacyTarget = Join-Path $fixtureDestination $legacyName
    New-Item -ItemType Directory -Force -Path $legacyTarget | Out-Null
    Set-Content -LiteralPath (Join-Path $legacyTarget "SKILL.md") -Value "stale $legacyName" -Encoding UTF8
  }
  $unifiedTarget = Join-Path $fixtureDestination $unifiedSkillName
  New-Item -ItemType Directory -Force -Path $unifiedTarget | Out-Null
  Set-Content -LiteralPath (Join-Path $unifiedTarget "SKILL.md") -Value "stale $unifiedSkillName" -Encoding UTF8
  return $fixtureDestination
}

function Assert-MetadataWriteFailureRetainsLegacyTargets {
  $failureDestination = New-StaleDestination -Name "metadata-write-failure-destination"
  $failureStateRoot = Join-Path $tempRoot "metadata-write-failure-state"
  New-Item -ItemType Directory -Force -Path (Join-Path $failureStateRoot "source.json") | Out-Null

  $invocation = Invoke-InstallerChild `
    -Destination $failureDestination `
    -StateRoot $failureStateRoot `
    -FailureInjection "metadata-write"
  if ($invocation.ExitCode -eq 0) {
    throw "Metadata write failure fixture unexpectedly exited 0"
  }
  foreach ($legacyName in $legacyNames) {
    if (-not (Test-Path -LiteralPath (Join-Path $failureDestination $legacyName) -PathType Container)) {
      throw "Metadata write failure removed legacy Skill before metadata persisted: $legacyName"
    }
  }
  $residue = @(
    Get-ChildItem -LiteralPath $failureStateRoot -Force |
      Where-Object { $_.Name -like ".source.json.*.tmp" -or $_.Name -like ".source.json.*.bak" }
  )
  if ($residue.Count -ne 0) {
    throw "Metadata write failure left temporary residue: $($residue.Name -join ', ')"
  }
}

try {
  Assert-DestinationIsRequired

  $sourceSkill = Join-Path $skillsRoot $unifiedSkillName
  $staleUnifiedTarget = Join-Path $destination $unifiedSkillName
  $unownedDirectory = Join-Path $destination "unowned-sentinel"
  foreach ($legacyName in $legacyNames) {
    $staleLegacyTarget = Join-Path $destination $legacyName
    New-Item -ItemType Directory -Path (Join-Path $staleLegacyTarget "stale-content") -Force | Out-Null
    Set-Content -LiteralPath (Join-Path $staleLegacyTarget "SKILL.md") -Value "obsolete $legacyName" -Encoding UTF8
  }
  New-Item -ItemType Directory -Path (Join-Path $staleUnifiedTarget "stale-content") -Force | Out-Null
  New-Item -ItemType Directory -Path $unownedDirectory -Force | Out-Null
  New-Item -ItemType Directory -Path $stateRoot -Force | Out-Null
  Set-Content -LiteralPath (Join-Path $staleUnifiedTarget "SKILL.md") -Value "stale unified skill" -Encoding UTF8
  Set-Content -LiteralPath (Join-Path $staleUnifiedTarget "stale-content\obsolete.txt") -Value "obsolete" -Encoding UTF8
  Set-Content -LiteralPath (Join-Path $unownedDirectory "keep.txt") -Value "keep" -Encoding UTF8
  Set-Content -LiteralPath (Join-Path $stateRoot "source.json") -Value '{"stale":true}' -Encoding UTF8

  $installerOutput = @(
    & powershell -NoProfile -ExecutionPolicy Bypass -File $installScript `
      -Destination $destination `
      -StateRoot $stateRoot
  )
  $installerExitCode = $LASTEXITCODE
  if ($installerExitCode -ne 0) {
    throw "Installer exited with code $installerExitCode"
  }

  $result = ($installerOutput -join "`n") | ConvertFrom-Json
  if (-not [StringComparer]::OrdinalIgnoreCase.Equals(
      [IO.Path]::GetFullPath([string]$result.destination),
      [IO.Path]::GetFullPath($destination)
    )) {
    throw "Installer JSON reported the wrong destination: $($result.destination)"
  }
  Assert-StringSetEqual `
    -Expected @($unifiedSkillName) `
    -Actual @($result.installed) `
    -Context "Installer JSON installed Skills"
  Assert-StringSetEqual `
    -Expected $legacyNames `
    -Actual @($result.removed) `
    -Context "Installer JSON removed legacy Skills"

  Assert-DirectoryParity `
    -Source $sourceSkill `
    -Installed (Join-Path $destination $unifiedSkillName) `
    -Context $unifiedSkillName

  foreach ($legacyName in $legacyNames) {
    $legacyTarget = Join-Path $destination $legacyName
    if (Test-Path -LiteralPath $legacyTarget) {
      throw "Installer did not remove legacy Skill: $legacyName"
    }
  }
  if (-not (Test-Path -LiteralPath (Join-Path $unownedDirectory "keep.txt") -PathType Leaf)) {
    throw "Installer removed unowned content"
  }

  Assert-SourceMetadata `
    -Result $result `
    -StateRoot $stateRoot `
    -SourceSkillRoot $sourceSkill `
    -InstalledSkillRoot (Join-Path $destination $unifiedSkillName)

  $stagingResidue = @(
    Get-ChildItem -LiteralPath $destination -Force |
      Where-Object { $_.Name -like ".luming-skills-install-*" }
  )
  if ($stagingResidue.Count -ne 0) {
    throw "Installer left staging residue: $($stagingResidue.Name -join ', ')"
  }

  $replacementOverlapDestination = New-StaleDestination -Name "state-overlap-replacement-destination"
  $replacementStateRoot = Join-Path (Join-Path $replacementOverlapDestination $legacyNames[0]) "state-root"
  New-Item -ItemType Directory -Force -Path $replacementStateRoot | Out-Null
  Assert-StateRootRejectedWithoutMutation `
    -Name "replacement target" `
    -Destination $replacementOverlapDestination `
    -StateRoot $replacementStateRoot `
    -SourceRoot $sourceSkill

  $unifiedOverlapDestination = New-StaleDestination -Name "state-overlap-unified-destination"
  $unifiedStateRoot = Join-Path (Join-Path $unifiedOverlapDestination $unifiedSkillName) "state-root"
  New-Item -ItemType Directory -Force -Path $unifiedStateRoot | Out-Null
  Assert-StateRootRejectedWithoutMutation `
    -Name "unified target" `
    -Destination $unifiedOverlapDestination `
    -StateRoot $unifiedStateRoot `
    -SourceRoot $sourceSkill

  $sourceMetadataPlaceholder = Join-Path $sourceSkill "source.json"
  if (Test-Path -LiteralPath $sourceMetadataPlaceholder) {
    throw "Source overlap fixture requires no pre-existing source.json: $sourceMetadataPlaceholder"
  }
  New-Item -ItemType Directory -Force -Path $sourceMetadataPlaceholder | Out-Null
  try {
    Assert-StateRootRejectedWithoutMutation `
      -Name "managed source root" `
      -Destination (Join-Path $tempRoot "state-overlap-source-destination") `
      -StateRoot $sourceSkill `
      -SourceRoot $sourceSkill
  } finally {
    Remove-Item -LiteralPath $sourceMetadataPlaceholder -Recurse -Force
  }

  Assert-MetadataWriteFailureRetainsLegacyTargets
  Assert-TransactionalRollback -Name "metadata-failure" -FailureInjection "metadata-write" -SeedMetadata $true
  Assert-TransactionalRollback -Name "legacy-removal-failure" -FailureInjection "legacy-removal" -SeedMetadata $false
  Assert-CleanupFailurePreservesCommittedInstall
  Assert-ReparseStateRootRejectedWithoutMutation
} finally {
  foreach ($reparsePath in $reparsePaths) {
    if (Test-Path -LiteralPath $reparsePath) {
      Remove-Item -LiteralPath $reparsePath -Force
    }
  }
  if (Test-Path -LiteralPath $tempRoot) {
    Remove-Item -LiteralPath $tempRoot -Recurse -Force
  }
}

Write-Output "luming skills install contract ok"
