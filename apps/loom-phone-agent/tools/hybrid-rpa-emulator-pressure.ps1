[CmdletBinding()]
param(
    [string]$Adb = 'D:\android-sdk-windows\android-sdk-windows\platform-tools\adb.exe',
    [string]$Serial = 'emulator-5554',
    [string]$BaseUrl = 'http://127.0.0.1:9527',
    [string]$Token = '',
    [ValidateRange(30, 30)][int]$Runs = 30,
    [string]$FixturePath = (Join-Path $PSScriptRoot 'fixtures/hybrid-native-run.json'),
    [string]$OutputPath = (Join-Path (Split-Path $PSScriptRoot -Parent) 'build/reports/hybrid-rpa-pressure.json')
)

$ErrorActionPreference = 'Stop'
$Package = 'com.apk.claw.android'
$FixtureActivity = 'com.apk.claw.android.debug.HybridRpaFixtureActivity'
$AccessibilityService = "$Package/com.apk.claw.android.service.ClawAccessibilityService"
$MandatoryLive = @(
    'status_capabilities',
    'observe_fast_no_llm',
    'screenshot_live',
    'active_tree_preferred_pressure',
    'busy_structured',
    'accessibility_disabled_structured',
    'model_missing_fast_path',
    'orientation_change_reobserve'
)
$Cases = New-Object System.Collections.Generic.List[object]
$RunRecords = New-Object System.Collections.Generic.List[object]
$OriginalAccessibility = $null
$OriginalAccessibilityEnabled = $null
$OriginalRotation = $null
$HadTemplateIndex = $false
$TemplateIndexProbed = $false
$TemplateIndexTouched = $false
$TemplateBackupCreated = $false
$TemplateTransactionCreated = $false
$CreatedForward = $false
$HarnessFailure = $null

function Redact-Text([string]$Text) {
    $safe = $Text
    if (-not [string]::IsNullOrEmpty($Token)) { $safe = $safe.Replace($Token, '[redacted]') }
    return [regex]::Replace($safe, '(?i)token\s*[:=]\s*\S+', 'token=[redacted]')
}

function Sanitize-Record($Value) {
    if ($null -eq $Value) { return $null }
    if ($Value -is [string]) { return (Redact-Text $Value) }
    if ($Value -is [System.ValueType]) { return $Value }
    if ($Value -is [System.Collections.IDictionary]) {
        $copy = [ordered]@{}
        foreach ($key in $Value.Keys) { $copy[$key] = Sanitize-Record $Value[$key] }
        return [pscustomobject]$copy
    }
    if ($Value -is [pscustomobject]) {
        $copy = [ordered]@{}
        foreach ($property in $Value.PSObject.Properties) {
            $copy[$property.Name] = Sanitize-Record $property.Value
        }
        return [pscustomobject]$copy
    }
    if ($Value -is [System.Collections.IEnumerable] -and $Value -isnot [string]) {
        return @($Value | ForEach-Object { Sanitize-Record $_ })
    }
    return $Value
}

function Add-Case([string]$Name, [ValidateSet('passed', 'skipped', 'source_verified', 'failed')] [string]$Status, [string]$Reason = '', $Data = $null) {
    $Cases.Add([pscustomobject]@{
        name = $Name
        status = $Status
        reason = Redact-Text $Reason
        data = Sanitize-Record $Data
    })
}

function New-EphemeralToken {
    $bytes = New-Object byte[] 24
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    return 'fixture-' + [Convert]::ToBase64String($bytes).Replace('+', 'A').Replace('/', 'B').Replace('=', '')
}

function Assert-Preflight([bool]$Condition, [string]$Reason) {
    if (-not $Condition) { throw $Reason }
}

function Test-JsonProperty($Value, [string]$Name) {
    return $null -ne $Value -and $null -ne $Value.PSObject.Properties[$Name]
}

