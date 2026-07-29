param(
    [switch]$VerifyOnly,
    [switch]$SkipValidation,
    [string]$OutputDir
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$SourceDir = Join-Path $Root "packages\luming-skills-library"
$LauncherSkillDir = Join-Path $Root "openclaw_new_launcher\public\skills"
$ManifestPath = Join-Path $SourceDir "manifest.json"
$BundleProvenancePath = Join-Path $SourceDir "BUNDLE_PROVENANCE.json"
$ValidateScript = Join-Path $SourceDir "scripts\validate.ps1"
$PackageScript = Join-Path $SourceDir "scripts\package.ps1"
$RepositoryValidator = Join-Path $PSScriptRoot "validate-skill.py"

if (-not (Test-Path -LiteralPath $ManifestPath -PathType Leaf)) {
    throw "Skill Library manifest is missing: $ManifestPath"
}
if (-not (Test-Path -LiteralPath $BundleProvenancePath -PathType Leaf)) {
    throw "Skill Library bundle provenance is missing: $BundleProvenancePath"
}

$Manifest = Get-Content -Raw -Encoding UTF8 -LiteralPath $ManifestPath | ConvertFrom-Json
$BundleProvenance = Get-Content -Raw -Encoding UTF8 -LiteralPath $BundleProvenancePath | ConvertFrom-Json
$Stamp = ([string]$Manifest.version) -replace '[^0-9]', ''
if ($Stamp.Length -ne 8) {
    throw "Skill Library version must resolve to an eight-digit package stamp: $($Manifest.version)"
}
$ArchiveName = "luming-skills-library-$Stamp.zip"
$BundledArchive = Join-Path $LauncherSkillDir $ArchiveName
$ExpectedHash = ([string]$BundleProvenance.sha256).ToUpperInvariant()

if ([string]$BundleProvenance.version -cne [string]$Manifest.version) {
    throw "Bundle provenance version does not match manifest: $($BundleProvenance.version) != $($Manifest.version)"
}
if ([string]$BundleProvenance.archive -cne $ArchiveName) {
    throw "Bundle provenance archive does not match manifest: $($BundleProvenance.archive) != $ArchiveName"
}
if ($ExpectedHash -notmatch '^[0-9A-F]{64}$') {
    throw "Bundle provenance SHA256 is invalid: $($BundleProvenance.sha256)"
}

if (-not $SkipValidation) {
    $validationResult = @(& $ValidateScript -Validator $RepositoryValidator)
    if (-not $?) {
        throw "Skill Library validation failed: $($validationResult -join "`n")"
    }
}

if (-not $OutputDir) {
    $OutputDir = if ($VerifyOnly) {
        Join-Path $Root "artifacts\repository-governance\skill-library"
    } else {
        $LauncherSkillDir
    }
}
New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null

$StagingDir = Join-Path ([IO.Path]::GetTempPath()) ("loom-skill-library-" + [Guid]::NewGuid().ToString("N"))
$TextExtensions = @(".json", ".md", ".ps1", ".py", ".toml", ".txt", ".yaml", ".yml")
$Utf8NoBom = [Text.UTF8Encoding]::new($false)
try {
    New-Item -ItemType Directory -Force -Path $StagingDir | Out-Null

    $expectedEntries = @(
        "README.md"
        "manifest.json"
        Get-ChildItem -LiteralPath (Join-Path $SourceDir "scripts") -Recurse -File |
            ForEach-Object {
                $_.FullName.Substring($SourceDir.Length).TrimStart([char[]]@('\', '/')).Replace('\', '/')
            }
        foreach ($manifestSkill in @($Manifest.skills)) {
            $skillRoot = Join-Path $SourceDir ([string]$manifestSkill.path)
            Get-ChildItem -LiteralPath $skillRoot -Recurse -File |
                ForEach-Object {
                    $_.FullName.Substring($SourceDir.Length).TrimStart([char[]]@('\', '/')).Replace('\', '/')
                }
        }
    ) | Sort-Object -Unique
    $provenanceEntries = @($BundleProvenance.entryTimestamps.PSObject.Properties.Name | Sort-Object -Unique)
    $missingFromProvenance = @($expectedEntries | Where-Object { $provenanceEntries -cnotcontains $_ })
    $staleProvenanceEntries = @($provenanceEntries | Where-Object { $expectedEntries -cnotcontains $_ })
    if ($missingFromProvenance.Count -ne 0 -or $staleProvenanceEntries.Count -ne 0) {
        throw (
            "Bundle provenance entry set differs from package sources. Missing: " +
            ($missingFromProvenance -join ", ") +
            "; stale: " +
            ($staleProvenanceEntries -join ", ")
        )
    }

    foreach ($property in $BundleProvenance.entryTimestamps.PSObject.Properties) {
        $entryName = [string]$property.Name
        $sourcePath = Join-Path $SourceDir ($entryName.Replace('/', [IO.Path]::DirectorySeparatorChar))
        if (-not (Test-Path -LiteralPath $sourcePath -PathType Leaf)) {
            throw "Bundle provenance references a missing source file: $entryName"
        }

        $stagedPath = Join-Path $StagingDir ($entryName.Replace('/', [IO.Path]::DirectorySeparatorChar))
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $stagedPath) | Out-Null

        if ([IO.Path]::GetExtension($sourcePath).ToLowerInvariant() -in $TextExtensions) {
            $content = [IO.File]::ReadAllText($sourcePath, [Text.Encoding]::UTF8)
            $content = $content.Replace("`r`n", "`n").Replace("`r", "`n")
            [IO.File]::WriteAllText($stagedPath, $content, $Utf8NoBom)
        } else {
            Copy-Item -LiteralPath $sourcePath -Destination $stagedPath
        }

        $entryTimestamp = if ($property.Value -is [DateTime]) {
            [DateTime]$property.Value
        } else {
            [DateTime]::ParseExact(
                [string]$property.Value,
                "yyyy-MM-ddTHH:mm:ss",
                [Globalization.CultureInfo]::InvariantCulture,
                [Globalization.DateTimeStyles]::None
            )
        }
        (Get-Item -LiteralPath $stagedPath).LastWriteTime = $entryTimestamp
    }

    # package.ps1 validates provenance but deliberately excludes it from the ZIP
    # to avoid a self-referential archive hash.
    Copy-Item `
        -LiteralPath $BundleProvenancePath `
        -Destination (Join-Path $StagingDir "BUNDLE_PROVENANCE.json")

    $StagedPackageScript = Join-Path $StagingDir "scripts\package.ps1"
    & $StagedPackageScript -OutputDir $OutputDir | Out-Null
    if (-not $?) {
        throw "Skill Library packaging failed"
    }
} finally {
    if (Test-Path -LiteralPath $StagingDir -PathType Container) {
        Remove-Item -LiteralPath $StagingDir -Recurse -Force
    }
}

$GeneratedArchive = Join-Path $OutputDir $ArchiveName
if (-not (Test-Path -LiteralPath $GeneratedArchive -PathType Leaf)) {
    throw "Expected Skill Library archive was not generated: $GeneratedArchive"
}

$GeneratedHash = (Get-FileHash -LiteralPath $GeneratedArchive -Algorithm SHA256).Hash
if ($GeneratedHash -cne $ExpectedHash) {
    throw "Skill Library build is not reproducible. Generated $GeneratedHash but provenance requires $ExpectedHash"
}
if ($VerifyOnly) {
    if (-not (Test-Path -LiteralPath $BundledArchive -PathType Leaf)) {
        throw "Bundled Skill Library archive is missing: $BundledArchive"
    }
    $BundledHash = (Get-FileHash -LiteralPath $BundledArchive -Algorithm SHA256).Hash
    if ($BundledHash -cne $ExpectedHash) {
        throw "Bundled Skill Library is stale. Generated $GeneratedHash but bundled $BundledHash"
    }
}

[pscustomobject]@{
    schema = "loom.skill_library_build.v1"
    version = [string]$Manifest.version
    archive = $ArchiveName
    sha256 = $GeneratedHash
    verified = $true
} | ConvertTo-Json -Compress
