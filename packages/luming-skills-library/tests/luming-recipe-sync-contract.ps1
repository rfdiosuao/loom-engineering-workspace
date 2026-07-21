$ErrorActionPreference = "Stop"
$env:PYTHONDONTWRITEBYTECODE = "1"

$repoRoot = Split-Path -Parent $PSScriptRoot
$scriptPath = Join-Path $repoRoot "skills\luming-phone-agent\scripts\sync_recipe.py"
$recipeSchemaPath = Join-Path $repoRoot "skills\luming-phone-agent\schemas\recipe.schema.json"
$indexSchemaPath = Join-Path $repoRoot "skills\luming-phone-agent\schemas\recipe-index.schema.json"
$tempRoot = Join-Path ([IO.Path]::GetTempPath()) ("luming-recipe-sync-" + [guid]::NewGuid().ToString("N"))
$utf8NoBom = [Text.UTF8Encoding]::new($false)
$reparsePaths = [Collections.Generic.List[string]]::new()

function Write-JsonFile {
  param([string]$Path, [object]$Document)
  $parent = Split-Path -Parent $Path
  if ($parent) { New-Item -ItemType Directory -Force -Path $parent | Out-Null }
  [IO.File]::WriteAllText($Path, ($Document | ConvertTo-Json -Depth 30), $utf8NoBom)
}

function New-Evidence {
  param(
    [string]$Reference,
    [string]$Type = "screenshot",
    [string]$Predicate = "visible",
    [string]$Subject = "target-page",
    [bool]$Expected = $true
  )
  return [ordered]@{
    type = $Type
    reference = $Reference
    assertion = [ordered]@{
      predicate = $Predicate
      subject = $Subject
      expected = $Expected
    }
  }
}

function New-Recipe {
  param(
    [string]$RecipeId,
    [string]$Status = "verified",
    [int]$SuccessCount = 1,
    [string]$StepVerification = "verified",
    [object[]]$Evidence,
    [switch]$Sensitive
  )

  if (-not $PSBoundParameters.ContainsKey("Evidence")) {
    $Evidence = @(
      (New-Evidence -Reference "screen-before-001" -Subject "target-entry-page"),
      (New-Evidence -Reference "screen-after-002" -Subject "expected-result")
    )
  }

  $recipe = [ordered]@{
    schema = "loom.phone-agent.recipe.v1"
    recipeId = $RecipeId
    name = "Contract recipe $RecipeId"
    aliases = @("contract $RecipeId")
    status = $Status
    app = [ordered]@{
      packageName = "com.example.contract"
      versionRange = ">=1.0.0"
      entryPage = "home"
    }
    goal = "Verify recipe synchronization"
    mode = "single"
    prerequisites = @("one healthy phone")
    steps = @(
      [ordered]@{
        stepId = "open-target"
        action = "Open the target page"
        requiresConfirmation = $false
        verification = $StepVerification
        evidence = $Evidence
        pageFingerprint = "page:contract:v1"
      }
    )
    safety = [ordered]@{
      requiresHumanReview = $true
      stopBefore = @("outbound action")
    }
    verification = [ordered]@{
      successCount = $SuccessCount
      lastSuccessfulRun = "2026-07-15T00:00:00Z"
    }
    source = [ordered]@{
      kind = "observed"
      deviceId = "device-contract-001"
      pageFingerprint = "page:contract:v1"
    }
  }

  if ($Sensitive) {
    $recipe.password = "never-persist"
    $recipe.passcode = "112233"
    $recipe.token = "token-value"
    $recipe.secret = "secret-value"
    $recipe.captcha = "captcha-value"
    $recipe.otp = "654321"
    $recipe.verificationCode = "887766"
    $recipe.phoneNumber = "13800138000"
    $recipe.email = "owner@example.com"
    $recipe.wechat = "wechat-id"
    $recipe.idCard = "110101199001011234"
  }
  return $recipe
}

