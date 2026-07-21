param(
    [string]$Owner = "rfdiosuao",
    [string]$Repo = "lumi",
    [string]$TagName = "",
    [string]$Name = "",
    [string]$Body = "",
    [string[]]$Assets = @(),
    [string]$Token = $env:GITEE_ACCESS_TOKEN,
    [string]$TokenFile = ""
)

$ErrorActionPreference = "Stop"

function Get-DefaultGiteeTokenFile {
    $appData = [Environment]::GetFolderPath([Environment+SpecialFolder]::ApplicationData)
    if ([string]::IsNullOrWhiteSpace($appData)) {
        $appData = $env:APPDATA
    }
    if ([string]::IsNullOrWhiteSpace($appData)) {
        return ""
    }
    return Join-Path $appData "LOOM\secrets\gitee-token.dpapi"
}

function Read-GiteeTokenFromFile {
    param([string]$Path)

    if ([string]::IsNullOrWhiteSpace($Path) -or -not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        return ""
    }
    $encrypted = (Get-Content -LiteralPath $Path -Raw -Encoding ASCII).Trim()
    if ([string]::IsNullOrWhiteSpace($encrypted)) {
        return ""
    }
    $secure = ConvertTo-SecureString -String $encrypted
    $credential = [System.Net.NetworkCredential]::new("", $secure)
    return $credential.Password
}

if ([string]::IsNullOrWhiteSpace($Token)) {
    $Token = $env:GITEE_TOKEN
}

if ([string]::IsNullOrWhiteSpace($Token)) {
    if ([string]::IsNullOrWhiteSpace($TokenFile)) {
        $TokenFile = Get-DefaultGiteeTokenFile
    }
    $Token = Read-GiteeTokenFromFile -Path $TokenFile
}

if ([string]::IsNullOrWhiteSpace($Token)) {
    throw "Missing Gitee token. Set GITEE_ACCESS_TOKEN/GITEE_TOKEN or run scripts\set-gitee-token.ps1 first."
}

if ([string]::IsNullOrWhiteSpace($TagName)) {
    $TagName = (git describe --tags --exact-match 2>$null).Trim()
    if ([string]::IsNullOrWhiteSpace($TagName)) {
        throw "TagName was not provided and current commit is not exactly tagged."
    }
}

if ([string]::IsNullOrWhiteSpace($Name)) {
    $Name = $TagName
}

if ([string]::IsNullOrWhiteSpace($Body)) {
    $template = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String("T3BlbkNsYXcg5ZCv5Yqo5Zmo5Y+R5biDIHswfQoK5p6E5bu65o+Q5Lqk77yaezF9Cgrmm7TmlrDlhoXlrrnvvJoKLSDor7flnKjlj5HluIPliY3ooaXlhYXmnKzmrKHpnaLlkJHnlKjmiLfnmoTkuK3mlofmm7TmlrDor7TmmI7jgIIKCuagoemqjOivtOaYju+8mgotIOWPkeW4g+mZhOS7tuW6lOWMheWQq+WuieijheWMheOAgeS+v+aQuuWMheWSjCBTSEEyNTYg5qCh6aqM5paH5Lu244CC"))
    $Body = $template -f $TagName, (git rev-parse --short HEAD)
}

function Invoke-GiteeApi {
    param(
        [string]$Method,
        [string]$Path,
        [hashtable]$Body = $null
    )

    $uri = "https://gitee.com/api/v5$Path"
    if ($Method -eq "GET" -or $Method -eq "DELETE") {
        $separator = if ($uri.Contains("?")) { "&" } else { "?" }
        $uri = "$uri${separator}access_token=$Token"
        return Invoke-RestMethod -Method $Method -Uri $uri
    }

    $payload = @{}
    if ($Body) {
        foreach ($key in $Body.Keys) {
            $payload[$key] = $Body[$key]
        }
    }
    $payload["access_token"] = $Token
    return Invoke-RestMethod -Method $Method -Uri $uri -Body $payload -ContentType "application/x-www-form-urlencoded"
}

