param(
  [string]$Destination,
  [string]$StateRoot
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$skillsRoot = Join-Path $repoRoot "skills"

function Get-NormalizedPath {
  param([string]$Path)

  $fullPath = [IO.Path]::GetFullPath($Path)
  $pathRoot = [IO.Path]::GetPathRoot($fullPath)
  if ($fullPath.Length -gt $pathRoot.Length) {
    return $fullPath.TrimEnd([char[]]@('\', '/'))
  }
  return $fullPath
}

function Assert-NoReparseComponents {
  param(
    [string]$Path,
    [string]$Context
  )

  $fullPath = Get-NormalizedPath -Path $Path
  $pathRoot = [IO.Path]::GetPathRoot($fullPath)
  $currentPath = $pathRoot
  $relativePath = $fullPath.Substring($pathRoot.Length)
  foreach ($segment in @($relativePath -split '[\\/]' | Where-Object { $_ })) {
    $currentPath = Join-Path $currentPath $segment
    if (Test-Path -LiteralPath $currentPath) {
      $item = Get-Item -LiteralPath $currentPath -Force
      if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "$Context must not contain a reparse-point component: $currentPath"
      }
    }
  }
}

function Test-IsSameOrChildPath {
  param(
    [string]$Path,
    [string]$Parent
  )

  if ([StringComparer]::OrdinalIgnoreCase.Equals($Path, $Parent)) {
    return $true
  }
  $parentPrefix = $Parent.TrimEnd([char[]]@('\', '/')) + [IO.Path]::DirectorySeparatorChar
  return $Path.StartsWith($parentPrefix, [StringComparison]::OrdinalIgnoreCase)
}

function Assert-DirectChildPath {
  param(
    [string]$Parent,
    [string]$Child,
    [string]$ExpectedName
  )

  $childParent = Get-NormalizedPath -Path (Split-Path -Parent $Child)
  $childName = Split-Path -Leaf $Child
  if (-not [StringComparer]::OrdinalIgnoreCase.Equals($Parent, $childParent) -or
      -not [StringComparer]::Ordinal.Equals($ExpectedName, $childName)) {
    throw "Refusing to replace path outside the expected destination scope: $Child"
  }
}

function Get-FileManifest {
  param([string]$Root)

  $rootPath = Get-NormalizedPath -Path $Root
  $manifest = [Collections.Generic.Dictionary[string, string]]::new(
    [StringComparer]::Ordinal
  )
  Get-ChildItem -LiteralPath $rootPath -Recurse -File -Force | ForEach-Object {
    $relativePath = $_.FullName.Substring($rootPath.Length).TrimStart([char[]]@('\', '/')).Replace('\', '/')
    $manifest.Add($relativePath, (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash)
  }
  return $manifest
}

function Assert-DirectoryParity {
  param(
    [string]$Source,
    [string]$Candidate,
    [string]$Context
  )

  if (-not (Test-Path -LiteralPath $Candidate -PathType Container)) {
    throw "$Context is missing: $Candidate"
  }

  $sourceManifest = Get-FileManifest -Root $Source
  $candidateManifest = Get-FileManifest -Root $Candidate
  if ($sourceManifest.Count -ne $candidateManifest.Count) {
    throw "$Context file count does not match the source"
  }
  foreach ($relativePath in $sourceManifest.Keys) {
    if (-not $candidateManifest.ContainsKey($relativePath)) {
      throw "$Context is missing source file: $relativePath"
    }
    if ($sourceManifest[$relativePath] -cne $candidateManifest[$relativePath]) {
      throw "$Context SHA256 does not match the source for: $relativePath"
    }
  }
}

function Remove-OwnedTarget {
  param([string]$Path)

  if (-not (Test-Path -LiteralPath $Path)) {
    return
  }

  $item = Get-Item -LiteralPath $Path -Force
  $isReparsePoint = ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0
  if ($item.PSIsContainer -and -not $isReparsePoint) {
    Remove-Item -LiteralPath $Path -Recurse -Force
  } else {
    Remove-Item -LiteralPath $Path -Force
  }
}

function Assert-DisjointPath {
  param(
    [string]$StateRoot,
    [string]$ManagedPath,
    [string]$Context
  )

  if ((Test-IsSameOrChildPath -Path $StateRoot -Parent $ManagedPath) -or
      (Test-IsSameOrChildPath -Path $ManagedPath -Parent $StateRoot)) {
    throw "StateRoot must not overlap ${Context}: $StateRoot"
  }
}

function Write-AtomicJson {
  param(
    [string]$Path,
    [object]$Document
  )

  $parent = Split-Path -Parent $Path
  New-Item -ItemType Directory -Force -Path $parent | Out-Null
  $temporaryPath = Join-Path $parent ("." + (Split-Path -Leaf $Path) + "." + [guid]::NewGuid().ToString("N") + ".tmp")
  $backupPath = Join-Path $parent ("." + (Split-Path -Leaf $Path) + "." + [guid]::NewGuid().ToString("N") + ".bak")
  $json = $Document | ConvertTo-Json -Depth 8
  $utf8NoBom = [Text.UTF8Encoding]::new($false)

  try {
    [IO.File]::WriteAllText($temporaryPath, $json, $utf8NoBom)
    if (Test-Path -LiteralPath $Path) {
      [IO.File]::Replace($temporaryPath, $Path, $backupPath)
    } else {
      [IO.File]::Move($temporaryPath, $Path)
    }
  } finally {
    if (Test-Path -LiteralPath $temporaryPath) {
      Remove-Item -LiteralPath $temporaryPath -Force
    }
    if (Test-Path -LiteralPath $backupPath) {
      Remove-Item -LiteralPath $backupPath -Force
    }
  }
}

function Invoke-FailureInjection {
  param([string]$Point)

  if ($env:LUMING_SKILLS_INSTALL_FAIL_AT -ceq $Point) {
    throw "Injected installer failure at $Point"
  }
}

function Invoke-RollbackStep {
  param(
    [string]$Description,
    [scriptblock]$Action,
    [Collections.Generic.List[string]]$Errors
  )

  try {
    & $Action
  } catch {
    $Errors.Add("${Description}: $($_.Exception.Message)")
  }
}

if ([string]::IsNullOrWhiteSpace($Destination)) {
  throw "Destination is required. Detect the current Agent host and pass its official Skills directory explicitly; never guess .codex."
}
if (-not $StateRoot) {
  $StateRoot = Join-Path (Join-Path $env:USERPROFILE ".luming") "phone-agent"
}

$skillsRootPath = Get-NormalizedPath -Path $skillsRoot
$destinationPath = Get-NormalizedPath -Path $Destination
Assert-NoReparseComponents -Path $skillsRootPath -Context "Source Skills root"
Assert-NoReparseComponents -Path $destinationPath -Context "Destination"
if (Test-IsSameOrChildPath -Path $destinationPath -Parent $skillsRootPath) {
  throw "Destination must not be the source Skills directory or one of its descendants"
}

$manifestPath = Join-Path $repoRoot "manifest.json"
$libraryManifest = Get-Content -Raw -Encoding UTF8 -LiteralPath $manifestPath | ConvertFrom-Json
$sourceSkills = @(
  foreach ($manifestSkill in @($libraryManifest.skills)) {
    $skillName = [string]$manifestSkill.name
    $sourcePath = Get-NormalizedPath -Path (Join-Path $repoRoot ([string]$manifestSkill.path))
    if (-not $skillName) {
      throw "Manifest Skill is missing a name"
    }
    Assert-DirectChildPath -Parent $skillsRootPath -Child $sourcePath -ExpectedName $skillName
    Assert-NoReparseComponents -Path $sourcePath -Context "Managed source Skill $skillName"
    if (-not (Test-Path -LiteralPath $sourcePath -PathType Container)) {
      throw "Manifest Skill source directory is missing: $sourcePath"
    }
    [pscustomobject]@{
      Name = $skillName
      FullName = $sourcePath
    }
  }
)
if ($sourceSkills.Count -eq 0) {
  throw "Manifest does not declare any managed Skills"
}
if (@($sourceSkills.Name | Select-Object -Unique).Count -ne $sourceSkills.Count) {
  throw "Manifest declares duplicate managed Skill names"
}
$replacedSkillNames = @($libraryManifest.replaces | ForEach-Object { [string]$_ })
if (@($replacedSkillNames | Select-Object -Unique).Count -ne $replacedSkillNames.Count) {
  throw "Manifest declares duplicate replacement Skill names"
}
foreach ($replacedSkillName in $replacedSkillNames) {
  if (-not $replacedSkillName) {
    throw "Manifest replacement Skill is missing a name"
  }
  if ($sourceSkills.Name -contains $replacedSkillName) {
    throw "Manifest replacement cannot also be a managed Skill: $replacedSkillName"
  }
}

$stateRootPath = Get-NormalizedPath -Path $StateRoot
Assert-NoReparseComponents -Path $stateRootPath -Context "StateRoot"
Assert-DisjointPath -StateRoot $stateRootPath -ManagedPath $destinationPath -Context "the destination"
foreach ($sourceSkill in $sourceSkills) {
  Assert-DisjointPath -StateRoot $stateRootPath -ManagedPath $sourceSkill.FullName -Context "managed source Skill $($sourceSkill.Name)"
  $target = Get-NormalizedPath -Path (Join-Path $destinationPath $sourceSkill.Name)
  Assert-DirectChildPath -Parent $destinationPath -Child $target -ExpectedName $sourceSkill.Name
  Assert-NoReparseComponents -Path $target -Context "Managed destination Skill $($sourceSkill.Name)"
  Assert-DisjointPath -StateRoot $stateRootPath -ManagedPath $target -Context "managed destination Skill $($sourceSkill.Name)"
}
foreach ($replacedSkillName in $replacedSkillNames) {
  $replacementTarget = Get-NormalizedPath -Path (Join-Path $destinationPath $replacedSkillName)
  Assert-DirectChildPath -Parent $destinationPath -Child $replacementTarget -ExpectedName $replacedSkillName
  Assert-NoReparseComponents -Path $replacementTarget -Context "Replacement Skill $replacedSkillName"
  Assert-DisjointPath -StateRoot $stateRootPath -ManagedPath $replacementTarget -Context "replacement Skill $replacedSkillName"
}

$destinationExisted = Test-Path -LiteralPath $destinationPath
New-Item -ItemType Directory -Force -Path $destinationPath | Out-Null
$transactionName = ".luming-skills-install-$([guid]::NewGuid().ToString('N'))"
$transactionRoot = Get-NormalizedPath -Path (Join-Path $destinationPath $transactionName)
Assert-DirectChildPath -Parent $destinationPath -Child $transactionRoot -ExpectedName $transactionName
$stagingRoot = Join-Path $transactionRoot "staged"
$destinationBackupRoot = Join-Path $transactionRoot "backups"

$metadataPath = Join-Path $stateRootPath "source.json"
$stateRootExisted = Test-Path -LiteralPath $stateRootPath
$stateTransactionRoot = $null
$metadataBackupPath = $null
$metadataWasBackedUp = $false
$metadataMutationStarted = $false
$managedBackups = @()
$replacementBackups = @()
$installedTargets = @()
$installed = @()
$removed = @()
$sourceMetadata = $null

try {
  New-Item -ItemType Directory -Path $transactionRoot | Out-Null
  New-Item -ItemType Directory -Path $stagingRoot | Out-Null
  New-Item -ItemType Directory -Path $destinationBackupRoot | Out-Null

  foreach ($sourceSkill in $sourceSkills) {
    Copy-Item -LiteralPath $sourceSkill.FullName -Destination $stagingRoot -Recurse -Force
    $stagedSkill = Join-Path $stagingRoot $sourceSkill.Name
    Assert-DirectoryParity `
      -Source $sourceSkill.FullName `
      -Candidate $stagedSkill `
      -Context "Staged Skill $($sourceSkill.Name)"
  }

  # Hide every legacy target before exposing the replacement, so this run never adds a sixth triggerable Skill.
  foreach ($replacedSkillName in $replacedSkillNames) {
    $replacementTarget = Get-NormalizedPath -Path (Join-Path $destinationPath $replacedSkillName)
    Assert-DirectChildPath -Parent $destinationPath -Child $replacementTarget -ExpectedName $replacedSkillName
    if (Test-Path -LiteralPath $replacementTarget) {
      $replacementBackup = Join-Path $destinationBackupRoot $replacedSkillName
      Move-Item -LiteralPath $replacementTarget -Destination $replacementBackup
      $replacementBackups += [pscustomobject]@{ Target = $replacementTarget; Backup = $replacementBackup }
      $removed += $replacedSkillName
    }
    Invoke-FailureInjection -Point "legacy-removal"
  }

  foreach ($sourceSkill in $sourceSkills) {
    $target = Get-NormalizedPath -Path (Join-Path $destinationPath $sourceSkill.Name)
    Assert-DirectChildPath -Parent $destinationPath -Child $target -ExpectedName $sourceSkill.Name
    if (Test-Path -LiteralPath $target) {
      $managedBackup = Join-Path $destinationBackupRoot $sourceSkill.Name
      Move-Item -LiteralPath $target -Destination $managedBackup
      $managedBackups += [pscustomobject]@{ Target = $target; Backup = $managedBackup }
    }
  }

  foreach ($sourceSkill in $sourceSkills) {
    $stagedSkill = Join-Path $stagingRoot $sourceSkill.Name
    $target = Get-NormalizedPath -Path (Join-Path $destinationPath $sourceSkill.Name)
    Move-Item -LiteralPath $stagedSkill -Destination $target
    $installedTargets += $target
    Assert-DirectoryParity `
      -Source $sourceSkill.FullName `
      -Candidate $target `
      -Context "Installed Skill $($sourceSkill.Name)"
    $installed += $sourceSkill.Name
  }

  if (-not (Test-Path -LiteralPath $stateRootPath)) {
    New-Item -ItemType Directory -Path $stateRootPath | Out-Null
  }
  $stateTransactionName = ".luming-skills-install-$([guid]::NewGuid().ToString('N'))"
  $stateTransactionRoot = Get-NormalizedPath -Path (Join-Path $stateRootPath $stateTransactionName)
  Assert-DirectChildPath -Parent $stateRootPath -Child $stateTransactionRoot -ExpectedName $stateTransactionName
  New-Item -ItemType Directory -Path $stateTransactionRoot | Out-Null
  $metadataBackupPath = Join-Path $stateTransactionRoot "source.json"
  if (Test-Path -LiteralPath $metadataPath) {
    Move-Item -LiteralPath $metadataPath -Destination $metadataBackupPath
    $metadataWasBackedUp = $true
  }

  $sourceMetadata = [ordered]@{
    schema = "loom.phone-agent.source.v1"
    sourceSkillRoot = $sourceSkills[0].FullName
    installedSkillRoot = Get-NormalizedPath -Path (Join-Path $destinationPath $sourceSkills[0].Name)
  }
  $metadataMutationStarted = $true
  Invoke-FailureInjection -Point "metadata-write"
  Write-AtomicJson -Path $metadataPath -Document $sourceMetadata
} catch {
  $operationError = $_.Exception.Message
  $rollbackErrors = [Collections.Generic.List[string]]::new()

  if ($metadataMutationStarted) {
    Invoke-RollbackStep -Description "remove new metadata" -Errors $rollbackErrors -Action {
      if (Test-Path -LiteralPath $metadataPath) {
        Remove-OwnedTarget -Path $metadataPath
      }
    }
  }
  if ($metadataWasBackedUp) {
    Invoke-RollbackStep -Description "restore metadata" -Errors $rollbackErrors -Action {
      if (-not (Test-Path -LiteralPath $metadataPath)) {
        Move-Item -LiteralPath $metadataBackupPath -Destination $metadataPath
      } else {
        throw "metadata target already exists: $metadataPath"
      }
    }
  }

  foreach ($installedTarget in $installedTargets) {
    Invoke-RollbackStep -Description "remove installed Skill $([IO.Path]::GetFileName($installedTarget))" -Errors $rollbackErrors -Action {
      if (Test-Path -LiteralPath $installedTarget) {
        Remove-OwnedTarget -Path $installedTarget
      }
    }
  }
  foreach ($managedBackup in $managedBackups) {
    Invoke-RollbackStep -Description "restore managed Skill $([IO.Path]::GetFileName($managedBackup.Target))" -Errors $rollbackErrors -Action {
      if (-not (Test-Path -LiteralPath $managedBackup.Target)) {
        Move-Item -LiteralPath $managedBackup.Backup -Destination $managedBackup.Target
      } else {
        throw "managed target already exists: $($managedBackup.Target)"
      }
    }
  }
  foreach ($replacementBackup in $replacementBackups) {
    Invoke-RollbackStep -Description "restore replacement Skill $([IO.Path]::GetFileName($replacementBackup.Target))" -Errors $rollbackErrors -Action {
      if (-not (Test-Path -LiteralPath $replacementBackup.Target)) {
        Move-Item -LiteralPath $replacementBackup.Backup -Destination $replacementBackup.Target
      } else {
        throw "replacement target already exists: $($replacementBackup.Target)"
      }
    }
  }

  if ($rollbackErrors.Count -eq 0) {
    Invoke-RollbackStep -Description "clean destination transaction" -Errors $rollbackErrors -Action {
      if (Test-Path -LiteralPath $transactionRoot) {
        Remove-OwnedTarget -Path $transactionRoot
      }
    }
    Invoke-RollbackStep -Description "clean metadata transaction" -Errors $rollbackErrors -Action {
      if ($stateTransactionRoot -and (Test-Path -LiteralPath $stateTransactionRoot)) {
        Remove-OwnedTarget -Path $stateTransactionRoot
      }
    }
    if (-not $stateRootExisted) {
      Invoke-RollbackStep -Description "restore absent StateRoot" -Errors $rollbackErrors -Action {
        if ((Test-Path -LiteralPath $stateRootPath) -and
            @(Get-ChildItem -LiteralPath $stateRootPath -Force).Count -eq 0) {
          Remove-Item -LiteralPath $stateRootPath -Force
        }
      }
    }
    if (-not $destinationExisted) {
      Invoke-RollbackStep -Description "restore absent destination" -Errors $rollbackErrors -Action {
        if ((Test-Path -LiteralPath $destinationPath) -and
            @(Get-ChildItem -LiteralPath $destinationPath -Force).Count -eq 0) {
          Remove-Item -LiteralPath $destinationPath -Force
        }
      }
    }
  }

  if ($rollbackErrors.Count -ne 0) {
    $recoverableBackups = (@($transactionRoot) + @($stateTransactionRoot | Where-Object { $_ })) -join "; "
    throw "Installation failed: $operationError. Rollback also failed: $($rollbackErrors -join '; '). Recoverable backups were preserved at: $recoverableBackups"
  }
  throw "Installation failed and was rolled back: $operationError"
}

$cleanupErrors = [Collections.Generic.List[string]]::new()
try {
  Invoke-FailureInjection -Point "cleanup-state"
  if ($stateTransactionRoot -and (Test-Path -LiteralPath $stateTransactionRoot)) {
    Remove-OwnedTarget -Path $stateTransactionRoot
  }
} catch {
  $cleanupErrors.Add("clean metadata transaction: $($_.Exception.Message)")
}

# Once cleanup begins, the new installation is committed. Never roll it back after deleting a backup.
if ($cleanupErrors.Count -eq 0) {
  try {
    Invoke-FailureInjection -Point "cleanup-destination"
    if (Test-Path -LiteralPath $transactionRoot) {
      Remove-OwnedTarget -Path $transactionRoot
    }
  } catch {
    $cleanupErrors.Add("clean destination transaction: $($_.Exception.Message)")
  }
}

if ($cleanupErrors.Count -ne 0) {
  $preservedTransactions = @(
    $transactionRoot
    if ($stateTransactionRoot -and (Test-Path -LiteralPath $stateTransactionRoot)) { $stateTransactionRoot }
  ) -join "; "
  throw "Installation committed, but transaction cleanup failed: $($cleanupErrors -join '; '). The installed state was preserved; cleanup residue remains at: $preservedTransactions"
}

[pscustomobject]@{
  destination = $Destination
  installed = $installed
  removed = $removed
  sourceMetadata = $sourceMetadata
} | ConvertTo-Json -Depth 4
