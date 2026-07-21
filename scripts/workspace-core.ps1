Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$script:LoomWorkspaceRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$script:LoomManifestPath = Join-Path $script:LoomWorkspaceRoot 'workspace.json'

function Get-LoomWorkspaceRoot {
    return $script:LoomWorkspaceRoot
}

function Get-LoomSharedWorkspaceRoot {
    $commonDir = (& git -C $script:LoomWorkspaceRoot rev-parse --path-format=absolute --git-common-dir 2>$null)
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($commonDir)) {
        return $script:LoomWorkspaceRoot
    }

    $commonPath = [System.IO.Path]::GetFullPath($commonDir.Trim())
    return [System.IO.Path]::GetFullPath((Split-Path $commonPath -Parent))
}

function Get-LoomWorkspaceConfig {
    if (-not (Test-Path -LiteralPath $script:LoomManifestPath -PathType Leaf)) {
        throw "Workspace manifest not found: $script:LoomManifestPath"
    }

    $config = Get-Content -LiteralPath $script:LoomManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($config.schema -ne 'loom.engineering.monorepo.v2') {
        throw "Unsupported workspace schema: $($config.schema)"
    }
    return $config
}

function Get-LoomComponentNames {
    $config = Get-LoomWorkspaceConfig
    return @($config.components.PSObject.Properties.Name)
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

function Get-LoomComponent {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name
    )

    $config = Get-LoomWorkspaceConfig
    $property = $config.components.PSObject.Properties[$Name]
    if ($null -eq $property) {
        $valid = (Get-LoomComponentNames) -join ', '
        throw "Unknown component '$Name'. Valid values: $valid"
    }

    $entry = $property.Value
    $path = [System.IO.Path]::GetFullPath((Join-Path $script:LoomWorkspaceRoot $entry.path))
    if (-not (Test-LoomPathWithinRoot -Path $path)) {
        throw "Component path escapes workspace: $path"
    }

    return [PSCustomObject]@{
        Name = $Name
        RelativePath = [string]$entry.path
        Path = $path
        Description = [string]$entry.description
    }
}

# Compatibility aliases for older local automation. These now return monorepo components.
function Get-LoomRepositoryNames {
    return @(Get-LoomComponentNames)
}

function Get-LoomRepository {
    param([Parameter(Mandatory = $true)][string]$Name)
    return Get-LoomComponent -Name $Name
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
        [Alias('Repository')]
        [ValidateSet('platform', 'phone', 'contracts', 'skills', 'docs', 'cross-cutting')]
        [string]$Area,

        [Parameter(Mandatory = $true)]
        [ValidateRange(1, 2147483647)]
        [int]$Issue,

        [Parameter(Mandatory = $true)]
        [string]$Name,

        [string]$BaseBranch
    )

    $config = Get-LoomWorkspaceConfig
    $slug = ConvertTo-LoomFeatureSlug -Name $Name
    if ([string]::IsNullOrWhiteSpace($BaseBranch)) {
        $BaseBranch = [string]$config.defaultBranch
    }

    $leaf = "$Issue-$slug"
    $sharedRoot = Get-LoomSharedWorkspaceRoot
    $relativeWorktreeRoot = ([string]$config.worktreeRoot).Replace('/', '\')
    $worktreePath = [System.IO.Path]::GetFullPath((Join-Path (Join-Path $sharedRoot $relativeWorktreeRoot) $leaf))
    if (-not (Test-LoomPathWithinRoot -Path $worktreePath -Root $sharedRoot)) {
        throw "Worktree path escapes shared workspace: $worktreePath"
    }

    return [PSCustomObject]@{
        Area = $Area
        RepositoryPath = $script:LoomWorkspaceRoot
        BaseBranch = $BaseBranch
        Branch = "codex/$leaf"
        RelativeWorktreePath = "$relativeWorktreeRoot\$leaf"
        WorktreePath = $worktreePath
    }
}
