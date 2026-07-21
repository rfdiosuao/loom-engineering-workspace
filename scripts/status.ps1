[CmdletBinding()]
param(
    [switch]$Json
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'workspace-core.ps1')

$root = Get-LoomWorkspaceRoot
Assert-LoomGitRepository -Path $root

$branch = (& git -C $root branch --show-current).Trim()
$dirtyLines = @(& git -C $root status --porcelain)
$upstream = (& git -C $root rev-parse --abbrev-ref '@{upstream}' 2>$null)
$ahead = 0
$behind = 0
if ($LASTEXITCODE -eq 0 -and -not [string]::IsNullOrWhiteSpace($upstream)) {
    $counts = ((& git -C $root rev-list --left-right --count "HEAD...$($upstream.Trim())").Trim() -split '\s+')
    if ($counts.Count -eq 2) {
        $ahead = [int]$counts[0]
        $behind = [int]$counts[1]
    }
}

$worktrees = @()
foreach ($line in @(& git -C $root worktree list --porcelain)) {
    if ($line.StartsWith('worktree ')) {
        $worktrees += $line.Substring(9)
    }
}

$components = @(Get-LoomComponentNames | ForEach-Object {
    $component = Get-LoomComponent -Name $_
    [PSCustomObject]@{
        name = $component.Name
        path = $component.RelativePath
        exists = Test-Path -LiteralPath $component.Path -PathType Container
    }
})

$result = [PSCustomObject]@{
    schema = 'loom.engineering.status.v2'
    repository = $root
    branch = $branch
    clean = $dirtyLines.Count -eq 0
    changedFiles = $dirtyLines.Count
    upstream = if ($upstream) { $upstream.Trim() } else { $null }
    ahead = $ahead
    behind = $behind
    worktrees = $worktrees
    components = $components
}

if ($Json) {
    $result | ConvertTo-Json -Depth 6
    exit 0
}

Write-Host ''
Write-Host 'LOOM Monorepo' -ForegroundColor Cyan
Write-Host $root -ForegroundColor DarkGray
Write-Host "Branch: $branch | Clean: $($result.clean) | Changes: $($result.changedFiles) | Ahead: $ahead | Behind: $behind"
Write-Host ''
$components | Format-Table name, path, exists -AutoSize
Write-Host "Registered worktrees: $($worktrees.Count)"