function Invoke-Api([string]$Method, [string]$Path, [string]$Body = $null) {
    $arguments = @{ Method = $Method; Uri = "$BaseUrl$Path"; Headers = @{ 'X-Agent-Phone-Token' = $Token }; TimeoutSec = 30; UseBasicParsing = $true }
    if (-not [string]::IsNullOrEmpty($Body)) { $arguments.ContentType = 'application/json'; $arguments.Body = $Body }
    try {
        $response = Invoke-WebRequest @arguments
        return [pscustomobject]@{ httpStatus = [int]$response.StatusCode; body = ($response.Content | ConvertFrom-Json); error = '' }
    } catch {
        $message = $_.Exception.Message
        return [pscustomobject]@{ httpStatus = 0; body = $null; error = (Redact-Text $message) }
    }
}

function Invoke-Adb([string[]]$Arguments) {
    $output = & $Adb -s $Serial @Arguments 2>&1 | Out-String
    if ($LASTEXITCODE -ne 0) { throw ('adb_command_failed: ' + (Redact-Text $output).Trim()) }
    return $output.Trim()
}

function Wait-RpaTerminal([string]$RunId) {
    $deadline = [DateTime]::UtcNow.AddSeconds(25)
    do {
        Start-Sleep -Milliseconds 150
        $response = Invoke-Api 'GET' "/api/rpa/runs/$RunId"
        if ($response.body -and $response.body.success -eq $true -and $response.body.data.status -notin @('queued', 'running')) {
            return $response.body.data
        }
    } while ([DateTime]::UtcNow -lt $deadline)
    return $null
}

function Wait-HybridRuntimeReady {
    $deadline = [DateTime]::UtcNow.AddSeconds(10)
    do {
        $response = Invoke-Api 'GET' '/api/rpa/capabilities'
        if ($response.body -and $response.body.success -eq $true -and $response.body.data.hybridRuntimeReady -eq $true) {
            return $response
        }
        Start-Sleep -Milliseconds 200
    } while ([DateTime]::UtcNow -lt $deadline)
    return $response
}

function Percentile([long[]]$Values, [double]$Percent) {
    if ($Values.Count -eq 0) { return $null }
    $sorted = @($Values | Sort-Object)
    $rank = [Math]::Ceiling($sorted.Count * $Percent)
    $index = [Math]::Min($sorted.Count - 1, [Math]::Max(0, $rank - 1))
    return $sorted[$index]
}

function Get-MandatoryLiveFailures {
    $failures = New-Object System.Collections.Generic.List[string]
    foreach ($name in $MandatoryLive) {
        $matches = @($Cases | Where-Object { $_.name -eq $name })
        if ($matches.Count -ne 1 -or $matches[0].status -ne 'passed') {
            $failures.Add($name)
        }
    }
    return @($failures)
}

function Start-Fixture {
    Invoke-Adb @('shell', 'am', 'start', '-W', '-n', "$Package/$FixtureActivity", '--ez', 'com.apk.claw.android.debug.HYBRID_RPA_CONFIGURE', 'true', '--es', 'com.apk.claw.android.debug.HYBRID_RPA_TOKEN', $Token) | Out-Null
}

function Snapshot-FixtureConfiguration {
    Invoke-Adb @('shell', 'am', 'start', '-W', '-n', "$Package/$FixtureActivity", '--ez', 'com.apk.claw.android.debug.HYBRID_RPA_SNAPSHOT_ONLY', 'true') | Out-Null
}

function Restore-FixtureConfiguration {
    Invoke-Adb @('shell', 'am', 'start', '-W', '-n', "$Package/$FixtureActivity", '--ez', 'com.apk.claw.android.debug.HYBRID_RPA_RESTORE', 'true') | Out-Null
    Start-Sleep -Milliseconds 200
    $recovery = & $Adb -s $Serial shell run-as $Package cat shared_prefs/hybrid_rpa_fixture_recovery.xml 2>$null | Out-String
    if ($recovery -match 'snapshot_taken') { throw 'fixture_configuration_restore_unconfirmed' }
}

