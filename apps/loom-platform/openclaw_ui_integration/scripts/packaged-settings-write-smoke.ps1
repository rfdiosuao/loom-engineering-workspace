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
$payload = (Resolve-Path -LiteralPath $payload).Path

$python = Join-Path $payload "_up_\python-runtime\python.exe"
$bridgePath = Join-Path $payload "_up_\python\bridge.py"
$node = Join-Path $payload "node\node.exe"
$startJs = Join-Path $payload "start.js"
$openclawConfig = Join-Path $payload "data\.openclaw\openclaw.json"
$authProfiles = Join-Path $payload "data\.openclaw\agents\main\agent\auth-profiles.json"
$modelsJson = Join-Path $payload "data\.openclaw\agents\main\agent\models.json"
$phoneAgent = Join-Path $payload "data\.openclaw\launcher\phone-agent.json"
$phoneAgents = Join-Path $payload "data\.openclaw\launcher\phone-agents.json"

foreach ($required in @($python, $bridgePath, $node, $startJs)) {
  if (-not (Test-Path -LiteralPath $required)) {
    throw "Required packaged file missing: $required"
  }
}

$backup = @{}
foreach ($filePath in @($openclawConfig, $authProfiles, $modelsJson, $phoneAgent, $phoneAgents)) {
  $backup[$filePath] = if (Test-Path -LiteralPath $filePath) {
    [System.IO.File]::ReadAllText($filePath)
  } else {
    $null
  }
}

$stdoutPath = Join-Path ([System.IO.Path]::GetTempPath()) "openclaw-settings-write-$PID.out"
$stderrPath = Join-Path ([System.IO.Path]::GetTempPath()) "openclaw-settings-write-$PID.err"
$gatewayOut = Join-Path ([System.IO.Path]::GetTempPath()) "openclaw-settings-gateway-$PID.out"
$gatewayErr = Join-Path ([System.IO.Path]::GetTempPath()) "openclaw-settings-gateway-$PID.err"
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
$bridgeProc = $null
$gatewayProc = $null

function Stop-Tree {
  param([int]$ProcessId)

  $children = @(Get-CimInstance Win32_Process -Filter "ParentProcessId=$ProcessId" -ErrorAction SilentlyContinue)
  foreach ($child in $children) {
    Stop-Tree -ProcessId ([int]$child.ProcessId)
  }
  if (Get-Process -Id $ProcessId -ErrorAction SilentlyContinue) {
    Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
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

  Stop-Tree -ProcessId $process.Id
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
      TimeoutSec = 20
    }
    if ($null -ne $Body) {
      $params.Body = ($Body | ConvertTo-Json -Depth 50)
      $params.ContentType = "application/json"
    }
    $json = Invoke-RestMethod @params
    if ($ExpectedStatus -ne 200) {
      throw "Expected HTTP $ExpectedStatus but got 200 for $ApiPath"
    }
    return $json
  } catch {
    $response = $_.Exception.Response
    if ($null -eq $response) {
      throw
    }
    $status = [int]$response.StatusCode
    if ($status -ne $ExpectedStatus) {
      throw "Expected HTTP $ExpectedStatus but got $status for $ApiPath"
    }
    return $null
  }
}

function Assert-NoLauncherPreview {
  $config = Get-Content -Raw -LiteralPath $openclawConfig | ConvertFrom-Json
  if ($config.PSObject.Properties.Name -contains "launcherPreview") {
    throw "launcherPreview is still present in openclaw.json."
  }
}

