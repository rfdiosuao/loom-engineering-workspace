$ErrorActionPreference = "Stop"

$packageRoot = Split-Path -Parent $PSScriptRoot
$installScript = Join-Path $packageRoot "scripts\install.ps1"
$tempRoot = Join-Path ([IO.Path]::GetTempPath()) ("luming-skills-install-hardening-" + [guid]::NewGuid().ToString("N"))
$utf8 = [Text.UTF8Encoding]::new($false)

function Start-Installer {
  param(
    [string]$Destination,
    [string]$StateRoot,
    [string]$HardExitAt
  )

  $startInfo = [Diagnostics.ProcessStartInfo]::new()
  $startInfo.FileName = "powershell.exe"
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
  if ($HardExitAt) {
    $startInfo.EnvironmentVariables["LUMING_SKILLS_INSTALL_HARD_EXIT_AT"] = $HardExitAt
  }

  $process = [Diagnostics.Process]::new()
  $process.StartInfo = $startInfo
  if (-not $process.Start()) {
    throw "Unable to start Skill installer"
  }
  return $process
}

function Complete-Installer {
  param([Diagnostics.Process]$Process)

  $stdout = $Process.StandardOutput.ReadToEnd()
  $stderr = $Process.StandardError.ReadToEnd()
  $Process.WaitForExit()
  return [pscustomobject]@{
    ExitCode = $Process.ExitCode
    StdOut = $stdout
    StdErr = $stderr
  }
}

function Invoke-Installer {
  param(
    [string]$Destination,
    [string]$StateRoot,
    [string]$HardExitAt
  )

  return Complete-Installer -Process (
    Start-Installer -Destination $Destination -StateRoot $StateRoot -HardExitAt $HardExitAt
  )
}

function Assert-Succeeded {
  param(
    [object]$Result,
    [string]$Context
  )

  if ($Result.ExitCode -ne 0) {
    throw "$Context failed with $($Result.ExitCode): $($Result.StdOut)`n$($Result.StdErr)"
  }
}

function Assert-OwnedInstall {
  param(
    [string]$Destination,
    [string]$StateRoot
  )

  $target = Join-Path $Destination "luming-phone-agent"
  $marker = Join-Path $target ".loom-skill-owner.json"
  $state = Join-Path $StateRoot "install-state.json"
  if (-not (Test-Path -LiteralPath $marker -PathType Leaf)) {
    throw "Installed Skill has no LOOM ownership marker"
  }
  if (-not (Test-Path -LiteralPath $state -PathType Leaf)) {
    throw "Installer has no durable ownership state"
  }
  $markerDocument = Get-Content -Raw -Encoding UTF8 -LiteralPath $marker | ConvertFrom-Json
  $stateDocument = Get-Content -Raw -Encoding UTF8 -LiteralPath $state | ConvertFrom-Json
  if ($markerDocument.schema -cne "loom.skills.owner.v1") {
    throw "Installed Skill ownership marker schema is invalid"
  }
  if ($stateDocument.schema -cne "loom.skills.install_state.v1") {
    throw "Installer state schema is invalid"
  }
  if ([string]$markerDocument.installId -cne [string]$stateDocument.installId) {
    throw "Ownership marker and installer state disagree"
  }
}