function Recover-AbandonedTemplateTransaction {
    & $Adb -s $Serial shell run-as $Package test -f files/workflow_templates/template_index.json.pressure-transaction 2>$null | Out-Null
    $hasTransaction = $LASTEXITCODE -eq 0
    & $Adb -s $Serial shell run-as $Package test -f files/workflow_templates/template_index.json.pressure-backup 2>$null | Out-Null
    $hasBackup = $LASTEXITCODE -eq 0
    if (-not $hasTransaction -and -not $hasBackup) {
        & $Adb -s $Serial shell run-as $Package rm -f files/workflow_templates/template_index.json.pressure-transaction-new files/workflow_templates/template_index.json.pressure-new 2>$null | Out-Null
        return
    }

    if ($hasTransaction) {
        $transaction = (& $Adb -s $Serial shell run-as $Package cat files/workflow_templates/template_index.json.pressure-transaction 2>$null | Out-String).Trim()
        if ($transaction -eq 'present') {
            if (-not $hasBackup) { throw 'template_index_abandoned_backup_missing' }
            & $Adb -s $Serial shell run-as $Package cp files/workflow_templates/template_index.json.pressure-backup files/workflow_templates/template_index.json 2>$null | Out-Null
            if ($LASTEXITCODE -ne 0) { throw 'template_index_abandoned_restore_failed' }
        } elseif ($transaction -eq 'absent') {
            & $Adb -s $Serial shell run-as $Package rm -f files/workflow_templates/template_index.json 2>$null | Out-Null
            if ($LASTEXITCODE -ne 0) { throw 'template_index_abandoned_cleanup_failed' }
        } else {
            throw 'template_index_transaction_invalid'
        }
    } elseif ($hasBackup) {
        & $Adb -s $Serial shell run-as $Package cp files/workflow_templates/template_index.json.pressure-backup files/workflow_templates/template_index.json 2>$null | Out-Null
        if ($LASTEXITCODE -ne 0) { throw 'template_index_orphan_backup_restore_failed' }
    }

    & $Adb -s $Serial shell run-as $Package rm -f files/workflow_templates/template_index.json.pressure-transaction 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'template_index_transaction_marker_cleanup_failed' }
    & $Adb -s $Serial shell run-as $Package rm -f files/workflow_templates/template_index.json.pressure-backup files/workflow_templates/template_index.json.pressure-new 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'template_index_transaction_cleanup_failed' }
    $script:TemplateIndexTouched = $false
    $script:TemplateBackupCreated = $false
    $script:TemplateTransactionCreated = $false
}

function Seed-TemplateIndex([string]$Json) {
    & $Adb -s $Serial shell run-as $Package mkdir -p files/workflow_templates 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'template_index_directory_failed' }
    Recover-AbandonedTemplateTransaction
    & $Adb -s $Serial shell run-as $Package test -f files/workflow_templates/template_index.json 2>$null | Out-Null
    $script:TemplateIndexProbed = $true
    $script:HadTemplateIndex = $LASTEXITCODE -eq 0
    if ($script:HadTemplateIndex) {
        & $Adb -s $Serial shell run-as $Package cp files/workflow_templates/template_index.json files/workflow_templates/template_index.json.pressure-backup 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) { throw 'template_index_backup_failed' }
        $script:TemplateBackupCreated = $true
    }
    $transactionState = if ($script:HadTemplateIndex) { 'present' } else { 'absent' }
    $transactionState | & $Adb -s $Serial shell run-as $Package tee files/workflow_templates/template_index.json.pressure-transaction-new 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'template_index_transaction_write_failed' }
    & $Adb -s $Serial shell run-as $Package mv files/workflow_templates/template_index.json.pressure-transaction-new files/workflow_templates/template_index.json.pressure-transaction 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'template_index_transaction_commit_failed' }
    $script:TemplateTransactionCreated = $true
    $Json | & $Adb -s $Serial shell run-as $Package tee files/workflow_templates/template_index.json.pressure-new 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'template_index_seed_failed' }
    & $Adb -s $Serial shell run-as $Package mv files/workflow_templates/template_index.json.pressure-new files/workflow_templates/template_index.json 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'template_index_replace_failed' }
    $script:TemplateIndexTouched = $true
}