function Get-TreeSnapshot {
  param([string]$Root)
  if (-not (Test-Path -LiteralPath $Root)) { return "<missing>" }
  $rootPath = (Resolve-Path -LiteralPath $Root).Path
  $entries = Get-ChildItem -LiteralPath $Root -Recurse -Force | Sort-Object FullName
  return (($entries | ForEach-Object {
    $relative = $_.FullName.Substring($rootPath.Length).TrimStart('\')
    if ($_.PSIsContainer) { "D|$relative" } else { "F|$relative|$((Get-FileHash -Algorithm SHA256 -LiteralPath $_.FullName).Hash)" }
  }) -join "`n")
}

function Invoke-Sync {
  param(
    [string]$RecipeFile,
    [string]$SourceRoot,
    [string]$InstalledRoot,
    [string]$StateRoot
  )
  $stderrPath = Join-Path $tempRoot ("stderr-" + [guid]::NewGuid().ToString("N") + ".txt")
  $stdout = @(& python $scriptPath --recipe-file $RecipeFile --source-skill-root $SourceRoot --installed-skill-root $InstalledRoot --state-root $StateRoot 2> $stderrPath)
  $exitCode = $LASTEXITCODE
  $stderr = if (Test-Path -LiteralPath $stderrPath) { Get-Content -Raw -LiteralPath $stderrPath } else { "" }
  if ($stdout.Count -eq 0) {
    throw "Synchronizer emitted no JSON (exit $exitCode): $stderr"
  }
  try {
    $result = ($stdout -join "`n") | ConvertFrom-Json
  } catch {
    throw "Synchronizer emitted invalid JSON (exit $exitCode): $($stdout -join "`n")`n$stderr"
  }
  return [pscustomobject]@{ ExitCode = $exitCode; Result = $result; Stderr = $stderr }
}

function Start-SyncChild {
  param([string[]]$Arguments)
  $startInfo = [Diagnostics.ProcessStartInfo]::new()
  $startInfo.FileName = "python"
  $startInfo.Arguments = (($Arguments | ForEach-Object { '"' + $_.Replace('"', '\"') + '"' }) -join " ")
  $startInfo.UseShellExecute = $false
  $startInfo.CreateNoWindow = $true
  $startInfo.RedirectStandardOutput = $true
  $startInfo.RedirectStandardError = $true
  $process = [Diagnostics.Process]::new()
  $process.StartInfo = $startInfo
  if (-not $process.Start()) { throw "Failed to start concurrent synchronizer" }
  return $process
}

function Assert-SyncHashes {
  param([object]$Result, [string]$Context)
  foreach ($pair in @(
    @("sourceRecipeSha256", "installedRecipeSha256"),
    @("sourceIndexSha256", "installedIndexSha256")
  )) {
    $left = $Result.($pair[0])
    $right = $Result.($pair[1])
    if (-not $left -or $left -cne $right) {
      throw "$Context hash mismatch: $($pair[0])=$left, $($pair[1])=$right"
    }
  }
}

function Assert-RejectedWithoutMutation {
  param(
    [string]$Name,
    [object]$Recipe,
    [string]$SourceRoot,
    [string]$InstalledRoot,
    [string]$StateRoot
  )
  $recipeFile = Join-Path $tempRoot ("invalid-$Name.json")
  Write-JsonFile -Path $recipeFile -Document $Recipe
  $sourceBefore = Get-TreeSnapshot $SourceRoot
  $installedBefore = Get-TreeSnapshot $InstalledRoot
  $invocation = Invoke-Sync -RecipeFile $recipeFile -SourceRoot $SourceRoot -InstalledRoot $InstalledRoot -StateRoot $StateRoot
  if ($invocation.ExitCode -eq 0) { throw "$Name recipe unexpectedly exited 0" }
  if ($invocation.Result.status -cne "rejected") { throw "$Name recipe was not rejected" }
  if ((Get-TreeSnapshot $SourceRoot) -cne $sourceBefore) { throw "$Name recipe mutated the source target" }
  if ((Get-TreeSnapshot $InstalledRoot) -cne $installedBefore) { throw "$Name recipe mutated the installed target" }
}

function Get-PersistedText {
  param([string[]]$Roots)
  $text = @()
  foreach ($root in $Roots) {
    if (Test-Path -LiteralPath $root) {
      $text += Get-ChildItem -LiteralPath $root -Recurse -File -Force | ForEach-Object {
        Get-Content -Raw -Encoding UTF8 -LiteralPath $_.FullName
      }
    }
  }
  return ($text -join "`n")
}

function New-IndexEntry {
  param([object]$Recipe, [string]$Path)
  return [ordered]@{
    recipeId = $Recipe.recipeId
    name = $Recipe.name
    aliases = $Recipe.aliases
    status = $Recipe.status
    app = $Recipe.app
    goal = $Recipe.goal
    mode = $Recipe.mode
    path = $Path
    verification = $Recipe.verification
  }
}

function Set-IdenticalIndex {
  param([string]$SourceRoot, [string]$InstalledRoot, [object]$Index)
  $sourceIndex = Join-Path $SourceRoot "recipes\index.json"
  $installedIndex = Join-Path $InstalledRoot "recipes\index.json"
  Write-JsonFile -Path $sourceIndex -Document $Index
  New-Item -ItemType Directory -Force -Path (Split-Path -Parent $installedIndex) | Out-Null
  Copy-Item -LiteralPath $sourceIndex -Destination $installedIndex -Force
}

function Assert-PendingWithoutMutation {
  param(
    [string]$Name,
    [object]$Recipe,
    [string]$SourceRoot,
    [string]$InstalledRoot,
    [string]$StateRoot
  )
  $recipeFile = Join-Path $tempRoot ("pending-$Name.json")
  Write-JsonFile -Path $recipeFile -Document $Recipe
  $sourceBefore = Get-TreeSnapshot $SourceRoot
  $installedBefore = Get-TreeSnapshot $InstalledRoot
  $invocation = Invoke-Sync -RecipeFile $recipeFile -SourceRoot $SourceRoot -InstalledRoot $InstalledRoot -StateRoot $StateRoot
  if ($invocation.ExitCode -eq 0 -or $invocation.Result.status -cne "sync_pending") {
    throw "$Name did not return nonzero sync_pending"
  }
  if ((Get-TreeSnapshot $SourceRoot) -cne $sourceBefore) { throw "$Name mutated the source target" }
  if ((Get-TreeSnapshot $InstalledRoot) -cne $installedBefore) { throw "$Name mutated the installed target" }
}

function Assert-UnindexedTargetPending {
  param(
    [string]$Name,
    [object]$Candidate,
    [AllowNull()][object]$SourceDocument,
    [AllowNull()][object]$InstalledDocument,
    [object]$Index,
    [string]$Marker = ""
  )
  $sourceRoot = Join-Path $tempRoot ("unindexed-$Name-source")
  $installedRoot = Join-Path $tempRoot ("unindexed-$Name-installed")
  $stateRoot = Join-Path $tempRoot ("unindexed-$Name-state")
  New-Item -ItemType Directory -Force -Path $sourceRoot, $installedRoot, $stateRoot | Out-Null
  Set-IdenticalIndex -SourceRoot $sourceRoot -InstalledRoot $installedRoot -Index $Index
  $relativeTarget = "recipes\$($Candidate.recipeId)\recipe.json"
  if ($null -ne $SourceDocument) {
    Write-JsonFile -Path (Join-Path $sourceRoot $relativeTarget) -Document $SourceDocument
  }
  if ($null -ne $InstalledDocument) {
    Write-JsonFile -Path (Join-Path $installedRoot $relativeTarget) -Document $InstalledDocument
  }
  $candidateFile = Join-Path $tempRoot ("unindexed-$Name-candidate.json")
  Write-JsonFile -Path $candidateFile -Document $Candidate
  $sourceBefore = Get-TreeSnapshot $sourceRoot
  $installedBefore = Get-TreeSnapshot $installedRoot
  $invocation = Invoke-Sync -RecipeFile $candidateFile -SourceRoot $sourceRoot -InstalledRoot $installedRoot -StateRoot $stateRoot
  if ($invocation.ExitCode -eq 0 -or $invocation.Result.status -cne "sync_pending") {
    throw "$Name unindexed target did not return nonzero sync_pending"
  }
  if ((Get-TreeSnapshot $sourceRoot) -cne $sourceBefore) { throw "$Name unindexed target mutated source" }
  if ((Get-TreeSnapshot $installedRoot) -cne $installedBefore) { throw "$Name unindexed target mutated installed" }
  $transactionPath = [string]$invocation.Result.transactionPath
  if (-not $transactionPath -or -not (Test-Path -LiteralPath $transactionPath)) {
    throw "$Name unindexed target did not preserve its transaction"
  }
  if (Test-Path -LiteralPath (Join-Path $transactionPath "candidate.index.json")) {
    throw "$Name persisted a candidate index before unindexed-target preflight"
  }
  if (Test-Path -LiteralPath (Join-Path $transactionPath "backup-manifest.json")) {
    throw "$Name created backups before unindexed-target preflight"
  }
  if ($Marker -and (Get-PersistedText -Roots @($stateRoot)).Contains($Marker)) {
    throw "$Name copied an unindexed target into transaction state"
  }
}

function Assert-UnindexedNonFilePending {
  param(
    [string]$Name,
    [ValidateSet("directory", "missing")][string]$InstalledKind,
    [object]$Index
  )
  $sourceRoot = Join-Path $tempRoot ("unindexed-nonfile-$Name-source")
  $installedRoot = Join-Path $tempRoot ("unindexed-nonfile-$Name-installed")
  $stateRoot = Join-Path $tempRoot ("unindexed-nonfile-$Name-state")
  New-Item -ItemType Directory -Force -Path $sourceRoot, $installedRoot, $stateRoot | Out-Null
  Set-IdenticalIndex -SourceRoot $sourceRoot -InstalledRoot $installedRoot -Index $Index
  $candidate = New-Recipe -RecipeId ("unindexed-nonfile-$Name")
  $relativeTarget = "recipes\$($candidate.recipeId)\recipe.json"
  New-Item -ItemType Directory -Force -Path (Join-Path $sourceRoot $relativeTarget) | Out-Null
  if ($InstalledKind -ceq "directory") {
    New-Item -ItemType Directory -Force -Path (Join-Path $installedRoot $relativeTarget) | Out-Null
  }
  $candidateFile = Join-Path $tempRoot ("unindexed-nonfile-$Name-candidate.json")
  Write-JsonFile -Path $candidateFile -Document $candidate
  $sourceBefore = Get-TreeSnapshot $sourceRoot
  $installedBefore = Get-TreeSnapshot $installedRoot
  $invocation = Invoke-Sync -RecipeFile $candidateFile -SourceRoot $sourceRoot -InstalledRoot $installedRoot -StateRoot $stateRoot
  if ($invocation.ExitCode -eq 0 -or $invocation.Result.status -cne "sync_pending") {
    throw "$Name non-file candidate target did not return nonzero sync_pending"
  }
  if ((Get-TreeSnapshot $sourceRoot) -cne $sourceBefore) { throw "$Name non-file target mutated source" }
  if ((Get-TreeSnapshot $installedRoot) -cne $installedBefore) { throw "$Name non-file target mutated installed" }
  $transactionPath = [string]$invocation.Result.transactionPath
  if (Test-Path -LiteralPath (Join-Path $transactionPath "candidate.index.json")) {
    throw "$Name non-file target persisted candidate.index.json"
  }
  if (Test-Path -LiteralPath (Join-Path $transactionPath "backup-manifest.json")) {
    throw "$Name non-file target created a backup manifest"
  }
}

function Assert-StateRootRejected {
  param(
    [string]$Name,
    [string]$SourceRoot,
    [string]$InstalledRoot,
    [string]$StateRoot
  )
  $recipeFile = Join-Path $tempRoot ("state-root-$Name.json")
  Write-JsonFile -Path $recipeFile -Document (New-Recipe -RecipeId "state-root-$Name")
  $sourceBefore = Get-TreeSnapshot $SourceRoot
  $installedBefore = Get-TreeSnapshot $InstalledRoot
  $stateBefore = Get-TreeSnapshot $StateRoot
  $invocation = Invoke-Sync -RecipeFile $recipeFile -SourceRoot $SourceRoot -InstalledRoot $InstalledRoot -StateRoot $StateRoot
  if ($invocation.ExitCode -eq 0 -or $invocation.Result.status -cne "rejected") { throw "$Name state root was not rejected" }
  if ((Get-TreeSnapshot $SourceRoot) -cne $sourceBefore) { throw "$Name state root mutated source" }
  if ((Get-TreeSnapshot $InstalledRoot) -cne $installedBefore) { throw "$Name state root mutated installed" }
  if ((Get-TreeSnapshot $StateRoot) -cne $stateBefore) { throw "$Name state root mutated state before rejection" }
}

function Wait-ForPaths {
  param([string[]]$Paths, [int]$TimeoutMilliseconds = 10000)
  $deadline = [DateTime]::UtcNow.AddMilliseconds($TimeoutMilliseconds)
  while ([DateTime]::UtcNow -lt $deadline) {
    if (@($Paths | Where-Object { -not (Test-Path -LiteralPath $_) }).Count -eq 0) { return }
    Start-Sleep -Milliseconds 25
  }
  throw "Timed out waiting for paths: $($Paths -join ', ')"
}

New-Item -ItemType Directory -Force -Path $tempRoot | Out-Null
try {
  foreach ($required in @($scriptPath, $recipeSchemaPath, $indexSchemaPath)) {
    if (-not (Test-Path -LiteralPath $required)) { throw "Missing Task 2 artifact: $required" }
  }

  $environmentOutput = & python $scriptPath --check-environment 2>&1
  if ($LASTEXITCODE -ne 0) { throw "Environment check exited ${LASTEXITCODE}: $($environmentOutput -join "`n")" }
  $environment = $environmentOutput -join "`n" | ConvertFrom-Json
  if ($environment.schema -cne "loom.phone-agent.environment-check.v1" -or
      $environment.status -cne "ready" -or
      -not $environment.pythonVersion -or
      -not $environment.jsonschemaVersion -or
      $environment.recipeSchema -cne "valid" -or
      $environment.indexSchema -cne "valid") {
    throw "Environment check did not report a complete ready result"
  }

  $previousErrorActionPreference = $ErrorActionPreference
  $ErrorActionPreference = "Continue"
  $missingDependencyOutput = @(& python -S $scriptPath --check-environment 2>&1)
  $missingDependencyExitCode = $LASTEXITCODE
  $ErrorActionPreference = $previousErrorActionPreference
  if ($missingDependencyExitCode -eq 0) { throw "Environment check unexpectedly passed without site packages" }
  $missingDependency = $missingDependencyOutput -join "`n" | ConvertFrom-Json
  if ($missingDependency.schema -cne "loom.phone-agent.environment-check.v1" -or
      $missingDependency.status -cne "blocked" -or
      -not $missingDependency.error -or
      -not $missingDependency.error.Contains("jsonschema")) {
    throw "Environment check did not emit a structured blocked result for missing jsonschema"
  }

  $missingDependencyRecipe = Join-Path $tempRoot "missing-jsonschema.json"
  Write-JsonFile -Path $missingDependencyRecipe -Document @{}
  $missingDependencySource = Join-Path $tempRoot "missing-jsonschema-source"
  $missingDependencyInstalled = Join-Path $tempRoot "missing-jsonschema-installed"
  $missingDependencyState = Join-Path $tempRoot "missing-jsonschema-state"
  New-Item -ItemType Directory -Force -Path $missingDependencySource, $missingDependencyInstalled, $missingDependencyState | Out-Null
  $previousErrorActionPreference = $ErrorActionPreference
  $ErrorActionPreference = "Continue"
  $missingSyncOutput = @(& python -S $scriptPath --recipe-file $missingDependencyRecipe --source-skill-root $missingDependencySource --installed-skill-root $missingDependencyInstalled --state-root $missingDependencyState 2>&1)
  $missingSyncExitCode = $LASTEXITCODE
  $ErrorActionPreference = $previousErrorActionPreference
  if ($missingSyncExitCode -eq 0) { throw "Recipe sync unexpectedly passed without jsonschema" }
  $missingSync = $missingSyncOutput -join "`n" | ConvertFrom-Json
  if ($missingSync.schema -cne "loom.phone-agent.recipe-sync.v1" -or
      $missingSync.status -cne "rejected" -or
      -not $missingSync.error -or
      -not $missingSync.error.Contains("jsonschema dependency is unavailable")) {
    throw "Recipe sync did not emit a structured missing-jsonschema rejection"
  }

  $singleSource = Join-Path $tempRoot "single-source"
  $singleInstalled = Join-Path $tempRoot "single-installed"
  $singleState = Join-Path $tempRoot "single-state"
  New-Item -ItemType Directory -Force -Path $singleSource, $singleInstalled, $singleState | Out-Null
  $singleFile = Join-Path $tempRoot "single.json"
  Write-JsonFile -Path $singleFile -Document (New-Recipe -RecipeId "privacy-contract" -Sensitive)

  $single = Invoke-Sync -RecipeFile $singleFile -SourceRoot $singleSource -InstalledRoot $singleInstalled -StateRoot $singleState
  if ($single.ExitCode -ne 0) { throw "Valid recipe exited $($single.ExitCode): $($single.Stderr)" }
  if ($single.Result.schema -cne "loom.phone-agent.recipe-sync.v1") { throw "Sync result schema is incorrect" }
  if ($single.Result.status -cne "synced") { throw "Recipe did not sync" }
  if (-not $single.Result.transactionPath -or -not (Test-Path -LiteralPath $single.Result.transactionPath)) {
    throw "Sync transaction was not preserved"
  }

  $sourceRecipe = Join-Path $singleSource "recipes\privacy-contract\recipe.json"
  $installedRecipe = Join-Path $singleInstalled "recipes\privacy-contract\recipe.json"
  $sourceIndex = Join-Path $singleSource "recipes\index.json"
  $installedIndex = Join-Path $singleInstalled "recipes\index.json"
  $sourceText = Get-Content -Raw -Encoding UTF8 -LiteralPath $sourceRecipe
  if ($sourceText -match '(?i)password|passcode|token|secret|captcha|otp|verificationCode|phoneNumber|email|wechat|idCard|138\d{8}|owner@example\.com') {
    throw "Sensitive data persisted"
  }
  foreach ($preserved in @("device-contract-001", "page:contract:v1")) {
    if (-not $sourceText.Contains($preserved)) { throw "Non-secret fingerprint was removed: $preserved" }
  }
  if (($single.Result.redactions | Measure-Object).Count -lt 11) { throw "Redactions were not reported" }
  if ((Get-FileHash $sourceRecipe).Hash -cne (Get-FileHash $installedRecipe).Hash) {
    throw "Source and installed recipe hashes differ"
  }
  if ((Get-FileHash $sourceIndex).Hash -cne (Get-FileHash $installedIndex).Hash) {
    throw "Source and installed index hashes differ"
  }
  Assert-SyncHashes -Result $single.Result -Context "Single sync"

  $allowedSource = Join-Path $tempRoot "allowed-string-source"
  $allowedInstalled = Join-Path $tempRoot "allowed-string-installed"
  $allowedState = Join-Path $tempRoot "allowed-string-state"
  New-Item -ItemType Directory -Force -Path $allowedSource, $allowedInstalled, $allowedState | Out-Null
  $allowedRecipe = New-Recipe -RecipeId "allowed-string-privacy"
  $allowedRecipe.name = "password: AllowedSecretName"
  $allowedRecipe.aliases = @("password: AllowedSecretAlias")
  $allowedRecipe.app.packageName = "password: AllowedSecretPackage"
  $allowedRecipe.app.versionRange = "password: AllowedSecretVersion"
  $allowedRecipe.app.entryPage = "password: AllowedSecretEntry"
  $allowedRecipe.goal = "password: AllowedSecretGoal"
  $allowedRecipe.prerequisites = @("password: AllowedSecretPrerequisite")
  $allowedRecipe.steps[0].action = "password: AllowedSecretAction"
  $allowedRecipe.steps[0].evidence = @(
    (New-Evidence -Reference "allowed-secret-evidence" -Subject "allowed-secret-evidence")
  )
  $allowedRecipe.steps[0].pageFingerprint = "password: AllowedSecretStepFingerprint"
  $allowedRecipe.safety.stopBefore = @("password: AllowedSecretSafety")
  $allowedRecipe.source.deviceId = "password: AllowedSecretDevice"
  $allowedRecipe.source.pageFingerprint = "password: AllowedSecretSourceFingerprint"
  $allowedFile = Join-Path $tempRoot "allowed-string-privacy.json"
  Write-JsonFile -Path $allowedFile -Document $allowedRecipe
  $allowedSync = Invoke-Sync -RecipeFile $allowedFile -SourceRoot $allowedSource -InstalledRoot $allowedInstalled -StateRoot $allowedState
  if ($allowedSync.ExitCode -eq 0 -or $allowedSync.Result.status -cne "rejected") { throw "Allowed-string privacy recipe was not rejected" }
  $allowedPersisted = Get-PersistedText -Roots @($allowedSource, $allowedInstalled, $allowedState)
  if ($allowedPersisted -match '(?i)AllowedSecret|password\s*:') { throw "A schema-allowed string bypassed recursive privacy filtering" }

  $classSource = Join-Path $tempRoot "privacy-class-source"
  $classInstalled = Join-Path $tempRoot "privacy-class-installed"
  $classState = Join-Path $tempRoot "privacy-class-state"
  New-Item -ItemType Directory -Force -Path $classSource, $classInstalled, $classState | Out-Null
  $privacyBypasses = @(
    @{ Name = "session-token"; Value = "session token: SessionTokenABC123"; Marker = "SessionTokenABC123" },
    @{ Name = "access-token"; Value = "access token is AccessTokenABC123"; Marker = "AccessTokenABC123" },
    @{ Name = "api-token"; Value = "API token: ApiTokenABC123"; Marker = "ApiTokenABC123" },
    @{ Name = "verification-code"; Value = "verification code: A1B2C3"; Marker = "A1B2C3" },
    @{ Name = "login-password"; Value = "login password: LoginPasswordABC123"; Marker = "LoginPasswordABC123" },
    @{ Name = "formatted-phone"; Value = "phone: (415) 555-2671"; Marker = "(415) 555-2671" },
    @{ Name = "international-phone"; Value = "phone: +44 20 7946 0958"; Marker = "+44 20 7946 0958" },
    @{ Name = "wechat-id"; Value = "WeChat ID is wxid_privacy_contract"; Marker = "wxid_privacy_contract" },
    @{ Name = "contact-id"; Value = "contact identifier: signal-user-private"; Marker = "signal-user-private" },
    @{ Name = "jwt"; Value = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJwcml2YWN5In0.PrivacyJwtSignature123"; Marker = "PrivacyJwtSignature123" },
    @{ Name = "id-card"; Value = "110101199001011234"; Marker = "110101199001011234" },
    @{ Name = "resume-sections"; Value = "Employment History: five years. Academic Background: university."; Marker = "Employment History" }
  )
  foreach ($privacyCase in $privacyBypasses) {
    $classRecipe = New-Recipe -RecipeId ("privacy-" + $privacyCase.Name)
    $classRecipe.steps[0].action = $privacyCase.Value
    Assert-RejectedWithoutMutation -Name ("allowed-" + $privacyCase.Name) -Recipe $classRecipe -SourceRoot $classSource -InstalledRoot $classInstalled -StateRoot $classState
    $classPersisted = Get-PersistedText -Roots @($classSource, $classInstalled, $classState)
    if ($classPersisted.Contains($privacyCase.Marker)) { throw "Prohibited privacy class persisted: $($privacyCase.Name)" }
  }

  $exactPrivacyBypasses = @(
    @{ Name = "auth-token-exact"; Value = "auth token: AuthTokenABC123"; Marker = "AuthTokenABC123" },
    @{ Name = "password-space-exact"; Value = "password Hunter2!"; Marker = "Hunter2!" },
    @{ Name = "call-phone-exact"; Value = "call 4155552671"; Marker = "4155552671" }
  )
  foreach ($privacyCase in $exactPrivacyBypasses) {
    $exactRecipe = New-Recipe -RecipeId ("privacy-" + $privacyCase.Name)
    $exactRecipe.steps[0].action = $privacyCase.Value
    Assert-RejectedWithoutMutation -Name $privacyCase.Name -Recipe $exactRecipe -SourceRoot $classSource -InstalledRoot $classInstalled -StateRoot $classState
    $exactPersisted = Get-PersistedText -Roots @($classSource, $classInstalled, $classState)
    if ($exactPersisted.Contains($privacyCase.Marker)) { throw "Exact privacy bypass persisted: $($privacyCase.Name)" }
  }

  $uiPrivacySource = Join-Path $tempRoot "privacy-ui-source"
  $uiPrivacyInstalled = Join-Path $tempRoot "privacy-ui-installed"
  $uiPrivacyState = Join-Path $tempRoot "privacy-ui-state"
  New-Item -ItemType Directory -Force -Path $uiPrivacySource, $uiPrivacyInstalled, $uiPrivacyState | Out-Null
  $uiPrivacyPairs = @(
    @{ Name = "password-field"; Benign = "password field"; Punctuated = "password field."; Secret = "password Hunter2!"; Marker = "Hunter2!"; Tail = "password field, Hunter2!"; TailMarker = "Hunter2!" },
    @{ Name = "password-screen"; Benign = "password screen"; Punctuated = "password screen!"; Secret = "password ScreenValue9!"; Marker = "ScreenValue9!"; Tail = "password screen. ScreenValue9!"; TailMarker = "ScreenValue9!" },
    @{ Name = "secret-settings"; Benign = "secret settings"; Punctuated = "secret settings?"; Secret = "secret SettingsValue9!"; Marker = "SettingsValue9!"; Tail = "secret settings; SettingsValue9!"; TailMarker = "SettingsValue9!" }
  )
  foreach ($privacyPair in $uiPrivacyPairs) {
    $tailRecipe = New-Recipe -RecipeId ("tail-" + $privacyPair.Name)
    $tailRecipe.steps[0].action = $privacyPair.Tail
    Assert-RejectedWithoutMutation -Name ("punctuation-tail-" + $privacyPair.Name) -Recipe $tailRecipe -SourceRoot $uiPrivacySource -InstalledRoot $uiPrivacyInstalled -StateRoot $uiPrivacyState
    if ((Get-PersistedText -Roots @($uiPrivacySource, $uiPrivacyInstalled, $uiPrivacyState)).Contains($privacyPair.TailMarker)) {
      throw "Punctuation-tail secret persisted: $($privacyPair.Name)"
    }

    $benignRecipe = New-Recipe -RecipeId ("benign-" + $privacyPair.Name)
    $benignRecipe.steps[0].action = $privacyPair.Benign
    $benignFile = Join-Path $tempRoot ("benign-" + $privacyPair.Name + ".json")
    Write-JsonFile -Path $benignFile -Document $benignRecipe
    $benignSync = Invoke-Sync -RecipeFile $benignFile -SourceRoot $uiPrivacySource -InstalledRoot $uiPrivacyInstalled -StateRoot $uiPrivacyState
    if ($benignSync.ExitCode -ne 0 -or $benignSync.Result.status -cne "synced") {
      throw "Benign UI description was rejected: $($privacyPair.Benign)"
    }
    $benignPersisted = Get-Content -Raw -Encoding UTF8 -LiteralPath (Join-Path $uiPrivacySource "recipes\$($benignRecipe.recipeId)\recipe.json") | ConvertFrom-Json
    if ($benignPersisted.steps[0].action -cne $privacyPair.Benign) { throw "Benign UI description was not preserved" }

    $punctuatedRecipe = New-Recipe -RecipeId ("punctuated-" + $privacyPair.Name)
    $punctuatedRecipe.steps[0].action = $privacyPair.Punctuated
    $punctuatedFile = Join-Path $tempRoot ("punctuated-" + $privacyPair.Name + ".json")
    Write-JsonFile -Path $punctuatedFile -Document $punctuatedRecipe
    $punctuatedSync = Invoke-Sync -RecipeFile $punctuatedFile -SourceRoot $uiPrivacySource -InstalledRoot $uiPrivacyInstalled -StateRoot $uiPrivacyState
    if ($punctuatedSync.ExitCode -ne 0 -or $punctuatedSync.Result.status -cne "synced") {
      throw "Terminal-punctuation UI description was rejected: $($privacyPair.Punctuated)"
    }
    $punctuatedPersisted = Get-Content -Raw -Encoding UTF8 -LiteralPath (Join-Path $uiPrivacySource "recipes\$($punctuatedRecipe.recipeId)\recipe.json") | ConvertFrom-Json
    if ($punctuatedPersisted.steps[0].action -cne $privacyPair.Punctuated) { throw "Terminal-punctuation UI description was not preserved" }

    $secretRecipe = New-Recipe -RecipeId ("secret-" + $privacyPair.Name)
    $secretRecipe.steps[0].action = $privacyPair.Secret
    Assert-RejectedWithoutMutation -Name ("value-like-" + $privacyPair.Name) -Recipe $secretRecipe -SourceRoot $uiPrivacySource -InstalledRoot $uiPrivacyInstalled -StateRoot $uiPrivacyState
    if ((Get-PersistedText -Roots @($uiPrivacySource, $uiPrivacyInstalled, $uiPrivacyState)).Contains($privacyPair.Marker)) {
      throw "Value-like secret persisted: $($privacyPair.Name)"
    }
  }

  $narrativeSource = Join-Path $tempRoot "privacy-narrative-source"
  $narrativeInstalled = Join-Path $tempRoot "privacy-narrative-installed"
  $narrativeState = Join-Path $tempRoot "privacy-narrative-state"
  New-Item -ItemType Directory -Force -Path $narrativeSource, $narrativeInstalled, $narrativeState | Out-Null
  $resumeNarrative = New-Recipe -RecipeId "raw-resume-narrative"
  $resumeNarrative.steps[0].action = "Work Experience: five years. Education: complete university history."
  Assert-RejectedWithoutMutation -Name "raw-resume-string" -Recipe $resumeNarrative -SourceRoot $narrativeSource -InstalledRoot $narrativeInstalled -StateRoot $narrativeState
  $personalNarrative = New-Recipe -RecipeId "unrelated-personal-narrative"
  $personalNarrative.steps[0].action = "date of birth: 1990-01-01"
  Assert-RejectedWithoutMutation -Name "unrelated-personal-string" -Recipe $personalNarrative -SourceRoot $narrativeSource -InstalledRoot $narrativeInstalled -StateRoot $narrativeState

  $concurrentSource = Join-Path $tempRoot "concurrent-source"
  $concurrentInstalled = Join-Path $tempRoot "concurrent-installed"
  $concurrentState = Join-Path $tempRoot "concurrent-state"
  New-Item -ItemType Directory -Force -Path $concurrentSource, $concurrentInstalled, $concurrentState | Out-Null
  $concurrentA = Join-Path $tempRoot "concurrent-a.json"
  $concurrentB = Join-Path $tempRoot "concurrent-b.json"
  Write-JsonFile -Path $concurrentA -Document (New-Recipe -RecipeId "concurrent-a")
  Write-JsonFile -Path $concurrentB -Document (New-Recipe -RecipeId "concurrent-b")
  $argumentsA = @($scriptPath, "--recipe-file", $concurrentA, "--source-skill-root", $concurrentSource, "--installed-skill-root", $concurrentInstalled, "--state-root", $concurrentState)
  $argumentsB = @($scriptPath, "--recipe-file", $concurrentB, "--source-skill-root", $concurrentSource, "--installed-skill-root", $concurrentInstalled, "--state-root", $concurrentState)
  $processA = Start-SyncChild -Arguments $argumentsA
  $processB = Start-SyncChild -Arguments $argumentsB
  $stdoutAText = $processA.StandardOutput.ReadToEnd()
  $stderrAText = $processA.StandardError.ReadToEnd()
  $stdoutBText = $processB.StandardOutput.ReadToEnd()
  $stderrBText = $processB.StandardError.ReadToEnd()
  $processA.WaitForExit()
  $processB.WaitForExit()
  if ($processA.ExitCode -ne 0) { throw "Concurrent process A failed: stdout=$stdoutAText; stderr=$stderrAText" }
  if ($processB.ExitCode -ne 0) { throw "Concurrent process B failed: stdout=$stdoutBText; stderr=$stderrBText" }
  $resultA = $stdoutAText | ConvertFrom-Json
  $resultB = $stdoutBText | ConvertFrom-Json
  if ($resultA.status -cne "synced" -or $resultB.status -cne "synced") { throw "Concurrent recipes did not both sync" }
  $concurrentIndex = Get-Content -Raw -Encoding UTF8 (Join-Path $concurrentSource "recipes\index.json") | ConvertFrom-Json
  foreach ($recipeId in @("concurrent-a", "concurrent-b")) {
    if (@($concurrentIndex.recipes | Where-Object recipeId -CEQ $recipeId).Count -ne 1) {
      throw "$recipeId did not appear exactly once in the concurrent index"
    }
  }
  if ((Get-FileHash (Join-Path $concurrentSource "recipes\index.json")).Hash -cne (Get-FileHash (Join-Path $concurrentInstalled "recipes\index.json")).Hash) {
    throw "Concurrent source and installed indexes differ"
  }

  $pairSource = Join-Path $tempRoot "pair-lock-source"
  $pairInstalled = Join-Path $tempRoot "pair-lock-installed"
  $pairStateA = Join-Path $tempRoot "pair-lock-state-a"
  $pairStateB = Join-Path $tempRoot "pair-lock-state-b"
  New-Item -ItemType Directory -Force -Path $pairSource, $pairInstalled, $pairStateA, $pairStateB | Out-Null
  Set-IdenticalIndex -SourceRoot $pairSource -InstalledRoot $pairInstalled -Index ([ordered]@{ schema = "loom.phone-agent.recipe-index.v1"; recipes = @() })
  $pairRecipeA = Join-Path $tempRoot "pair-lock-a.json"
  $pairRecipeB = Join-Path $tempRoot "pair-lock-b.json"
  Write-JsonFile -Path $pairRecipeA -Document (New-Recipe -RecipeId "pair-lock-a")
  Write-JsonFile -Path $pairRecipeB -Document (New-Recipe -RecipeId "pair-lock-b")
  $pairProbePath = Join-Path $tempRoot "pair_lock_probe.py"
  $pairProbe = @'
import importlib.util
import json
import sys
import time
from pathlib import Path

script_path, recipe_path, source_root, installed_root, state_root, start_barrier, ready_path, marker_path, other_marker = map(Path, sys.argv[1:])
spec = importlib.util.spec_from_file_location("sync_recipe_pair_lock_contract", script_path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
real_update_index = module.update_index

def barrier_update(index, recipe, relative_path):
    updated = real_update_index(index, recipe, relative_path)
    marker_path.write_text("ready", encoding="utf-8")
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline and not other_marker.exists():
        time.sleep(0.01)
    return updated

module.update_index = barrier_update
ready_path.write_text("ready", encoding="utf-8")
while not start_barrier.exists():
    time.sleep(0.01)
result = module.sync_recipe(module.load_json(recipe_path), source_root, installed_root, state_root)
print(json.dumps(result, ensure_ascii=False))
raise SystemExit(0 if result.get("status") == "synced" else 1)
'@
  [IO.File]::WriteAllText($pairProbePath, $pairProbe, $utf8NoBom)
  $pairStart = Join-Path $tempRoot "pair-lock-start"
  $pairReadyA = Join-Path $tempRoot "pair-lock-ready-a"
  $pairReadyB = Join-Path $tempRoot "pair-lock-ready-b"
  $pairMarkerA = Join-Path $tempRoot "pair-lock-marker-a"
  $pairMarkerB = Join-Path $tempRoot "pair-lock-marker-b"
  $pairProcessA = Start-SyncChild -Arguments @($pairProbePath, $scriptPath, $pairRecipeA, $pairSource, $pairInstalled, $pairStateA, $pairStart, $pairReadyA, $pairMarkerA, $pairMarkerB)
  $pairProcessB = Start-SyncChild -Arguments @($pairProbePath, $scriptPath, $pairRecipeB, $pairSource, $pairInstalled, $pairStateB, $pairStart, $pairReadyB, $pairMarkerB, $pairMarkerA)
  Wait-ForPaths -Paths @($pairReadyA, $pairReadyB)
  [IO.File]::WriteAllText($pairStart, "start", $utf8NoBom)
  $pairStdoutA = $pairProcessA.StandardOutput.ReadToEnd()
  $pairStderrA = $pairProcessA.StandardError.ReadToEnd()
  $pairStdoutB = $pairProcessB.StandardOutput.ReadToEnd()
  $pairStderrB = $pairProcessB.StandardError.ReadToEnd()
  $pairProcessA.WaitForExit()
  $pairProcessB.WaitForExit()
  if ($pairProcessA.ExitCode -ne 0) { throw "Pair-lock process A failed: $pairStdoutA $pairStderrA" }
  if ($pairProcessB.ExitCode -ne 0) { throw "Pair-lock process B failed: $pairStdoutB $pairStderrB" }
  $pairIndex = Get-Content -Raw -Encoding UTF8 (Join-Path $pairSource "recipes\index.json") | ConvertFrom-Json
  foreach ($recipeId in @("pair-lock-a", "pair-lock-b")) {
    if (@($pairIndex.recipes | Where-Object recipeId -CEQ $recipeId).Count -ne 1) {
      throw "Target-pair lock lost concurrent recipe $recipeId across different state roots"
    }
  }
  if ((Get-FileHash (Join-Path $pairSource "recipes\index.json")).Hash -cne (Get-FileHash (Join-Path $pairInstalled "recipes\index.json")).Hash) {
    throw "Target-pair lock left indexes out of parity"
  }

  $invalidSource = Join-Path $tempRoot "invalid-source"
  $invalidInstalled = Join-Path $tempRoot "invalid-installed"
  $invalidState = Join-Path $tempRoot "invalid-state"
  New-Item -ItemType Directory -Force -Path $invalidSource, $invalidInstalled, $invalidState | Out-Null
  Assert-RejectedWithoutMutation -Name "draft" -Recipe (New-Recipe -RecipeId "invalid-draft" -Status "draft") -SourceRoot $invalidSource -InstalledRoot $invalidInstalled -StateRoot $invalidState
  Assert-RejectedWithoutMutation -Name "zero-success" -Recipe (New-Recipe -RecipeId "invalid-zero" -SuccessCount 0) -SourceRoot $invalidSource -InstalledRoot $invalidInstalled -StateRoot $invalidState
  Assert-RejectedWithoutMutation -Name "unknown-step" -Recipe (New-Recipe -RecipeId "invalid-unknown" -StepVerification "unknown") -SourceRoot $invalidSource -InstalledRoot $invalidInstalled -StateRoot $invalidState
  Assert-RejectedWithoutMutation -Name "empty-evidence" -Recipe (New-Recipe -RecipeId "invalid-evidence" -Evidence @()) -SourceRoot $invalidSource -InstalledRoot $invalidInstalled -StateRoot $invalidState
  $unknownEvidenceType = New-Recipe -RecipeId "invalid-evidence-type"
  $unknownEvidenceType.steps[0].evidence = @(
    (New-Evidence -Reference "unknown-type-001" -Type "raw-text")
  )
  Assert-RejectedWithoutMutation -Name "unknown-evidence-type" -Recipe $unknownEvidenceType -SourceRoot $invalidSource -InstalledRoot $invalidInstalled -StateRoot $invalidState
  $longEvidenceReference = New-Recipe -RecipeId "invalid-evidence-reference"
  $longEvidenceReference.steps[0].evidence = @(
    (New-Evidence -Reference ("r" * 161))
  )
  Assert-RejectedWithoutMutation -Name "long-evidence-reference" -Recipe $longEvidenceReference -SourceRoot $invalidSource -InstalledRoot $invalidInstalled -StateRoot $invalidState
  $placeholderEvidence = New-Recipe -RecipeId "invalid-placeholder-evidence"
  $placeholderEvidence.steps[0].evidence = @(
    (New-Evidence -Reference "placeholder-001" -Subject "[REDACTED]")
  )
  Assert-RejectedWithoutMutation -Name "placeholder-evidence" -Recipe $placeholderEvidence -SourceRoot $invalidSource -InstalledRoot $invalidInstalled -StateRoot $invalidState
  $schemaInvalid = New-Recipe -RecipeId "invalid-schema"
  $schemaInvalid.Remove("name")
  Assert-RejectedWithoutMutation -Name "schema-invalid" -Recipe $schemaInvalid -SourceRoot $invalidSource -InstalledRoot $invalidInstalled -StateRoot $invalidState
  Assert-RejectedWithoutMutation -Name "unknown-status" -Recipe (New-Recipe -RecipeId "invalid-status" -Status "published") -SourceRoot $invalidSource -InstalledRoot $invalidInstalled -StateRoot $invalidState
  $invalidBoolean = New-Recipe -RecipeId "invalid-boolean"
  $invalidBoolean.steps[0].requiresConfirmation = "false"
  Assert-RejectedWithoutMutation -Name "non-boolean-confirmation" -Recipe $invalidBoolean -SourceRoot $invalidSource -InstalledRoot $invalidInstalled -StateRoot $invalidState
  Assert-RejectedWithoutMutation -Name "negative-success" -Recipe (New-Recipe -RecipeId "invalid-negative" -SuccessCount -1) -SourceRoot $invalidSource -InstalledRoot $invalidInstalled -StateRoot $invalidState
  $invalidDate = New-Recipe -RecipeId "invalid-date-time"
  $invalidDate.verification.lastSuccessfulRun = "not-a-date-time"
  Assert-RejectedWithoutMutation -Name "malformed-date-time" -Recipe $invalidDate -SourceRoot $invalidSource -InstalledRoot $invalidInstalled -StateRoot $invalidState
  $privacyInvalid = New-Recipe -RecipeId "invalid-privacy"
  $privacyInvalid.rawResume = "complete candidate resume"
  Assert-RejectedWithoutMutation -Name "privacy-invalid" -Recipe $privacyInvalid -SourceRoot $invalidSource -InstalledRoot $invalidInstalled -StateRoot $invalidState

  $paritySource = Join-Path $tempRoot "parity-source"
  $parityInstalled = Join-Path $tempRoot "parity-installed"
  $parityState = Join-Path $tempRoot "parity-state"
  New-Item -ItemType Directory -Force -Path $paritySource, $parityInstalled, $parityState | Out-Null
  $emptyIndex = [ordered]@{ schema = "loom.phone-agent.recipe-index.v1"; recipes = @() }
  Write-JsonFile -Path (Join-Path $paritySource "recipes\index.json") -Document $emptyIndex
  New-Item -ItemType Directory -Force -Path (Join-Path $parityInstalled "recipes") | Out-Null
  [IO.File]::WriteAllText((Join-Path $parityInstalled "recipes\index.json"), '{"schema":"loom.phone-agent.recipe-index.v1","recipes":[]}', $utf8NoBom)
  Assert-PendingWithoutMutation -Name "byte-divergent-indexes" -Recipe (New-Recipe -RecipeId "parity-recipe") -SourceRoot $paritySource -InstalledRoot $parityInstalled -StateRoot $parityState

  $invalidPairSource = Join-Path $tempRoot "invalid-pair-source"
  $invalidPairInstalled = Join-Path $tempRoot "invalid-pair-installed"
  $invalidPairState = Join-Path $tempRoot "invalid-pair-state"
  New-Item -ItemType Directory -Force -Path $invalidPairSource, $invalidPairInstalled, $invalidPairState | Out-Null
  Write-JsonFile -Path (Join-Path $invalidPairSource "recipes\index.json") -Document $emptyIndex
  New-Item -ItemType Directory -Force -Path (Join-Path $invalidPairInstalled "recipes") | Out-Null
  [IO.File]::WriteAllText((Join-Path $invalidPairInstalled "recipes\index.json"), '{"schema":"loom.phone-agent.recipe-index.v1","recipes":"invalid"}', $utf8NoBom)
  Assert-PendingWithoutMutation -Name "invalid-installed-index" -Recipe (New-Recipe -RecipeId "invalid-index-pair") -SourceRoot $invalidPairSource -InstalledRoot $invalidPairInstalled -StateRoot $invalidPairState

  $pathSource = Join-Path $tempRoot "canonical-path-source"
  $pathInstalled = Join-Path $tempRoot "canonical-path-installed"
  $pathState = Join-Path $tempRoot "canonical-path-state"
  New-Item -ItemType Directory -Force -Path $pathSource, $pathInstalled, $pathState | Out-Null
  $pathRecipeA = New-Recipe -RecipeId "path-alpha"
  $pathRecipeB = New-Recipe -RecipeId "path-beta"
  $badPathIndex = [ordered]@{
    schema = "loom.phone-agent.recipe-index.v1"
    recipes = @(
      (New-IndexEntry -Recipe $pathRecipeA -Path "recipes/path-alpha/recipe.json"),
      (New-IndexEntry -Recipe $pathRecipeB -Path "recipes/path-alpha/recipe.json")
    )
  }
  Set-IdenticalIndex -SourceRoot $pathSource -InstalledRoot $pathInstalled -Index $badPathIndex
  Assert-PendingWithoutMutation -Name "duplicate-noncanonical-path" -Recipe (New-Recipe -RecipeId "path-new") -SourceRoot $pathSource -InstalledRoot $pathInstalled -StateRoot $pathState

  $dirtyIndexSource = Join-Path $tempRoot "dirty-index-source"
  $dirtyIndexInstalled = Join-Path $tempRoot "dirty-index-installed"
  $dirtyIndexState = Join-Path $tempRoot "dirty-index-state"
  New-Item -ItemType Directory -Force -Path $dirtyIndexSource, $dirtyIndexInstalled, $dirtyIndexState | Out-Null
  $existingIndexRecipe = New-Recipe -RecipeId "existing-dirty-index"
  $dirtyIndexEntry = New-IndexEntry -Recipe $existingIndexRecipe -Path "recipes/existing-dirty-index/recipe.json"
  $dirtyIndexEntry.name = "login password: DirtyIndexSecretABC123"
  $dirtyIndexDocument = [ordered]@{ schema = "loom.phone-agent.recipe-index.v1"; recipes = @($dirtyIndexEntry) }
  Set-IdenticalIndex -SourceRoot $dirtyIndexSource -InstalledRoot $dirtyIndexInstalled -Index $dirtyIndexDocument
  $dirtyIndexSourceRecipe = Join-Path $dirtyIndexSource "recipes\existing-dirty-index\recipe.json"
  $dirtyIndexInstalledRecipe = Join-Path $dirtyIndexInstalled "recipes\existing-dirty-index\recipe.json"
  Write-JsonFile -Path $dirtyIndexSourceRecipe -Document $existingIndexRecipe
  New-Item -ItemType Directory -Force -Path (Split-Path -Parent $dirtyIndexInstalledRecipe) | Out-Null
  Copy-Item -LiteralPath $dirtyIndexSourceRecipe -Destination $dirtyIndexInstalledRecipe -Force
  Assert-PendingWithoutMutation -Name "dirty-existing-index" -Recipe (New-Recipe -RecipeId "after-dirty-index") -SourceRoot $dirtyIndexSource -InstalledRoot $dirtyIndexInstalled -StateRoot $dirtyIndexState
  if ((Get-PersistedText -Roots @($dirtyIndexState)).Contains("DirtyIndexSecretABC123")) { throw "Dirty existing index was copied into transaction state" }

  $dirtyRecipeSource = Join-Path $tempRoot "dirty-recipe-source"
  $dirtyRecipeInstalled = Join-Path $tempRoot "dirty-recipe-installed"
  $dirtyRecipeState = Join-Path $tempRoot "dirty-recipe-state"
  New-Item -ItemType Directory -Force -Path $dirtyRecipeSource, $dirtyRecipeInstalled, $dirtyRecipeState | Out-Null
  $cleanExistingRecipe = New-Recipe -RecipeId "existing-dirty-recipe"
  $cleanRecipeIndex = [ordered]@{
    schema = "loom.phone-agent.recipe-index.v1"
    recipes = @((New-IndexEntry -Recipe $cleanExistingRecipe -Path "recipes/existing-dirty-recipe/recipe.json"))
  }
  Set-IdenticalIndex -SourceRoot $dirtyRecipeSource -InstalledRoot $dirtyRecipeInstalled -Index $cleanRecipeIndex
  $dirtyExistingRecipe = New-Recipe -RecipeId "existing-dirty-recipe"
  $dirtyExistingRecipe.steps[0].action = "session token: DirtyRecipeTokenABC123"
  $dirtySourceRecipePath = Join-Path $dirtyRecipeSource "recipes\existing-dirty-recipe\recipe.json"
  $dirtyInstalledRecipePath = Join-Path $dirtyRecipeInstalled "recipes\existing-dirty-recipe\recipe.json"
  Write-JsonFile -Path $dirtySourceRecipePath -Document $dirtyExistingRecipe
  New-Item -ItemType Directory -Force -Path (Split-Path -Parent $dirtyInstalledRecipePath) | Out-Null
  Copy-Item -LiteralPath $dirtySourceRecipePath -Destination $dirtyInstalledRecipePath -Force
  Assert-PendingWithoutMutation -Name "dirty-existing-recipe" -Recipe (New-Recipe -RecipeId "after-dirty-recipe") -SourceRoot $dirtyRecipeSource -InstalledRoot $dirtyRecipeInstalled -StateRoot $dirtyRecipeState
  if ((Get-PersistedText -Roots @($dirtyRecipeState)).Contains("DirtyRecipeTokenABC123")) { throw "Dirty existing recipe was copied into transaction state" }

  Assert-UnindexedNonFilePending -Name "paired-directories" -InstalledKind "directory" -Index $emptyIndex
  Assert-UnindexedNonFilePending -Name "directory-plus-missing" -InstalledKind "missing" -Index $emptyIndex

  $unindexedDirtyCandidate = New-Recipe -RecipeId "unindexed-dirty"
  $unindexedDirtyExisting = New-Recipe -RecipeId "unindexed-dirty"
  $unindexedDirtyExisting.steps[0].action = "auth token: UnindexedDirtyTokenABC123"
  Assert-UnindexedTargetPending -Name "dirty" -Candidate $unindexedDirtyCandidate -SourceDocument $unindexedDirtyExisting -InstalledDocument $unindexedDirtyExisting -Index $emptyIndex -Marker "UnindexedDirtyTokenABC123"

  $unindexedOneSidedCandidate = New-Recipe -RecipeId "unindexed-one-sided"
  $unindexedOneSidedExisting = New-Recipe -RecipeId "unindexed-one-sided"
  Assert-UnindexedTargetPending -Name "one-sided" -Candidate $unindexedOneSidedCandidate -SourceDocument $unindexedOneSidedExisting -InstalledDocument $null -Index $emptyIndex

  $unindexedInvalidCandidate = New-Recipe -RecipeId "unindexed-schema-invalid"
  $unindexedInvalidExisting = New-Recipe -RecipeId "unindexed-schema-invalid"
  $unindexedInvalidExisting.Remove("name")
  Assert-UnindexedTargetPending -Name "schema-invalid" -Candidate $unindexedInvalidCandidate -SourceDocument $unindexedInvalidExisting -InstalledDocument $unindexedInvalidExisting -Index $emptyIndex

  $unindexedWrongIdCandidate = New-Recipe -RecipeId "unindexed-wrong-id"
  $unindexedWrongIdExisting = New-Recipe -RecipeId "different-recipe-id"
  Assert-UnindexedTargetPending -Name "wrong-id" -Candidate $unindexedWrongIdCandidate -SourceDocument $unindexedWrongIdExisting -InstalledDocument $unindexedWrongIdExisting -Index $emptyIndex

  $unindexedDivergentCandidate = New-Recipe -RecipeId "unindexed-divergent"
  $unindexedDivergentSource = New-Recipe -RecipeId "unindexed-divergent"
  $unindexedDivergentInstalled = New-Recipe -RecipeId "unindexed-divergent"
  $unindexedDivergentInstalled.goal = "Divergent installed recipe"
  Assert-UnindexedTargetPending -Name "divergent" -Candidate $unindexedDivergentCandidate -SourceDocument $unindexedDivergentSource -InstalledDocument $unindexedDivergentInstalled -Index $emptyIndex

  $unindexedValidSource = Join-Path $tempRoot "unindexed-valid-source"
  $unindexedValidInstalled = Join-Path $tempRoot "unindexed-valid-installed"
  $unindexedValidState = Join-Path $tempRoot "unindexed-valid-state"
  New-Item -ItemType Directory -Force -Path $unindexedValidSource, $unindexedValidInstalled, $unindexedValidState | Out-Null
  Set-IdenticalIndex -SourceRoot $unindexedValidSource -InstalledRoot $unindexedValidInstalled -Index $emptyIndex
  $unindexedValidExisting = New-Recipe -RecipeId "unindexed-valid"
  $unindexedValidSourceTarget = Join-Path $unindexedValidSource "recipes\unindexed-valid\recipe.json"
  $unindexedValidInstalledTarget = Join-Path $unindexedValidInstalled "recipes\unindexed-valid\recipe.json"
  Write-JsonFile -Path $unindexedValidSourceTarget -Document $unindexedValidExisting
  New-Item -ItemType Directory -Force -Path (Split-Path -Parent $unindexedValidInstalledTarget) | Out-Null
  Copy-Item -LiteralPath $unindexedValidSourceTarget -Destination $unindexedValidInstalledTarget -Force
  $unindexedValidCandidate = New-Recipe -RecipeId "unindexed-valid"
  $unindexedValidCandidate.goal = "Replace a validated unindexed target pair"
  $unindexedValidFile = Join-Path $tempRoot "unindexed-valid-candidate.json"
  Write-JsonFile -Path $unindexedValidFile -Document $unindexedValidCandidate
  $unindexedValidSync = Invoke-Sync -RecipeFile $unindexedValidFile -SourceRoot $unindexedValidSource -InstalledRoot $unindexedValidInstalled -StateRoot $unindexedValidState
  if ($unindexedValidSync.ExitCode -ne 0 -or $unindexedValidSync.Result.status -cne "synced") { throw "Valid unindexed target pair did not sync" }

  $equalRoot = Join-Path $tempRoot "equal-root"
  $equalState = Join-Path $tempRoot "equal-state"
  New-Item -ItemType Directory -Force -Path $equalRoot, $equalState | Out-Null
  $equalFile = Join-Path $tempRoot "equal-root.json"
  Write-JsonFile -Path $equalFile -Document (New-Recipe -RecipeId "equal-root")
  $equalBefore = Get-TreeSnapshot $equalRoot
  $equalInvocation = Invoke-Sync -RecipeFile $equalFile -SourceRoot $equalRoot -InstalledRoot $equalRoot -StateRoot $equalState
  if ($equalInvocation.ExitCode -eq 0 -or $equalInvocation.Result.status -cne "rejected") { throw "Equal source and installed roots were not rejected" }
  if ((Get-TreeSnapshot $equalRoot) -cne $equalBefore) { throw "Equal-root rejection mutated its target" }

  $overlapSource = Join-Path $tempRoot "overlap-root"
  $overlapInstalled = Join-Path $overlapSource "installed"
  $overlapState = Join-Path $tempRoot "overlap-state"
  New-Item -ItemType Directory -Force -Path $overlapSource, $overlapInstalled, $overlapState | Out-Null
  $overlapFile = Join-Path $tempRoot "overlap-root.json"
  Write-JsonFile -Path $overlapFile -Document (New-Recipe -RecipeId "overlap-root")
  $overlapBefore = Get-TreeSnapshot $overlapSource
  $overlapInvocation = Invoke-Sync -RecipeFile $overlapFile -SourceRoot $overlapSource -InstalledRoot $overlapInstalled -StateRoot $overlapState
  if ($overlapInvocation.ExitCode -eq 0 -or $overlapInvocation.Result.status -cne "rejected") { throw "Overlapping roots were not rejected" }
  if ((Get-TreeSnapshot $overlapSource) -cne $overlapBefore) { throw "Overlapping-root rejection mutated its target" }

  $stateEqualSource = Join-Path $tempRoot "state-equal-source"
  $stateEqualInstalled = Join-Path $tempRoot "state-equal-installed"
  New-Item -ItemType Directory -Force -Path $stateEqualSource, $stateEqualInstalled | Out-Null
  Assert-StateRootRejected -Name "equal-source" -SourceRoot $stateEqualSource -InstalledRoot $stateEqualInstalled -StateRoot $stateEqualSource

  $stateNestedSource = Join-Path $tempRoot "state-nested-source"
  $stateNestedInstalled = Join-Path $tempRoot "state-nested-installed"
  $stateNested = Join-Path $stateNestedSource "state"
  New-Item -ItemType Directory -Force -Path $stateNestedSource, $stateNestedInstalled | Out-Null
  Assert-StateRootRejected -Name "nested-source" -SourceRoot $stateNestedSource -InstalledRoot $stateNestedInstalled -StateRoot $stateNested

  $stateAncestor = Join-Path $tempRoot "state-ancestor"
  $stateAncestorSource = Join-Path $stateAncestor "source"
  $stateAncestorInstalled = Join-Path $tempRoot "state-ancestor-installed"
  New-Item -ItemType Directory -Force -Path $stateAncestorSource, $stateAncestorInstalled | Out-Null
  Assert-StateRootRejected -Name "ancestor-source" -SourceRoot $stateAncestorSource -InstalledRoot $stateAncestorInstalled -StateRoot $stateAncestor

  $stateTargetSource = Join-Path $tempRoot "state-target-source"
  $stateTargetInstalled = Join-Path $tempRoot "state-target-installed"
  New-Item -ItemType Directory -Force -Path $stateTargetSource, $stateTargetInstalled | Out-Null
  Set-IdenticalIndex -SourceRoot $stateTargetSource -InstalledRoot $stateTargetInstalled -Index $emptyIndex
  Assert-StateRootRejected -Name "exact-index-target" -SourceRoot $stateTargetSource -InstalledRoot $stateTargetInstalled -StateRoot (Join-Path $stateTargetSource "recipes\index.json")

  $reparseSource = Join-Path $tempRoot "reparse-source"
  $reparseInstalled = Join-Path $tempRoot "reparse-installed"
  $reparseOutside = Join-Path $tempRoot "reparse-outside"
  $reparseState = Join-Path $tempRoot "reparse-state"
  New-Item -ItemType Directory -Force -Path $reparseSource, $reparseInstalled, $reparseOutside, $reparseState | Out-Null
  $junctionPath = Join-Path $reparseSource "recipes"
  New-Item -ItemType Junction -Path $junctionPath -Target $reparseOutside | Out-Null
  $reparsePaths.Add($junctionPath)
  $reparseFile = Join-Path $tempRoot "reparse-root.json"
  Write-JsonFile -Path $reparseFile -Document (New-Recipe -RecipeId "reparse-root")
  $outsideBefore = Get-TreeSnapshot $reparseOutside
  $reparseInvocation = Invoke-Sync -RecipeFile $reparseFile -SourceRoot $reparseSource -InstalledRoot $reparseInstalled -StateRoot $reparseState
  if ($reparseInvocation.ExitCode -eq 0 -or $reparseInvocation.Result.status -cne "rejected") { throw "Reparse-point target was not rejected" }
  if ((Get-TreeSnapshot $reparseOutside) -cne $outsideBefore) { throw "Reparse-point rejection wrote outside its root" }

  $setupSource = Join-Path $tempRoot "setup-source"
  $setupInstalled = Join-Path $tempRoot "setup-installed"
  $setupStateFile = Join-Path $tempRoot "setup-state-file"
  New-Item -ItemType Directory -Force -Path $setupSource, $setupInstalled | Out-Null
  [IO.File]::WriteAllText($setupStateFile, "not a directory", $utf8NoBom)
  $setupRecipeFile = Join-Path $tempRoot "setup-failure.json"
  Write-JsonFile -Path $setupRecipeFile -Document (New-Recipe -RecipeId "setup-failure" -Sensitive)
  $setupInvocation = Invoke-Sync -RecipeFile $setupRecipeFile -SourceRoot $setupSource -InstalledRoot $setupInstalled -StateRoot $setupStateFile
  if ($setupInvocation.ExitCode -eq 0 -or $setupInvocation.Result.status -cne "sync_pending") { throw "Transaction setup failure was not sync_pending" }
  if ($setupInvocation.Result.recipeId -cne "setup-failure" -or @($setupInvocation.Result.redactions).Count -lt 11) { throw "Transaction setup failure lost recipe/redaction metadata" }
  if (-not $setupInvocation.Result.error.StartsWith("transaction setup failed:")) { throw "Transaction setup fallback error was not deterministic" }
  if ((Get-TreeSnapshot $setupSource) -ne "" -or (Get-TreeSnapshot $setupInstalled) -ne "") { throw "Transaction setup failure mutated targets" }

  $candidateProbePath = Join-Path $tempRoot "candidate_setup_probe.py"
  $candidateProbe = @'
import importlib.util
import json
import sys
from pathlib import Path

script_path, recipe_path, source_root, installed_root, state_root = map(Path, sys.argv[1:])
spec = importlib.util.spec_from_file_location("sync_recipe_candidate_setup_contract", script_path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
real_atomic_write = module.atomic_write_json

def fail_candidate(path, document):
    if Path(path).name == "candidate.recipe.json":
        raise OSError("injected candidate persistence failure")
    return real_atomic_write(path, document)

module.atomic_write_json = fail_candidate
result = module.sync_recipe(module.load_json(recipe_path), source_root, installed_root, state_root)
print(json.dumps(result, ensure_ascii=False))
ok = result.get("status") == "sync_pending" and result.get("recipeId") == "setup-failure" and len(result.get("redactions", [])) >= 11
raise SystemExit(0 if ok else 1)
'@
  [IO.File]::WriteAllText($candidateProbePath, $candidateProbe, $utf8NoBom)
  $candidateState = Join-Path $tempRoot "candidate-setup-state"
  New-Item -ItemType Directory -Force -Path $candidateState | Out-Null
  $candidateOutput = @(& python $candidateProbePath $scriptPath $setupRecipeFile $setupSource $setupInstalled $candidateState 2>&1)
  if ($LASTEXITCODE -ne 0) { throw "Candidate setup failure probe failed: $($candidateOutput -join "`n")" }

  $schemaProbePath = Join-Path $tempRoot "schema_probe.py"
  $schemaProbe = @'
import importlib.util
import sys
from pathlib import Path

script_path, skill_root = map(Path, sys.argv[1:])
spec = importlib.util.spec_from_file_location("sync_recipe_schema_contract", script_path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
module.validate_document(module.load_json(skill_root / "recipes" / "boss-resume-screening" / "recipe.json"), module.RECIPE_SCHEMA_PATH)
module.validate_document(module.load_json(skill_root / "recipes" / "acquisition" / "recipe.json"), module.RECIPE_SCHEMA_PATH)
module.validate_document(module.load_json(skill_root / "recipes" / "index.json"), module.INDEX_SCHEMA_PATH)
'@
  [IO.File]::WriteAllText($schemaProbePath, $schemaProbe, $utf8NoBom)
  & python $schemaProbePath $scriptPath (Join-Path $repoRoot "skills\luming-phone-agent")
  if ($LASTEXITCODE -ne 0) { throw "Built-in recipe schema validation failed" }

  $rollbackSource = Join-Path $tempRoot "rollback-source"
  $rollbackInstalled = Join-Path $tempRoot "rollback-installed"
  $rollbackState = Join-Path $tempRoot "rollback-state"
  New-Item -ItemType Directory -Force -Path $rollbackSource, $rollbackInstalled, $rollbackState | Out-Null
  $baselineIndex = [ordered]@{ schema = "loom.phone-agent.recipe-index.v1"; recipes = @() }
  Write-JsonFile -Path (Join-Path $rollbackSource "recipes\index.json") -Document $baselineIndex
  Write-JsonFile -Path (Join-Path $rollbackInstalled "recipes\index.json") -Document $baselineIndex
  $rollbackRecipeFile = Join-Path $tempRoot "rollback-recipe.json"
  Write-JsonFile -Path $rollbackRecipeFile -Document (New-Recipe -RecipeId "rollback-contract")
  $rollbackSourceBefore = Get-TreeSnapshot $rollbackSource
  $rollbackInstalledBefore = Get-TreeSnapshot $rollbackInstalled
  $probePath = Join-Path $tempRoot "rollback_probe.py"
  $probe = @'
import importlib.util
import json
import sys
from pathlib import Path

script_path, recipe_path, source_root, installed_root, state_root = map(Path, sys.argv[1:])
spec = importlib.util.spec_from_file_location("sync_recipe_contract", script_path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
real_atomic_write = module.atomic_write_json

def fail_installed_index(path, document):
    path = Path(path)
    if path == installed_root / "recipes" / "index.json":
        raise OSError("injected installed-root index write failure")
    return real_atomic_write(path, document)

module.atomic_write_json = fail_installed_index
result = module.sync_recipe(module.load_json(recipe_path), source_root, installed_root, state_root)
print(json.dumps(result, ensure_ascii=False))
raise SystemExit(0 if result.get("status") == "sync_pending" else 1)
'@
  [IO.File]::WriteAllText($probePath, $probe, $utf8NoBom)
  $rollbackOutput = @(& python $probePath $scriptPath $rollbackRecipeFile $rollbackSource $rollbackInstalled $rollbackState)
  if ($LASTEXITCODE -ne 0) { throw "Rollback probe failed: $($rollbackOutput -join "`n")" }
  $rollbackResult = ($rollbackOutput -join "`n") | ConvertFrom-Json
  if ($rollbackResult.status -cne "sync_pending") { throw "Injected failure did not return sync_pending" }
  if (-not $rollbackResult.transactionPath -or -not (Test-Path -LiteralPath $rollbackResult.transactionPath)) {
    throw "Failed transaction was not preserved"
  }
  if ((Get-TreeSnapshot $rollbackSource) -cne $rollbackSourceBefore) { throw "Rollback did not restore source root" }
  if ((Get-TreeSnapshot $rollbackInstalled) -cne $rollbackInstalledBefore) { throw "Rollback did not restore installed root" }

  $aggregateSource = Join-Path $tempRoot "aggregate-source"
  $aggregateInstalled = Join-Path $tempRoot "aggregate-installed"
  $aggregateState = Join-Path $tempRoot "aggregate-state"
  New-Item -ItemType Directory -Force -Path $aggregateSource, $aggregateInstalled, $aggregateState | Out-Null
  Set-IdenticalIndex -SourceRoot $aggregateSource -InstalledRoot $aggregateInstalled -Index $baselineIndex
  $aggregateRecipeFile = Join-Path $tempRoot "aggregate-recipe.json"
  Write-JsonFile -Path $aggregateRecipeFile -Document (New-Recipe -RecipeId "aggregate-rollback")
  $aggregateProbePath = Join-Path $tempRoot "aggregate_rollback_probe.py"
  $aggregateProbe = @'
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

script_path, recipe_path, source_root, installed_root, state_root = map(Path, sys.argv[1:])
spec = importlib.util.spec_from_file_location("sync_recipe_aggregate_rollback_contract", script_path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
source_index = source_root / "recipes" / "index.json"
installed_index = installed_root / "recipes" / "index.json"
source_recipe = source_root / "recipes" / "aggregate-rollback" / "recipe.json"
installed_recipe = installed_root / "recipes" / "aggregate-rollback" / "recipe.json"
installed_index_hash = hashlib.sha256(installed_index.read_bytes()).hexdigest()
real_atomic_json = module.atomic_write_json
real_atomic_bytes = module._atomic_write_bytes
rollback_started = False

def fail_final_write(path, document):
    global rollback_started
    if Path(path) == installed_index:
        rollback_started = True
        raise OSError("injected final write failure")
    return real_atomic_json(path, document)

def fail_one_restore(path, content):
    if rollback_started and Path(path) == source_index:
        raise OSError("injected source-index restore failure")
    return real_atomic_bytes(path, content)

module.atomic_write_json = fail_final_write
module._atomic_write_bytes = fail_one_restore
result = module.sync_recipe(module.load_json(recipe_path), source_root, installed_root, state_root)
print(json.dumps(result, ensure_ascii=False))
later_records_restored = not source_recipe.exists() and not installed_recipe.exists()
installed_index_restored = hashlib.sha256(installed_index.read_bytes()).hexdigest() == installed_index_hash
ok = result.get("status") == "sync_pending" and result.get("rollbackError") and later_records_restored and installed_index_restored
raise SystemExit(0 if ok else 1)
'@
  [IO.File]::WriteAllText($aggregateProbePath, $aggregateProbe, $utf8NoBom)
  $aggregateOutput = @(& python $aggregateProbePath $scriptPath $aggregateRecipeFile $aggregateSource $aggregateInstalled $aggregateState 2>&1)
  if ($LASTEXITCODE -ne 0) { throw "Aggregate rollback probe failed: $($aggregateOutput -join "`n")" }

  $finalizationProbePath = Join-Path $tempRoot "finalization_probe.py"
  $finalizationProbe = @'
import contextlib
import hashlib
import importlib.util
import io
import json
import sys
from pathlib import Path

script_path = Path(sys.argv[1])
recipe_path = Path(sys.argv[2])
recovery_path = Path(sys.argv[3])
source_root = Path(sys.argv[4])
installed_root = Path(sys.argv[5])
state_root = Path(sys.argv[6])
fault = sys.argv[7]
spec = importlib.util.spec_from_file_location("sync_recipe_finalization_contract", script_path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

def snapshot(root):
    rows = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        rows.append(("d", relative) if path.is_dir() else ("f", relative, hashlib.sha256(path.read_bytes()).hexdigest()))
    return rows

real_atomic_json = module.atomic_write_json
real_persist_journal = module._persist_journal
real_remove_journal = module._remove_canonical_journal
fault_active = True

def fail_result(path, document):
    if fault_active and fault == "result-json" and Path(path).name == "result.json":
        raise OSError("injected persistent result failure")
    return real_atomic_json(path, document)

def fail_committed_journal(journal_path, journal):
    if fault_active and fault == "committed-journal" and journal.get("phase") == "committed":
        raise OSError("injected committed journal failure")
    return real_persist_journal(journal_path, journal)

def fail_canonical_remove(journal_path):
    if fault_active and fault == "canonical-remove":
        raise OSError("injected canonical journal removal failure")
    return real_remove_journal(journal_path)

module.atomic_write_json = fail_result
module._persist_journal = fail_committed_journal
module._remove_canonical_journal = fail_canonical_remove
before_source = snapshot(source_root)
before_installed = snapshot(installed_root)
stdout = io.StringIO()
with contextlib.redirect_stdout(stdout):
    first_exit = module.main([
        "--recipe-file", str(recipe_path),
        "--source-skill-root", str(source_root),
        "--installed-skill-root", str(installed_root),
        "--state-root", str(state_root),
    ])
first = json.loads(stdout.getvalue())
after_source = snapshot(source_root)
after_installed = snapshot(installed_root)
hash_fields = ("sourceRecipeSha256", "installedRecipeSha256", "sourceIndexSha256", "installedIndexSha256")
hashes_cleared = all(first.get(field) is None for field in hash_fields) and all(value is None for value in first.get("hashes", {}).values())
transaction_path = Path(first["transactionPath"]) if first.get("transactionPath") else None
stored_result_ok = True
journal_phase = None
if transaction_path is not None:
    result_path = transaction_path / "result.json"
    if result_path.exists():
        stored_result = json.loads(result_path.read_text(encoding="utf-8"))
        stored_result_ok = stored_result.get("status") == "sync_pending" and all(stored_result.get(field) is None for field in hash_fields)
    journal_path = transaction_path / "journal.json"
    if journal_path.exists():
        journal_phase = json.loads(journal_path.read_text(encoding="utf-8")).get("phase")

fault_active = False
module.atomic_write_json = real_atomic_json
module._persist_journal = real_persist_journal
module._remove_canonical_journal = real_remove_journal
recovery = module.sync_recipe(module.load_json(recovery_path), source_root, installed_root, state_root)
first_recipe = source_root / "recipes" / module.load_json(recipe_path)["recipeId"] / "recipe.json"
recovery_recipe = source_root / "recipes" / module.load_json(recovery_path)["recipeId"] / "recipe.json"
recovered_result_ok = False
if transaction_path is not None and (transaction_path / "result.json").is_file():
    recovered_result = json.loads((transaction_path / "result.json").read_text(encoding="utf-8"))
    recovered_result_ok = recovered_result.get("status") == "sync_pending" and all(recovered_result.get(field) is None for field in hash_fields)
checks = {
    "firstExitNonzero": first_exit != 0,
    "firstPending": first.get("status") == "sync_pending",
    "hashesCleared": hashes_cleared,
    "sourceRestored": after_source == before_source,
    "installedRestored": after_installed == before_installed,
    "storedResultPending": stored_result_ok,
    "journalRecoverable": journal_phase in {"rolled_back", "rollback_failed"},
    "recoveredResultPending": recovered_result_ok,
    "recoverySynced": recovery.get("status") == "synced",
    "partialRecipeAbsent": not first_recipe.exists(),
    "recoveryRecipePresent": recovery_recipe.is_file(),
}
print(json.dumps({"fault": fault, "first": first, "firstExit": first_exit, "recovery": recovery, "checks": checks}, ensure_ascii=False))
raise SystemExit(0 if all(checks.values()) else 1)
'@
  [IO.File]::WriteAllText($finalizationProbePath, $finalizationProbe, $utf8NoBom)
  foreach ($fault in @("result-json", "committed-journal", "canonical-remove")) {
    $finalSource = Join-Path $tempRoot "final-$fault-source"
    $finalInstalled = Join-Path $tempRoot "final-$fault-installed"
    $finalState = Join-Path $tempRoot "final-$fault-state"
    New-Item -ItemType Directory -Force -Path $finalSource, $finalInstalled, $finalState | Out-Null
    Set-IdenticalIndex -SourceRoot $finalSource -InstalledRoot $finalInstalled -Index $baselineIndex
    $finalRecipeFile = Join-Path $tempRoot "final-$fault.json"
    $finalRecoveryFile = Join-Path $tempRoot "final-$fault-recovery.json"
    Write-JsonFile -Path $finalRecipeFile -Document (New-Recipe -RecipeId "final-$fault")
    Write-JsonFile -Path $finalRecoveryFile -Document (New-Recipe -RecipeId "final-$fault-recovery")
    $finalOutput = @(& python $finalizationProbePath $scriptPath $finalRecipeFile $finalRecoveryFile $finalSource $finalInstalled $finalState $fault 2>&1)
    if ($LASTEXITCODE -ne 0) { throw "Finalization probe failed for $fault`: $($finalOutput -join "`n")" }
    $finalResult = ($finalOutput -join "`n") | ConvertFrom-Json
    if ($finalResult.first.status -cne "sync_pending" -or $finalResult.firstExit -eq 0) { throw "Finalization fault $fault exposed synced status" }
  }

  $terminalJournalProbePath = Join-Path $tempRoot "terminal_journal_probe.py"
  $terminalJournalProbe = @'
import importlib.util
import os
import sys
from pathlib import Path

script_path = Path(sys.argv[1])
recipe_path = Path(sys.argv[2])
source_root = Path(sys.argv[3]).resolve()
installed_root = Path(sys.argv[4]).resolve()
state_root = Path(sys.argv[5]).resolve()
mode = sys.argv[6]
spec = importlib.util.spec_from_file_location("sync_recipe_terminal_journal_contract", script_path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
recipe = module.load_json(recipe_path)
coordination_root = module._coordination_root(source_root, installed_root)
(state_root / "coordination-root.txt").write_text(str(coordination_root), encoding="utf-8")
journals_root = coordination_root / "journals"
source_recipe_target = source_root / "recipes" / recipe["recipeId"] / "recipe.json"
installed_index_target = installed_root / "recipes" / "index.json"
real_atomic_write = module.atomic_write_json

def crash_between_terminal_journals(path, document):
    target = Path(path)
    if (
        mode == "rolled_back"
        and module._path_key(target) == module._path_key(installed_index_target)
    ):
        raise OSError("injected write failure before rolled_back terminal phase")
    real_atomic_write(target, document)
    if mode == "seed-recovered" and target == source_recipe_target:
        os._exit(93)
    phase_exit = {"committed": 91, "rolled_back": 92, "recovered": 94}
    if target.parent == journals_root and document.get("phase") == mode:
        os._exit(phase_exit[mode])

module.atomic_write_json = crash_between_terminal_journals
module.sync_recipe(recipe, source_root, installed_root, state_root)
raise SystemExit(2)
'@
  [IO.File]::WriteAllText($terminalJournalProbePath, $terminalJournalProbe, $utf8NoBom)
  foreach ($terminalPhase in @("committed", "rolled_back", "recovered")) {
    $terminalSource = Join-Path $tempRoot "terminal-$terminalPhase-source"
    $terminalInstalled = Join-Path $tempRoot "terminal-$terminalPhase-installed"
    $terminalState = Join-Path $tempRoot "terminal-$terminalPhase-state"
    New-Item -ItemType Directory -Force -Path $terminalSource, $terminalInstalled, $terminalState | Out-Null
    Set-IdenticalIndex -SourceRoot $terminalSource -InstalledRoot $terminalInstalled -Index $baselineIndex
    $terminalRecipePhase = $terminalPhase.Replace("_", "-")
    $originalRecipeId = "terminal-$terminalRecipePhase-original"
    $originalRecipeFile = Join-Path $tempRoot "$originalRecipeId.json"
    Write-JsonFile -Path $originalRecipeFile -Document (New-Recipe -RecipeId $originalRecipeId)

    if ($terminalPhase -ceq "recovered") {
      $seedOutput = @(& python $terminalJournalProbePath $scriptPath $originalRecipeFile $terminalSource $terminalInstalled $terminalState "seed-recovered" 2>&1)
      if ($LASTEXITCODE -ne 93) { throw "Recovered terminal seed did not hard-exit at target boundary: $($seedOutput -join "`n")" }
      $recoveryAttemptFile = Join-Path $tempRoot "terminal-recovered-attempt.json"
      Write-JsonFile -Path $recoveryAttemptFile -Document (New-Recipe -RecipeId "terminal-recovered-attempt")
      $terminalOutput = @(& python $terminalJournalProbePath $scriptPath $recoveryAttemptFile $terminalSource $terminalInstalled $terminalState "recovered" 2>&1)
      if ($LASTEXITCODE -ne 94) { throw "Recovered terminal probe did not hard-exit between journal writes: $($terminalOutput -join "`n")" }
    } else {
      $expectedExit = if ($terminalPhase -ceq "committed") { 91 } else { 92 }
      $terminalOutput = @(& python $terminalJournalProbePath $scriptPath $originalRecipeFile $terminalSource $terminalInstalled $terminalState $terminalPhase 2>&1)
      if ($LASTEXITCODE -ne $expectedExit) { throw "$terminalPhase terminal probe exited $LASTEXITCODE instead of $expectedExit`: $($terminalOutput -join "`n")" }
    }

    $finalRecoveryId = "terminal-$terminalRecipePhase-final-recovery"
    $finalRecoveryFile = Join-Path $tempRoot "$finalRecoveryId.json"
    Write-JsonFile -Path $finalRecoveryFile -Document (New-Recipe -RecipeId $finalRecoveryId)
    $terminalRecovery = Invoke-Sync -RecipeFile $finalRecoveryFile -SourceRoot $terminalSource -InstalledRoot $terminalInstalled -StateRoot $terminalState
    if ($terminalRecovery.ExitCode -ne 0 -or $terminalRecovery.Result.status -cne "synced") {
      throw "$terminalPhase terminal recovery did not continue with a new sync"
    }

    $matchingLocalJournals = @(Get-ChildItem -LiteralPath (Join-Path $terminalState "transactions") -Recurse -File -Filter "journal.json" | Where-Object {
      (Get-Content -Raw -Encoding UTF8 -LiteralPath $_.FullName | ConvertFrom-Json).recipeId -ceq $originalRecipeId
    })
    if ($matchingLocalJournals.Count -ne 1) { throw "$terminalPhase terminal recovery did not preserve exactly one local journal" }
    $localJournalPath = $matchingLocalJournals[0].FullName
    $localJournal = Get-Content -Raw -Encoding UTF8 -LiteralPath $localJournalPath | ConvertFrom-Json
    $expectedResultStatus = if ($terminalPhase -ceq "committed") { "synced" } else { "sync_pending" }
    if ($localJournal.phase -cne $terminalPhase -or $localJournal.resultStatus -cne $expectedResultStatus) {
      throw "$terminalPhase terminal local journal was not self-healed"
    }
    $localResult = Get-Content -Raw -Encoding UTF8 -LiteralPath (Join-Path (Split-Path -Parent $localJournalPath) "result.json") | ConvertFrom-Json
    if ($localResult.status -cne $expectedResultStatus) { throw "$terminalPhase terminal result status was not self-healed" }
    if ($expectedResultStatus -ceq "sync_pending" -and $localResult.sourceRecipeSha256) { throw "$terminalPhase terminal pending result exposed hashes" }
    $coordinationRoot = (Get-Content -Raw -Encoding UTF8 -LiteralPath (Join-Path $terminalState "coordination-root.txt")).Trim()
    $transactionId = Split-Path -Leaf (Split-Path -Parent $localJournalPath)
    $canonicalJournalPath = Join-Path $coordinationRoot ("journals\$transactionId.json")
    if (Test-Path -LiteralPath $canonicalJournalPath) { throw "$terminalPhase terminal canonical journal pointer was not removed" }
    $originalTarget = Join-Path $terminalSource "recipes\$originalRecipeId\recipe.json"
    if ($terminalPhase -ceq "committed" -and -not (Test-Path -LiteralPath $originalTarget)) { throw "Committed terminal recovery rolled back committed targets" }
    if ($terminalPhase -cne "committed" -and (Test-Path -LiteralPath $originalTarget)) { throw "$terminalPhase terminal recovery retained rolled-back targets" }
  }

  $crashProbePath = Join-Path $tempRoot "crash_recovery_probe.py"
  $crashProbe = @'
import importlib.util
import os
import sys
from pathlib import Path

script_path = Path(sys.argv[1])
recipe_path = Path(sys.argv[2])
source_root = Path(sys.argv[3])
installed_root = Path(sys.argv[4])
state_root = Path(sys.argv[5])
boundary = int(sys.argv[6])
spec = importlib.util.spec_from_file_location("sync_recipe_crash_contract", script_path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
recipe = module.load_json(recipe_path)
relative_path = Path("recipes") / recipe["recipeId"] / "recipe.json"
targets = {
    source_root / relative_path,
    installed_root / relative_path,
    source_root / "recipes" / "index.json",
    installed_root / "recipes" / "index.json",
}
real_atomic_write = module.atomic_write_json
write_count = 0

def crash_after_boundary(path, document):
    global write_count
    real_atomic_write(path, document)
    if Path(path) in targets:
        write_count += 1
        if write_count == boundary:
            os._exit(80 + boundary)
    if boundary == 5 and Path(path).name == "result.json" and document.get("status") == "synced":
        os._exit(85)

module.atomic_write_json = crash_after_boundary
module.sync_recipe(recipe, source_root, installed_root, state_root)
raise SystemExit(2)
'@
  [IO.File]::WriteAllText($crashProbePath, $crashProbe, $utf8NoBom)
  foreach ($boundary in 1..5) {
    $crashSource = Join-Path $tempRoot "crash-$boundary-source"
    $crashInstalled = Join-Path $tempRoot "crash-$boundary-installed"
    $crashState = Join-Path $tempRoot "crash-$boundary-state"
    New-Item -ItemType Directory -Force -Path $crashSource, $crashInstalled, $crashState | Out-Null
    Set-IdenticalIndex -SourceRoot $crashSource -InstalledRoot $crashInstalled -Index $baselineIndex
    $crashRecipeFile = Join-Path $tempRoot "crash-$boundary.json"
    $recoveryRecipeFile = Join-Path $tempRoot "recovery-$boundary.json"
    Write-JsonFile -Path $crashRecipeFile -Document (New-Recipe -RecipeId "crash-$boundary")
    Write-JsonFile -Path $recoveryRecipeFile -Document (New-Recipe -RecipeId "recovery-$boundary")
    & python $crashProbePath $scriptPath $crashRecipeFile $crashSource $crashInstalled $crashState $boundary
    if ($LASTEXITCODE -ne (80 + $boundary)) { throw "Crash boundary $boundary did not terminate at the expected write" }
    $recovery = Invoke-Sync -RecipeFile $recoveryRecipeFile -SourceRoot $crashSource -InstalledRoot $crashInstalled -StateRoot $crashState
    if ($recovery.ExitCode -ne 0 -or $recovery.Result.status -cne "synced") { throw "Crash boundary $boundary was not recovered on the next invocation" }
    foreach ($root in @($crashSource, $crashInstalled)) {
      if (Test-Path -LiteralPath (Join-Path $root "recipes\crash-$boundary\recipe.json")) { throw "Crash boundary $boundary left a partial recipe" }
      if (-not (Test-Path -LiteralPath (Join-Path $root "recipes\recovery-$boundary\recipe.json"))) { throw "Crash boundary $boundary blocked the recovery recipe" }
    }
    $recoveredIndex = Get-Content -Raw -Encoding UTF8 (Join-Path $crashSource "recipes\index.json") | ConvertFrom-Json
    if (@($recoveredIndex.recipes | Where-Object recipeId -CEQ "crash-$boundary").Count -ne 0) { throw "Crash boundary $boundary left a partial index entry" }
    if (@($recoveredIndex.recipes | Where-Object recipeId -CEQ "recovery-$boundary").Count -ne 1) { throw "Crash boundary $boundary lost the recovery index entry" }
    $journals = @(Get-ChildItem -LiteralPath (Join-Path $crashState "transactions") -Recurse -File -Filter "journal.json" | ForEach-Object {
      [pscustomobject]@{ Path = $_.FullName; Document = (Get-Content -Raw -Encoding UTF8 $_.FullName | ConvertFrom-Json) }
    })
    $recoveredJournals = @($journals | Where-Object { $_.Document.phase -CEQ "recovered" })
    if ($recoveredJournals.Count -lt 1) { throw "Crash boundary $boundary did not persist recovered journal state" }
    foreach ($recoveredJournal in $recoveredJournals) {
      $recoveredResultPath = Join-Path (Split-Path -Parent $recoveredJournal.Path) "result.json"
      if (-not (Test-Path -LiteralPath $recoveredResultPath)) { throw "Crash boundary $boundary recovery did not persist pending result" }
      $recoveredResult = Get-Content -Raw -Encoding UTF8 $recoveredResultPath | ConvertFrom-Json
      if ($recoveredResult.status -cne "sync_pending" -or $recoveredResult.sourceRecipeSha256) { throw "Crash boundary $boundary exposed finalized status after recovery" }
    }
    if ((Get-FileHash (Join-Path $crashSource "recipes\index.json")).Hash -cne (Get-FileHash (Join-Path $crashInstalled "recipes\index.json")).Hash) {
      throw "Crash boundary $boundary recovery broke index parity"
    }
  }

  Write-Output "luming recipe sync contract ok"
} finally {
  foreach ($reparsePath in $reparsePaths) {
    if (Test-Path -LiteralPath $reparsePath) { Remove-Item -LiteralPath $reparsePath -Force }
  }
  if (Test-Path -LiteralPath $tempRoot) { Remove-Item -LiteralPath $tempRoot -Recurse -Force }
}
