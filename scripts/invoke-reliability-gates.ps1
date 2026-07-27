[CmdletBinding()]
param(
    [ValidateSet('all', 'installer', 'model', 'agent', 'matrix', 'ui')]
    [string[]]$Domain = @('all'),

    [ValidateSet('all', 'high', 'medium', 'low')]
    [string]$Risk = 'all',

    [string]$IncidentType = '',

    [switch]$Ci,

    [switch]$List
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'workspace-core.ps1')

$root = Get-LoomWorkspaceRoot
$manifestPath = Join-Path $root 'packages\contracts\reliability-gates.v1.json'
$manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
$allowedExecutables = @('python', 'npm', 'powershell')

function Assert-ReadOnlyGateCommand {
    param(
        [Parameter(Mandatory = $true)]
        [object]$Gate
    )

    $executable = [string]$Gate.command.executable
    $arguments = @($Gate.command.arguments | ForEach-Object { [string]$_ })

    switch ($executable) {
        'python' {
            if ($arguments.Count -lt 4 -or
                $arguments[0] -ne '-B' -or
                $arguments[1] -ne '-m' -or
                $arguments[2] -ne 'pytest') {
                throw "Python gate must invoke pytest with bytecode disabled: $($Gate.id)"
            }
        }
        'npm' {
            if ($arguments.Count -ne 2 -or
                $arguments[0] -ne 'run' -or
                -not $arguments[1].StartsWith('test:')) {
                throw "npm gate must invoke a test:* script: $($Gate.id)"
            }
        }
        'powershell' {
            $fileIndex = [Array]::IndexOf($arguments, '-File')
            if ($fileIndex -lt 0 -or $fileIndex + 1 -ge $arguments.Count) {
                throw "PowerShell gate must use -File: $($Gate.id)"
            }
            $scriptName = [System.IO.Path]::GetFileNameWithoutExtension($arguments[$fileIndex + 1])
            if (-not ($scriptName.StartsWith('test-') -or $scriptName.StartsWith('verify-'))) {
                throw "PowerShell gate must invoke a test-* or verify-* script: $($Gate.id)"
            }
        }
        default {
            throw "Gate executable is not allow-listed: $($Gate.id)"
        }
    }
}

if ($manifest.schema -ne 'loom.reliability-gates.v1') {
    throw "Unsupported reliability gate manifest: $($manifest.schema)"
}

$incidentGateIds = @()
if (-not [string]::IsNullOrWhiteSpace($IncidentType)) {
    $mapping = @($manifest.incidentMappings | Where-Object { $_.type -eq $IncidentType })
    if ($mapping.Count -ne 1) {
        throw "Unknown incident type: $IncidentType"
    }
    $incidentGateIds = @($mapping[0].gateIds)
}

$selected = @(
    $manifest.gates | Where-Object {
        $gate = $_
        $domainMatch = $Domain -contains 'all' -or $Domain -contains $gate.domain
        $riskMatch = $Risk -eq 'all' -or $Risk -eq $gate.risk
        $incidentMatch = $incidentGateIds.Count -eq 0 -or $incidentGateIds -contains $gate.id
        $ciMatch = -not $Ci -or $gate.ci -eq $true
        $domainMatch -and $riskMatch -and $incidentMatch -and $ciMatch
    } | Sort-Object domain, id
)

if ($selected.Count -eq 0) {
    throw 'No reliability gates matched the requested filters.'
}

foreach ($gate in $selected) {
    if ($gate.readOnly -ne $true -or $gate.requiresExternalEnvironment -ne $false) {
        throw "Gate is not safe for this runner: $($gate.id)"
    }
    if ($allowedExecutables -notcontains $gate.command.executable) {
        throw "Gate executable is not allow-listed: $($gate.id)"
    }
    Assert-ReadOnlyGateCommand -Gate $gate

    $workingDirectory = [System.IO.Path]::GetFullPath((Join-Path $root $gate.workingDirectory))
    if (-not (Test-LoomPathWithinRoot -Path $workingDirectory)) {
        throw "Gate working directory escapes the repository: $($gate.id)"
    }
    if (-not (Test-Path -LiteralPath $workingDirectory -PathType Container)) {
        throw "Gate working directory does not exist: $($gate.id)"
    }
}

if ($List) {
    $selected | Select-Object id, domain, risk, description, workingDirectory
    exit 0
}

$oldPythonBytecode = $env:PYTHONDONTWRITEBYTECODE
$oldReadOnly = $env:LOOM_RELIABILITY_GATE_READ_ONLY
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:LOOM_RELIABILITY_GATE_READ_ONLY = '1'

$passed = 0
try {
    foreach ($gate in $selected) {
        $workingDirectory = [System.IO.Path]::GetFullPath((Join-Path $root $gate.workingDirectory))
        $arguments = @($gate.command.arguments | ForEach-Object { [string]$_ })

        Write-Host "`n[$($gate.domain)] $($gate.id)" -ForegroundColor Cyan
        Write-Host $gate.description

        Push-Location $workingDirectory
        try {
            & $gate.command.executable @arguments
            if ($LASTEXITCODE -ne 0) {
                throw "Reliability gate failed: $($gate.id) (exit $LASTEXITCODE)"
            }
        } finally {
            Pop-Location
        }
        $passed += 1
    }
} finally {
    $env:PYTHONDONTWRITEBYTECODE = $oldPythonBytecode
    $env:LOOM_RELIABILITY_GATE_READ_ONLY = $oldReadOnly
}

Write-Host "`nReliability gates passed: $passed/$($selected.Count)" -ForegroundColor Green