function Get-ReleaseByTag {
    param([string]$Tag)

    try {
        $result = Invoke-GiteeApi -Method "GET" -Path "/repos/$Owner/$Repo/releases/tags/$Tag"
        if ($null -eq $result -or ($result -is [string] -and $result -eq "null")) {
            return $null
        }
        return $result
    } catch {
    }
    try {
        $items = @(Invoke-GiteeApi -Method "GET" -Path "/repos/$Owner/$Repo/releases?page=1&per_page=100")
        return $items | Where-Object { $_.tag_name -eq $Tag } | Select-Object -First 1
    } catch {
        return $null
    }
}

function Invoke-GiteeFormPost {
    param(
        [string]$Url,
        [hashtable]$Fields
    )

    $responsePath = Join-Path $env:TEMP ("gitee-api-" + [guid]::NewGuid().ToString("N") + ".json")
    $curlArgs = @(
        "-sS",
        "-o", $responsePath,
        "-w", "%{http_code}",
        "-X", "POST"
    )
    foreach ($key in $Fields.Keys) {
        $curlArgs += "-F"
        $curlArgs += "$key=$($Fields[$key])"
    }
    $curlArgs += $Url

    try {
        $status = & curl.exe @curlArgs
        $content = if (Test-Path -LiteralPath $responsePath) {
            Get-Content -LiteralPath $responsePath -Raw -Encoding UTF8
        } else {
            ""
        }
        if ($LASTEXITCODE -ne 0 -or $status -notmatch "^2") {
            throw "Gitee form POST failed with HTTP ${status}: $($content.Substring(0, [Math]::Min(300, $content.Length)))"
        }
        return $content | ConvertFrom-Json
    } finally {
        if (Test-Path -LiteralPath $responsePath) {
            Remove-Item -LiteralPath $responsePath -Force
        }
    }
}

function New-GiteeRelease {
    return Invoke-GiteeApi -Method "POST" -Path "/repos/$Owner/$Repo/releases" -Body @{
        tag_name = $TagName
        name = $Name
        body = $Body
        target_commitish = "master"
        prerelease = "false"
    }
}

function Publish-Asset {
    param(
        [int]$ReleaseId,
        [string]$AssetPath
    )

    if (-not (Test-Path -LiteralPath $AssetPath)) {
        throw "Asset not found: $AssetPath"
    }

    $resolved = (Resolve-Path -LiteralPath $AssetPath).Path
    $fileName = Split-Path -Leaf $resolved
    $existing = @()

    try {
        $existing = @(Invoke-GiteeApi -Method "GET" -Path "/repos/$Owner/$Repo/releases/$ReleaseId/attach_files")
    } catch {
        $existing = @()
    }

    foreach ($item in $existing) {
        if ($item.name -eq $fileName -or $item.filename -eq $fileName) {
            try {
                Invoke-GiteeApi -Method "DELETE" -Path "/repos/$Owner/$Repo/releases/$ReleaseId/attach_files/$($item.id)" | Out-Null
            } catch {
                Write-Host "Skipping stale Gitee asset delete failure: $fileName"
            }
        }
    }

    $url = "https://gitee.com/api/v5/repos/$Owner/$Repo/releases/$ReleaseId/attach_files"
    $curlArgs = @(
        "-sS",
        "-X", "POST",
        "-F", "access_token=$Token",
        "-F", "file=@$resolved",
        $url
    )
    $result = & curl.exe @curlArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to upload asset: $fileName"
    }
    Write-Host "Uploaded asset: $fileName"
}

$release = Get-ReleaseByTag -Tag $TagName

if ($release) {
    Write-Host "Using existing Gitee release: $TagName"
} else {
    Write-Host "Creating Gitee release: $TagName"
    $release = New-GiteeRelease
}

foreach ($asset in $Assets) {
    Publish-Asset -ReleaseId ([int]$release.id) -AssetPath $asset
}

Write-Host "Gitee release ready: $TagName"
