[CmdletBinding()]
param(
    [switch]$Json
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'workspace-core.ps1')

function Get-RepositoryStatus {
    param([string]$Name)

    $repo = Get-LoomRepository -Name $Name
    Assert-LoomGitRepository -Path $repo.Path

    $branch = (& git -C $repo.Path branch --show-current).Trim()
    $dirtyLines = @(& git -C $repo.Path status --porcelain)
    $upstream = (& git -C $repo.Path rev-parse --abbrev-ref '@{upstream}' 2>$null)
    $ahead = 0
    $behind = 0
    if ($LASTEXITCODE -eq 0 -and -not [string]::IsNullOrWhiteSpace($upstream)) {
        $counts = ((& git -C $repo.Path rev-list --left-right --count "HEAD...$upstream").Trim() -split '\s+')
        if ($counts.Count -eq 2) {
            $ahead = [int]$counts[0]
            $behind = [int]$counts[1]
        }
    }

    $worktreePaths = @($repo.Path)
    foreach ($line in @(& git -C $repo.Path worktree list --porcelain)) {
        if ($line.StartsWith('worktree ')) {
            $candidate = [System.IO.Path]::GetFullPath($line.Substring(9))
            if ($candidate.StartsWith($repo.WorktreeRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
                $worktreePaths += $candidate
            }
        }
    }

    return [PSCustomObject]@{
        repository = $Name
        branch = $branch
        clean = $dirtyLines.Count -eq 0
        changedFiles = $dirtyLines.Count
        upstream = if ($upstream) { $upstream.Trim() } else { $null }
        ahead = $ahead
        behind = $behind
        worktrees = $worktreePaths
        path = $repo.Path
    }
}

$repositories = @(Get-LoomRepositoryNames | ForEach-Object { Get-RepositoryStatus -Name $_ })
$hubChanges = @(& git -C (Get-LoomWorkspaceRoot) status --porcelain).Count
$result = [PSCustomObject]@{
    schema = 'loom.engineering.status.v1'
    workspace = Get-LoomWorkspaceRoot
    hubChangedFiles = $hubChanges
    repositories = $repositories
}

if ($Json) {
    $result | ConvertTo-Json -Depth 6
    exit 0
}

Write-Host ''
Write-Host 'LOOM Engineering Workspace' -ForegroundColor Cyan
Write-Host (Get-LoomWorkspaceRoot) -ForegroundColor DarkGray
Write-Host ''
$repositories |
    Select-Object @{Name = 'Repository'; Expression = { $_.repository } },
        @{Name = 'Branch'; Expression = { $_.branch } },
        @{Name = 'Clean'; Expression = { $_.clean } },
        @{Name = 'Changes'; Expression = { $_.changedFiles } },
        @{Name = 'Ahead'; Expression = { $_.ahead } },
        @{Name = 'Behind'; Expression = { $_.behind } },
        @{Name = 'Worktrees'; Expression = { $_.worktrees.Count } } |
    Format-Table -AutoSize
Write-Host "Hub changed files: $hubChanges"
