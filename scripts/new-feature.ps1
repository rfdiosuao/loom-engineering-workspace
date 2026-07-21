[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [Parameter(Mandatory = $true)]
    [Alias('Repository')]
    [ValidateSet('platform', 'phone', 'contracts', 'skills', 'docs', 'cross-cutting')]
    [string]$Area,

    [Parameter(Mandatory = $true)]
    [ValidateRange(1, 2147483647)]
    [int]$Issue,

    [Parameter(Mandatory = $true)]
    [string]$Name,

    [string]$BaseBranch,

    [switch]$DryRun,

    [switch]$Json
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'workspace-core.ps1')

$root = Get-LoomWorkspaceRoot
$spec = Get-LoomFeatureSpec -Area $Area -Issue $Issue -Name $Name -BaseBranch $BaseBranch
Assert-LoomGitRepository -Path $root

$ignoreProbe = ($spec.RelativeWorktreePath -replace '\\', '/')
& git -C $root check-ignore --quiet -- $ignoreProbe
if ($LASTEXITCODE -ne 0) {
    throw "Worktree path is not ignored by the monorepo: $ignoreProbe"
}

if (-not $DryRun) {
    $dirty = @(& git -C $root status --porcelain)
    if ($dirty.Count -ne 0) {
        throw "Monorepo checkout is not clean: $root"
    }

    & git -C $root show-ref --verify --quiet "refs/heads/$($spec.Branch)"
    if ($LASTEXITCODE -eq 0) {
        throw "Local branch already exists: $($spec.Branch)"
    }

    if (Test-Path -LiteralPath $spec.WorktreePath) {
        throw "Worktree path already exists: $($spec.WorktreePath)"
    }

    & git -C $root fetch origin $spec.BaseBranch
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to fetch origin/$($spec.BaseBranch)"
    }

    $parent = Split-Path -Parent $spec.WorktreePath
    New-Item -ItemType Directory -Path $parent -Force | Out-Null
    if ($PSCmdlet.ShouldProcess($spec.WorktreePath, "Create $($spec.Branch) from origin/$($spec.BaseBranch)")) {
        & git -C $root worktree add -b $spec.Branch $spec.WorktreePath "origin/$($spec.BaseBranch)"
        if ($LASTEXITCODE -ne 0) {
            throw "Git worktree creation failed: $($spec.WorktreePath)"
        }
    }
}

$result = [PSCustomObject]@{
    schema = 'loom.engineering.feature_worktree.v2'
    dryRun = [bool]$DryRun
    area = $spec.Area
    baseBranch = $spec.BaseBranch
    branch = $spec.Branch
    worktreePath = $spec.WorktreePath
}

if ($Json) {
    $result | ConvertTo-Json -Depth 4
} else {
    Write-Host "Area       : $($result.area)"
    Write-Host "Base       : $($result.baseBranch)"
    Write-Host "Branch     : $($result.branch)"
    Write-Host "Worktree   : $($result.worktreePath)"
    Write-Host "Dry run    : $($result.dryRun)"
}
