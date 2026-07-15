[CmdletBinding()]
param(
    [ValidateSet('all', 'platform', 'phone')]
    [string]$Repository = 'all',

    [switch]$Json
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'workspace-core.ps1')

$names = if ($Repository -eq 'all') { @(Get-LoomRepositoryNames) } else { @($Repository) }
$results = @()
foreach ($name in $names) {
    $repo = Get-LoomRepository -Name $name
    Assert-LoomGitRepository -Path $repo.Path
    & git -C $repo.Path fetch origin --prune
    if ($LASTEXITCODE -ne 0) {
        throw "Fetch failed for $name"
    }
    $results += [PSCustomObject]@{
        repository = $name
        remote = $repo.Remote
        fetched = $true
    }
}

if ($Json) {
    [PSCustomObject]@{
        schema = 'loom.engineering.sync.v1'
        results = $results
    } | ConvertTo-Json -Depth 4
} else {
    $results | Format-Table repository, fetched, remote -AutoSize
}
