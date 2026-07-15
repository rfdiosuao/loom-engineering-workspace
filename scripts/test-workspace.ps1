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
$expectedHookPath = (Join-Path $root '.githooks').Replace('\', '/')
$hubHookPath = (& git -C $root config --get core.hooksPath).Trim()
Assert-Workspace -Condition ($hubHookPath -eq $expectedHookPath) -Message 'hub uses versioned Git hooks'

foreach ($scriptFile in Get-ChildItem -LiteralPath $PSScriptRoot -Filter '*.ps1' -File) {
    $tokens = $null
    $parseErrors = $null
    [System.Management.Automation.Language.Parser]::ParseFile($scriptFile.FullName, [ref]$tokens, [ref]$parseErrors) | Out-Null
    Assert-Workspace -Condition ($parseErrors.Count -eq 0) -Message "$($scriptFile.Name) parses without errors"
}

foreach ($name in Get-LoomRepositoryNames) {
    $repo = Get-LoomRepository -Name $name
    Assert-Workspace -Condition (Test-Path -LiteralPath $repo.Path -PathType Container) -Message "$name directory exists"
    Assert-LoomGitRepository -Path $repo.Path
    $origin = (& git -C $repo.Path remote get-url origin).Trim()
    Assert-Workspace -Condition ($origin -eq $repo.Remote) -Message "$name origin is private source of truth"
    Assert-Workspace -Condition (Test-LoomPathWithinRoot -Path $repo.WorktreeRoot) -Message "$name worktrees stay inside workspace"
    $repositoryHookPath = (& git -C $repo.Path config --get core.hooksPath).Trim()
    Assert-Workspace -Condition ($repositoryHookPath -eq $expectedHookPath) -Message "$name uses versioned Git hooks"
}

$spec = Get-LoomFeatureSpec -Repository platform -Issue 101 -Name 'Matrix Device Assignments'
Assert-Workspace -Condition ($spec.Branch -eq 'codex/101-matrix-device-assignments') -Message 'feature branch naming is deterministic'
Assert-Workspace -Condition ($spec.WorktreePath.EndsWith('worktrees\platform\101-matrix-device-assignments')) -Message 'feature worktree path is deterministic'

$ignoredPaths = @(
    'worktrees\platform\probe',
    'artifacts\probe',
    'probe.apk',
    'probe.jks',
    'probe.log',
    'local.properties'
)
foreach ($path in $ignoredPaths) {
    & git -C $root check-ignore --quiet -- $path
    Assert-Workspace -Condition ($LASTEXITCODE -eq 0) -Message "$path is ignored"
}

$dryRunJson = & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'new-feature.ps1') -Repository platform -Issue 101 -Name 'Matrix Device Assignments' -DryRun -Json
$dryRun = $dryRunJson | ConvertFrom-Json
Assert-Workspace -Condition ($dryRun.dryRun -eq $true) -Message 'new-feature dry run does not mutate Git'
Assert-Workspace -Condition ($dryRun.branch -eq 'codex/101-matrix-device-assignments') -Message 'new-feature dry run returns expected branch'

Write-Host "Workspace tests passed: $script:Passed" -ForegroundColor Green
