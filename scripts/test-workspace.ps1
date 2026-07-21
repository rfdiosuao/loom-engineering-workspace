Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'workspace-core.ps1')

$script:Passed = 0

function Assert-Workspace {
    param(
        [bool]$Condition,
        [string]$Message
    )

    if (-not $Condition) {
        throw "Assertion failed: $Message"
    }
    $script:Passed += 1
}

$root = Get-LoomWorkspaceRoot
Assert-Workspace -Condition (Test-Path -LiteralPath (Join-Path $root 'workspace.json')) -Message 'workspace.json exists'
Assert-Workspace -Condition (Test-Path -LiteralPath (Join-Path $root '.githooks\pre-push')) -Message 'versioned pre-push hook exists'
Assert-Workspace -Condition (Test-LoomPathWithinRoot -Path (Join-Path $root 'apps')) -Message 'apps is inside workspace'
Assert-Workspace -Condition (-not (Test-LoomPathWithinRoot -Path (Join-Path $root '..\outside'))) -Message 'outside path is rejected'
$hubGitCommonDir = (& git -C $root rev-parse --path-format=absolute --git-common-dir).Trim()
$expectedHookPath = (Join-Path (Split-Path $hubGitCommonDir -Parent) '.githooks').Replace('\', '/')
$sharedWorkspaceRoot = Split-Path $hubGitCommonDir -Parent
$hubHookPath = (& git -C $root config --get core.hooksPath).Trim()
Assert-Workspace -Condition ($hubHookPath -eq $expectedHookPath) -Message 'hub uses versioned Git hooks'

$schemaRoot = Join-Path $root 'packages\contracts\schemas'
$requiredSchemas = @(
    'realtime-event.v1.schema.json',
    'matrix-dispatch.v2.schema.json',
    'matrix-campaign.v2.schema.json',
    'agent-session.v1.schema.json',
    'agent-approval.v1.schema.json'
)
foreach ($name in $requiredSchemas) {
    $path = Join-Path $schemaRoot $name
    Assert-Workspace -Condition (Test-Path -LiteralPath $path -PathType Leaf) -Message "$name exists"
    $document = Get-Content -LiteralPath $path -Raw -Encoding UTF8 | ConvertFrom-Json
    Assert-Workspace -Condition (-not [string]::IsNullOrWhiteSpace($document.'$id')) -Message "$name has an id"
}

$contractValidator = Join-Path $root 'packages\contracts\validate_contracts.py'
Assert-Workspace -Condition (Test-Path -LiteralPath $contractValidator -PathType Leaf) -Message 'validate_contracts.py exists'
& python -B $contractValidator
Assert-Workspace -Condition ($LASTEXITCODE -eq 0) -Message 'contract schemas and fixtures validate'

foreach ($scriptFile in Get-ChildItem -LiteralPath $PSScriptRoot -Filter '*.ps1' -File) {
    $tokens = $null
    $parseErrors = $null
    [System.Management.Automation.Language.Parser]::ParseFile($scriptFile.FullName, [ref]$tokens, [ref]$parseErrors) | Out-Null
    Assert-Workspace -Condition ($parseErrors.Count -eq 0) -Message "$($scriptFile.Name) parses without errors"
}

$workspaceConfig = Get-LoomWorkspaceConfig
foreach ($name in Get-LoomRepositoryNames) {
    $repo = Get-LoomRepository -Name $name
    $repositoryEntry = $workspaceConfig.repositories.PSObject.Properties[$name].Value
    $repositoryPath = Join-Path $sharedWorkspaceRoot $repositoryEntry.path
    Assert-Workspace -Condition (Test-Path -LiteralPath $repositoryPath -PathType Container) -Message "$name directory exists"
    Assert-LoomGitRepository -Path $repositoryPath
    $origin = (& git -C $repositoryPath remote get-url origin).Trim()
    Assert-Workspace -Condition ($origin -eq $repo.Remote) -Message "$name origin is private source of truth"
    $repositoryWorktreeRoot = Join-Path $sharedWorkspaceRoot "worktrees\$name"
    Assert-Workspace -Condition (Test-LoomPathWithinRoot -Path $repositoryWorktreeRoot -Root $sharedWorkspaceRoot) -Message "$name worktrees stay inside workspace"
    $repositoryHookPath = (& git -C $repositoryPath config --get core.hooksPath).Trim()
    Assert-Workspace -Condition ($repositoryHookPath -eq $expectedHookPath) -Message "$name uses versioned Git hooks"
}

$spec = Get-LoomFeatureSpec -Repository platform -Issue 101 -Name 'Matrix Device Assignments'
Assert-Workspace -Condition ($spec.Branch -eq 'codex/101-matrix-device-assignments') -Message 'feature branch naming is deterministic'
Assert-Workspace -Condition ($spec.WorktreePath.EndsWith('worktrees\platform\101-matrix-device-assignments')) -Message 'feature worktree path is deterministic'

$ignoredPaths = @(
    'worktrees\platform\probe',
    'artifacts\probe',
    '.gradle-apkclaw-qa\probe',
    'probe.apk',
    'probe.jks',
    'probe.log',
    'local.properties'
)
foreach ($path in $ignoredPaths) {
    & git -C $root check-ignore --quiet -- $path
    Assert-Workspace -Condition ($LASTEXITCODE -eq 0) -Message "$path is ignored"
}

$dryRunJson = & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root 'scripts\new-feature.ps1') -Repository platform -Issue 101 -Name 'Matrix Device Assignments' -DryRun -Json
$dryRun = $dryRunJson | ConvertFrom-Json
Assert-Workspace -Condition ($dryRun.dryRun -eq $true) -Message 'new-feature dry run does not mutate Git'
Assert-Workspace -Condition ($dryRun.branch -eq 'codex/101-matrix-device-assignments') -Message 'new-feature dry run returns expected branch'
Assert-Workspace -Condition ($dryRun.baseBranch -eq 'codex/18-stability-spine') -Message 'platform worktrees use the active stability baseline'

$requiredDocs = @(
    'docs\DEVELOPMENT_WIKI.md',
    'docs\runbooks\repository-hygiene.md'
)
foreach ($path in $requiredDocs) {
    Assert-Workspace -Condition (Test-Path -LiteralPath (Join-Path $root $path) -PathType Leaf) -Message "$path exists"
}

Write-Host "Workspace tests passed: $script:Passed" -ForegroundColor Green