try {
  New-Item -ItemType Directory -Force -Path $tempRoot | Out-Null

  $destination = Join-Path $tempRoot "protected-destination"
  $stateRoot = Join-Path $tempRoot "protected-state"
  $thirdParty = Join-Path $destination "phone-agent"
  New-Item -ItemType Directory -Force -Path $thirdParty | Out-Null
  [IO.File]::WriteAllText((Join-Path $thirdParty "SKILL.md"), "third party phone agent", $utf8)
  [IO.File]::WriteAllText((Join-Path $thirdParty "keep.txt"), "must survive", $utf8)

  $first = Invoke-Installer -Destination $destination -StateRoot $stateRoot
  Assert-Succeeded -Result $first -Context "First protected install"
  if (-not (Test-Path -LiteralPath (Join-Path $thirdParty "keep.txt") -PathType Leaf)) {
    throw "Installer removed an unowned same-name Skill"
  }
  $firstDocument = $first.StdOut | ConvertFrom-Json
  if (@($firstDocument.skippedUnowned) -cnotcontains "phone-agent") {
    throw "Installer did not report the unowned replacement it preserved"
  }
  Assert-OwnedInstall -Destination $destination -StateRoot $stateRoot

  $installedRecipe = Join-Path $destination "luming-phone-agent\recipes\customer-route\recipe.json"
  New-Item -ItemType Directory -Force -Path (Split-Path -Parent $installedRecipe) | Out-Null
  [IO.File]::WriteAllText($installedRecipe, '{"recipeId":"customer-route","note":"keep me"}', $utf8)
  $second = Invoke-Installer -Destination $destination -StateRoot $stateRoot
  Assert-Succeeded -Result $second -Context "Recipe-preserving upgrade"
  if ((Get-Content -Raw -Encoding UTF8 -LiteralPath $installedRecipe) -notmatch "keep me") {
    throw "Upgrade discarded an installed recipe"
  }
  $durableRecipe = Join-Path $stateRoot "source\luming-phone-agent\recipes\customer-route\recipe.json"
  if (-not (Test-Path -LiteralPath $durableRecipe -PathType Leaf)) {
    throw "Upgrade did not preserve recipes in the durable source mirror"
  }

  $unownedDestination = Join-Path $tempRoot "unowned-unified-destination"
  $unownedState = Join-Path $tempRoot "unowned-unified-state"
  $unownedUnified = Join-Path $unownedDestination "luming-phone-agent"
  New-Item -ItemType Directory -Force -Path $unownedUnified | Out-Null
  [IO.File]::WriteAllText((Join-Path $unownedUnified "SKILL.md"), "unowned unified", $utf8)
  $unownedAttempt = Invoke-Installer -Destination $unownedDestination -StateRoot $unownedState
  if ($unownedAttempt.ExitCode -eq 0) {
    throw "Installer overwrote an unowned luming-phone-agent directory"
  }
  if ((Get-Content -Raw -Encoding UTF8 -LiteralPath (Join-Path $unownedUnified "SKILL.md")) -cne "unowned unified") {
    throw "Rejected unowned target was mutated"
  }

  $concurrentDestination = Join-Path $tempRoot "concurrent-destination"
  $concurrentState = Join-Path $tempRoot "concurrent-state"
  $processOne = Start-Installer -Destination $concurrentDestination -StateRoot $concurrentState
  $processTwo = Start-Installer -Destination $concurrentDestination -StateRoot $concurrentState
  $concurrentOne = Complete-Installer -Process $processOne
  $concurrentTwo = Complete-Installer -Process $processTwo
  Assert-Succeeded -Result $concurrentOne -Context "Concurrent installer one"
  Assert-Succeeded -Result $concurrentTwo -Context "Concurrent installer two"
  Assert-OwnedInstall -Destination $concurrentDestination -StateRoot $concurrentState

  $crashRecipe = Join-Path $destination "luming-phone-agent\recipes\crash-safe\recipe.json"
  New-Item -ItemType Directory -Force -Path (Split-Path -Parent $crashRecipe) | Out-Null
  [IO.File]::WriteAllText($crashRecipe, '{"recipeId":"crash-safe","note":"recover me"}', $utf8)
  $crashed = Invoke-Installer `
    -Destination $destination `
    -StateRoot $stateRoot `
    -HardExitAt "after-managed-backup"
  if ($crashed.ExitCode -eq 0) {
    throw "Hard-exit injection unexpectedly completed"
  }
  $recovered = Invoke-Installer -Destination $destination -StateRoot $stateRoot
  Assert-Succeeded -Result $recovered -Context "Post-crash recovery install"
  if ((Get-Content -Raw -Encoding UTF8 -LiteralPath $crashRecipe) -notmatch "recover me") {
    throw "Post-crash recovery lost an installed recipe"
  }
  if (Test-Path -LiteralPath (Join-Path $stateRoot "install-transaction.json")) {
    throw "Successful recovery left a persistent transaction journal"
  }

  Write-Output "luming skills install hardening contract ok"
} finally {
  if (Test-Path -LiteralPath $tempRoot -PathType Container) {
    Remove-Item -LiteralPath $tempRoot -Recurse -Force
  }
}
