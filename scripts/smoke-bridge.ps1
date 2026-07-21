param(
    [int]$TimeoutSeconds = 20,
    [string]$PythonExe = "python",
    [switch]$RequireFastApi
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$LauncherDir = Join-Path $Root "openclaw_new_launcher"
$BridgePath = Join-Path $LauncherDir "python\bridge.py"

if (-not (Test-Path -LiteralPath $BridgePath)) {
    throw "Bridge script not found: $BridgePath"
}

function Invoke-BridgeJson {
    param(
        [Parameter(Mandatory = $true)][string]$Url,
        [Parameter(Mandatory = $true)][hashtable]$Headers,
        [string]$Method = "GET",
        [object]$Body = $null
    )

    $params = @{
        Uri = $Url
        Method = $Method
        Headers = $Headers
        TimeoutSec = 8
    }
    if ($null -ne $Body) {
        $params.ContentType = "application/json"
        $params.Body = ($Body | ConvertTo-Json -Depth 20)
    }
    try {
        return Invoke-RestMethod @params
    } catch {
        $response = $_.Exception.Response
        if ($null -ne $response) {
            $stream = $response.GetResponseStream()
            if ($null -ne $stream) {
                $reader = [System.IO.StreamReader]::new($stream)
                try {
                    $text = $reader.ReadToEnd()
                    if ($text) {
                        throw "Bridge request failed: $Method $Url HTTP $([int]$response.StatusCode) $text"
                    }
                } finally {
                    $reader.Dispose()
                }
            }
        }
        throw
    }
}

function Assert-Property {
    param(
        [Parameter(Mandatory = $true)][object]$Object,
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Context
    )

    if (-not ($Object.PSObject.Properties.Name -contains $Name)) {
        throw "$Context missing property: $Name"
    }
}

function Assert-BridgeMeta {
    param(
        [Parameter(Mandatory = $true)][object]$Object,
        [Parameter(Mandatory = $true)][string]$Context,
        [int]$ExpectedStatus = 200,
        [bool]$ExpectedOk = $true
    )

    Assert-Property -Object $Object -Name "_meta" -Context $Context
    Assert-Property -Object $Object._meta -Name "ok" -Context "$Context _meta"
    Assert-Property -Object $Object._meta -Name "status" -Context "$Context _meta"
    if ([bool]$Object._meta.ok -ne $ExpectedOk) {
        throw "$Context _meta.ok expected $ExpectedOk, got $($Object._meta.ok)"
    }
    if ([int]$Object._meta.status -ne $ExpectedStatus) {
        throw "$Context _meta.status expected $ExpectedStatus, got $($Object._meta.status)"
    }
    if (-not $ExpectedOk) {
        Assert-Property -Object $Object._meta -Name "error" -Context "$Context _meta"
        Assert-Property -Object $Object._meta.error -Name "code" -Context "$Context _meta.error"
        Assert-Property -Object $Object._meta.error -Name "message" -Context "$Context _meta.error"
    }
}

function Get-FileText {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        return ""
    }
    $stream = [System.IO.File]::Open($Path, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::ReadWrite)
    try {
        $reader = [System.IO.StreamReader]::new($stream, [System.Text.Encoding]::UTF8)
        try {
            return $reader.ReadToEnd()
        } finally {
            $reader.Dispose()
        }
    } finally {
        $stream.Dispose()
    }
}

