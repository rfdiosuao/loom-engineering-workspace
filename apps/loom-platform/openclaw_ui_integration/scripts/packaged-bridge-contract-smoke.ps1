param(
  [Parameter(Mandatory = $true)]
  [string]$Path
)

$ErrorActionPreference = "Stop"

$packageDir = (Resolve-Path -LiteralPath $Path).Path
$payload = Join-Path $packageDir "OpenClawFiles"
if (-not (Test-Path -LiteralPath $payload)) {
  $payload = $packageDir
}

$python = Join-Path $payload "_up_\python-runtime\python.exe"
$bridgePath = Join-Path $payload "_up_\python\bridge.py"
$videoConfigPath = Join-Path $payload "video_config.json"
$stdoutPath = Join-Path ([System.IO.Path]::GetTempPath()) "openclaw-packaged-bridge-$PID.out"
$stderrPath = Join-Path ([System.IO.Path]::GetTempPath()) "openclaw-packaged-bridge-$PID.err"

if (-not (Test-Path -LiteralPath $python)) {
  throw "Bundled Python not found: $python"
}
if (-not (Test-Path -LiteralPath $bridgePath)) {
  throw "Bundled bridge.py not found: $bridgePath"
}

$originalVideoExists = Test-Path -LiteralPath $videoConfigPath
$originalVideoContent = if ($originalVideoExists) { [System.IO.File]::ReadAllText($videoConfigPath) } else { $null }

function Stop-PackagedBridge {
  param([object]$Process)

  if ($null -ne $Process -and -not $Process.HasExited) {
    Stop-Process -Id $Process.Id -Force
    $Process.WaitForExit(5000) | Out-Null
  }
  if ($null -ne $Process) {
    $Process.Dispose()
  }
}

function Remove-TempFile {
  param([string]$TempPath)

  if (Test-Path -LiteralPath $TempPath) {
    Remove-Item -LiteralPath $TempPath -Force
  }
}

