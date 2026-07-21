[CmdletBinding()]
param(
    [switch]$Json
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'workspace-core.ps1')

$root = Get-LoomWorkspaceRoot
Assert-LoomGitRepository -Path $root
& git -C $root fetch origin --prune
if ($LASTEXITCODE -ne 0) {
    throw 'Fetch failed for the LOOM monorepo.'
}

$remote = (& git -C $root remote get-url origin).Trim()
$result = [PSCustomObject]@{
    schema = 'loom.engineering.sync.v2'
    repository = $remote
    fetched = $true
}

if ($Json) {
    $result | ConvertTo-Json -Depth 3
} else {
    $result | Format-List repository, fetched
}
