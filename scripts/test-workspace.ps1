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

function Normalize-GitRemote {
    param([string]$Remote)
    return $Remote.Trim().TrimEnd('/').ToLowerInvariant() -replace '\.git$', ''
}

$root = Get-LoomWorkspaceRoot
$config = Get-LoomWorkspaceConfig
Assert-LoomGitRepository -Path $root

Assert-Workspace -Condition ($config.schema -eq 'loom.engineering.monorepo.v2') -Message 'workspace uses monorepo schema v2'
Assert-Workspace -Condition (-not (Test-Path -LiteralPath (Join-Path $root '.gitmodules'))) -Message '.gitmodules is absent'
Assert-Workspace -Condition (Test-Path -LiteralPath (Join-Path $root '.githooks\pre-push') -PathType Leaf) -Message 'versioned pre-push hook exists'
Assert-Workspace -Condition (Test-LoomPathWithinRoot -Path (Join-Path $root 'apps')) -Message 'apps is inside workspace'
Assert-Workspace -Condition (-not (Test-LoomPathWithinRoot -Path (Join-Path $root '..\outside'))) -Message 'outside path is rejected'

$gitlinks = @(& git -C $root ls-files -s | Where-Object { $_ -match '^160000\s' })
Assert-Workspace -Condition ($gitlinks.Count -eq 0) -Message 'repository contains no Gitlink entries'

$origin = (& git -C $root remote get-url origin).Trim()
Assert-Workspace -Condition ((Normalize-GitRemote $origin) -eq (Normalize-GitRemote $config.repository)) -Message 'origin is the canonical monorepo'

foreach ($name in Get-LoomComponentNames) {
    $component = Get-LoomComponent -Name $name
    Assert-Workspace -Condition (Test-Path -LiteralPath $component.Path -PathType Container) -Message "$name component exists"
}

foreach ($componentName in @('platform', 'phone')) {
    $component = Get-LoomComponent -Name $componentName
    Assert-Workspace -Condition (-not (Test-Path -LiteralPath (Join-Path $component.Path '.git'))) -Message "$componentName is not a nested Git repository"
}

$spec = Get-LoomFeatureSpec -Area platform -Issue 101 -Name 'Matrix Device Assignments'
Assert-Workspace -Condition ($spec.Branch -eq 'codex/101-matrix-device-assignments') -Message 'feature branch naming is deterministic'
Assert-Workspace -Condition ($spec.WorktreePath.EndsWith('worktrees\features\101-matrix-device-assignments')) -Message 'feature worktree path is deterministic'
Assert-Workspace -Condition ($spec.BaseBranch -eq 'main') -Message 'feature worktrees use main by default'

$ignoredPaths = @(
    'worktrees/features/probe',
    'artifacts/probe',
    '.gradle-apkclaw-qa/probe',
    'probe.apk',
    'probe.jks',
    'probe.log',
    'apps/loom-phone-agent/local.properties'
)
foreach ($path in $ignoredPaths) {
    & git -C $root check-ignore --quiet -- $path
    Assert-Workspace -Condition ($LASTEXITCODE -eq 0) -Message "$path is ignored"
}

$dryRunJson = & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root 'scripts\new-feature.ps1') -Area platform -Issue 101 -Name 'Matrix Device Assignments' -DryRun -Json
$dryRun = $dryRunJson | ConvertFrom-Json
Assert-Workspace -Condition ($dryRun.dryRun -eq $true) -Message 'new-feature dry run does not mutate Git'
Assert-Workspace -Condition ($dryRun.area -eq 'platform') -Message 'new-feature records the ownership area'
Assert-Workspace -Condition ($dryRun.branch -eq 'codex/101-matrix-device-assignments') -Message 'new-feature dry run returns expected branch'
Assert-Workspace -Condition ($dryRun.baseBranch -eq 'main') -Message 'new-feature uses the monorepo default branch'

$requiredDocs = @(
    'LICENSE',
    'LICENSE-COMMERCIAL.md',
    'THIRD_PARTY_NOTICES.md',
    'docs\DEVELOPMENT_WIKI.md',
    'docs\runbooks\repository-hygiene.md',
    'docs\decisions\0002-single-repository-monorepo.md',
    'docs\migration\MONOREPO_CUTOVER_20260722.md'
)
foreach ($path in $requiredDocs) {
    Assert-Workspace -Condition (Test-Path -LiteralPath (Join-Path $root $path) -PathType Leaf) -Message "$path exists"
}

$license = Get-Content -LiteralPath (Join-Path $root 'LICENSE') -Raw
$commercialLicense = Get-Content -LiteralPath (Join-Path $root 'LICENSE-COMMERCIAL.md') -Raw
$thirdPartyNotices = Get-Content -LiteralPath (Join-Path $root 'THIRD_PARTY_NOTICES.md') -Raw
$launcherPackage = Get-Content -LiteralPath (Join-Path $root 'apps\loom-platform\openclaw_new_launcher\package.json') -Raw | ConvertFrom-Json
$pullRequestTemplate = Get-Content -LiteralPath (Join-Path $root '.github\PULL_REQUEST_TEMPLATE.md') -Raw

Assert-Workspace -Condition ($license.Contains('GNU AFFERO GENERAL PUBLIC LICENSE')) -Message 'root license is GNU AGPL'
Assert-Workspace -Condition ($commercialLicense.Contains('separate commercial license')) -Message 'commercial alternative is documented'
Assert-Workspace -Condition ($thirdPartyNotices.Contains('apps/loom-phone-agent')) -Message 'phone-agent upstream exception is documented'
Assert-Workspace -Condition ($launcherPackage.license -eq 'AGPL-3.0-only') -Message 'launcher package declares AGPL-3.0-only'
Assert-Workspace -Condition ($pullRequestTemplate.Contains('AGPL-3.0-only')) -Message 'pull requests record dual-license contribution consent'

Write-Host "Workspace tests passed: $script:Passed" -ForegroundColor Green