function Restore-TemplateIndex {
    if (-not $TemplateIndexProbed -and -not $TemplateIndexTouched -and -not $TemplateBackupCreated -and -not $TemplateTransactionCreated) { return }
    Recover-AbandonedTemplateTransaction
}

try {
    Assert-Preflight ([IO.Path]::IsPathRooted($Adb) -and (Test-Path -LiteralPath $Adb)) 'adb_not_found_or_not_absolute'
    Assert-Preflight (Test-Path -LiteralPath $FixturePath) 'fixture_not_found'
    Assert-Preflight (-not [string]::IsNullOrWhiteSpace($Serial)) 'serial_required'
    if ([string]::IsNullOrWhiteSpace($Token)) { $Token = New-EphemeralToken }
    Assert-Preflight ($Token.Length -ge 16 -and $Token.Length -le 128) 'token_length_invalid'
    $FixturePath = (Resolve-Path -LiteralPath $FixturePath).Path
    $OutputPath = [IO.Path]::GetFullPath($OutputPath)
    New-Item -ItemType Directory -Force (Split-Path -Parent $OutputPath) | Out-Null

    $devices = (& $Adb devices 2>$null | Out-String)
    Assert-Preflight ($devices -match "(?m)^$([regex]::Escape($Serial))\s+device\s*$") 'emulator_not_ready'
    Assert-Preflight ((Invoke-Adb @('shell', 'run-as', $Package, 'id')).Length -gt 0) 'debuggable_package_required'
    Assert-Preflight ((Invoke-Adb @('shell', 'cmd', 'package', 'resolve-activity', '--brief', '-n', "$Package/$FixtureActivity")).Contains('HybridRpaFixtureActivity')) 'debug_fixture_activity_missing'

    $forwardLines = @(& $Adb -s $Serial forward --list 2>$null)
    $existingForward = @($forwardLines | Where-Object { $_ -match "^$([regex]::Escape($Serial))\s+tcp:9527\s+" })
    Assert-Preflight ($existingForward.Count -eq 0 -or $existingForward[0] -match '\s+tcp:9527$') 'host_forward_conflict'
    $CreatedForward = $existingForward.Count -eq 0
    Invoke-Adb @('forward', 'tcp:9527', 'tcp:9527') | Out-Null
    $OriginalAccessibility = (Invoke-Adb @('shell', 'settings', 'get', 'secure', 'enabled_accessibility_services'))
    $OriginalAccessibilityEnabled = (Invoke-Adb @('shell', 'settings', 'get', 'secure', 'accessibility_enabled'))
    $OriginalRotation = (Invoke-Adb @('shell', 'wm', 'user-rotation'))
    Snapshot-FixtureConfiguration
    Invoke-Adb @('shell', 'am', 'force-stop', $Package) | Out-Null
    Start-Fixture
    Invoke-Adb @('shell', 'settings', 'delete', 'secure', 'enabled_accessibility_services') | Out-Null
    Invoke-Adb @('shell', 'settings', 'put', 'secure', 'accessibility_enabled', '0') | Out-Null
    $enabled = @(
        @($OriginalAccessibility -split ':' | Where-Object { $_ -and $_ -ne 'null' })
        $AccessibilityService
    ) | Select-Object -Unique
    $enabled = $enabled -join ':'
    Invoke-Adb @('shell', 'settings', 'put', 'secure', 'enabled_accessibility_services', $enabled) | Out-Null
    Invoke-Adb @('shell', 'settings', 'put', 'secure', 'accessibility_enabled', '1') | Out-Null
    $runtimeReady = Wait-HybridRuntimeReady
    $fixtureRaw = Get-Content -Raw -LiteralPath $FixturePath
    $profileId = '000000000000000000000000'
    $fixture = (($fixtureRaw -replace '__PROFILE_ID__', $profileId) | ConvertFrom-Json)
    Seed-TemplateIndex ($fixture.templateIndex | ConvertTo-Json -Depth 100 -Compress)
    Start-Fixture
    $runBody = $fixture.rpaRunPayload | ConvertTo-Json -Depth 100 -Compress

    $status = Invoke-Api 'GET' '/api/device/status'
    $capabilities = if ($runtimeReady) { $runtimeReady } else { Invoke-Api 'GET' '/api/rpa/capabilities' }
    if ($status.body.success -eq $true -and $capabilities.body.success -eq $true -and $capabilities.body.data.hybridSchema -eq 'apkclaw.hybrid-rpa.v2') {
        Add-Case 'status_capabilities' 'passed' '' @{ versionCode = $status.body.data.versionCode; hybridRuntimeState = $capabilities.body.data.hybridRuntimeState }
    } else { Add-Case 'status_capabilities' 'failed' 'status_or_capabilities_not_structured' @{ statusError = $status.error; capabilitiesError = $capabilities.error; statusHttp = $status.httpStatus; capabilitiesHttp = $capabilities.httpStatus } }

    $observe = Invoke-Api 'GET' '/api/tool/observe_fast?debug=true'
    if ($observe.body.success -eq $true -and $observe.body.data.metrics -and $observe.body.data.metrics.llmRoundMs -eq 0 -and $observe.body.data.metrics.rounds -eq 0) {
        Add-Case 'observe_fast_no_llm' 'passed' '' @{ cacheHit = $observe.body.data.cacheHit; durationMs = $observe.body.data.durationMs; screenTreeMs = $observe.body.data.metrics.screenTreeMs }
    } else { Add-Case 'observe_fast_no_llm' 'failed' 'observe_fast_missing_structured_no_llm_evidence' @{ httpStatus = $observe.httpStatus; error = $observe.error; errorCode = $observe.body.data.errorCode } }

    $screenshot = Invoke-Api 'GET' '/api/tool/screenshot'
    if ($screenshot.body.success -eq $true -and $screenshot.body.data.mime -eq 'image/png' -and -not [string]::IsNullOrWhiteSpace($screenshot.body.data.base64)) {
        Add-Case 'screenshot_live' 'passed' '' @{ width = $screenshot.body.data.width; height = $screenshot.body.data.height; mime = $screenshot.body.data.mime }
    } else { Add-Case 'screenshot_live' 'failed' 'screenshot_not_successful_and_structured' @{ httpStatus = $screenshot.httpStatus; error = $screenshot.error; errorCode = $screenshot.body.data.errorCode } }

    for ($index = 1; $index -le $Runs; $index++) {
        Start-Fixture
        $started = [Diagnostics.Stopwatch]::StartNew()
        $start = Invoke-Api 'POST' '/api/rpa/run' $runBody
        $terminal = if ($start.body.success -eq $true -and $start.body.data.accepted -eq $true) { Wait-RpaTerminal $start.body.data.runId } else { $null }
        $started.Stop()
        $requiredMetricNames = @('totalMs', 'screenTreeMs', 'llmRoundMs', 'toolCallMs', 'rounds', 'mode')
        $metricsComplete = $null -ne $terminal -and (Test-JsonProperty $terminal 'metrics')
        foreach ($metricName in $requiredMetricNames) {
            $metricsComplete = $metricsComplete -and (Test-JsonProperty $terminal.metrics $metricName)
        }
        $dispatchCountPresent = $null -ne $terminal -and (Test-JsonProperty $terminal 'dispatchCount')
        $record = [pscustomobject]@{
            run = $index
            accepted = [bool]($start.body.success -eq $true -and $start.body.data.accepted -eq $true)
            status = if ($terminal) { $terminal.status } else { 'not_started' }
            outcomeState = if ($terminal) { $terminal.outcomeState } else { $start.body.data.outcomeState }
            errorCode = if ($terminal) { $terminal.errorCode } else { $start.body.data.errorCode }
            wallMs = $started.ElapsedMilliseconds
            metricsComplete = [bool]$metricsComplete
            rounds = if ($metricsComplete) { [int]$terminal.metrics.rounds } else { -1 }
            resolverRounds = if ($terminal) { [int]$terminal.rounds } else { 0 }
            fullTreeReads = if ($terminal -and (Test-JsonProperty $terminal 'fullTreeReads')) { [int]$terminal.fullTreeReads } else { -1 }
            dispatchCount = if ($dispatchCountPresent) { [int]$terminal.dispatchCount } else { -1 }
            metricsMode = if ($metricsComplete) { [string]$terminal.metrics.mode } else { '' }
            metricTotalMs = if ($metricsComplete) { [long]$terminal.metrics.totalMs } else { -1 }
            metricScreenTreeMs = if ($metricsComplete) { [long]$terminal.metrics.screenTreeMs } else { -1 }
            metricLlmRoundMs = if ($metricsComplete) { [long]$terminal.metrics.llmRoundMs } else { -1 }
            metricToolCallMs = if ($metricsComplete) { [long]$terminal.metrics.toolCallMs } else { -1 }
            toolCallMeasured = if ($metricsComplete -and (Test-JsonProperty $terminal.metrics 'toolCallMeasured')) { [bool]$terminal.metrics.toolCallMeasured } else { $false }
            resolverUsed = if ($terminal -and $terminal.steps.Count -gt 0) { $terminal.steps[0].resolverUsed } else { '' }
            actionMs = if ($terminal -and $terminal.steps.Count -gt 0) { [long]$terminal.steps[0].actionMs } else { 0 }
            treeMs = if ($terminal -and $terminal.steps.Count -gt 0) { [long]$terminal.steps[0].treeSnapshotMs + [long]$terminal.steps[0].treeLookupMs } else { 0 }
        }
        $RunRecords.Add($record)
    }
    $successful = @($RunRecords | Where-Object { $_.status -eq 'succeeded' -and $_.outcomeState -eq 'verified' })
    $badReads = @($RunRecords | Where-Object { $_.rounds -ne 0 -or $_.fullTreeReads -ne 0 })
    $badMetrics = @($RunRecords | Where-Object {
        -not $_.metricsComplete -or $_.metricsMode -ne 'hybrid_rpa' -or
        $_.metricTotalMs -lt 0 -or $_.metricScreenTreeMs -lt 0 -or $_.metricLlmRoundMs -ne 0 -or
        $_.metricToolCallMs -le 0 -or -not $_.toolCallMeasured -or $_.dispatchCount -le 0
    })
    $resolverDistribution = @($successful | Group-Object resolverUsed | ForEach-Object { [pscustomobject]@{ resolver = $_.Name; count = $_.Count } })
    $timings = @($successful | ForEach-Object { $_.actionMs })
    $wallTimings = @($successful | ForEach-Object { $_.wallMs })
    $treeTimings = @($successful | ForEach-Object { $_.treeMs })
    $resolverTimings = @($successful | ForEach-Object { $_.resolverRounds })
    $unexpectedResolvers = @($successful | Where-Object { $_.resolverUsed -ne 'RESOURCE_ID' })
    $toolTimings = @($successful | ForEach-Object { $_.metricToolCallMs })
    $pressureData = @{ successes = $successful.Count; requiredSuccesses = 29; nonZeroLlmRoundsOrFullTrees = $badReads.Count; invalidMetricContracts = $badMetrics.Count; unexpectedResolvers = $unexpectedResolvers.Count; resolverDistribution = $resolverDistribution; resolverRoundsP50 = Percentile $resolverTimings 0.50; resolverRoundsP95 = Percentile $resolverTimings 0.95; treeMsP50 = Percentile $treeTimings 0.50; treeMsP95 = Percentile $treeTimings 0.95; toolCallMsP50 = Percentile $toolTimings 0.50; toolCallMsP95 = Percentile $toolTimings 0.95; actionMsP50 = Percentile $timings 0.50; actionMsP95 = Percentile $timings 0.95; wallMsP50 = Percentile $wallTimings 0.50; wallMsP95 = Percentile $wallTimings 0.95 }
    if ($RunRecords.Count -eq 30 -and $successful.Count -ge 29 -and $badReads.Count -eq 0 -and $badMetrics.Count -eq 0 -and $unexpectedResolvers.Count -eq 0) {
        Add-Case 'active_tree_preferred_pressure' 'passed' '' $pressureData
    } else { Add-Case 'active_tree_preferred_pressure' 'failed' 'success_rate_below_29_of_30_or_invalid_metrics_or_nonzero_rounds_or_full_tree_reads' $pressureData }

    Add-Case 'duplicate_selector_zero_dispatch' 'source_verified' 'semantic ambiguity is source-covered; exact stored-template authorization prevents injecting a different selector without a separately validated revision' @{ expectedDispatchCount = 0 }
    Add-Case 'api36_visual_missing_stale_zero_dispatch' 'source_verified' 'runtime visual asset and stale-frame injection are not deterministic in this fixture; production visual tests cover zero-dispatch behavior' @{ expectedDispatchCount = 0 }
    Add-Case 'timeout_structured' 'source_verified' 'timeout outcome has unit coverage; this fixture contains no separately authorized bounded wait revision' $null
    Start-Fixture
    $busyOwner = Invoke-Api 'POST' '/api/rpa/run' $runBody
    $busyContender = Invoke-Api 'POST' '/api/rpa/run' $runBody
    if ($busyOwner.body.success -eq $true -and $busyOwner.body.data.accepted -eq $true -and
        $busyContender.body.success -eq $false -and $busyContender.body.data.errorCode -eq 'rpa_busy' -and
        $busyContender.body.data.currentStep -eq 'precheck' -and $busyContender.body.data.retryable -eq $true
    ) {
        Add-Case 'busy_structured' 'passed' '' @{ errorCode = $busyContender.body.data.errorCode; retryable = $busyContender.body.data.retryable }
    } else {
        Add-Case 'busy_structured' 'failed' 'busy_response_not_structured' @{ ownerAccepted = $busyOwner.body.data.accepted; contenderSuccess = $busyContender.body.success; errorCode = $busyContender.body.data.errorCode; retryable = $busyContender.body.data.retryable }
    }
    if ($busyOwner.body.data.runId) { Wait-RpaTerminal $busyOwner.body.data.runId | Out-Null }

    Invoke-Adb @('shell', 'settings', 'delete', 'secure', 'enabled_accessibility_services') | Out-Null
    Invoke-Adb @('shell', 'settings', 'put', 'secure', 'accessibility_enabled', '0') | Out-Null
    Start-Sleep -Milliseconds 300
    $disabled = Invoke-Api 'GET' '/api/tool/observe_fast'
    if ($disabled.body.success -eq $false -and $disabled.body.data.errorCode -in @('accessibility_disabled', 'accessibility_reenable_required')) {
        Add-Case 'accessibility_disabled_structured' 'passed' '' @{ errorCode = $disabled.body.data.errorCode }
    } else { Add-Case 'accessibility_disabled_structured' 'failed' 'accessibility_failure_not_structured' }
    Invoke-Adb @('shell', 'settings', 'put', 'secure', 'enabled_accessibility_services', $enabled) | Out-Null
    Invoke-Adb @('shell', 'settings', 'put', 'secure', 'accessibility_enabled', '1') | Out-Null
    Wait-HybridRuntimeReady | Out-Null

    if ($status.body.data.llmConfigured -eq $false -and $capabilities.body.data.llmRequired -eq $false) {
        Add-Case 'model_missing_fast_path' 'passed' '' @{ llmConfigured = $false; llmRequired = $false }
    } else { Add-Case 'model_missing_fast_path' 'failed' 'model_presence_prevents_missing_model_fast_path' }

    try {
        Invoke-Adb @('shell', 'wm', 'user-rotation', 'lock', '1') | Out-Null
        Start-Fixture
        Wait-HybridRuntimeReady | Out-Null
        $rotationDeadline = [DateTime]::UtcNow.AddSeconds(10)
        do {
            $rotated = Invoke-Api 'GET' '/api/tool/observe_fast?debug=true'
            if ($rotated.body.success -eq $true) { break }
            Start-Sleep -Milliseconds 250
        } while ([DateTime]::UtcNow -lt $rotationDeadline)
        if ($rotated.body.success -eq $true) { Add-Case 'orientation_change_reobserve' 'passed' '' @{ durationMs = $rotated.body.data.durationMs } }
        else { Add-Case 'orientation_change_reobserve' 'failed' 'reobserve_not_structured_after_rotation' @{ httpStatus = $rotated.httpStatus; transportError = $rotated.error; errorCode = $rotated.body.data.errorCode; accessibilityState = $rotated.body.data.accessibilityState } }
    } catch { Add-Case 'orientation_change_reobserve' 'skipped' 'emulator_rotation_control_unavailable' }
    finally { & $Adb -s $Serial shell wm user-rotation free 2>$null | Out-Null }

    Add-Case 'process_death_uncertain' 'source_verified' 'deterministic dispatch interruption requires an injected production dispatcher; UNCERTAIN persistence is unit-covered' $null
    Add-Case 'agent_fallback_handoff' 'source_verified' 'handoff is source/unit-covered; no model is configured for this deterministic fixture' $null
}
catch {
    $HarnessFailure = Redact-Text $_.Exception.Message
    Add-Case 'harness_execution' 'failed' $HarnessFailure
}
finally {
    try { Restore-TemplateIndex } catch {
        if (-not $HarnessFailure) { $HarnessFailure = Redact-Text $_.Exception.Message }
    }
    try { Restore-FixtureConfiguration } catch {
        if (-not $HarnessFailure) { $HarnessFailure = Redact-Text $_.Exception.Message }
    }
    if ($null -ne $OriginalAccessibility) {
        if ($OriginalAccessibility -eq 'null' -or [string]::IsNullOrWhiteSpace($OriginalAccessibility)) {
            & $Adb -s $Serial shell settings delete secure enabled_accessibility_services 2>$null | Out-Null
        } else {
            & $Adb -s $Serial shell settings put secure enabled_accessibility_services $OriginalAccessibility 2>$null | Out-Null
        }
        if ($null -ne $OriginalAccessibilityEnabled -and $OriginalAccessibilityEnabled -ne 'null') {
            & $Adb -s $Serial shell settings put secure accessibility_enabled $OriginalAccessibilityEnabled 2>$null | Out-Null
        }
    }
    if ($OriginalRotation -match '^lock\s+([0-3])$') {
        & $Adb -s $Serial shell wm user-rotation lock $Matches[1] 2>$null | Out-Null
    } elseif ($null -ne $OriginalRotation) {
        & $Adb -s $Serial shell wm user-rotation free 2>$null | Out-Null
    }
    if ($CreatedForward) { & $Adb -s $Serial forward --remove tcp:9527 2>$null | Out-Null }
    $aggregate = [ordered]@{
        generatedAtUtc = [DateTime]::UtcNow.ToString('o')
        fixturePath = $FixturePath
        runsRequested = $Runs
        cases = @($Cases | ForEach-Object { Sanitize-Record $_ })
        runs = @($RunRecords | ForEach-Object { Sanitize-Record $_ })
        summary = [ordered]@{
            passed = @($Cases | Where-Object status -eq 'passed').Count
            skipped = @($Cases | Where-Object status -eq 'skipped').Count
            sourceVerified = @($Cases | Where-Object status -eq 'source_verified').Count
            failed = @($Cases | Where-Object status -eq 'failed').Count
            gatePassed = @(Get-MandatoryLiveFailures).Count -eq 0
        }
    }
    if ($OutputPath) { $aggregate | ConvertTo-Json -Depth 100 | Set-Content -LiteralPath $OutputPath -Encoding utf8 }
}

$failedHarness = $HarnessFailure
if ($failedHarness) { throw ('pressure_harness_failed: ' + $failedHarness) }
$serializedReport = Get-Content -Raw -LiteralPath $OutputPath
if (-not [string]::IsNullOrEmpty($Token) -and $serializedReport.Contains($Token)) { throw 'pressure_report_contains_token' }
$mandatoryFailures = @(Get-MandatoryLiveFailures)
if ($mandatoryFailures.Count -gt 0) { throw ('mandatory_live_cases_failed: ' + ($mandatoryFailures -join ',')) }
