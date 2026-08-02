param(
    [Parameter(Mandatory = $true)]
    [string]$CandidateDirectory,
    [Parameter(Mandatory = $true)]
    [string]$Installer,
    [Parameter(Mandatory = $true)]
    [string]$OutputDirectory,
    [ValidateRange(4096, 32768)]
    [int]$MemoryMB = 8192,
    [switch]$Launch,
    [switch]$Force
)

$ErrorActionPreference = "Stop"

function Resolve-ExistingDirectory {
    param([string]$Path, [string]$Label)
    if (-not (Test-Path -LiteralPath $Path -PathType Container)) {
        throw "$Label directory does not exist: $Path"
    }
    return (Resolve-Path -LiteralPath $Path).Path.TrimEnd(
        [System.IO.Path]::DirectorySeparatorChar,
        [System.IO.Path]::AltDirectorySeparatorChar
    )
}

function Resolve-ExistingFile {
    param([string]$Path, [string]$Label)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "$Label file does not exist: $Path"
    }
    return (Resolve-Path -LiteralPath $Path).Path
}

function Test-ChildPath {
    param([string]$Parent, [string]$Child)
    $prefix = $Parent + [System.IO.Path]::DirectorySeparatorChar
    return $Child.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)
}

function Get-Sha256Hash {
    param([string]$Path)
    $stream = [System.IO.File]::OpenRead($Path)
    $sha256 = [System.Security.Cryptography.SHA256]::Create()
    try {
        return ([System.BitConverter]::ToString(
            $sha256.ComputeHash($stream)
        )).Replace("-", "")
    }
    finally {
        $sha256.Dispose()
        $stream.Dispose()
    }
}

function Write-XmlTextElement {
    param(
        [System.Xml.XmlWriter]$Writer,
        [string]$Name,
        [string]$Value
    )
    $Writer.WriteStartElement($Name)
    $Writer.WriteString($Value)
    $Writer.WriteEndElement()
}

function Write-MappedFolder {
    param(
        [System.Xml.XmlWriter]$Writer,
        [string]$HostFolder,
        [string]$SandboxFolder,
        [bool]$ReadOnly
    )
    $Writer.WriteStartElement("MappedFolder")
    Write-XmlTextElement -Writer $Writer -Name "HostFolder" -Value $HostFolder
    Write-XmlTextElement -Writer $Writer -Name "SandboxFolder" -Value $SandboxFolder
    Write-XmlTextElement -Writer $Writer -Name "ReadOnly" -Value $(
        if ($ReadOnly) { "true" } else { "false" }
    )
    $Writer.WriteEndElement()
}

$candidatePath = Resolve-ExistingDirectory -Path $CandidateDirectory -Label "Candidate"
$installerPath = Resolve-ExistingFile -Path $Installer -Label "Installer"
if (-not (Test-ChildPath -Parent $candidatePath -Child $installerPath)) {
    throw "Installer must stay inside CandidateDirectory"
}

$harnessPath = Resolve-ExistingDirectory -Path $PSScriptRoot -Label "Harness"
$bootstrapPath = Resolve-ExistingFile -Path (
    Join-Path $harnessPath "windows-sandbox-bootstrap.ps1"
) -Label "Bootstrap"
$checklistPath = Resolve-ExistingFile -Path (
    Join-Path $harnessPath "windows-sandbox-acceptance-checklist.md"
) -Label "Checklist"

$outputPath = [System.IO.Path]::GetFullPath($OutputDirectory).TrimEnd(
    [System.IO.Path]::DirectorySeparatorChar,
    [System.IO.Path]::AltDirectorySeparatorChar
)
if ($outputPath -eq $candidatePath -or (Test-ChildPath -Parent $candidatePath -Child $outputPath)) {
    throw "OutputDirectory must stay outside CandidateDirectory"
}
if (-not (Test-Path -LiteralPath $outputPath)) {
    New-Item -ItemType Directory -Path $outputPath | Out-Null
}
$outputPath = Resolve-ExistingDirectory -Path $outputPath -Label "Output"

