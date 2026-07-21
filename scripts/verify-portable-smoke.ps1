param(
    [Parameter(Mandatory = $true)]
    [string]$Path
)

$ErrorActionPreference = "Stop"

function Resolve-PayloadRoot {
    param([string]$InputPath)

    $item = Get-Item -LiteralPath $InputPath
    if (-not $item.PSIsContainer) {
        throw "Smoke verification expects an extracted portable directory, not a zip: $InputPath"
    }

    $legacyFiles = Join-Path $item.FullName "OpenClawFiles"
    if (Test-Path -LiteralPath $legacyFiles) {
        throw "Legacy OpenClawFiles payload is not allowed in a LOOM portable package: $legacyFiles"
    }
    $loomFiles = Join-Path $item.FullName "LOOMFiles"
    if (Test-Path -LiteralPath $loomFiles) {
        return $loomFiles
    }
    throw "LOOMFiles payload is missing: $($item.FullName)"
}

function Assert-File {
    param(
        [string]$Root,
        [string]$RelativePath
    )

    $full = Join-Path $Root $RelativePath
    if (-not (Test-Path -LiteralPath $full -PathType Leaf)) {
        throw "Missing required file: $RelativePath"
    }
    return $full
}

function Assert-Missing {
    param(
        [string]$Root,
        [string]$RelativePath
    )

    $full = Join-Path $Root $RelativePath
    if (Test-Path -LiteralPath $full) {
        throw "Forbidden legacy artifact included: $RelativePath"
    }
}

function Assert-PackageScriptsResolve {
    param([string]$PayloadRoot)

    $packageJsonPath = Assert-File -Root $PayloadRoot -RelativePath "package.json"
    $packageJson = Get-Content -LiteralPath $packageJsonPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if (-not $packageJson.scripts) {
        throw "package.json scripts are missing"
    }

    foreach ($property in $packageJson.scripts.PSObject.Properties) {
        $command = [string]$property.Value
        foreach ($match in [regex]::Matches($command, "node\s+scripts[\\/][^\s]+\.mjs")) {
            $relative = ($match.Value -replace "^node\s+", "") -replace "/", "\"
            Assert-File -Root $PayloadRoot -RelativePath $relative | Out-Null
        }
    }
}

function Invoke-Checked {
    param(
        [string]$Label,
        [scriptblock]$Script
    )

    Write-Host "==> $Label" -ForegroundColor Cyan
    & $Script
    Write-Host "OK: $Label" -ForegroundColor Green
}

$payloadRoot = Resolve-PayloadRoot -InputPath $Path
$packageRoot = Split-Path -Parent $payloadRoot
Write-Host "Portable smoke target: $payloadRoot"

Invoke-Checked "Required file layout" {
    Assert-File -Root $packageRoot -RelativePath "LOOM.exe" | Out-Null
    Assert-File -Root $payloadRoot -RelativePath "node\node.exe" | Out-Null
    Assert-File -Root $payloadRoot -RelativePath "start.js" | Out-Null
    Assert-File -Root $payloadRoot -RelativePath "node_modules\openclaw\openclaw.mjs" | Out-Null
    Assert-File -Root $payloadRoot -RelativePath "_up_\python-runtime\python.exe" | Out-Null
    Assert-File -Root $payloadRoot -RelativePath "_up_\python\bridge.py" | Out-Null
    Assert-File -Root $payloadRoot -RelativePath "_up_\python\loom_cli.py" | Out-Null
    Assert-File -Root $payloadRoot -RelativePath "_up_\python\loom_mcp.py" | Out-Null
    Assert-File -Root $packageRoot -RelativePath ".mcp.json" | Out-Null
    Assert-File -Root $payloadRoot -RelativePath "_up_\python\fastapi\__init__.py" | Out-Null
    Assert-File -Root $payloadRoot -RelativePath "_up_\python\uvicorn\__init__.py" | Out-Null
    Assert-File -Root $payloadRoot -RelativePath "scripts\openclaw-phone-agent.mjs" | Out-Null
    Assert-File -Root $payloadRoot -RelativePath "scripts\openclaw-context.mjs" | Out-Null
    Assert-File -Root $payloadRoot -RelativePath "scripts\openclaw-publish-phone.mjs" | Out-Null
    Assert-File -Root $payloadRoot -RelativePath "scripts\openclaw-publish-relay.mjs" | Out-Null
    Assert-File -Root $payloadRoot -RelativePath "scripts\openclaw-publish-relay-check.mjs" | Out-Null
    Assert-File -Root $payloadRoot -RelativePath "scripts\openclaw-publish-relay-smoke.mjs" | Out-Null
    Assert-PackageScriptsResolve -PayloadRoot $payloadRoot
    Assert-File -Root $payloadRoot -RelativePath "data\.openclaw\workspace\AGENTS.md" | Out-Null
    Assert-File -Root $payloadRoot -RelativePath "data\.openclaw\workspace\SOUL.md" | Out-Null
    Assert-File -Root $payloadRoot -RelativePath "data\.openclaw\workspace\TOOLS.md" | Out-Null
    Assert-File -Root $payloadRoot -RelativePath "data\.openclaw\workspace\CAPABILITIES.md" | Out-Null
    foreach ($legacy in @(
        "scripts\bot-plugin-helper.mjs",
        "scripts\package-mac-complete.mjs",
        "scripts\package-mac-online.mjs"
    )) {
        Assert-Missing -Root $payloadRoot -RelativePath $legacy
    }
    foreach ($privateArtifact in @(
        "data\.openclaw\launcher\phone-agent.json",
        "data\.openclaw\launcher\phone-agents.json",
        "data\.openclaw\launcher\desktop-agent.json",
        "data\.openclaw\launcher\bridge-session.json",
        "data\.openclaw\launcher\member-session.json",
        "data\.openclaw\launcher\wire-current.json",
        "data\.openclaw\launcher\wire-last-good.json",
        "data\.openclaw\launcher\agent-model-configs",
        "data\.openclaw\launcher\mcp-audit.jsonl",
        "data\.openclaw\launcher\loom-cli-audit.jsonl",
        "data\.openclaw\launcher\loom-task-ledger.jsonl",
        "data\.openclaw\launcher\loom-action-trace.jsonl",
        "data\.openclaw\launcher\loom-template-optimizer.json",
        "data\logs\bridge-service.log",
        "data\logs\openclaw-service.log",
        "data\logs\openclaw-startup-snapshot.json",
        "data\logs\loom-task-ledger.jsonl",
        "data\logs\loom-action-trace.jsonl",
        "data\logs\loom-template-optimizer.json"
    )) {
        Assert-Missing -Root $payloadRoot -RelativePath $privateArtifact
    }
}

