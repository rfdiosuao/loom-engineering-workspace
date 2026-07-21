param(
    [string[]]$Path = @(),
    [switch]$Source
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$TextExtensions = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
@(
    ".css", ".html", ".js", ".jsx", ".json", ".lock", ".md", ".mjs",
    ".ps1", ".py", ".rs", ".svg", ".toml", ".ts", ".tsx", ".txt",
    ".yaml", ".yml"
) | ForEach-Object { [void]$TextExtensions.Add($_) }

$SourceRoots = @(
    "openclaw_new_launcher",
    "scripts",
    "docs"
)

$IgnoredSourcePatterns = @(
    "(^|/)node_modules(/|$)",
    "(^|/)dist(/|$)",
    "(^|/)target(/|$)",
    "(^|/)release(/|$)",
    "(^|/)artifacts(/|$)",
    "(^|/)\.git(/|$)",
    "(^|/)openclaw_new_launcher/(?:node-runtime|python-runtime)(/|$)",
    "(^|/)openclaw_new_launcher/agents(/|$)",
    "(^|/)openclaw_new_launcher/redist(/|$)",
    "(^|/)openclaw_new_launcher/releases(/|$)",
    "(^|/)openclaw_ui_integration(/|$)"
)

$Patterns = @(
    @{ Name = "openai_project_key"; Regex = [regex]"sk-proj-[A-Za-z0-9_\-]{32,}" },
    @{ Name = "openai_legacy_key"; Regex = [regex]"sk-[A-Za-z0-9]{32,}" },
    @{ Name = "github_pat"; Regex = [regex]"(?:ghp_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{40,})" },
    @{ Name = "aws_access_key"; Regex = [regex]"AKIA[0-9A-Z]{16}" },
    @{ Name = "slack_token"; Regex = [regex]"xox[baprs]-[A-Za-z0-9-]{20,}" },
    @{ Name = "private_key"; Regex = [regex]"-----BEGIN (?:RSA |OPENSSH |EC |DSA )?PRIVATE KEY-----" }
)

$AllowedPackageFindings = @(
    @{ Kind = "aws_access_key"; Path = "LOOMFiles/_up_/python/PIL/ImageFont.py" },
    @{ Kind = "aws_access_key"; Path = "*/LOOMFiles/_up_/python/PIL/ImageFont.py" },
    @{ Kind = "aws_access_key"; Path = "*/LOOMFiles/_up_/python-runtime/Lib/site-packages/PIL/ImageFont.py" },
    @{ Kind = "aws_access_key"; Path = "_up_/python/PIL/ImageFont.py" },
    @{ Kind = "aws_access_key"; Path = "*/_up_/python/PIL/ImageFont.py" },
    @{ Kind = "aws_access_key"; Path = "_up_/python-runtime/Lib/site-packages/PIL/ImageFont.py" },
    @{ Kind = "aws_access_key"; Path = "*/_up_/python-runtime/Lib/site-packages/PIL/ImageFont.py" },
    @{ Kind = "private_key"; Path = "LOOMFiles/_up_/python/cryptography/hazmat/primitives/serialization/ssh.py" },
    @{ Kind = "private_key"; Path = "*/LOOMFiles/_up_/python/cryptography/hazmat/primitives/serialization/ssh.py" },
    @{ Kind = "private_key"; Path = "*/LOOMFiles/_up_/python-runtime/Lib/site-packages/cryptography/hazmat/primitives/serialization/ssh.py" },
    @{ Kind = "private_key"; Path = "_up_/python/cryptography/hazmat/primitives/serialization/ssh.py" },
    @{ Kind = "private_key"; Path = "*/_up_/python/cryptography/hazmat/primitives/serialization/ssh.py" },
    @{ Kind = "private_key"; Path = "_up_/python-runtime/Lib/site-packages/cryptography/hazmat/primitives/serialization/ssh.py" },
    @{ Kind = "private_key"; Path = "*/_up_/python-runtime/Lib/site-packages/cryptography/hazmat/primitives/serialization/ssh.py" },
    @{ Kind = "private_key"; Path = "LOOMFiles/node/node_modules/npm/docs/content/using-npm/config.md" },
    @{ Kind = "private_key"; Path = "*/LOOMFiles/node/node_modules/npm/docs/content/using-npm/config.md" },
    @{ Kind = "private_key"; Path = "LOOMFiles/node/node_modules/npm/docs/output/using-npm/config.html" },
    @{ Kind = "private_key"; Path = "*/LOOMFiles/node/node_modules/npm/docs/output/using-npm/config.html" },
    @{ Kind = "private_key"; Path = "LOOMFiles/node/node_modules/npm/node_modules/@npmcli/config/lib/definitions/definitions.js" },
    @{ Kind = "private_key"; Path = "*/LOOMFiles/node/node_modules/npm/node_modules/@npmcli/config/lib/definitions/definitions.js" },
    @{ Kind = "private_key"; Path = "_up_/node-runtime/node_modules/npm/docs/content/using-npm/config.md" },
    @{ Kind = "private_key"; Path = "*/_up_/node-runtime/node_modules/npm/docs/content/using-npm/config.md" },
    @{ Kind = "private_key"; Path = "_up_/node-runtime/node_modules/npm/docs/output/using-npm/config.html" },
    @{ Kind = "private_key"; Path = "*/_up_/node-runtime/node_modules/npm/docs/output/using-npm/config.html" },
    @{ Kind = "private_key"; Path = "_up_/node-runtime/node_modules/npm/node_modules/@npmcli/config/lib/definitions/definitions.js" },
    @{ Kind = "private_key"; Path = "*/_up_/node-runtime/node_modules/npm/node_modules/@npmcli/config/lib/definitions/definitions.js" },
    @{ Kind = "private_key"; Path = "LOOMFiles/node_modules/openclaw/dist/*" },
    @{ Kind = "private_key"; Path = "*/LOOMFiles/node_modules/openclaw/dist/*" },
    @{ Kind = "private_key"; Path = "LOOMFiles/node_modules/openclaw/node_modules/dotenv/README*.md" },
    @{ Kind = "private_key"; Path = "*/LOOMFiles/node_modules/openclaw/node_modules/dotenv/README*.md" },
    @{ Kind = "private_key"; Path = "LOOMFiles/node_modules/openclaw/node_modules/jose/dist/*" },
    @{ Kind = "private_key"; Path = "*/LOOMFiles/node_modules/openclaw/node_modules/jose/dist/*" },
    @{ Kind = "private_key"; Path = "LOOMFiles/node_modules/openclaw/node_modules/jose/src/*" },
    @{ Kind = "private_key"; Path = "*/LOOMFiles/node_modules/openclaw/node_modules/jose/src/*" }
)

function Convert-ToPortablePath {
    param([string]$Value)
    return $Value.Replace("\", "/").TrimStart("/")
}

function Test-TextFileName {
    param([string]$Value)
    $name = [System.IO.Path]::GetFileName($Value)
    if ($name -in @(".gitignore", ".mcp.json")) {
        return $true
    }
    return $TextExtensions.Contains([System.IO.Path]::GetExtension($Value))
}

function Test-IgnoredSourcePath {
    param([string]$RelativePath)
    $normalized = Convert-ToPortablePath $RelativePath
    foreach ($pattern in $IgnoredSourcePatterns) {
        if ($normalized -match $pattern) {
            return $true
        }
    }
    return $false
}

function Test-AllowedPackageFinding {
    param(
        [string]$Kind,
        [string]$RelativePath
    )
    $normalized = Convert-ToPortablePath $RelativePath
    foreach ($entry in $AllowedPackageFindings) {
        if ($Kind -eq $entry.Kind -and $normalized -like $entry.Path) {
            return $true
        }
    }
    return $false
}

function Add-Findings {
    param(
        [string]$RelativePath,
        [string]$Content,
        [bool]$PackageMode,
        [System.Collections.Generic.List[string]]$Errors,
        [System.Collections.Generic.List[string]]$Allowed
    )

    foreach ($pattern in $Patterns) {
        $matches = $pattern.Regex.Matches($Content)
        foreach ($match in $matches) {
            if ($PackageMode -and (Test-AllowedPackageFinding -Kind $pattern.Name -RelativePath $RelativePath)) {
                $Allowed.Add("$($pattern.Name): $RelativePath")
            }
            else {
                $Errors.Add("$($pattern.Name): $RelativePath => [REDACTED]")
            }
        }
    }
}

function Add-SourceTargets {
    param([System.Collections.Generic.List[object]]$Targets)

    foreach ($sourceRoot in $SourceRoots) {
        $absoluteRoot = Join-Path $Root $sourceRoot
        if (-not (Test-Path -LiteralPath $absoluteRoot)) {
            continue
        }
        Get-ChildItem -LiteralPath $absoluteRoot -Recurse -Force -File |
            Where-Object { Test-TextFileName $_.FullName } |
            ForEach-Object {
                $relative = Convert-ToPortablePath ($_.FullName.Substring($Root.Length).TrimStart("\", "/"))
                if (-not (Test-IgnoredSourcePath $relative)) {
                    $Targets.Add([pscustomobject]@{
                        Label = "source"
                        Path = $_.FullName
                        RelativePath = $relative
                        PackageMode = $false
                    })
                }
            }
    }
}

function Test-ExplicitSourceRoot {
    param([string]$InputPath)
    if (-not $Source.IsPresent) {
        return $false
    }
    $resolved = (Resolve-Path -LiteralPath $InputPath).Path.TrimEnd("\", "/")
    foreach ($sourceRoot in $SourceRoots) {
        $absoluteRoot = (Join-Path $Root $sourceRoot).TrimEnd("\", "/")
        if ($resolved -ieq $absoluteRoot) {
            return $true
        }
    }
    return $false
}

function Add-DirectoryTargets {
    param(
        [string]$InputPath,
        [System.Collections.Generic.List[object]]$Targets
    )

    $item = Get-Item -LiteralPath $InputPath
    $rootPath = $item.FullName
    Get-ChildItem -LiteralPath $rootPath -Recurse -Force -File |
        Where-Object { Test-TextFileName $_.FullName -and $_.Length -le 4MB } |
        ForEach-Object {
            $relative = Convert-ToPortablePath ($_.FullName.Substring($rootPath.Length).TrimStart("\", "/"))
            $Targets.Add([pscustomobject]@{
                Label = $item.Name
                Path = $_.FullName
                RelativePath = $relative
                PackageMode = $true
            })
        }
}

function Add-FileTarget {
    param(
        [string]$InputPath,
        [System.Collections.Generic.List[object]]$Targets
    )

    $item = Get-Item -LiteralPath $InputPath
    if ($item.Length -gt 4MB -or -not (Test-TextFileName $item.FullName)) {
        return
    }
    $Targets.Add([pscustomobject]@{
        Label = "file"
        Path = $item.FullName
        RelativePath = Convert-ToPortablePath $item.Name
        PackageMode = $false
    })
}

function Scan-ZipTarget {
    param(
        [string]$InputPath,
        [System.Collections.Generic.List[string]]$Errors,
        [System.Collections.Generic.List[string]]$Allowed,
        [ref]$Checked
    )

    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $zip = [System.IO.Compression.ZipFile]::OpenRead((Resolve-Path -LiteralPath $InputPath).Path)
    try {
        foreach ($entry in $zip.Entries) {
            if ($entry.Length -le 0 -or $entry.Length -gt 4MB -or -not (Test-TextFileName $entry.FullName)) {
                continue
            }
            $reader = New-Object System.IO.StreamReader($entry.Open(), [System.Text.UTF8Encoding]::new($false, $false))
            try {
                $content = $reader.ReadToEnd()
            }
            finally {
                $reader.Dispose()
            }
            $Checked.Value += 1
            Add-Findings -RelativePath (Convert-ToPortablePath $entry.FullName) -Content $content -PackageMode $true -Errors $Errors -Allowed $Allowed
        }
    }
    finally {
        $zip.Dispose()
    }
}

$targets = [System.Collections.Generic.List[object]]::new()
if ($Source.IsPresent) {
    Add-SourceTargets -Targets $targets
}

foreach ($inputPath in $Path) {
    if (-not (Test-Path -LiteralPath $inputPath)) {
        throw "Scan path does not exist: $inputPath"
    }
    if (Test-ExplicitSourceRoot $inputPath) {
        continue
    }
    $item = Get-Item -LiteralPath $inputPath
    if ($item.PSIsContainer) {
        Add-DirectoryTargets -InputPath $item.FullName -Targets $targets
    }
    elseif ($item.Extension -ine ".zip") {
        Add-FileTarget -InputPath $item.FullName -Targets $targets
    }
}

if ($targets.Count -eq 0 -and @($Path | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf }).Count -eq 0) {
    throw "No secret scan targets were selected. Use -Source or provide -Path."
}

$errors = [System.Collections.Generic.List[string]]::new()
$allowed = [System.Collections.Generic.List[string]]::new()
$checked = 0

foreach ($target in $targets) {
    try {
        $content = Get-Content -LiteralPath $target.Path -Raw -Encoding UTF8 -ErrorAction Stop
    }
    catch {
        continue
    }
    $checked += 1
    Add-Findings -RelativePath $target.RelativePath -Content $content -PackageMode ([bool]$target.PackageMode) -Errors $errors -Allowed $allowed
}

foreach ($inputPath in $Path) {
    $item = Get-Item -LiteralPath $inputPath
    if (-not $item.PSIsContainer -and $item.Extension -ieq ".zip") {
        Scan-ZipTarget -InputPath $item.FullName -Errors $errors -Allowed $allowed -Checked ([ref]$checked)
    }
}

Write-Host "Secret verification target count: $($targets.Count + @($Path | Where-Object { (Test-Path -LiteralPath $_ -PathType Leaf) -and ([System.IO.Path]::GetExtension($_) -ieq '.zip') }).Count)"
Write-Host "Checked text files: $checked"
Write-Host "Allowed third-party findings: $($allowed.Count)"

if ($errors.Count -gt 0) {
    Write-Host ""
    Write-Host "Errors:"
    foreach ($errorItem in $errors) {
        Write-Host "  - $errorItem"
    }
    exit 1
}

Write-Host "Secret verification passed."
