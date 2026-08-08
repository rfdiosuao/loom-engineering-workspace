[CmdletBinding()]
param(
    [ValidateRange(1, 100)]
    [int]$Iterations = 5,

    [ValidateRange(0, 5000)]
    [int]$SyntheticRemoteStepLatencyMs = 10,

    [string]$FixturePath,

    [string]$RuntimeAdapterExecutable,

    [ValidatePattern('^[0-9A-Fa-f]{64}$')]
    [string]$RuntimeAdapterSha256,

    [string]$OutputPath
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$toolRoot = Split-Path -Parent $PSCommandPath
if ([string]::IsNullOrWhiteSpace($FixturePath)) {
    $FixturePath = Join-Path $toolRoot 'fixtures\mobile-runtime-batch.jsonl'
}

$resolvedFixture = (Resolve-Path -LiteralPath $FixturePath).Path
$fixtureLines = @(
    Get-Content -LiteralPath $resolvedFixture -Encoding UTF8 |
        Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
)
if ($fixtureLines.Count -eq 0) {
    throw 'Benchmark fixture must contain at least one JSONL item.'
}
foreach ($line in $fixtureLines) {
    $item = $line | ConvertFrom-Json
    if ([string]::IsNullOrWhiteSpace([string]$item.id) -or [string]::IsNullOrWhiteSpace([string]$item.text)) {
        throw 'Each fixture item must contain non-empty id and text fields.'
    }
}

function Measure-Samples {
    param(
        [Parameter(Mandatory)]
        [scriptblock]$Operation,
        [Parameter(Mandatory)]
        [int]$Count
    )

    $samples = New-Object System.Collections.Generic.List[double]
    for ($index = 0; $index -lt $Count; $index++) {
        $stopwatch = [System.Diagnostics.Stopwatch]::StartNew()
        & $Operation | Out-Null
        $stopwatch.Stop()
        $samples.Add([Math]::Round($stopwatch.Elapsed.TotalMilliseconds, 3))
    }
    $sorted = @($samples | Sort-Object)
    $medianIndex = [Math]::Floor(($sorted.Count - 1) / 2)
    [ordered]@{
        samplesMs = @($samples)
        medianMs = $sorted[$medianIndex]
        minMs = $sorted[0]
        maxMs = $sorted[-1]
    }
}

$nativeOperation = {
    foreach ($line in $fixtureLines) {
        $item = $line | ConvertFrom-Json
        ([string]$item.text).Trim().ToLowerInvariant() | Out-Null
    }
}

$nativeCold = Measure-Samples -Operation $nativeOperation -Count 1
$nativeWarm = Measure-Samples -Operation $nativeOperation -Count $Iterations
$nativeMeasurement = [ordered]@{
    status = 'measured_host_harness'
    cold = $nativeCold
    warm = $nativeWarm
    peakWorkingSetBytes = $null
    battery = 'not_collected_no_entity_device'
}

$remoteOperation = {
    foreach ($line in $fixtureLines) {
        if ($SyntheticRemoteStepLatencyMs -gt 0) {
            Start-Sleep -Milliseconds $SyntheticRemoteStepLatencyMs
        }
    }
}
$remoteMeasurement = [ordered]@{
    status = 'synthetic_latency_model'
    perStepLatencyMs = $SyntheticRemoteStepLatencyMs
    stepsPerIteration = $fixtureLines.Count
    cold = Measure-Samples -Operation $remoteOperation -Count 1
    warm = Measure-Samples -Operation $remoteOperation -Count $Iterations
    peakWorkingSetBytes = $null
    battery = 'not_collected_no_entity_device'
}

$runtimeMeasurement = [ordered]@{
    status = 'not_measured_adapter_missing'
    cold = $null
    warm = $null
    peakWorkingSetBytes = $null
    battery = 'not_collected_no_entity_device'
}

if (-not [string]::IsNullOrWhiteSpace($RuntimeAdapterExecutable)) {
    if ([string]::IsNullOrWhiteSpace($RuntimeAdapterSha256)) {
        throw 'RuntimeAdapterSha256 is required when RuntimeAdapterExecutable is provided.'
    }
    $resolvedAdapter = (Resolve-Path -LiteralPath $RuntimeAdapterExecutable).Path
    $actualAdapterHash = (Get-FileHash -LiteralPath $resolvedAdapter -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actualAdapterHash -ne $RuntimeAdapterSha256.ToLowerInvariant()) {
        throw "Runtime adapter SHA-256 mismatch. actual=$actualAdapterHash"
    }

    $script:runtimePeakWorkingSet = 0L
    $runtimeOperation = {
        $temporaryOutput = Join-Path ([System.IO.Path]::GetTempPath()) ("loom-runtime-benchmark-{0}.json" -f [Guid]::NewGuid().ToString('N'))
        try {
            $startInfo = [System.Diagnostics.ProcessStartInfo]::new()
            $startInfo.FileName = $resolvedAdapter
            $startInfo.UseShellExecute = $false
            $startInfo.RedirectStandardOutput = $true
            $startInfo.RedirectStandardError = $true
            $startInfo.ArgumentList.Add('--loom-benchmark-batch')
            $startInfo.ArgumentList.Add('--input')
            $startInfo.ArgumentList.Add($resolvedFixture)
            $startInfo.ArgumentList.Add('--output')
            $startInfo.ArgumentList.Add($temporaryOutput)
            $process = [System.Diagnostics.Process]::Start($startInfo)
            if (-not $process.WaitForExit(120000)) {
                $process.Kill($true)
                throw 'Runtime adapter benchmark timed out.'
            }
            $standardOutput = $process.StandardOutput.ReadToEnd()
            $standardError = $process.StandardError.ReadToEnd()
            if ($process.ExitCode -ne 0) {
                throw "Runtime adapter failed with exit code $($process.ExitCode): $($standardError.Substring(0, [Math]::Min(512, $standardError.Length)))"
            }
            if (-not (Test-Path -LiteralPath $temporaryOutput -PathType Leaf)) {
                throw 'Runtime adapter did not produce the fixed benchmark output.'
            }
            $script:runtimePeakWorkingSet = [Math]::Max($script:runtimePeakWorkingSet, $process.PeakWorkingSet64)
            $standardOutput | Out-Null
        }
        finally {
            if (Test-Path -LiteralPath $temporaryOutput -PathType Leaf) {
                Remove-Item -LiteralPath $temporaryOutput -Force
            }
        }
    }

    $runtimeMeasurement = [ordered]@{
        status = 'measured_verified_adapter'
        adapterSha256 = $actualAdapterHash
        cold = Measure-Samples -Operation $runtimeOperation -Count 1
        warm = Measure-Samples -Operation $runtimeOperation -Count $Iterations
        peakWorkingSetBytes = $script:runtimePeakWorkingSet
        battery = 'not_collected_no_entity_device'
    }
}

$result = [ordered]@{
    schema = 'loom.mobile-linux-runtime-benchmark.v1'
    generatedAt = [DateTimeOffset]::UtcNow.ToString('o')
    environment = 'host_harness'
    fixture = [ordered]@{
        path = $resolvedFixture
        sha256 = (Get-FileHash -LiteralPath $resolvedFixture -Algorithm SHA256).Hash.ToLowerInvariant()
        bytes = (Get-Item -LiteralPath $resolvedFixture).Length
        items = $fixtureLines.Count
    }
    iterations = $Iterations
    nativeTyped = $nativeMeasurement
    optionalLinux = $runtimeMeasurement
    remoteSteps = $remoteMeasurement
    performanceClaimAllowed = $false
    claimBlockReason = 'Entity Android measurements for latency, memory, battery, temperature, and failure rate are required.'
}

$json = $result | ConvertTo-Json -Depth 10
if (-not [string]::IsNullOrWhiteSpace($OutputPath)) {
    $outputParent = Split-Path -Parent $OutputPath
    if ([string]::IsNullOrWhiteSpace($outputParent)) {
        $outputParent = (Get-Location).Path
    }
    $resolvedOutputParent = (Resolve-Path -LiteralPath $outputParent).Path
    $resolvedOutput = Join-Path $resolvedOutputParent (Split-Path -Leaf $OutputPath)
    [System.IO.File]::WriteAllText($resolvedOutput, $json, [System.Text.UTF8Encoding]::new($false))
}

$json