$wsbPath = Join-Path $outputPath "Luming-2.4.5-Acceptance.wsb"
$sessionPath = Join-Path $outputPath "sandbox-preparation.json"
foreach ($target in @($wsbPath, $sessionPath)) {
    if ((Test-Path -LiteralPath $target) -and -not $Force.IsPresent) {
        throw "Refusing to overwrite existing acceptance asset without -Force: $target"
    }
}

$installerItem = Get-Item -LiteralPath $installerPath
$installerHash = Get-Sha256Hash -Path $installerPath
$command = 'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "C:\LumingHarness\windows-sandbox-bootstrap.ps1"' +
    ' -CandidateRoot "C:\LumingCandidate"' +
    ' -EvidenceRoot "C:\LumingEvidence"' +
    ' -InstallerName "' + $installerItem.Name + '"' +
    ' -ExpectedSha256 "' + $installerHash + '"'

$settings = [System.Xml.XmlWriterSettings]::new()
$settings.Indent = $true
$settings.OmitXmlDeclaration = $true
$settings.Encoding = [System.Text.UTF8Encoding]::new($false)
$builder = [System.Text.StringBuilder]::new()
$writer = [System.Xml.XmlWriter]::Create($builder, $settings)
try {
    $writer.WriteStartDocument()
    $writer.WriteStartElement("Configuration")
    Write-XmlTextElement -Writer $writer -Name "MemoryInMB" -Value ([string]$MemoryMB)
    Write-XmlTextElement -Writer $writer -Name "VGpu" -Value "Disable"
    Write-XmlTextElement -Writer $writer -Name "Networking" -Value "Enable"
    Write-XmlTextElement -Writer $writer -Name "ClipboardRedirection" -Value "Enable"
    Write-XmlTextElement -Writer $writer -Name "PrinterRedirection" -Value "Disable"
    Write-XmlTextElement -Writer $writer -Name "AudioInput" -Value "Disable"
    Write-XmlTextElement -Writer $writer -Name "VideoInput" -Value "Disable"
    $writer.WriteStartElement("MappedFolders")
    Write-MappedFolder -Writer $writer -HostFolder $candidatePath -SandboxFolder "C:\LumingCandidate" -ReadOnly $true
    Write-MappedFolder -Writer $writer -HostFolder $harnessPath -SandboxFolder "C:\LumingHarness" -ReadOnly $true
    Write-MappedFolder -Writer $writer -HostFolder $outputPath -SandboxFolder "C:\LumingEvidence" -ReadOnly $false
    $writer.WriteEndElement()
    $writer.WriteStartElement("LogonCommand")
    Write-XmlTextElement -Writer $writer -Name "Command" -Value $command
    $writer.WriteEndElement()
    $writer.WriteEndElement()
    $writer.WriteEndDocument()
}
finally {
    $writer.Dispose()
}

[System.IO.File]::WriteAllText(
    $wsbPath,
    $builder.ToString(),
    [System.Text.UTF8Encoding]::new($false)
)
[pscustomobject]@{
    schemaVersion = 1
    preparedAt = [DateTimeOffset]::UtcNow.ToString("o")
    candidateDirectory = $candidatePath
    installer = $installerItem.Name
    installerBytes = $installerItem.Length
    installerSha256 = $installerHash
    harness = $bootstrapPath
    checklist = $checklistPath
    evidenceDirectory = $outputPath
    network = "enabled"
    usbPassthrough = $false
} | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $sessionPath -Encoding UTF8

$sandboxExecutable = Join-Path $env:WINDIR "System32\WindowsSandbox.exe"
if ($Launch.IsPresent) {
    if (-not (Test-Path -LiteralPath $sandboxExecutable -PathType Leaf)) {
        throw "WindowsSandbox.exe is unavailable. Enable Windows Sandbox and reboot before using -Launch."
    }
    Start-Process -FilePath $sandboxExecutable -ArgumentList ('"' + $wsbPath + '"')
}

[pscustomobject]@{
    wsb = $wsbPath
    metadata = $sessionPath
    installerSha256 = $installerHash
    launched = $Launch.IsPresent
}