function Start-PackagedBridge {
  Remove-TempFile $stdoutPath
  Remove-TempFile $stderrPath

  $process = Start-Process `
    -FilePath $python `
    -ArgumentList @("-u", $bridgePath) `
    -WorkingDirectory $payload `
    -RedirectStandardOutput $stdoutPath `
    -RedirectStandardError $stderrPath `
    -WindowStyle Hidden `
    -PassThru

  $port = $null
  $token = $null
  $deadline = (Get-Date).AddSeconds(30)
  while ((Get-Date) -lt $deadline) {
    if ($process.HasExited) {
      $stderr = if (Test-Path -LiteralPath $stderrPath) { Get-Content -Raw -LiteralPath $stderrPath } else { "" }
      throw "Packaged bridge exited early: $stderr"
    }
    if (Test-Path -LiteralPath $stdoutPath) {
      foreach ($line in (Get-Content -LiteralPath $stdoutPath -ErrorAction SilentlyContinue)) {
        if ($line -match "^BRIDGE_PORT=(\d+)$") {
          $port = [int]$Matches[1]
        }
        if ($line -match "^BRIDGE_TOKEN=(.+)$") {
          $token = [string]$Matches[1]
        }
      }
      if ($port -and $token) {
        return [pscustomobject]@{ Process = $process; Port = $port; Token = $token }
      }
    }
    Start-Sleep -Milliseconds 200
  }

  Stop-PackagedBridge $process
  throw "Timed out waiting for packaged bridge port/token."
}

function Invoke-PackagedBridge {
  param(
    [object]$Context,
    [string]$Method,
    [string]$ApiPath,
    [object]$Body = $null,
    [int]$ExpectedStatus = 200
  )

  $headers = @{ "X-Bridge-Token" = $Context.Token }
  $uri = "http://127.0.0.1:$($Context.Port)$ApiPath"
  try {
    $params = @{
      Method = $Method
      Uri = $uri
      Headers = $headers
      TimeoutSec = 15
    }
    if ($null -ne $Body) {
      $params.Body = ($Body | ConvertTo-Json -Depth 20)
      $params.ContentType = "application/json"
    }
    $json = Invoke-RestMethod @params
    if ($ExpectedStatus -ne 200) {
      throw "Expected HTTP $ExpectedStatus but got 200 for $ApiPath"
    }
    return [pscustomobject]@{ Status = 200; Json = $json }
  } catch {
    $response = $_.Exception.Response
    if ($null -eq $response) {
      throw
    }
    $status = [int]$response.StatusCode
    if ($status -ne $ExpectedStatus) {
      throw "Expected HTTP $ExpectedStatus but got $status for $ApiPath"
    }
    return [pscustomobject]@{ Status = $status; Json = $null }
  }
}

function Assert-HasProperty {
  param(
    [object]$Value,
    [string]$Name,
    [string]$Message
  )

  if ($null -eq $Value -or -not ($Value.PSObject.Properties.Name -contains $Name)) {
    throw $Message
  }
}

function Remove-PythonCaches {
  param([string]$Root)

  Get-ChildItem -LiteralPath $Root -Recurse -Directory -Filter "__pycache__" -ErrorAction SilentlyContinue |
    Sort-Object { $_.FullName.Length } -Descending |
    Remove-Item -Recurse -Force
  Get-ChildItem -LiteralPath $Root -Recurse -File -ErrorAction SilentlyContinue |
    Where-Object { $_.Extension -in @(".pyc", ".pyo") } |
    Remove-Item -Force
}

$ctx = $null
try {
  $ctx = Start-PackagedBridge

  $member = Invoke-PackagedBridge -Context $ctx -Method "GET" -ApiPath "/api/member/current"
  Assert-HasProperty $member.Json "member" "/api/member/current missing member."

  $license = Invoke-PackagedBridge -Context $ctx -Method "GET" -ApiPath "/api/license/current"
  Assert-HasProperty $license.Json "license" "/api/license/current missing license."
  Assert-HasProperty $license.Json "gatewayProfile" "/api/license/current missing gatewayProfile."
  Assert-HasProperty $license.Json "member" "/api/license/current missing member."

  Invoke-PackagedBridge -Context $ctx -Method "POST" -ApiPath "/api/config/read" -Body @{ path = "video_config.json"; default = @{ smoke = "default" } } | Out-Null
  Invoke-PackagedBridge -Context $ctx -Method "POST" -ApiPath "/api/config/read" -Body @{ path = "..\forbidden.json"; default = @{} } -ExpectedStatus 403 | Out-Null
  Invoke-PackagedBridge -Context $ctx -Method "POST" -ApiPath "/api/config/write" -Body @{ path = "video_config.json" } -ExpectedStatus 400 | Out-Null

  $diagnostics = Invoke-PackagedBridge -Context $ctx -Method "GET" -ApiPath "/api/diagnostics/run"
  Assert-HasProperty $diagnostics.Json "summary" "/api/diagnostics/run missing summary."
  Assert-HasProperty $diagnostics.Json "checks" "/api/diagnostics/run missing checks."

  foreach ($endpoint in @("/api/process/status", "/api/system/info", "/api/update/check")) {
    Invoke-PackagedBridge -Context $ctx -Method "GET" -ApiPath $endpoint | Out-Null
  }

  $marker = "packaged-$([guid]::NewGuid().ToString('N'))"
  Invoke-PackagedBridge -Context $ctx -Method "POST" -ApiPath "/api/config/write" -Body @{ path = "video_config.json"; data = @{ marker = $marker; providerId = "packaged-smoke" } } | Out-Null
  Stop-PackagedBridge $ctx.Process
  $ctx = $null

  $ctx = Start-PackagedBridge
  $persisted = Invoke-PackagedBridge -Context $ctx -Method "POST" -ApiPath "/api/config/read" -Body @{ path = "video_config.json"; default = @{} }
  if ($persisted.Json.data.marker -ne $marker) {
    throw "video_config.json did not persist across packaged bridge restart."
  }

  Write-Host "Packaged bridge contract smoke passed."
} finally {
  if ($null -ne $ctx) {
    Stop-PackagedBridge $ctx.Process
  }
  if ($originalVideoExists) {
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($videoConfigPath, $originalVideoContent, $utf8NoBom)
  } elseif (Test-Path -LiteralPath $videoConfigPath) {
    Remove-Item -LiteralPath $videoConfigPath -Force
  }
  Remove-PythonCaches $payload
  Remove-TempFile $stdoutPath
  Remove-TempFile $stderrPath
}
