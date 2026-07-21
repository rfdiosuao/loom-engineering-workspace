param(
    [switch]$NoGit
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot

function Resolve-LauncherRootName {
    $candidates = @("openclaw_new_launcher")
    foreach ($candidate in $candidates) {
        $path = Join-Path $Root $candidate
        if (
            (Test-Path -LiteralPath (Join-Path $path "package.json")) -and
            (Test-Path -LiteralPath (Join-Path $path "src-tauri"))
        ) {
            return $candidate
        }
    }
    throw "No launcher project found. Expected openclaw_new_launcher."
}

$LauncherRootName = Resolve-LauncherRootName

$sourceRoots = @(
    "$LauncherRootName/src",
    "$LauncherRootName/python",
    "$LauncherRootName/scripts",
    "$LauncherRootName/docs",
    "$LauncherRootName/openclaw-workspace",
    "$LauncherRootName/src-tauri/src",
    "$LauncherRootName/src-tauri/capabilities",
    "scripts",
    "license_server"
)

$extensions = @(
    ".css",
    ".html",
    ".json",
    ".md",
    ".mjs",
    ".ps1",
    ".py",
    ".rs",
    ".toml",
    ".ts",
    ".tsx"
)

$ignoredPatterns = @(
    "(^|/)node_modules(/|$)",
    "(^|/)target(/|$)",
    "(^|/)dist(/|$)",
    "(^|/)release(/|$)",
    "(^|/)\.git(/|$)",
    "(^|/)package-lock\.json$",
    "(^|/)pnpm-lock\.yaml$"
)

$mojibakePattern = "\uFFFD|\u935A|\u74D2|\u93C8|\u95BF|\u93C9|\u93C3|\u95C7|\u6D93|\u5158|\u5DFF|\u7487|\u20AC|\uE045|\uE047|\uE044|\u951B|\u9428|\u7ED4|\u59AB|\u60E7|\u59DD|\u93B5|\u7039|\u95B0|\u4FD9|\u76AF|\u7EC2|\u4EBE|\u9A9E|\u6748|\u52ED|\u53C6|\u71BB|\u52EC|\u70B0|\u51A7|\u6FC8"
$sensitivePattern = "(?i)\b(sk-[A-Za-z0-9_\-]{24,}|(?:OPENAI|DASHSCOPE|ANTHROPIC|GOOGLE|GITHUB|AZURE|COHERE)_API_KEY\s*[:=]\s*[\x22\x27]?[A-Za-z0-9_\-]{16,})\b"
$utf8 = [System.Text.UTF8Encoding]::new($false, $true)

function Convert-ToPortablePath {
    param([string]$Value)
    return $Value.Replace("\", "/").TrimStart("/")
}

function Test-IgnoredPath {
    param([string]$Path)

    $normalized = Convert-ToPortablePath $Path
    foreach ($pattern in $ignoredPatterns) {
        if ($normalized -match $pattern) {
            return $true
        }
    }
    return $false
}

function Test-SourceRoot {
    param([string]$Path)

    $normalized = Convert-ToPortablePath $Path
    foreach ($sourceRoot in $sourceRoots) {
        if ($normalized -eq $sourceRoot -or $normalized.StartsWith("$sourceRoot/", [System.StringComparison]::OrdinalIgnoreCase)) {
            return $true
        }
    }
    return $false
}

function Get-LineNumber {
    param(
        [string]$Content,
        [int]$Index
    )

    if ($Index -le 0) {
        return 1
    }
    return (($Content.Substring(0, $Index) -split "`r?`n").Count)
}

function Get-SourceFiles {
    if (-not $NoGit) {
        $gitFiles = & git -C $Root ls-files 2>$null
        if ($LASTEXITCODE -eq 0 -and $gitFiles) {
            return @($gitFiles |
                Where-Object { Test-SourceRoot $_ } |
                Where-Object { -not (Test-IgnoredPath $_) } |
                Where-Object { $extensions -contains ([System.IO.Path]::GetExtension($_).ToLowerInvariant()) })
        }
    }

    $files = New-Object System.Collections.Generic.List[string]
    foreach ($sourceRoot in $sourceRoots) {
        $absoluteRoot = Join-Path $Root $sourceRoot
        if (-not (Test-Path -LiteralPath $absoluteRoot)) {
            continue
        }
        Get-ChildItem -LiteralPath $absoluteRoot -Recurse -File |
            ForEach-Object {
                $relative = Convert-ToPortablePath ($_.FullName.Substring($Root.Length).TrimStart("\", "/"))
                if (-not (Test-IgnoredPath $relative) -and $extensions -contains $_.Extension.ToLowerInvariant()) {
                    $files.Add($relative)
                }
            }
    }
    return @($files)
}

$errors = New-Object System.Collections.Generic.List[string]
$checked = 0

foreach ($relativePath in Get-SourceFiles) {
    $fullPath = Join-Path $Root $relativePath
    if (-not (Test-Path -LiteralPath $fullPath)) {
        continue
    }

    $checked += 1
    try {
        $content = $utf8.GetString([System.IO.File]::ReadAllBytes($fullPath))
    } catch {
        $errors.Add("Invalid UTF-8: $relativePath")
        continue
    }

    $mojibakeMatch = [regex]::Match($content, $mojibakePattern)
    if ($mojibakeMatch.Success) {
        $lineNumber = Get-LineNumber -Content $content -Index $mojibakeMatch.Index
        $errors.Add("Possible mojibake text: ${relativePath}:$lineNumber")
    }

    $secretMatch = [regex]::Match($content, $sensitivePattern)
    if ($secretMatch.Success) {
        $lineNumber = Get-LineNumber -Content $content -Index $secretMatch.Index
        $errors.Add("Possible secret committed: ${relativePath}:$lineNumber")
    }
}

Write-Host "Source text verification target: $Root"
Write-Host "Checked files: $checked"

if ($errors.Count -gt 0) {
    Write-Host ""
    Write-Host "Errors:"
    foreach ($errorItem in $errors) {
        Write-Host "  - $errorItem"
    }
    exit 1
}

Write-Host "Source text check passed."
