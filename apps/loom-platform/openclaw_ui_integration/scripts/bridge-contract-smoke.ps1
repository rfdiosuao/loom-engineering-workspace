param(
  [string]$Python = ""
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = (Resolve-Path (Join-Path $scriptDir "..")).Path
$bridgePath = Join-Path $root "python\bridge.py"
$venvPython = Join-Path $root ".venv\Scripts\python.exe"
if (-not $Python) {
  if (Test-Path -LiteralPath $venvPython) {
    $Python = $venvPython
  } elseif ($env:PYTHON) {
    $Python = $env:PYTHON
  } else {
    $Python = "python"
  }
}
$videoConfigPath = Join-Path $root "video_config.json"
$stdoutPath = Join-Path ([System.IO.Path]::GetTempPath()) "openclaw-bridge-smoke-$PID.out"
$stderrPath = Join-Path ([System.IO.Path]::GetTempPath()) "openclaw-bridge-smoke-$PID.err"
$bridge = $null
$originalVideoExists = Test-Path -LiteralPath $videoConfigPath
$originalVideoContent = if ($originalVideoExists) { Get-Content -Raw -LiteralPath $videoConfigPath } else { $null }

function Assert-True {
  param(
    [bool]$Condition,
    [string]$Message
  )
  if (-not $Condition) {
    throw $Message
  }
}

function Has-Property {
  param(
    [object]$Value,
    [string]$Name
  )
  return $null -ne $Value -and ($Value.PSObject.Properties.Name -contains $Name)
}

function Stop-Bridge {
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
  param([string]$Path)
  if (-not (Test-Path -LiteralPath $Path)) {
    return
  }
  for ($i = 0; $i -lt 10; $i += 1) {
    try {
      Remove-Item -LiteralPath $Path -Force
      return
    } catch {
      Start-Sleep -Milliseconds 200
    }
  }
  Write-Warning "Could not remove temp file: $Path"
}

function Start-Bridge {
  Remove-TempFile $stdoutPath
  Remove-TempFile $stderrPath

  $process = Start-Process `
    -FilePath $Python `
    -ArgumentList @("-u", $bridgePath) `
    -WorkingDirectory (Join-Path $root "python") `
    -RedirectStandardOutput $stdoutPath `
    -RedirectStandardError $stderrPath `
    -WindowStyle Hidden `
    -PassThru

  $deadline = (Get-Date).AddSeconds(35)
  while ((Get-Date) -lt $deadline) {
    if ($process.HasExited) {
      $out = if (Test-Path -LiteralPath $stdoutPath) { [string](Get-Content -Raw -LiteralPath $stdoutPath) } else { "" }
      $err = if (Test-Path -LiteralPath $stderrPath) { [string](Get-Content -Raw -LiteralPath $stderrPath) } else { "" }
      throw "Bridge exited before startup.`nSTDOUT:`n$out`nSTDERR:`n$err"
    }

    $text = if (Test-Path -LiteralPath $stdoutPath) { [string](Get-Content -Raw -LiteralPath $stdoutPath) } else { "" }
    $portMatch = [regex]::Match($text, "BRIDGE_PORT=(\d+)")
    $tokenMatch = [regex]::Match($text, "BRIDGE_TOKEN=([0-9a-fA-F]+)")
    $implMatch = [regex]::Match($text, "BRIDGE_IMPL=([^\r\n]+)")

    if ($portMatch.Success -and $tokenMatch.Success -and $implMatch.Success) {
      $impl = $implMatch.Groups[1].Value.Trim()
      Assert-True ($impl -eq "fastapi") "Expected FastAPI bridge, got '$impl'."
      return [pscustomobject]@{
        Process = $process
        Port = [int]$portMatch.Groups[1].Value
        Token = $tokenMatch.Groups[1].Value
      }
    }

    Start-Sleep -Milliseconds 250
  }

  $outText = if (Test-Path -LiteralPath $stdoutPath) { [string](Get-Content -Raw -LiteralPath $stdoutPath) } else { "" }
  $errText = if (Test-Path -LiteralPath $stderrPath) { [string](Get-Content -Raw -LiteralPath $stderrPath) } else { "" }
  Stop-Bridge $process
  throw "Timed out waiting for bridge startup.`nSTDOUT:`n$outText`nSTDERR:`n$errText"
}

function Invoke-Bridge {
  param(
    [string]$Method,
    [string]$Path,
    [object]$Body = $null,
    [int]$ExpectedStatus = 200
  )

  $uri = "http://127.0.0.1:$($script:bridgeInfo.Port)$Path"
  $headers = @{ "X-Bridge-Token" = $script:bridgeInfo.Token }
  $jsonBody = if ($null -ne $Body) { $Body | ConvertTo-Json -Depth 50 } else { $null }
  $status = $null
  $content = ""

  try {
    $response = Invoke-WebRequest `
      -UseBasicParsing `
      -Method $Method `
      -Uri $uri `
      -Headers $headers `
      -ContentType "application/json" `
      -Body $jsonBody
    $status = [int]$response.StatusCode
    $content = [string]$response.Content
  } catch {
    $response = $_.Exception.Response
    if ($null -eq $response) {
      throw
    }
    $status = [int]$response.StatusCode
    if ($_.ErrorDetails -and $_.ErrorDetails.Message) {
      $content = $_.ErrorDetails.Message
    } else {
      $stream = $response.GetResponseStream()
      if ($stream) {
        $reader = New-Object System.IO.StreamReader($stream)
        $content = $reader.ReadToEnd()
      }
    }
  }

  if ($status -ne $ExpectedStatus) {
    throw "Expected HTTP $ExpectedStatus for $Method $Path, got $status. Body: $content"
  }

  $parsed = $null
  if ($content.Trim()) {
    $parsed = $content | ConvertFrom-Json
  }

  return [pscustomobject]@{
    Status = $status
    Json = $parsed
    Content = $content
  }
}

try {
  $script:bridgeInfo = Start-Bridge

  $member = Invoke-Bridge -Method "GET" -Path "/api/member/current"
  Assert-True (Has-Property $member.Json "member") "/api/member/current must include member."

  $license = Invoke-Bridge -Method "GET" -Path "/api/license/current"
  Assert-True (Has-Property $license.Json "license") "/api/license/current must include license."
  Assert-True (Has-Property $license.Json "gatewayProfile") "/api/license/current must include gatewayProfile."
  Assert-True (Has-Property $license.Json "member") "/api/license/current must include member."

  $configRead = Invoke-Bridge -Method "POST" -Path "/api/config/read" -Body @{ path = "video_config.json"; default = @{ smoke = "default" } }
  Assert-True ($configRead.Json.data.smoke -eq "default") "/api/config/read did not return the default value."

  Invoke-Bridge -Method "POST" -Path "/api/config/read" -Body @{ path = "..\outside-openclaw-smoke.json"; default = @{} } -ExpectedStatus 403 | Out-Null
  Invoke-Bridge -Method "POST" -Path "/api/config/write" -Body @{ path = "video_config.json" } -ExpectedStatus 400 | Out-Null

  $diagnostics = Invoke-Bridge -Method "GET" -Path "/api/diagnostics/run"
  Assert-True (Has-Property $diagnostics.Json "summary") "/api/diagnostics/run must include summary."
  Assert-True (Has-Property $diagnostics.Json "checks") "/api/diagnostics/run must include checks."

  $processStatus = Invoke-Bridge -Method "GET" -Path "/api/process/status"
  Assert-True (Has-Property $processStatus.Json "running") "/api/process/status must include running."

  $systemInfo = Invoke-Bridge -Method "GET" -Path "/api/system/info"
  Assert-True (Has-Property $systemInfo.Json "base_path") "/api/system/info must include base_path."

  $update = Invoke-Bridge -Method "GET" -Path "/api/update/check"
  Assert-True (Has-Property $update.Json "current") "/api/update/check must include current."
  Assert-True (Has-Property $update.Json "latest") "/api/update/check must include latest."
  Assert-True (Has-Property $update.Json "hasUpdate") "/api/update/check must include hasUpdate."

  $marker = "bridge-smoke-$PID"
  Invoke-Bridge -Method "POST" -Path "/api/config/write" -Body @{ path = "video_config.json"; data = @{ marker = $marker; providerId = "smoke"; nested = @{ ok = $true } } } | Out-Null

  Stop-Bridge $script:bridgeInfo.Process
  $script:bridgeInfo = Start-Bridge

  $persisted = Invoke-Bridge -Method "POST" -Path "/api/config/read" -Body @{ path = "video_config.json"; default = @{} }
  Assert-True ($persisted.Json.data.marker -eq $marker) "video_config.json did not persist across bridge restart."

  Write-Host "Bridge contract smoke test passed."
} finally {
  if ($script:bridgeInfo) {
    Stop-Bridge $script:bridgeInfo.Process
  }
  if ($originalVideoExists) {
    Set-Content -LiteralPath $videoConfigPath -Value $originalVideoContent -Encoding UTF8 -NoNewline
  } elseif (Test-Path -LiteralPath $videoConfigPath) {
    Remove-Item -LiteralPath $videoConfigPath -Force
  }
  Remove-TempFile $stdoutPath
  Remove-TempFile $stderrPath
}