$timestamp = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
$stdoutPath = Join-Path ([System.IO.Path]::GetTempPath()) "openclaw-bridge-smoke-$timestamp.out"
$stderrPath = Join-Path ([System.IO.Path]::GetTempPath()) "openclaw-bridge-smoke-$timestamp.err"
$smokeConfigRelativePath = "data/.openclaw/launcher/bridge-smoke.json"
$smokeConfigPath = Join-Path $LauncherDir $smokeConfigRelativePath
$smokeSkillId = "bridge-smoke-skill-$timestamp"
$smokeSkillFilename = "$smokeSkillId.zip"
$smokeSkillSourceDir = Join-Path ([System.IO.Path]::GetTempPath()) $smokeSkillId
$smokeSkillZipPath = Join-Path ([System.IO.Path]::GetTempPath()) $smokeSkillFilename
$smokeSkillInstalledDir = Join-Path $LauncherDir "data\.openclaw\skills\$smokeSkillId"
$smokeSkillUploadPath = Join-Path $LauncherDir "data\.openclaw\launcher\skill-uploads\$smokeSkillFilename"
$diagnosticsExportPath = $null
$process = $null
$previousUtf8 = $env:PYTHONUTF8
$previousIoEncoding = $env:PYTHONIOENCODING
$previousDontWriteBytecode = $env:PYTHONDONTWRITEBYTECODE
$previousRequireFastApi = $env:OPENCLAW_BRIDGE_REQUIRE_FASTAPI

