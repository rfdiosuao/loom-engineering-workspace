param(
    [string]$Path = "",
    [switch]$Clear
)

$ErrorActionPreference = "Stop"

function Get-DefaultGiteeTokenFile {
    $appData = [Environment]::GetFolderPath([Environment+SpecialFolder]::ApplicationData)
    if ([string]::IsNullOrWhiteSpace($appData)) {
        $appData = $env:APPDATA
    }
    if ([string]::IsNullOrWhiteSpace($appData)) {
        throw "APPDATA is not available; pass -Path explicitly."
    }
    return Join-Path $appData "LOOM\secrets\gitee-token.dpapi"
}

if ([string]::IsNullOrWhiteSpace($Path)) {
    $Path = Get-DefaultGiteeTokenFile
}

if ($Clear) {
    if (Test-Path -LiteralPath $Path) {
        Remove-Item -LiteralPath $Path -Force
    }
    Write-Host "Removed encrypted Gitee token file: $Path"
    exit 0
}

$parent = Split-Path -Parent $Path
New-Item -ItemType Directory -Path $parent -Force | Out-Null

$token = Read-Host -Prompt "Gitee token" -AsSecureString
$encrypted = $token | ConvertFrom-SecureString
Set-Content -LiteralPath $Path -Value $encrypted -Encoding ASCII

Write-Host "Encrypted Gitee token saved for this Windows user: $Path"
