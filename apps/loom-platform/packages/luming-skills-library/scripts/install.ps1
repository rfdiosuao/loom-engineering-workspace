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

function Get-FileSha256 {
  param([string]$Path)

  $stream = [IO.File]::OpenRead($Path)
  $algorithm = [Security.Cryptography.SHA256]::Create()
  try {
    return ([BitConverter]::ToString($algorithm.ComputeHash($stream))).Replace("-", "")
  } finally {
    $algorithm.Dispose()
    $stream.Dispose()
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
    $manifest.Add($relativePath, (Get-FileSha256 -Path $_.FullName))
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

function Read-JsonDocument {
  param(
    [string]$Path,
    [string]$Context
  )

  if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
    return $null
  }
  try {
    return Get-Content -Raw -Encoding UTF8 -LiteralPath $Path | ConvertFrom-Json
  } catch {
    throw "$Context is not valid JSON: $Path. $($_.Exception.Message)"
  }
}

function Enter-InstallLock {
  param(
    [string]$Path,
    [int]$TimeoutSeconds = 30
  )

  $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
  while ($true) {
    try {
      return [IO.File]::Open(
        $Path,
        [IO.FileMode]::OpenOrCreate,
        [IO.FileAccess]::ReadWrite,
        [IO.FileShare]::None
      )
    } catch [IO.IOException] {
      if ([DateTime]::UtcNow -ge $deadline) {
        throw "Timed out waiting for another LOOM Skill installation to finish: $Path"
      }
      Start-Sleep -Milliseconds 100
    }
  }
}

function Test-MatchingOwnerMarker {
  param(
    [string]$Target,
    [string]$SkillName,
    [string]$InstallId
  )

  $marker = Read-JsonDocument `
    -Path (Join-Path $Target ".loom-skill-owner.json") `
    -Context "LOOM Skill ownership marker"
  return (
    $null -ne $marker -and
    [string]$marker.schema -ceq "loom.skills.owner.v1" -and
    [string]$marker.package -ceq "luming-skills-library" -and
    [string]$marker.skill -ceq $SkillName -and
    [string]$marker.installId -ceq $InstallId
  )
}

function Test-OwnedSkillTarget {
  param(
    [string]$Target,
    [string]$SkillName,
    [object]$InstallState,
    [string]$Destination,
    [string]$MigrationMetadataPath,
    [switch]$AllowUnifiedMigration
  )

  if (
    $null -ne $InstallState -and
    [string]$InstallState.schema -ceq "loom.skills.install_state.v1" -and
    [string]$InstallState.package -ceq "luming-skills-library" -and
    [StringComparer]::OrdinalIgnoreCase.Equals(
      (Get-NormalizedPath -Path ([string]$InstallState.destination)),
      $Destination
    )
  ) {
    $ownedEntry = @(
      @($InstallState.ownedSkills) |
        Where-Object { [string]$_.name -ceq $SkillName } |
        Select-Object -First 1
    )
    if (
      $ownedEntry.Count -eq 1 -and
      (Test-MatchingOwnerMarker `
        -Target $Target `
        -SkillName $SkillName `
        -InstallId ([string]$ownedEntry[0].markerId))
    ) {
      return $true
    }
  }

  if ($AllowUnifiedMigration -and $null -eq $InstallState) {
    $migration = Read-JsonDocument `
      -Path $MigrationMetadataPath `
      -Context "Legacy LOOM Skill source metadata"
    if (
      $null -ne $migration -and
      [string]$migration.schema -ceq "loom.phone-agent.source.v1" -and
      [IO.Path]::IsPathRooted([string]$migration.installedSkillRoot) -and
      [StringComparer]::OrdinalIgnoreCase.Equals(
        (Get-NormalizedPath -Path ([string]$migration.installedSkillRoot)),
        $Target
      )
    ) {
      return $true
    }
  }

  return $false
}

function Merge-RecipeTree {
  param(
    [string]$SourceSkillRoot,
    [string]$CandidateSkillRoot
  )

  $sourceRecipes = Join-Path $SourceSkillRoot "recipes"
  if (-not (Test-Path -LiteralPath $sourceRecipes -PathType Container)) {
    return
  }
  $candidateRecipes = Join-Path $CandidateSkillRoot "recipes"
  New-Item -ItemType Directory -Force -Path $candidateRecipes | Out-Null
  Get-ChildItem -LiteralPath $sourceRecipes -Force | ForEach-Object {
    Copy-Item -LiteralPath $_.FullName -Destination $candidateRecipes -Recurse -Force
  }
}

function Assert-ManagedSkillIntegrity {
  param(
    [string]$Source,
    [string]$Candidate,
    [string]$Context
  )

  if (-not (Test-Path -LiteralPath $Candidate -PathType Container)) {
    throw "$Context is missing: $Candidate"
  }
  $sourcePath = Get-NormalizedPath -Path $Source
  $candidatePath = Get-NormalizedPath -Path $Candidate
  Get-ChildItem -LiteralPath $sourcePath -Recurse -File -Force | ForEach-Object {
    $relativePath = $_.FullName.Substring($sourcePath.Length).TrimStart([char[]]@('\', '/')).Replace('\', '/')
    if ($relativePath.StartsWith("recipes/", [StringComparison]::Ordinal)) {
      return
    }
    $candidateFile = Join-Path $candidatePath ($relativePath.Replace('/', [IO.Path]::DirectorySeparatorChar))
    if (-not (Test-Path -LiteralPath $candidateFile -PathType Leaf)) {
      throw "$Context is missing package file: $relativePath"
    }
    if ((Get-FileSha256 -Path $_.FullName) -cne (Get-FileSha256 -Path $candidateFile)) {
      throw "$Context SHA256 does not match the package for: $relativePath"
    }
  }
}

function Invoke-HardExitInjection {
  param([string]$Point)

  if ($env:LUMING_SKILLS_INSTALL_HARD_EXIT_AT -ceq $Point) {
    [Environment]::Exit(91)
  }
}

function Remove-StaleInstallTransactions {
  param(
    [string]$Destination,
    [string]$StateRoot
  )

  foreach ($root in @($Destination, $StateRoot)) {
    if (-not (Test-Path -LiteralPath $root -PathType Container)) {
      continue
    }
    Get-ChildItem -LiteralPath $root -Directory -Force |
      Where-Object { $_.Name -like ".luming-skills-install-*" } |
      ForEach-Object { Remove-OwnedTarget -Path $_.FullName }
  }
}

function Recover-InstallTransaction {
  param(
    [string]$JournalPath,
    [string]$Destination,
    [string]$StateRoot,
    [string]$DurableSourceTarget,
    [string]$InstallStatePath,
    [string]$SourceMetadataPath,
    [string[]]$AllowedDestinationNames
  )

  $journal = Read-JsonDocument -Path $JournalPath -Context "LOOM Skill install transaction"
  if ($null -eq $journal) {
    return $false
  }
  if (
    [string]$journal.schema -cne "loom.skills.install_transaction.v1" -or
    -not [StringComparer]::OrdinalIgnoreCase.Equals(
      (Get-NormalizedPath -Path ([string]$journal.destination)),
      $Destination
    ) -or
    -not [StringComparer]::OrdinalIgnoreCase.Equals(
      (Get-NormalizedPath -Path ([string]$journal.stateRoot)),
      $StateRoot
    )
  ) {
    throw "Refusing to recover a Skill transaction for another destination or state root"
  }

  $transactionRoot = Get-NormalizedPath -Path ([string]$journal.transactionRoot)
  $stateTransactionRoot = Get-NormalizedPath -Path ([string]$journal.stateTransactionRoot)
  if (
    (Split-Path -Leaf $transactionRoot) -notlike ".luming-skills-install-*" -or
    (Split-Path -Leaf $stateTransactionRoot) -notlike ".luming-skills-install-*"
  ) {
    throw "Skill transaction directory name is invalid"
  }
  Assert-DirectChildPath `
    -Parent $Destination `
    -Child $transactionRoot `
    -ExpectedName (Split-Path -Leaf $transactionRoot)
  Assert-DirectChildPath `
    -Parent $StateRoot `
    -Child $stateTransactionRoot `
    -ExpectedName (Split-Path -Leaf $stateTransactionRoot)

  if ([string]$journal.phase -cne "committed") {
    $records = @($journal.records)
    [array]::Reverse($records)
    foreach ($record in $records) {
      $target = Get-NormalizedPath -Path ([string]$record.target)
      $backup = Get-NormalizedPath -Path ([string]$record.backup)
      $kind = [string]$record.kind
      $name = [string]$record.name
      $priorExisted = [bool]$record.priorExisted

      if ($kind -in @("legacy", "managed")) {
        if ($AllowedDestinationNames -cnotcontains $name) {
          throw "Skill transaction contains an unexpected destination target: $name"
        }
        $expectedTarget = Get-NormalizedPath -Path (Join-Path $Destination $name)
        if (-not [StringComparer]::OrdinalIgnoreCase.Equals($target, $expectedTarget)) {
          throw "Skill transaction destination target does not match its declared name: $name"
        }
        if (-not (Test-IsSameOrChildPath -Path $backup -Parent $transactionRoot)) {
          throw "Skill transaction backup escapes its destination transaction root: $backup"
        }
      } elseif ($kind -ceq "source") {
        if (-not [StringComparer]::OrdinalIgnoreCase.Equals($target, $DurableSourceTarget)) {
          throw "Skill transaction durable source target is invalid"
        }
        if (-not (Test-IsSameOrChildPath -Path $backup -Parent $stateTransactionRoot)) {
          throw "Skill transaction source backup escapes its state transaction root"
        }
      } elseif ($kind -in @("install-state", "source-metadata")) {
        $expectedTarget = if ($kind -ceq "install-state") { $InstallStatePath } else { $SourceMetadataPath }
        if (-not [StringComparer]::OrdinalIgnoreCase.Equals($target, $expectedTarget)) {
          throw "Skill transaction metadata target is invalid: $kind"
        }
        if (-not (Test-IsSameOrChildPath -Path $backup -Parent $stateTransactionRoot)) {
          throw "Skill transaction metadata backup escapes its state transaction root"
        }
      } else {
        throw "Skill transaction record kind is invalid: $kind"
      }

      $backupExists = Test-Path -LiteralPath $backup
      $targetExists = Test-Path -LiteralPath $target
      if ($kind -ceq "legacy") {
        if ($backupExists -and $targetExists) {
          throw "Cannot recover legacy Skill because both target and backup exist: $name"
        }
        if ($backupExists) {
          Move-Item -LiteralPath $backup -Destination $target
        }
        continue
      }

      if ($kind -ceq "managed" -and $targetExists) {
        if (Test-MatchingOwnerMarker `
          -Target $target `
          -SkillName $name `
          -InstallId ([string]$journal.installId)
        ) {
          Remove-OwnedTarget -Path $target
          $targetExists = $false
        } elseif ($backupExists -or -not $priorExisted) {
          throw "Cannot recover managed Skill because the target ownership changed: $name"
        }
      }

      if ($kind -in @("source", "install-state", "source-metadata")) {
        if ($backupExists -and $targetExists) {
          Remove-OwnedTarget -Path $target
          $targetExists = $false
        } elseif (-not $priorExisted -and $targetExists) {
          Remove-OwnedTarget -Path $target
          $targetExists = $false
        }
      }

      if ($backupExists) {
        if (Test-Path -LiteralPath $target) {
          throw "Cannot restore Skill transaction backup because the target exists: $target"
        }
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $target) | Out-Null
        Move-Item -LiteralPath $backup -Destination $target
      }
    }
  }

  if (Test-Path -LiteralPath $transactionRoot) {
    Remove-OwnedTarget -Path $transactionRoot
  }
  if (Test-Path -LiteralPath $stateTransactionRoot) {
    Remove-OwnedTarget -Path $stateTransactionRoot
  }
  $durableSourceParent = Split-Path -Parent $DurableSourceTarget
  if (
    (Test-Path -LiteralPath $durableSourceParent -PathType Container) -and
    @(Get-ChildItem -LiteralPath $durableSourceParent -Force).Count -eq 0
  ) {
    Remove-Item -LiteralPath $durableSourceParent -Force
  }
  if (Test-Path -LiteralPath $JournalPath) {
    Remove-OwnedTarget -Path $JournalPath
  }
  return $true
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
$stateRootExisted = Test-Path -LiteralPath $stateRootPath
New-Item -ItemType Directory -Force -Path $stateRootPath | Out-Null
$lockPath = Join-Path $stateRootPath "install.lock"
$journalPath = Join-Path $stateRootPath "install-transaction.json"
$installStatePath = Join-Path $stateRootPath "install-state.json"
$metadataPath = Join-Path $stateRootPath "source.json"
$durableSourceParent = Get-NormalizedPath -Path (Join-Path $stateRootPath "source")
$durableSourceTarget = Get-NormalizedPath -Path (Join-Path $durableSourceParent $sourceSkills[0].Name)
Assert-DirectChildPath `
  -Parent $durableSourceParent `
  -Child $durableSourceTarget `
  -ExpectedName $sourceSkills[0].Name
$installLock = $null
try {
  $installLock = Enter-InstallLock -Path $lockPath
  $allowedDestinationNames = @($sourceSkills.Name) + @($replacedSkillNames)
  $recovered = Recover-InstallTransaction `
    -JournalPath $journalPath `
    -Destination $destinationPath `
    -StateRoot $stateRootPath `
    -DurableSourceTarget $durableSourceTarget `
    -InstallStatePath $installStatePath `
    -SourceMetadataPath $metadataPath `
    -AllowedDestinationNames $allowedDestinationNames
  if (-not $recovered) {
    Remove-StaleInstallTransactions -Destination $destinationPath -StateRoot $stateRootPath
  }

  $installState = Read-JsonDocument -Path $installStatePath -Context "LOOM Skill install state"
  $ownedReplacementTargets = @()
  $skippedUnowned = @()
  foreach ($replacedSkillName in $replacedSkillNames) {
    $replacementTarget = Get-NormalizedPath -Path (Join-Path $destinationPath $replacedSkillName)
    if (-not (Test-Path -LiteralPath $replacementTarget)) {
      continue
    }
    if (Test-OwnedSkillTarget `
      -Target $replacementTarget `
      -SkillName $replacedSkillName `
      -InstallState $installState `
      -Destination $destinationPath `
      -MigrationMetadataPath $metadataPath
    ) {
      $ownedReplacementTargets += [pscustomobject]@{
        Name = $replacedSkillName
        Target = $replacementTarget
      }
    } else {
      $skippedUnowned += $replacedSkillName
    }
  }

  $managedTargets = @()
  foreach ($sourceSkill in $sourceSkills) {
    $target = Get-NormalizedPath -Path (Join-Path $destinationPath $sourceSkill.Name)
    $targetExists = Test-Path -LiteralPath $target
    if (
      $targetExists -and
      -not (Test-OwnedSkillTarget `
        -Target $target `
        -SkillName $sourceSkill.Name `
        -InstallState $installState `
        -Destination $destinationPath `
        -MigrationMetadataPath $metadataPath `
        -AllowUnifiedMigration)
    ) {
      throw "Refusing to replace unowned Skill directory: $target"
    }
    $managedTargets += [pscustomobject]@{
      Name = $sourceSkill.Name
      Source = $sourceSkill.FullName
      Target = $target
      PriorExisted = $targetExists
    }
  }

  $installId = [guid]::NewGuid().ToString("N")
  $transactionName = ".luming-skills-install-$installId"
  $transactionRoot = Get-NormalizedPath -Path (Join-Path $destinationPath $transactionName)
  $stateTransactionRoot = Get-NormalizedPath -Path (Join-Path $stateRootPath $transactionName)
  Assert-DirectChildPath -Parent $destinationPath -Child $transactionRoot -ExpectedName $transactionName
  Assert-DirectChildPath -Parent $stateRootPath -Child $stateTransactionRoot -ExpectedName $transactionName
  $stagingRoot = Join-Path $transactionRoot "staged"
  $destinationBackupRoot = Join-Path $transactionRoot "backups"
  $stateStagingRoot = Join-Path $stateTransactionRoot "staged"
  $stateBackupRoot = Join-Path $stateTransactionRoot "backups"
  New-Item -ItemType Directory -Force -Path $stagingRoot, $destinationBackupRoot, $stateStagingRoot, $stateBackupRoot | Out-Null

  $ownerMarker = [ordered]@{
    schema = "loom.skills.owner.v1"
    package = "luming-skills-library"
    skill = $sourceSkills[0].Name
    installId = $installId
    version = [string]$libraryManifest.version
  }
  foreach ($managedTarget in $managedTargets) {
    Copy-Item -LiteralPath $managedTarget.Source -Destination $stagingRoot -Recurse -Force
    $stagedSkill = Join-Path $stagingRoot $managedTarget.Name
    if (Test-Path -LiteralPath $durableSourceTarget -PathType Container) {
      Merge-RecipeTree -SourceSkillRoot $durableSourceTarget -CandidateSkillRoot $stagedSkill
    }
    if ($managedTarget.PriorExisted) {
      Merge-RecipeTree -SourceSkillRoot $managedTarget.Target -CandidateSkillRoot $stagedSkill
    }
    Write-AtomicJson -Path (Join-Path $stagedSkill ".loom-skill-owner.json") -Document $ownerMarker
    Assert-ManagedSkillIntegrity `
      -Source $managedTarget.Source `
      -Candidate $stagedSkill `
      -Context "Staged Skill $($managedTarget.Name)"

    $stagedSource = Join-Path $stateStagingRoot $managedTarget.Name
    Copy-Item -LiteralPath $stagedSkill -Destination $stateStagingRoot -Recurse -Force
    Remove-Item -LiteralPath (Join-Path $stagedSource ".loom-skill-owner.json") -Force
    Assert-ManagedSkillIntegrity `
      -Source $managedTarget.Source `
      -Candidate $stagedSource `
      -Context "Staged durable source $($managedTarget.Name)"
  }

  $records = @()
  foreach ($ownedReplacement in $ownedReplacementTargets) {
    $records += [ordered]@{
      kind = "legacy"
      name = $ownedReplacement.Name
      target = $ownedReplacement.Target
      backup = Get-NormalizedPath -Path (Join-Path $destinationBackupRoot $ownedReplacement.Name)
      priorExisted = $true
    }
  }
  foreach ($managedTarget in $managedTargets) {
    $records += [ordered]@{
      kind = "managed"
      name = $managedTarget.Name
      target = $managedTarget.Target
      backup = Get-NormalizedPath -Path (Join-Path $destinationBackupRoot $managedTarget.Name)
      priorExisted = [bool]$managedTarget.PriorExisted
    }
  }
  $records += [ordered]@{
    kind = "source"
    name = $sourceSkills[0].Name
    target = $durableSourceTarget
    backup = Get-NormalizedPath -Path (Join-Path $stateBackupRoot "source")
    priorExisted = [bool](Test-Path -LiteralPath $durableSourceTarget)
  }
  $records += [ordered]@{
    kind = "install-state"
    name = "install-state.json"
    target = $installStatePath
    backup = Get-NormalizedPath -Path (Join-Path $stateBackupRoot "install-state.json")
    priorExisted = [bool](Test-Path -LiteralPath $installStatePath)
  }
  $records += [ordered]@{
    kind = "source-metadata"
    name = "source.json"
    target = $metadataPath
    backup = Get-NormalizedPath -Path (Join-Path $stateBackupRoot "source.json")
    priorExisted = [bool](Test-Path -LiteralPath $metadataPath)
  }
  $journal = [ordered]@{
    schema = "loom.skills.install_transaction.v1"
    phase = "prepared"
    installId = $installId
    destination = $destinationPath
    stateRoot = $stateRootPath
    transactionRoot = $transactionRoot
    stateTransactionRoot = $stateTransactionRoot
    records = $records
  }
  Write-AtomicJson -Path $journalPath -Document $journal

  try {
    $journal.phase = "mutating"
    Write-AtomicJson -Path $journalPath -Document $journal
    foreach ($record in @($records | Where-Object { $_.kind -ceq "legacy" })) {
      Move-Item -LiteralPath $record.target -Destination $record.backup
      Invoke-FailureInjection -Point "legacy-removal"
    }
    foreach ($record in @($records | Where-Object { $_.kind -ceq "managed" })) {
      if ($record.priorExisted) {
        Move-Item -LiteralPath $record.target -Destination $record.backup
      }
      Invoke-HardExitInjection -Point "after-managed-backup"
    }
    $sourceRecord = @($records | Where-Object { $_.kind -ceq "source" })[0]
    if ($sourceRecord.priorExisted) {
      Move-Item -LiteralPath $sourceRecord.target -Destination $sourceRecord.backup
    }
    foreach ($record in @($records | Where-Object { $_.kind -in @("install-state", "source-metadata") })) {
      if ($record.priorExisted) {
        Move-Item -LiteralPath $record.target -Destination $record.backup
      }
    }

    foreach ($managedTarget in $managedTargets) {
      Move-Item `
        -LiteralPath (Join-Path $stagingRoot $managedTarget.Name) `
        -Destination $managedTarget.Target
      Assert-ManagedSkillIntegrity `
        -Source $managedTarget.Source `
        -Candidate $managedTarget.Target `
        -Context "Installed Skill $($managedTarget.Name)"
    }
    New-Item -ItemType Directory -Force -Path $durableSourceParent | Out-Null
    Move-Item `
      -LiteralPath (Join-Path $stateStagingRoot $sourceSkills[0].Name) `
      -Destination $durableSourceTarget

    Invoke-FailureInjection -Point "metadata-write"
    $sourceMetadata = [ordered]@{
      schema = "loom.phone-agent.source.v1"
      sourceSkillRoot = $durableSourceTarget
      installedSkillRoot = $managedTargets[0].Target
    }
    $newInstallState = [ordered]@{
      schema = "loom.skills.install_state.v1"
      package = "luming-skills-library"
      version = [string]$libraryManifest.version
      installId = $installId
      destination = $destinationPath
      sourceSkillRoot = $durableSourceTarget
      ownedSkills = @(
        foreach ($managedTarget in $managedTargets) {
          [ordered]@{
            name = $managedTarget.Name
            markerId = $installId
          }
        }
      )
    }
    Write-AtomicJson -Path $installStatePath -Document $newInstallState
    Write-AtomicJson -Path $metadataPath -Document $sourceMetadata

    $journal.phase = "committed"
    Write-AtomicJson -Path $journalPath -Document $journal
  } catch {
    $operationError = $_.Exception.Message
    try {
      Recover-InstallTransaction `
        -JournalPath $journalPath `
        -Destination $destinationPath `
        -StateRoot $stateRootPath `
        -DurableSourceTarget $durableSourceTarget `
        -InstallStatePath $installStatePath `
        -SourceMetadataPath $metadataPath `
        -AllowedDestinationNames $allowedDestinationNames | Out-Null
    } catch {
      throw "Installation failed: $operationError. Recovery failed: $($_.Exception.Message). Journal preserved at: $journalPath"
    }
    throw "Installation failed and was recovered: $operationError"
  }

  Invoke-FailureInjection -Point "cleanup-state"
  if (Test-Path -LiteralPath $stateTransactionRoot) {
    Remove-OwnedTarget -Path $stateTransactionRoot
  }
  Invoke-FailureInjection -Point "cleanup-destination"
  if (Test-Path -LiteralPath $transactionRoot) {
    Remove-OwnedTarget -Path $transactionRoot
  }
  if (Test-Path -LiteralPath $journalPath) {
    Remove-OwnedTarget -Path $journalPath
  }

  [pscustomobject]@{
    destination = $Destination
    installed = @($managedTargets.Name)
    removed = @($ownedReplacementTargets.Name)
    skippedUnowned = @($skippedUnowned)
    recoveredPreviousTransaction = [bool]$recovered
    sourceMetadata = $sourceMetadata
  } | ConvertTo-Json -Depth 6
} finally {
  if ($null -ne $installLock) {
    $installLock.Dispose()
  }
}
