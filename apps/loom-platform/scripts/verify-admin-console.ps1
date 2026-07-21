param(
    [string]$AdminHtmlPath = ""
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
if (-not $AdminHtmlPath) {
    $AdminHtmlPath = Join-Path $Root "license_server\admin_console.html"
}

function Join-Codepoints {
    param([int[]]$Codepoints)
    return -join ($Codepoints | ForEach-Object { [char]$_ })
}

if (-not (Test-Path -LiteralPath $AdminHtmlPath)) {
    throw "Admin console not found: $AdminHtmlPath"
}

$html = Get-Content -LiteralPath $AdminHtmlPath -Raw -Encoding UTF8

$requiredText = @(
    (Join-Codepoints @(0x53D1, 0x5361, 0x7F51, 0x7AD9, 0x914D, 0x7F6E)),
    "api/public-settings",
    "audit-code-col",
    (Join-Codepoints @(0x5DF2, 0x4F7F, 0x7528)),
    (Join-Codepoints @(0x672A, 0x4F7F, 0x7528))
)

foreach ($text in $requiredText) {
    if (-not $html.Contains($text)) {
        throw "Admin console missing required text: $text"
    }
}

$idSet = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::Ordinal)
foreach ($match in [regex]::Matches($html, 'id="([^"]+)"')) {
    [void]$idSet.Add($match.Groups[1].Value)
}

$refSet = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::Ordinal)
foreach ($match in [regex]::Matches($html, '\$\("([^"]+)"\)')) {
    [void]$refSet.Add($match.Groups[1].Value)
}
foreach ($match in [regex]::Matches($html, 'getElementById\("([^"]+)"\)')) {
    [void]$refSet.Add($match.Groups[1].Value)
}

$missing = @()
foreach ($ref in $refSet) {
    if (-not $idSet.Contains($ref)) {
        $missing += $ref
    }
}

if ($missing.Count -gt 0) {
    throw "Admin console JavaScript references missing DOM ids: $($missing -join ', ')"
}

$scriptMatches = [regex]::Matches(
    $html,
    '<script\b[^>]*>([\s\S]*?)</script>',
    [System.Text.RegularExpressions.RegexOptions]::IgnoreCase
)

if ($scriptMatches.Count -eq 0) {
    throw "Admin console has no inline script to verify."
}

$node = Get-Command node -ErrorAction SilentlyContinue
if (-not $node) {
    throw "Node.js is required for admin console JavaScript syntax verification."
}

$tmpFile = Join-Path ([System.IO.Path]::GetTempPath()) "openclaw-admin-console-$([System.Guid]::NewGuid().ToString('N')).js"
try {
    $script = ($scriptMatches | ForEach-Object { $_.Groups[1].Value }) -join "`n"
    [System.IO.File]::WriteAllText($tmpFile, $script, [System.Text.UTF8Encoding]::new($false))
    & $node.Source --check $tmpFile
    if ($LASTEXITCODE -ne 0) {
        throw "Admin console JavaScript syntax check failed."
    }
} finally {
    Remove-Item -LiteralPath $tmpFile -Force -ErrorAction SilentlyContinue
}

Write-Host "Admin console verification passed." -ForegroundColor Green