function Wait-GatewayPort {
  param(
    [int]$Port,
    [object]$Process
  )

  $deadline = (Get-Date).AddSeconds(35)
  while ((Get-Date) -lt $deadline) {
    if ($Process.HasExited) {
      $out = if (Test-Path -LiteralPath $gatewayOut) { Get-Content -Raw -LiteralPath $gatewayOut } else { "" }
      $err = if (Test-Path -LiteralPath $gatewayErr) { Get-Content -Raw -LiteralPath $gatewayErr } else { "" }
      throw "Gateway exited early. stdout=$out stderr=$err"
    }
    if (Test-NetConnection -ComputerName "127.0.0.1" -Port $Port -InformationLevel Quiet -WarningAction SilentlyContinue) {
      return
    }
    Start-Sleep -Milliseconds 500
  }
  throw "Gateway did not listen on $Port after Settings-style config write."
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

try {
  $bridge = Start-PackagedBridge
  $bridgeProc = $bridge.Process

  $badOpenClaw = @{
    gateway = @{ auth = @{ mode = "none" }; bind = "loopback" }
    agents = @{ defaults = @{ workspace = "data/.openclaw/workspace"; contextInjection = "always"; bootstrapPromptTruncationWarning = "once" } }
    launcherPreview = @{ stale = $true; writtenBy = "settings-write-smoke" }
  }
  Invoke-PackagedBridge -Context $bridge -Method "POST" -ApiPath "/api/config/write" -Body @{ path = "data/.openclaw/openclaw.json"; data = $badOpenClaw } | Out-Null
  Assert-NoLauncherPreview

  $fakeProfiles = @{
    models = @{
      primary = "openclaw_gateway"
      providers = @{
        openclaw_gateway = @{
          id = "openclaw_gateway"
          name = "OpenClaw Gateway"
          baseUrl = "https://api.example.invalid/v1"
          apiKey = "contract-smoke-key-not-real"
          models = @("gpt-4o")
        }
      }
    }
  }
  Invoke-PackagedBridge -Context $bridge -Method "POST" -ApiPath "/api/config/write" -Body @{ path = "data/.openclaw/agents/main/agent/auth-profiles.json"; data = $fakeProfiles } | Out-Null
  Assert-NoLauncherPreview
  if (-not (Test-Path -LiteralPath $modelsJson)) {
    throw "models.json was not generated after auth-profiles.json write."
  }

  $packageJson = Get-Content -Raw -LiteralPath (Join-Path $payload "package.json") | ConvertFrom-Json
  foreach ($scriptName in @("phone:agent", "phone:fleet", "verify:phone")) {
    if (-not $packageJson.scripts.PSObject.Properties.Name.Contains($scriptName)) {
      throw "Packaged package.json is missing script: $scriptName"
    }
  }

  $phoneDevice = @{
    id = "contract-phone"
    name = "Contract APKClaw"
    baseUrl = "http://127.0.0.1:9527"
    token = "phone-contract-smoke-not-real"
    enabled = $true
    tags = @("smoke")
  }
  Invoke-PackagedBridge -Context $bridge -Method "POST" -ApiPath "/api/config/write" -Body @{ path = "data/.openclaw/launcher/phone-agent.json"; data = $phoneDevice } | Out-Null
  Invoke-PackagedBridge -Context $bridge -Method "POST" -ApiPath "/api/config/write" -Body @{
    path = "data/.openclaw/launcher/phone-agents.json"
    data = @{
      schema = "openclaw.launcher.phone-agents.v1"
      selectedDeviceId = "contract-phone"
      devices = @($phoneDevice)
    }
  } | Out-Null
  $fleetJson = & $node (Join-Path $payload "scripts\openclaw-phone-fleet.mjs") list --json | ConvertFrom-Json
  if (-not $fleetJson.ok -or $fleetJson.devices.Count -ne 1 -or $fleetJson.devices[0].configured -ne $true -or $fleetJson.devices[0].tokenAvailable -ne $true) {
    throw "phone fleet list did not see the persisted launcher phone config."
  }

  Stop-Tree -ProcessId $bridgeProc.Id
  $bridgeProc.WaitForExit(5000) | Out-Null
  $bridgeProc = $null

  $gatewayPort = 18897
  $gatewayEnv = @{
    OPENCLAW_HOME = Join-Path $payload "data"
    OPENCLAW_STATE_DIR = Join-Path $payload "data\.openclaw"
    OPENCLAW_CONFIG_PATH = $openclawConfig
    OPENCLAW_GATEWAY_PORT = [string]$gatewayPort
    NO_COLOR = "1"
  }
  foreach ($entry in $gatewayEnv.GetEnumerator()) {
    [Environment]::SetEnvironmentVariable($entry.Key, $entry.Value, "Process")
  }

  Remove-TempFile $gatewayOut
  Remove-TempFile $gatewayErr
  $gatewayProc = Start-Process `
    -FilePath $node `
    -ArgumentList @($startJs) `
    -WorkingDirectory $payload `
    -RedirectStandardOutput $gatewayOut `
    -RedirectStandardError $gatewayErr `
    -WindowStyle Hidden `
    -PassThru
  Wait-GatewayPort -Port $gatewayPort -Process $gatewayProc

  Write-Host "Packaged Settings write and gateway startup smoke passed."
} finally {
  if ($null -ne $gatewayProc -and -not $gatewayProc.HasExited) {
    Stop-Tree -ProcessId $gatewayProc.Id
    $gatewayProc.WaitForExit(5000) | Out-Null
  }
  if ($null -ne $bridgeProc -and -not $bridgeProc.HasExited) {
    Stop-Tree -ProcessId $bridgeProc.Id
    $bridgeProc.WaitForExit(5000) | Out-Null
  }
  foreach ($filePath in @($phoneAgents, $phoneAgent, $modelsJson, $authProfiles, $openclawConfig)) {
    $content = $backup[$filePath]
    if ($null -eq $content) {
      if (Test-Path -LiteralPath $filePath) {
        Remove-Item -LiteralPath $filePath -Force
      }
    } else {
      New-Item -ItemType Directory -Path (Split-Path -Parent $filePath) -Force | Out-Null
      [System.IO.File]::WriteAllText($filePath, $content, $utf8NoBom)
    }
  }
  Remove-PythonCaches $payload
  Remove-TempFile $stdoutPath
  Remove-TempFile $stderrPath
  Remove-TempFile $gatewayOut
  Remove-TempFile $gatewayErr
}
