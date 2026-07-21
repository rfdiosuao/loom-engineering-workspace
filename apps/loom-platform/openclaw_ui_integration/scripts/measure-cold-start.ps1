param(
    [string]$Root = (Get-Location).Path,
    [string]$LauncherExe = "OpenClaw.exe",
    [Alias("timeout-sec")]
    [int]$TimeoutSec = 600,
    [Alias("poll-ms")]
    [int]$PollMs = 500,
    [Alias("stop-after-measure")]
    [switch]$StopAfterMeasure,
    [Alias("output-path")]
    [string]$OutputPath = "",
    [Alias("budget-ms")]
    [int]$BudgetMs = 30000
)

$ErrorActionPreference = "Stop"

function Resolve-PythonExe {
    param([string]$BaseRoot)

    $candidates = @(
        (Join-Path $BaseRoot "python-runtime\python.exe"),
        (Join-Path $BaseRoot "OpenClawFiles\python-runtime\python.exe"),
        (Join-Path $BaseRoot "OpenClawFiles\_up_\python-runtime\python.exe")
    )

    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate) {
            return $candidate
        }
    }

    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd) {
        return $cmd.Source
    }

    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) {
        return $py.Source
    }

    throw "Python interpreter not found. Looked for bundled runtime and PATH python."
}

$Root = (Resolve-Path -LiteralPath $Root).Path
$pythonExe = Resolve-PythonExe -BaseRoot $Root
$helperScript = Join-Path $PSScriptRoot "measure-cold-start.py"

if (-not (Test-Path -LiteralPath $helperScript)) {
    throw "Helper script not found: $helperScript"
}

$argsList = @(
    $helperScript,
    "--root", $Root,
    "--timeout-sec", $TimeoutSec,
    "--poll-ms", $PollMs
)
if ($StopAfterMeasure) {
    $argsList += "--stop-after-measure"
}
if (-not [string]::IsNullOrWhiteSpace($OutputPath)) {
    $argsList += "--output-path"
    $argsList += $OutputPath
}
$argsList += "--budget-ms"
$argsList += $BudgetMs

$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = $pythonExe
$psi.Arguments = ($argsList | ForEach-Object {
    if ($_ -match '\s') { '"' + ($_ -replace '"', '\"') + '"' } else { $_ }
}) -join ' '
$psi.WorkingDirectory = $Root
$psi.UseShellExecute = $false
$psi.RedirectStandardOutput = $true
$psi.RedirectStandardError = $true
$psi.StandardOutputEncoding = [System.Text.Encoding]::UTF8
$psi.StandardErrorEncoding = [System.Text.Encoding]::UTF8

$process = New-Object System.Diagnostics.Process
$process.StartInfo = $psi
[void]$process.Start()

$stdoutTask = $process.StandardOutput.ReadToEndAsync()
$stderrTask = $process.StandardError.ReadToEndAsync()
$process.WaitForExit()
$stdout = $stdoutTask.GetAwaiter().GetResult()
$stderr = $stderrTask.GetAwaiter().GetResult()

if ($process.ExitCode -ne 0) {
    if ($stdout) { Write-Host $stdout }
    $message = $stderr.Trim()
    if ([string]::IsNullOrWhiteSpace($message)) {
        $message = "Cold start measurement failed with exit code $($process.ExitCode)"
    }
    throw $message
}

if ($stdout) { Write-Host $stdout }