try {
    if (Test-Path -LiteralPath $smokeSkillSourceDir) {
        Remove-Item -LiteralPath $smokeSkillSourceDir -Recurse -Force
    }
    if (Test-Path -LiteralPath $smokeSkillZipPath) {
        Remove-Item -LiteralPath $smokeSkillZipPath -Force
    }
    New-Item -ItemType Directory -Path $smokeSkillSourceDir -Force | Out-Null
    $utf8NoBom = [System.Text.UTF8Encoding]::new($false)
    $skillJson = @{
        id = $smokeSkillId
        name = "Bridge Smoke Skill"
        version = "0.0.1"
        description = "Temporary skill used by bridge smoke tests."
        runtime = "external"
        category = "test"
        icon = "TS"
    } | ConvertTo-Json -Depth 10
    [System.IO.File]::WriteAllText((Join-Path $smokeSkillSourceDir "skill.json"), $skillJson, $utf8NoBom)
    [System.IO.File]::WriteAllText(
        (Join-Path $smokeSkillSourceDir "README.md"),
        "# Bridge Smoke Skill`n`nTemporary README for bridge smoke tests.",
        $utf8NoBom
    )
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    [System.IO.Compression.ZipFile]::CreateFromDirectory($smokeSkillSourceDir, $smokeSkillZipPath)
    $smokeSkillData = [Convert]::ToBase64String([System.IO.File]::ReadAllBytes($smokeSkillZipPath))

    Write-Host "Starting Python bridge smoke test..."
    $env:PYTHONUTF8 = "1"
    $env:PYTHONIOENCODING = "utf-8"
    $env:PYTHONDONTWRITEBYTECODE = "1"
    if ($RequireFastApi) {
        $env:OPENCLAW_BRIDGE_REQUIRE_FASTAPI = "1"
    }

    $process = Start-Process `
        -FilePath $PythonExe `
        -ArgumentList "`"$BridgePath`"" `
        -WorkingDirectory $LauncherDir `
        -RedirectStandardOutput $stdoutPath `
        -RedirectStandardError $stderrPath `
        -PassThru `
        -WindowStyle Hidden

    $port = $null
    $token = $null
    $impl = $null
    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)

    while ([DateTime]::UtcNow -lt $deadline -and (-not $port -or -not $token -or ($RequireFastApi -and -not $impl))) {
        if ($process.HasExited) {
            $stderrText = Get-FileText -Path $stderrPath
            throw "Bridge exited before becoming ready. $stderrText"
        }

        $stdoutText = Get-FileText -Path $stdoutPath
        foreach ($line in ($stdoutText -split "`r?`n")) {
            if (-not $port -and $line -match "^BRIDGE_PORT=(\d+)$") {
                $port = [int]$Matches[1]
                Write-Host "Bridge port: $port"
            }
            if (-not $token -and $line -match "^BRIDGE_TOKEN=(.+)$") {
                $token = $Matches[1]
                Write-Host "Bridge token received."
            }
            if (-not $impl -and $line -match "^BRIDGE_IMPL=(.+)$") {
                $impl = $Matches[1]
                Write-Host "Bridge implementation: $impl"
            }
        }

        if (-not $port -or -not $token -or ($RequireFastApi -and -not $impl)) {
            Start-Sleep -Milliseconds 100
        }
    }

    if (-not $port -or -not $token) {
        $stderrText = Get-FileText -Path $stderrPath
        $stdoutText = Get-FileText -Path $stdoutPath
        throw "Bridge did not become ready within ${TimeoutSeconds}s.`nSTDOUT:`n$stdoutText`nSTDERR:`n$stderrText"
    }
    if ($RequireFastApi -and $impl -ne "fastapi") {
        throw "Expected FastAPI bridge implementation, got: $impl"
    }

    $baseUrl = "http://127.0.0.1:$port"
    $headers = @{ "X-Bridge-Token" = $token }

    Write-Host "Checking token rejection..."
    try {
        Invoke-RestMethod -Uri "$baseUrl/api/system/info" -Method GET -TimeoutSec 8 | Out-Null
        throw "Bridge accepted a request without X-Bridge-Token."
    } catch {
        $response = $_.Exception.Response
        if ($null -eq $response) {
            throw
        }
        $statusCode = [int]$response.StatusCode
        if ($statusCode -ne 401) {
            throw "Expected HTTP 401 without token, got $statusCode"
        }
    }

    Write-Host "Checking protected process start rejection..."
    try {
        Invoke-RestMethod -Uri "$baseUrl/api/process/start" -Method POST -Headers $headers -ContentType "application/json" -Body "{}" -TimeoutSec 8 | Out-Null
        throw "Bridge started OpenClaw without a local license."
    } catch {
        $response = $_.Exception.Response
        if ($null -eq $response) {
            throw
        }
        $statusCode = [int]$response.StatusCode
        if ($statusCode -ne 403) {
            throw "Expected HTTP 403 for protected process start, got $statusCode"
        }
    }

    foreach ($protectedPath in @("/api/image/generate", "/api/video/generate")) {
        Write-Host "Checking protected endpoint rejection: $protectedPath..."
        try {
            Invoke-RestMethod -Uri "$baseUrl$protectedPath" -Method POST -Headers $headers -ContentType "application/json" -Body "{}" -TimeoutSec 8 | Out-Null
            throw "Bridge allowed protected endpoint without a local license: $protectedPath"
        } catch {
            $response = $_.Exception.Response
            if ($null -eq $response) {
                throw
            }
            $statusCode = [int]$response.StatusCode
            if ($statusCode -ne 403) {
                throw "Expected HTTP 403 for $protectedPath, got $statusCode"
            }
        }
    }

    Write-Host "Checking empty license activation rejection..."
    try {
        Invoke-RestMethod -Uri "$baseUrl/api/license/activate" -Method POST -Headers $headers -ContentType "application/json" -Body "{}" -TimeoutSec 8 | Out-Null
        throw "Bridge accepted an empty license activation request."
    } catch {
        $response = $_.Exception.Response
        if ($null -eq $response) {
            throw
        }
        $statusCode = [int]$response.StatusCode
        if ($statusCode -ne 400) {
            throw "Expected HTTP 400 for empty license activation, got $statusCode"
        }
    }

    $checks = @(
        @{ Name = "system info"; Path = "/api/system/info"; Method = "GET"; Props = @("node_path", "base_path", "openclaw_version") },
        @{ Name = "process status"; Path = "/api/process/status"; Method = "GET"; Props = @("running", "pid") },
        @{ Name = "process stop"; Path = "/api/process/stop"; Method = "POST"; Props = @("status", "message") },
        @{ Name = "log get"; Path = "/api/log/get"; Method = "GET"; Props = @("log") },
        @{ Name = "license current"; Path = "/api/license/current"; Method = "GET"; Props = @("license") },
        @{ Name = "license authorized"; Path = "/api/license/authorized"; Method = "POST"; Body = @{ feature = "openclaw" }; Props = @("authorized") },
        @{ Name = "theme current"; Path = "/api/theme/current"; Method = "GET"; Props = @("theme") },
        @{ Name = "theme list"; Path = "/api/theme/list"; Method = "GET"; Props = @("themes") },
        @{ Name = "auth profiles"; Path = "/api/auth/profiles"; Method = "GET"; Props = @("profiles") },
        @{ Name = "diagnostics run"; Path = "/api/diagnostics/run"; Method = "GET"; Props = @("checks", "summary") },
        @{ Name = "config write"; Path = "/api/config/write"; Method = "POST"; Body = @{ path = $smokeConfigRelativePath; data = @{ smoke = "ok"; timestamp = $timestamp } }; Props = @("status") },
        @{ Name = "config read"; Path = "/api/config/read"; Method = "POST"; Body = @{ path = $smokeConfigRelativePath; default = @{} }; Props = @("data") },
        @{ Name = "log clear"; Path = "/api/log/clear"; Method = "POST"; Props = @("status") },
        @{ Name = "skills list"; Path = "/api/skills/list"; Method = "GET"; Props = @("skills", "directories", "sites") },
        @{ Name = "skills paths"; Path = "/api/skills/paths"; Method = "GET"; Props = @("directories", "sites") },
        @{ Name = "skills install zip"; Path = "/api/skills/install_zip"; Method = "POST"; Body = @{ filename = $smokeSkillFilename; data = $smokeSkillData }; Props = @("skill") },
        @{ Name = "skills readme"; Path = "/api/skills/readme"; Method = "POST"; Body = @{ id = $smokeSkillId }; Props = @("id", "path", "content") },
        @{ Name = "skills disable"; Path = "/api/skills/enable"; Method = "POST"; Body = @{ id = $smokeSkillId; enabled = $false }; Props = @("skill") },
        @{ Name = "skills enable"; Path = "/api/skills/enable"; Method = "POST"; Body = @{ id = $smokeSkillId; enabled = $true }; Props = @("skill") },
        @{ Name = "skills uninstall"; Path = "/api/skills/uninstall"; Method = "POST"; Body = @{ id = $smokeSkillId }; Props = @("status", "id") }
    )

    foreach ($check in $checks) {
        Write-Host "Checking $($check.Name)..."
        $response = Invoke-BridgeJson -Url "$baseUrl$($check.Path)" -Headers $headers -Method $check.Method -Body $check.Body
        Assert-BridgeMeta -Object $response -Context $check.Name
        foreach ($prop in $check.Props) {
            Assert-Property -Object $response -Name $prop -Context $check.Name
        }
    }

    Write-Host "Checking diagnostics export..."
    $exportResponse = Invoke-BridgeJson -Url "$baseUrl/api/diagnostics/export" -Headers $headers -Method "POST"
    Assert-BridgeMeta -Object $exportResponse -Context "diagnostics export"
    foreach ($prop in @("path", "directory", "filename", "size")) {
        Assert-Property -Object $exportResponse -Name $prop -Context "diagnostics export"
    }
    $diagnosticsExportPath = [string]$exportResponse.path
    if (-not (Test-Path -LiteralPath $diagnosticsExportPath)) {
        throw "diagnostics export did not create file: $diagnosticsExportPath"
    }

    Write-Host "Bridge smoke check passed." -ForegroundColor Green
} finally {
    $env:PYTHONUTF8 = $previousUtf8
    $env:PYTHONIOENCODING = $previousIoEncoding
    $env:PYTHONDONTWRITEBYTECODE = $previousDontWriteBytecode
    $env:OPENCLAW_BRIDGE_REQUIRE_FASTAPI = $previousRequireFastApi

    if ($process -and -not $process.HasExited) {
        try {
            Stop-Process -Id $process.Id -Force -ErrorAction Stop
            $process.WaitForExit(5000) | Out-Null
        } catch {
            Write-Warning "Failed to stop bridge process $($process.Id): $_"
        }
    }

    Remove-Item -LiteralPath $stdoutPath, $stderrPath -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $smokeConfigPath -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $smokeSkillZipPath -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $smokeSkillSourceDir -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $smokeSkillInstalledDir -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $smokeSkillUploadPath -Force -ErrorAction SilentlyContinue
    if ($diagnosticsExportPath) {
        Remove-Item -LiteralPath $diagnosticsExportPath -Force -ErrorAction SilentlyContinue
    }
}
