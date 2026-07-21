[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('platform', 'phone')]
    [string]$Repository,

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

$repo = Get-LoomRepository -Name $Repository
$spec = Get-LoomFeatureSpec -Repository $Repository -Issue $Issue -Name $Name -BaseBranch $BaseBranch
Assert-LoomGitRepository -Path $repo.Path

$relativeWorktree = $spec.RelativeWorktreePath
& git -C (Get-LoomWorkspaceRoot) check-ignore --quiet -- $relativeWorktree
if ($LASTEXITCODE -ne 0) {
    throw "Worktree path is not ignored by the hub repository: $relativeWorktree"
}

if (-not $DryRun) {
    $dirty = @(& git -C $repo.Path status --porcelain)
    if ($dirty.Count -ne 0) {
        throw "Repository checkout is not clean: $($repo.Path)"
    }

    & git -C $repo.Path show-ref --verify --quiet "refs/heads/$($spec.Branch)"
    if ($LASTEXITCODE -eq 0) {
        throw "Local branch already exists: $($spec.Branch)"
    }

    if (Test-Path -LiteralPath $spec.WorktreePath) {
        throw "Worktree path already exists: $($spec.WorktreePath)"
    }

    & git -C $repo.Path fetch origin $spec.BaseBranch
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to fetch origin/$($spec.BaseBranch)"
    }

    $parent = Split-Path -Parent $spec.WorktreePath
    New-Item -ItemType Directory -Path $parent -Force | Out-Null
    if ($PSCmdlet.ShouldProcess($spec.WorktreePath, "Create $($spec.Branch) from origin/$($spec.BaseBranch)")) {
        & git -C $repo.Path worktree add -b $spec.Branch $spec.WorktreePath "origin/$($spec.BaseBranch)"
        if ($LASTEXITCODE -ne 0) {
            throw "Git worktree creation failed: $($spec.WorktreePath)"
        }
    }
}

$result = [PSCustomObject]@{
    schema = 'loom.engineering.feature_worktree.v1'
    dryRun = [bool]$DryRun
    repository = $spec.Repository
    baseBranch = $spec.BaseBranch
    branch = $spec.Branch
    worktreePath = $spec.WorktreePath
}

if ($Json) {
    $result | ConvertTo-Json -Depth 4
} else {
    Write-Host "Repository : $($result.repository)"
    Write-Host "Base       : $($result.baseBranch)"
    Write-Host "Branch     : $($result.branch)"
    Write-Host "Worktree   : $($result.worktreePath)"
    Write-Host "Dry run    : $($result.dryRun)"
}
