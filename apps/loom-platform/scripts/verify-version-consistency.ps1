[CmdletBinding()]
param(
    [string]$TagName = "",
    [string]$ExpectedVersion = ""
)

$ErrorActionPreference = "Stop"
$hasTagName = $PSBoundParameters.ContainsKey("TagName")
$hasExpectedVersion = $PSBoundParameters.ContainsKey("ExpectedVersion")

$Root = Split-Path -Parent $PSScriptRoot

function Resolve-LauncherDir {
    $candidates = @("openclaw_new_launcher")
    foreach ($candidate in $candidates) {
        $path = Join-Path $Root $candidate
        if (
            (Test-Path -LiteralPath (Join-Path $path "package.json")) -and
            (Test-Path -LiteralPath (Join-Path $path "src-tauri"))
        ) {
            return $path
        }
    }
    throw "No launcher project found. Expected openclaw_new_launcher."
}

$LauncherDir = Resolve-LauncherDir
$TauriDir = Join-Path $LauncherDir "src-tauri"
$JsonEmptyPropertyName = "__LOOM_JSON_EMPTY_PROPERTY__"

function Read-JsonDocument {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        throw "Missing file: $Path"
    }

    $text = Get-Content -LiteralPath $Path -Raw
    $reservedToken = '"' + $JsonEmptyPropertyName + '"'
    if ($text.Contains($reservedToken)) {
        throw "Reserved JSON property name '$JsonEmptyPropertyName' appears in $Path"
    }

    $normalizedText = [regex]::Replace(
        $text,
        '""(?=\s*:)',
        $reservedToken
    )
    try {
        return ConvertFrom-Json -InputObject $normalizedText -ErrorAction Stop
    } catch {
        throw "Unable to parse JSON from ${Path}: $($_.Exception.Message)"
    }
}

function Get-RequiredJsonPropertyValue {
    param(
        [object]$Document,
        [string]$Name,
        [string]$Context
    )

    if ($null -eq $Document) {
        throw "Missing JSON property '$Name' in $Context"
    }
    $lookupName = if ($Name -ceq "") { $JsonEmptyPropertyName } else { $Name }
    $properties = @(
        $Document.PSObject.Properties |
            Where-Object { $_.Name -ceq $lookupName }
    )
    if ($properties.Count -ne 1) {
        throw "Missing JSON property '$Name' in $Context"
    }
    return $properties[0].Value
}

function Get-RequiredJsonStringProperty {
    param(
        [object]$Document,
        [string]$Name,
        [string]$Context
    )

    $value = Get-RequiredJsonPropertyValue -Document $Document -Name $Name -Context $Context
    if ($value -isnot [string] -or [string]::IsNullOrWhiteSpace($value)) {
        throw "JSON property '$Name' in $Context must be a non-empty string"
    }
    return $value
}

function Read-JsonVersion {
    param([string]$Path)
    $document = Read-JsonDocument -Path $Path
    return Get-RequiredJsonStringProperty -Document $document -Name "version" -Context $Path
}

function Read-PackageLockRootPackageVersion {
    param([string]$Path)
    $document = Read-JsonDocument -Path $Path
    $packages = Get-RequiredJsonPropertyValue -Document $document -Name "packages" -Context $Path
    $rootPackage = Get-RequiredJsonPropertyValue -Document $packages -Name "" -Context "$Path packages"
    return Get-RequiredJsonStringProperty -Document $rootPackage -Name "version" -Context "$Path packages['']"
}

function Read-CargoPackageVersion {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        throw "Missing file: $Path"
    }

    $inPackage = $false
    foreach ($line in Get-Content -LiteralPath $Path) {
        if ($line -match '^\[package\]\s*$') {
            $inPackage = $true
            continue
        }
        if ($inPackage -and $line -match '^\[') {
            break
        }
        if ($inPackage -and $line -match '^version\s*=\s*"(?<version>[^"]+)"') {
            return $Matches["version"]
        }
    }

    throw "Unable to read [package] version from $Path"
}

function Read-CargoLockPackageVersion {
    param(
        [string]$Path,
        [string]$PackageName
    )
    if (-not (Test-Path -LiteralPath $Path)) {
        throw "Missing file: $Path"
    }

    $inPackage = $false
    $currentName = ""
    $currentVersion = ""
    $matchedVersions = @()
    $lines = @(Get-Content -LiteralPath $Path) + "[[package]]"
    foreach ($line in $lines) {
        if ($line -match '^\[\[package\]\]\s*$') {
            if ($inPackage -and $currentName -ceq $PackageName) {
                $matchedVersions += [string]$currentVersion
            }
            $inPackage = $true
            $currentName = ""
            $currentVersion = ""
            continue
        }
        if (-not $inPackage) {
            continue
        }
        if ($line -match '^name\s*=\s*"(?<name>[^"]+)"') {
            $currentName = $Matches["name"]
            continue
        }
        if ($line -match '^version\s*=\s*"(?<version>[^"]+)"') {
            $currentVersion = $Matches["version"]
        }
    }

    if ($matchedVersions.Count -ne 1) {
        throw "Expected exactly one Cargo.lock package named '$PackageName' in $Path; found $($matchedVersions.Count)"
    }
    if ([string]::IsNullOrWhiteSpace($matchedVersions[0])) {
        throw "Cargo.lock package '$PackageName' in $Path has an empty version"
    }
    return $matchedVersions[0]
}

$packageJsonVersion = Read-JsonVersion (Join-Path $LauncherDir "package.json")
$packageLockVersion = Read-JsonVersion (Join-Path $LauncherDir "package-lock.json")
$packageLockRootPackageVersion = Read-PackageLockRootPackageVersion (Join-Path $LauncherDir "package-lock.json")
$tauriConfigVersion = Read-JsonVersion (Join-Path $TauriDir "tauri.conf.json")
$cargoVersion = Read-CargoPackageVersion (Join-Path $TauriDir "Cargo.toml")
$cargoLockVersion = Read-CargoLockPackageVersion (Join-Path $TauriDir "Cargo.lock") "app"

$versions = [ordered]@{
    "package.json" = [string]$packageJsonVersion
    "package-lock.json" = [string]$packageLockVersion
    "package-lock.json packages root" = [string]$packageLockRootPackageVersion
    "tauri.conf.json" = [string]$tauriConfigVersion
    "Cargo.toml" = [string]$cargoVersion
    "Cargo.lock" = [string]$cargoLockVersion
}

$expected = $versions["package.json"]
$mismatches = @()
foreach ($entry in $versions.GetEnumerator()) {
    if ([string]::IsNullOrWhiteSpace($entry.Value)) {
        $mismatches += "$($entry.Key) is empty"
    } elseif ($entry.Value -ne $expected) {
        $mismatches += "$($entry.Key)=$($entry.Value), expected $expected"
    }
}

if ($hasExpectedVersion -and $ExpectedVersion -cne $expected) {
    $mismatches += "expected-version=$ExpectedVersion, package.json=$expected"
}

if ($hasTagName -and $TagName -cne "v$expected") {
    $mismatches += "tag=$TagName, expected v$expected"
}

if ($mismatches.Count -gt 0) {
    throw "Launcher version mismatch:`n$($mismatches -join "`n")"
}

Write-Host "Version consistency check passed: $expected" -ForegroundColor Green
