$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$skillRoot = Join-Path $repoRoot "skills\luming-phone-agent"

function Assert-Contains {
  param([string]$Text, [string]$Marker, [string]$Context)
  if (-not $Text.Contains($Marker)) {
    throw "$Context is missing marker: $Marker"
  }
}

function Assert-NotContains {
  param([string]$Text, [string]$Marker, [string]$Context)
  if ($Text.Contains($Marker)) {
    throw "$Context contains forbidden marker: $Marker"
  }
}

function Assert-Fields {
  param([object]$Value, [string[]]$Fields, [string]$Context)
  $propertyNames = @($Value.PSObject.Properties.Name)
  foreach ($field in $Fields) {
    if ($propertyNames -notcontains $field) {
      throw "$Context is missing required field: $field"
    }
  }
}

function Assert-Boolean {
  param([object]$Value, [string]$Context)
  if ($Value -isnot [bool]) {
    throw "$Context must be a JSON Boolean"
  }
}

function Assert-AcceptanceRow {
  param(
    [string]$Text,
    [string]$Scenario,
    [string]$State,
    [string]$ResultStatus,
    [string]$ResumeBehavior,
    [string]$ProhibitedAction
  )
  $row = [regex]::Match(
    $Text,
    "(?m)^\|\s*$([regex]::Escape($Scenario))\s*\|\s*(?<state>.+?)\s*\|\s*(?<status>.+?)\s*\|\s*(?<resume>.+?)\s*\|\s*(?<prohibited>.+?)\s*\|\s*$"
  )
  if (-not $row.Success) {
    throw "Acceptance table is missing scenario: $Scenario"
  }
  $expectedColumns = @{
    state = $State
    status = $ResultStatus
    resume = $ResumeBehavior
    prohibited = $ProhibitedAction
  }
  foreach ($column in $expectedColumns.Keys) {
    Assert-Contains -Text $row.Groups[$column].Value -Marker $expectedColumns[$column] -Context "Acceptance $column for $Scenario"
  }
}

