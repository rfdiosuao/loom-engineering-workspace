Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$script:LoomWorkspaceRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$script:LoomManifestPath = Join-Path $script:LoomWorkspaceRoot 'workspace.json'

function Get-LoomWorkspaceRoot {
    return $script:LoomWorkspaceRoot
}

function Get-LoomWorkspaceConfig {
    if (-not (Test-Path -LiteralPath $script:LoomManifestPath -PathType Leaf)) {
        throw "Workspace manifest not found: $script:LoomManifestPath"
    }

    return Get-Content -LiteralPath $script:LoomManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
}

function Get-LoomRepositoryNames {
    $config = Get-LoomWorkspaceConfig
    return @($config.repositories.PSObject.Properties.Name)
}

function Test-LoomPathWithinRoot {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,

        [string]$Root = $script:LoomWorkspaceRoot
    )

    $rootPath = [System.IO.Path]::GetFullPath($Root).TrimEnd('\', '/') + [System.IO.Path]::DirectorySeparatorChar
    $candidate = [System.IO.Path]::GetFullPath($Path)
    return $candidate.StartsWith($rootPath, [System.StringComparison]::OrdinalIgnoreCase)
}

function Get-LoomRepository {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name
    )

    $config = Get-LoomWorkspaceConfig
    $property = $config.repositories.PSObject.Properties[$Name]
    if ($null -eq $property) {
        $valid = (Get-LoomRepositoryNames) -join ', '
        throw "Unknown repository '$Name'. Valid values: $valid"
    }

    $entry = $property.Value
    $path = [System.IO.Path]::GetFullPath((Join-Path $script:LoomWorkspaceRoot $entry.path))
    if (-not (Test-LoomPathWithinRoot -Path $path)) {
        throw "Repository path escapes workspace: $path"
    }

    return [PSCustomObject]@{
        Name = $Name
        Path = $path
        Remote = [string]$entry.remote
        BaselineBranch = [string]$entry.baselineBranch
        WorktreeRoot = [System.IO.Path]::GetFullPath((Join-Path $script:LoomWorkspaceRoot "worktrees\$Name"))
        Verify = @($entry.verify)
    }
}

function Assert-LoomGitRepository {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    if (-not (Test-Path -LiteralPath $Path -PathType Container)) {
        throw "Repository directory not found: $Path"
    }

    & git -C $Path rev-parse --is-inside-work-tree *> $null
    if ($LASTEXITCODE -ne 0) {
        throw "Not a Git repository: $Path"
    }
}

function ConvertTo-LoomFeatureSlug {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name
    )

    $slug = $Name.Trim().ToLowerInvariant()
    $slug = [System.Text.RegularExpressions.Regex]::Replace($slug, '[^a-z0-9]+', '-')
    $slug = $slug.Trim('-')
    if ([string]::IsNullOrWhiteSpace($slug)) {
        throw 'Feature name must contain at least one ASCII letter or number.'
    }
    if ($slug.Length -gt 48) {
        throw 'Feature slug must be 48 characters or fewer.'
    }
    return $slug
}

function Get-LoomFeatureSpec {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Repository,

        [Parameter(Mandatory = $true)]
        [ValidateRange(1, 2147483647)]
        [int]$Issue,

        [Parameter(Mandatory = $true)]
        [string]$Name,

        [string]$BaseBranch
    )

    $repo = Get-LoomRepository -Name $Repository
    $slug = ConvertTo-LoomFeatureSlug -Name $Name
    if ([string]::IsNullOrWhiteSpace($BaseBranch)) {
        $BaseBranch = $repo.BaselineBranch
    }

    $leaf = "$Issue-$slug"
    $worktreePath = [System.IO.Path]::GetFullPath((Join-Path $repo.WorktreeRoot $leaf))
    if (-not (Test-LoomPathWithinRoot -Path $worktreePath)) {
        throw "Worktree path escapes workspace: $worktreePath"
    }

    return [PSCustomObject]@{
        Repository = $repo.Name
        RepositoryPath = $repo.Path
        BaseBranch = $BaseBranch
        Branch = "codex/$leaf"
        RelativeWorktreePath = "worktrees\$($repo.Name)\$leaf"
        WorktreePath = $worktreePath
    }
}