Invoke-Checked "Bundled Python imports" {
    $pythonExe = Assert-File -Root $payloadRoot -RelativePath "_up_\python-runtime\python.exe"
    $pythonPath = Join-Path $payloadRoot "_up_\python"
    $oldPythonPath = $env:PYTHONPATH
    $oldDontWriteBytecode = $env:PYTHONDONTWRITEBYTECODE
    try {
        $env:PYTHONPATH = $pythonPath
        $env:PYTHONDONTWRITEBYTECODE = "1"
        & $pythonExe -B -c "import fastapi, uvicorn; import bridge; print('python smoke ok')"
        if ($LASTEXITCODE -ne 0) {
            throw "Bundled Python import smoke failed with exit code $LASTEXITCODE"
        }
    }
    finally {
        $env:PYTHONPATH = $oldPythonPath
        if ($null -eq $oldDontWriteBytecode) {
            Remove-Item Env:\PYTHONDONTWRITEBYTECODE -ErrorAction SilentlyContinue
        }
        else {
            $env:PYTHONDONTWRITEBYTECODE = $oldDontWriteBytecode
        }
    }
}

Invoke-Checked "Bundled Node CLI syntax" {
    $nodeExe = Assert-File -Root $payloadRoot -RelativePath "node\node.exe"
    foreach ($script in @(
        "scripts\openclaw-context.mjs",
        "scripts\openclaw-phone-agent.mjs",
        "scripts\openclaw-phone-fleet.mjs",
        "scripts\openclaw-phone-secure.mjs",
        "scripts\openclaw-phone-vision.mjs",
        "scripts\openclaw-phone-game.mjs",
        "scripts\openclaw-phone-video.mjs",
        "scripts\openclaw-image-phone.mjs",
        "scripts\openclaw-publish-phone.mjs",
        "scripts\openclaw-publish-relay.mjs",
        "scripts\openclaw-publish-relay-check.mjs",
        "scripts\openclaw-publish-relay-smoke.mjs"
    )) {
        $scriptPath = Assert-File -Root $payloadRoot -RelativePath $script
        & $nodeExe --check $scriptPath
        if ($LASTEXITCODE -ne 0) {
            throw "Node syntax smoke failed: $script"
        }
    }
}

Invoke-Checked "Runtime context hard guard" {
    $contextPath = Assert-File -Root $payloadRoot -RelativePath "data\.openclaw\workspace\runtime-context.json"
    $context = Get-Content -LiteralPath $contextPath -Raw | ConvertFrom-Json
    if ($context.phone.baseUrl) {
        throw "runtime-context.json must not expose phone.baseUrl"
    }
    if ($context.phone.endpoint -ne "launcher-cli-wrapper") {
        throw "phone.endpoint must be launcher-cli-wrapper"
    }
    if ($context.capabilities.phoneAgent.controlPolicy -ne "wrapper-only") {
        throw "phoneAgent.controlPolicy must be wrapper-only"
    }
    if ($context.capabilities.phoneAgent.agentCli -ne "npm run phone:agent") {
        throw "phoneAgent.agentCli must be npm run phone:agent"
    }
    if ($context.capabilities.phoneAgent.fleetCli -ne "npm run phone:fleet") {
        throw "phoneAgent.fleetCli must be npm run phone:fleet"
    }
}

Write-Host "Portable smoke verification passed." -ForegroundColor Green