function Assert-StringSetEqual {
  param([string[]]$Expected, [string[]]$Actual, [string]$Context)
  $expectedSet = [Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
  $actualSet = [Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
  foreach ($value in $Expected) { $expectedSet.Add($value) | Out-Null }
  foreach ($value in $Actual) { $actualSet.Add($value) | Out-Null }
  if (-not $expectedSet.SetEquals($actualSet)) {
    throw "$Context differs. Expected: $($Expected -join ', '); actual: $($Actual -join ', ')"
  }
}

function Assert-ReusableRecipe {
  param([object]$Recipe, [string]$Context)
  if ($Recipe.status -ne "verified") {
    throw "$Context must have status == verified"
  }
  if ($null -eq $Recipe.verification -or $Recipe.verification.successCount -lt 1) {
    throw "$Context must have verification.successCount >= 1"
  }
  foreach ($step in @($Recipe.route)) {
    if ($step.verification -ne "verified") {
      throw "$Context route step $($step.stepId) must have verification == verified"
    }
    if (@($step.evidence).Count -eq 0) {
      throw "$Context route step $($step.stepId) must have non-empty evidence"
    }
  }
}

function Assert-SafeRecipeCandidate {
  param([object]$Candidate, [string]$Context)
  foreach ($field in @("rawResume", "unrelatedPersonalData")) {
    if ($Candidate.PSObject.Properties.Name -contains $field -and $null -ne $Candidate.$field) {
      throw "$Context must reject $field"
    }
  }
}

if (-not (Test-Path -LiteralPath $skillRoot)) {
  throw "Unified Skill directory is missing"
}

$requiredFiles = @(
  "SKILL.md",
  "agents\openai.yaml",
  "references\environment-preflight.md",
  "references\loom-capability-map.md",
  "references\phone-discovery.md",
  "references\safe-navigation.md",
  "references\task-compiler.md",
  "references\matrix-supervision.md",
  "references\builtin-playbooks.md",
  "references\acquisition-workflow.md",
  "references\boss-resume-screening.md",
  "references\scenario-skill-authoring.md",
  "references\recipe-sync-contract.md",
  "examples\self-check-ready.json",
  "examples\self-check-blocked.json",
  "examples\task-plan.json",
  "examples\sync-result.json"
)
foreach ($relativePath in $requiredFiles) {
  if (-not (Test-Path -LiteralPath (Join-Path $skillRoot $relativePath))) {
    throw "Missing required file: $relativePath"
  }
}

$skillText = Get-Content -Raw -Encoding UTF8 -LiteralPath (Join-Path $skillRoot "SKILL.md")
$states = @(
  "SELF_CHECK", "PHONE_DISCOVERY", "ASK_TASK", "RECIPE_MATCH",
  "PREFLIGHT", "REUSE_OR_EXPLORE", "PLAN", "EXECUTE_VERIFY",
  "SYNC_RECIPE", "REPORT"
)
$cursor = -1
foreach ($state in $states) {
  $next = $skillText.IndexOf($state, $cursor + 1, [StringComparison]::Ordinal)
  if ($next -lt 0) { throw "Missing or out-of-order state: $state" }
  $cursor = $next
}

$hardStops = @(
  "login submission", "captcha", "2FA", "membership purchase", "payment",
  "candidate rejection", "final hiring decision", "device administrator",
  "accessibility service", "VPN", "unknown-source installation",
  "security or ownership change", "platform risk bypass"
)
foreach ($marker in $hardStops) {
  Assert-Contains -Text $skillText -Marker $marker -Context "SKILL.md hard stop"
}
foreach ($marker in @(
  "gateMode: weak",
  "weak safety gate",
  "routine permission grant",
  "deletion, archive, block, report, follow, unfollow, and add contact",
  "non-security account or profile mutation",
  "without per-action confirmation"
)) {
  Assert-Contains -Text $skillText -Marker $marker -Context "SKILL.md weak safety gate"
}
foreach ($marker in @(
  "automatic outbound",
  "publish, comment, and private message",
  "task-level authorization",
  "without per-action confirmation",
  "recipient or audience scope",
  "content policy",
  "frequency cap",
  "duplicate prevention",
  "audit log",
  "recipient or audience mismatch",
  "platform risk prompt",
  "rate limit"
)) {
  Assert-Contains -Text $skillText -Marker $marker -Context "SKILL.md automatic outbound policy"
}
Assert-NotContains -Text $skillText -Marker "payment, publish, comment, private message" -Context "SKILL.md hard stops"
Assert-NotContains -Text $skillText -Marker "payment, deletion, rejection" -Context "SKILL.md hard stops"

foreach ($marker in @(
  "never invent CLI commands",
  "only the reference needed for the current state",
  "ASK_TASK follows PHONE_DISCOVERY",
  "one healthy phone is auto-selected",
  "single-device or matrix decision",
  "three unchanged page fingerprints",
  "exploration_budget_exhausted",
  "Internal modes (not triggerable Skills)",
  "acquisition dry-run dispatch",
  "loom.acquisition.agent_result.v1",
  "loom.hr.resume_screening.v1",
  "scenario Skill creation or update",
  "loom.phone-agent.run-result.v1",
  '"status": "completed|blocked|needs_human|failed"',
  '"selfCheck": "ready|blocked"',
  '"outbound": {"mode": "none|auto", "status": "not_requested|executed|stopped"',
  '"sync": "not_needed|synced|sync_pending"'
)) {
  Assert-Contains -Text $skillText -Marker $marker -Context "SKILL.md"
}

$linkedReferences = @([regex]::Matches($skillText, "\[.+?\]\((references/[^)]+)\)") | ForEach-Object { $_.Groups[1].Value } | Select-Object -Unique)
$requiredReferenceLinks = @(
  "references/environment-preflight.md",
  "references/loom-capability-map.md",
  "references/phone-discovery.md",
  "references/safe-navigation.md",
  "references/task-compiler.md",
  "references/matrix-supervision.md",
  "references/builtin-playbooks.md",
  "references/acquisition-workflow.md",
  "references/boss-resume-screening.md",
  "references/scenario-skill-authoring.md",
  "references/recipe-sync-contract.md"
)
Assert-StringSetEqual -Expected $requiredReferenceLinks -Actual $linkedReferences -Context "SKILL.md reference links"
foreach ($reference in $linkedReferences) {
  if (-not (Test-Path -LiteralPath (Join-Path $skillRoot $reference))) {
    throw "SKILL.md reference link does not resolve: $reference"
  }
}

$safeNavigation = Get-Content -Raw -Encoding UTF8 -LiteralPath (Join-Path $skillRoot "references\safe-navigation.md")
foreach ($marker in $hardStops + @("automatic outbound", "task-level authorization", "without per-action confirmation", "irreversible")) {
  Assert-Contains -Text $safeNavigation -Marker $marker -Context "safe-navigation reference"
}
Assert-NotContains -Text $safeNavigation -Marker "payment, publish, comment, private message" -Context "safe-navigation hard stops"
foreach ($marker in @("gateMode: weak", "routine permission grant", "deletion", "archive", "follow", "add contact", "non-security account or profile mutation")) {
  Assert-Contains -Text $safeNavigation -Marker $marker -Context "safe-navigation weak safety gate"
}
foreach ($marker in @(
  "single-device EXECUTE_VERIFY",
  "verified recipe reuse",
  "recipe's evidence/verification steps",
  "new/stale exploration",
  "exploration budgets"
)) {
  Assert-Contains -Text $safeNavigation -Marker $marker -Context "safe-navigation execution mode"
}

$stateRows = @{
  "PLAN" = @("task compiler", "built-in playbooks", "BOSS or acquisition")
  "EXECUTE_VERIFY" = @("safe navigation", "single-device", "matrix supervision", "matrix execution", "built-in playbooks", "BOSS or acquisition")
}
foreach ($state in $stateRows.Keys) {
  $stateRow = [regex]::Match($skillText, "(?m)^\|\s*[^|]*$([regex]::Escape($state))[^|]*\|(?<body>.+)$")
  if (-not $stateRow.Success) {
    throw "SKILL.md state table is missing row: $state"
  }
  foreach ($marker in $stateRows[$state]) {
    Assert-Contains -Text $stateRow.Groups["body"].Value -Marker $marker -Context "$state reference selection"
  }
}

$matrix = Get-Content -Raw -Encoding UTF8 -LiteralPath (Join-Path $skillRoot "references\matrix-supervision.md")
foreach ($marker in @("dispatch_once", "watch_events", "poll_health_lightly", "diagnose_abnormal_only", "one abnormal device")) {
  Assert-Contains -Text $matrix -Marker $marker -Context "matrix supervision reference"
}
foreach ($marker in @("automatic outbound", "outbound preflight", "target mismatch", "platform-risk prompt", "rate limit")) {
  Assert-Contains -Text $matrix -Marker $marker -Context "matrix automatic outbound reference"
}
foreach ($marker in @("weak safety gate", "routine permission", "routine mutation", "security-sensitive prompt")) {
  Assert-Contains -Text $matrix -Marker $marker -Context "matrix weak safety reference"
}

$environmentPreflight = Get-Content -Raw -Encoding UTF8 -LiteralPath (Join-Path $skillRoot "references\environment-preflight.md")
foreach ($marker in @("gateMode: weak", "routine permission grant", "without per-action confirmation", "device administrator", "accessibility service", "VPN", "unknown-source installation")) {
  Assert-Contains -Text $environmentPreflight -Marker $marker -Context "environment weak safety reference"
}

$playbooks = Get-Content -Raw -Encoding UTF8 -LiteralPath (Join-Path $skillRoot "references\builtin-playbooks.md")
foreach ($marker in @("BOSS", "acquisition", "automatic outbound", "task-level authorization", "frequency cap", "audit log")) {
  Assert-Contains -Text $playbooks -Marker $marker -Context "built-in playbooks reference"
}

$acquisition = Get-Content -Raw -Encoding UTF8 -LiteralPath (Join-Path $skillRoot "references\acquisition-workflow.md")
foreach ($marker in @(
  "acquisition agent-run --json --dry-run",
  "loom.acquisition.agent_result.v1",
  "acquisition agent-result --json --agent-result-json",
  "pending/sync_failed",
  "integration feishu status --json",
  "acquisition template save --json",
  "acquisition template retry --json",
  "outboundMode: auto",
  "publish, comment, and private message",
  "task-level authorization",
  "target scope",
  "frequency cap",
  "duplicate prevention",
  "audit log",
  "outbound_completed",
  "Never put customer secrets, tokens, real account passwords, or private lead data into templates"
)) {
  Assert-Contains -Text $acquisition -Marker $marker -Context "acquisition workflow reference"
}

$boss = Get-Content -Raw -Encoding UTF8 -LiteralPath (Join-Path $skillRoot "references\boss-resume-screening.md")
foreach ($marker in @(
  "frozen job scorecard",
  "priority_review",
  "interview_candidate",
  "manual_review",
  "lower_priority_review",
  "not_enough_info",
  "loom.hr.resume_screening.v1",
  "humanReviewRequired",
  "Never mark a candidate as finally rejected solely through automation",
  "automatic private message",
  "without per-message confirmation",
  "Keep reject and interview-invitation actions human-owned",
  "allow task-authorized archive, block, report, follow, add-contact, routine permission, and non-security profile actions"
)) {
  Assert-Contains -Text $boss -Marker $marker -Context "BOSS resume screening reference"
}

$scenarioAuthoring = Get-Content -Raw -Encoding UTF8 -LiteralPath (Join-Path $skillRoot "references\scenario-skill-authoring.md")
foreach ($marker in @(
  "scenario Skill creation or update",
  "not a separate triggerable Skill",
  "Trigger description",
  "Scenario identity",
  "Inputs",
  "Operating mode",
  "Execution loop",
  "Safety boundary",
  "Evidence",
  "Output schema",
  "Verification",
  "Template memory",
  "quick_validate.py",
  "artifact report",
  "safe_navigation",
  "blocked_by_prerequisite"
)) {
  Assert-Contains -Text $scenarioAuthoring -Marker $marker -Context "scenario Skill authoring reference"
}

$acceptance = Get-Content -Raw -Encoding UTF8 -LiteralPath (Join-Path $skillRoot "references\task-compiler.md")
$syncContract = Get-Content -Raw -Encoding UTF8 -LiteralPath (Join-Path $skillRoot "references\recipe-sync-contract.md")
foreach ($reference in @(
  @{ Name = "task compiler"; Text = $acceptance },
  @{ Name = "recipe sync contract"; Text = $syncContract }
)) {
  foreach ($marker in @(
    "status == verified",
    "verification.successCount >= 1",
    "non-empty evidence for every route step",
    "raw resumes",
    "unrelated personal data",
    "candidate creation",
    "validation",
    "privacy scan"
  )) {
    Assert-Contains -Text $reference.Text -Marker $marker -Context $reference.Name
  }
}

$validRecipe = [pscustomobject]@{
  status = "verified"
  verification = [pscustomobject]@{ successCount = 1 }
  route = @(
    [pscustomobject]@{
      stepId = "visible-step"
      verification = "verified"
      evidence = @("before:visible-step:screen-001", "after:visible-step:screen-002")
    }
  )
}
Assert-ReusableRecipe -Recipe $validRecipe -Context "Valid recipe"
foreach ($mutation in @(
  @{ Name = "missing success count"; Recipe = [pscustomobject]@{ status = "verified"; verification = [pscustomobject]@{ successCount = 0 }; route = $validRecipe.route }; Expected = "verification.successCount >= 1" },
  @{ Name = "unknown step"; Recipe = [pscustomobject]@{ status = "verified"; verification = $validRecipe.verification; route = @([pscustomobject]@{ stepId = "unknown-step"; verification = "unknown"; evidence = @("screen-003") }) }; Expected = "verification == verified" },
  @{ Name = "empty evidence"; Recipe = [pscustomobject]@{ status = "verified"; verification = $validRecipe.verification; route = @([pscustomobject]@{ stepId = "empty-evidence"; verification = "verified"; evidence = @() }) }; Expected = "non-empty evidence" }
)) {
  try {
    Assert-ReusableRecipe -Recipe $mutation.Recipe -Context $mutation.Name
    throw "Recipe mutation was accepted: $($mutation.Name)"
  } catch {
    if (-not $_.Exception.Message.Contains($mutation.Expected)) { throw }
  }
}
foreach ($mutation in @(
  @{ Name = "raw resume"; Candidate = [pscustomobject]@{ rawResume = "full resume text" }; Expected = "rawResume" },
  @{ Name = "unrelated personal data"; Candidate = [pscustomobject]@{ unrelatedPersonalData = "family status" }; Expected = "unrelatedPersonalData" }
)) {
  try {
    Assert-SafeRecipeCandidate -Candidate $mutation.Candidate -Context $mutation.Name
    throw "Recipe candidate mutation was accepted: $($mutation.Name)"
  } catch {
    if (-not $_.Exception.Message.Contains($mutation.Expected)) { throw }
  }
}

$acceptanceCases = @(
  @{ Scenario = "low-risk first launch repair"; State = "SELF_CHECK"; ResultStatus = "completed"; Resume = "none"; Prohibited = "no App installation" },
  @{ Scenario = "no connected phone"; State = "PHONE_DISCOVERY"; ResultStatus = "blocked"; Resume = "PHONE_DISCOVERY"; Prohibited = "no invented device command" },
  @{ Scenario = "one healthy phone"; State = "ASK_TASK"; ResultStatus = "completed"; Resume = "none"; Prohibited = "no matrix dispatch" },
  @{ Scenario = "multiple healthy phones"; State = "ASK_TASK"; ResultStatus = "needs_human"; Resume = "ASK_TASK"; Prohibited = "no automatic device selection" },
  @{ Scenario = "verified recipe reuse"; State = "RECIPE_MATCH"; ResultStatus = "completed"; Resume = "none"; Prohibited = "no reuse before all three gates" },
  @{ Scenario = "changed page or App version"; State = "REUSE_OR_EXPLORE"; ResultStatus = "completed"; Resume = "REUSE_OR_EXPLORE"; Prohibited = "no stale reuse" },
  @{ Scenario = "new task exploration"; State = "EXECUTE_VERIFY"; ResultStatus = "completed"; Resume = "SYNC_RECIPE"; Prohibited = "no promotion without evidence" },
  @{ Scenario = "missing prerequisite"; State = "PREFLIGHT"; ResultStatus = "blocked"; Resume = "PREFLIGHT"; Prohibited = "no prerequisite bypass" },
  @{ Scenario = "authorized automatic outbound"; State = "EXECUTE_VERIFY"; ResultStatus = "completed"; Resume = "none"; Prohibited = "no send without outbound preflight" },
  @{ Scenario = "authorized routine mutation"; State = "EXECUTE_VERIFY"; ResultStatus = "completed"; Resume = "none"; Prohibited = "no mutation outside task scope" },
  @{ Scenario = "hard-stop action"; State = "EXECUTE_VERIFY"; ResultStatus = "needs_human"; Resume = "EXECUTE_VERIFY"; Prohibited = "no action submission" },
  @{ Scenario = "three unchanged fingerprints"; State = "REUSE_OR_EXPLORE"; ResultStatus = "blocked"; Resume = "REUSE_OR_EXPLORE"; Prohibited = "no continued exploration" },
  @{ Scenario = "concurrent recipe sync"; State = "SYNC_RECIPE"; ResultStatus = "blocked"; Resume = "SYNC_RECIPE"; Prohibited = "no unlocked write" },
  @{ Scenario = "sensitive recipe content"; State = "SYNC_RECIPE"; ResultStatus = "blocked"; Resume = "PLAN"; Prohibited = "no candidate write" },
  @{ Scenario = "source-install-ZIP parity"; State = "REPORT"; ResultStatus = "completed"; Resume = "later packaging task"; Prohibited = "no parity claim" },
  @{ Scenario = "legacy Skill transition"; State = "REPORT"; ResultStatus = "completed"; Resume = "later migration task"; Prohibited = "no legacy removal" }
)
foreach ($case in $acceptanceCases) {
  Assert-AcceptanceRow -Text $acceptance -Scenario $case.Scenario -State $case.State -ResultStatus $case.ResultStatus -ResumeBehavior $case.Resume -ProhibitedAction $case.Prohibited
}

$examplePaths = @(
  "examples\self-check-ready.json",
  "examples\self-check-blocked.json",
  "examples\task-plan.json",
  "examples\sync-result.json"
)
$examples = @()
foreach ($relativePath in $examplePaths) {
  try {
    $examples += Get-Content -Raw -Encoding UTF8 -LiteralPath (Join-Path $skillRoot $relativePath) | ConvertFrom-Json
  } catch {
    throw "Invalid JSON example: $relativePath ($($_.Exception.Message))"
  }
}

$schemas = @($examples | ForEach-Object { $_.schema })
if (@($schemas | Select-Object -Unique).Count -ne $examples.Count) {
  throw "Each example must use a unique schema"
}
foreach ($example in $examples) {
  Assert-Fields -Value $example -Fields @("schema", "requiresHumanReview") -Context "Example $($example.schema)"
  Assert-Boolean -Value $example.requiresHumanReview -Context "Example $($example.schema) requiresHumanReview"
}

$ready = $examples | Where-Object { $_.schema -eq "loom.phone-agent.self-check.v1" -and $_.status -eq "ready" }
if (@($ready).Count -ne 1) { throw "Ready self-check example is missing" }
Assert-Boolean -Value $ready.healthy -Context "Ready self-check healthy"

$blocked = $examples | Where-Object { $_.schema -eq "loom.phone-agent.self-check-blocked.v1" }
if (@($blocked).Count -ne 1) { throw "Blocked self-check example is missing" }
Assert-Boolean -Value $blocked.healthy -Context "Blocked self-check healthy"
if ($blocked.healthy -ne $false -or -not $blocked.resumeFrom) {
  throw "Blocked self-check must be unhealthy and resumable"
}

$taskPlan = $examples | Where-Object { $_.schema -eq "loom.phone-agent.task-plan.v1" }
if (@($taskPlan).Count -ne 1) { throw "Task plan example has the wrong schema" }
Assert-Boolean -Value $taskPlan.requiresHumanReview -Context "Task plan requiresHumanReview"
Assert-Boolean -Value $taskPlan.matrix -Context "Task plan matrix"
Assert-Fields -Value $taskPlan -Fields @("requiresHumanConfirmation") -Context "Task plan"
Assert-Boolean -Value $taskPlan.requiresHumanConfirmation -Context "Task plan requiresHumanConfirmation"
Assert-Fields -Value $taskPlan -Fields @("gateMode", "automaticActions", "mutationPolicy", "outboundMode", "outboundChannels", "outboundPolicy") -Context "Task plan weak gate"
if ($taskPlan.gateMode -cne "weak") { throw "Task plan gateMode must be weak" }
Assert-StringSetEqual -Expected @("publish", "comment", "private_message", "routine_permission", "delete", "archive", "block", "report", "follow", "unfollow", "add_contact", "non_security_profile_change") -Actual @($taskPlan.automaticActions) -Context "Task plan automatic actions"
Assert-Fields -Value $taskPlan.mutationPolicy -Fields @("taskAuthorized", "targetScope", "auditLog", "stopOn") -Context "Task plan mutation policy"
Assert-Boolean -Value $taskPlan.mutationPolicy.taskAuthorized -Context "Task plan mutation taskAuthorized"
Assert-Boolean -Value $taskPlan.mutationPolicy.auditLog -Context "Task plan mutation auditLog"
if ($taskPlan.outboundMode -cne "auto") { throw "Task plan outboundMode must be auto" }
Assert-StringSetEqual -Expected @("publish", "comment", "private_message") -Actual @($taskPlan.outboundChannels) -Context "Task plan outbound channels"
Assert-Fields -Value $taskPlan.outboundPolicy -Fields @("taskAuthorized", "accountScope", "targetScope", "contentPolicy", "frequencyCap", "duplicatePrevention", "auditLog", "successEvidence", "stopOn") -Context "Task plan outbound policy"
Assert-Boolean -Value $taskPlan.outboundPolicy.taskAuthorized -Context "Task plan outbound taskAuthorized"
Assert-Boolean -Value $taskPlan.outboundPolicy.duplicatePrevention -Context "Task plan outbound duplicatePrevention"
Assert-Boolean -Value $taskPlan.outboundPolicy.auditLog -Context "Task plan outbound auditLog"

$sync = $examples | Where-Object { $_.schema -eq "loom.phone-agent.recipe-sync-result.v1" }
if (@($sync).Count -ne 1) { throw "Sync example has the wrong schema" }
Assert-Boolean -Value $sync.sourceAndInstallMatch -Context "Sync sourceAndInstallMatch"

Write-Output "luming-phone-agent contract ok"
