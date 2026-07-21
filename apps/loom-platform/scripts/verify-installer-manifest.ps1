param(
    [string]$ManifestPath = "",
    [string]$PublicKey = "",
    [string]$PublicKeyPath = "",
    [string[]]$RequiredComponents = @("codex-desktop", "claude-code", "opencode", "openclaw-companion", "hermes")
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($ManifestPath)) {
    $ManifestPath = Join-Path $Root "release-manifest.json"
}

if (-not (Test-Path -LiteralPath $ManifestPath)) {
    throw "Missing installer manifest: $ManifestPath"
}

$resolvedManifest = (Resolve-Path -LiteralPath $ManifestPath).Path
if ($resolvedManifest -match "[\\/]examples[\\/]" -or $resolvedManifest -match "\.example\.json$") {
    throw "Example installer manifest is not a release source: $resolvedManifest"
}

function Get-ReleaseManifestPublicKey {
    if (-not [string]::IsNullOrWhiteSpace($PublicKey)) {
        return $PublicKey.Trim()
    }
    if (-not [string]::IsNullOrWhiteSpace($PublicKeyPath)) {
        if (-not (Test-Path -LiteralPath $PublicKeyPath -PathType Leaf)) {
            throw "Installer manifest public key file is missing: $PublicKeyPath"
        }
        return (Get-Content -LiteralPath $PublicKeyPath -Raw -Encoding UTF8).Trim()
    }
    if (-not [string]::IsNullOrWhiteSpace($env:LOOM_RELEASE_MANIFEST_PUBLIC_KEY)) {
        return $env:LOOM_RELEASE_MANIFEST_PUBLIC_KEY.Trim()
    }
    $defaultPublicKeyPath = Join-Path $Root "release-public-key.txt"
    if (Test-Path -LiteralPath $defaultPublicKeyPath -PathType Leaf) {
        return (Get-Content -LiteralPath $defaultPublicKeyPath -Raw -Encoding UTF8).Trim()
    }
    throw "Missing installer manifest public key. Provide -PublicKey, -PublicKeyPath, LOOM_RELEASE_MANIFEST_PUBLIC_KEY, or release-public-key.txt."
}

$releaseManifestPublicKey = Get-ReleaseManifestPublicKey

$pythonPath = Join-Path $Root "openclaw_new_launcher\python"
$previousPythonPath = $env:PYTHONPATH
try {
    if ([string]::IsNullOrWhiteSpace($previousPythonPath)) {
        $env:PYTHONPATH = $pythonPath
    } else {
        $env:PYTHONPATH = "$pythonPath$([System.IO.Path]::PathSeparator)$previousPythonPath"
    }

    $requiredList = ($RequiredComponents -join ",")
    $checkScript = @'
import sys
from core.release_manifest import load_release_manifest_file

manifest = load_release_manifest_file(
    sys.argv[1],
    public_key=sys.argv[3],
    require_signature_verification=True,
)
if manifest.product != "LOOM":
    raise SystemExit("Installer manifest product must be LOOM")
required = [item for item in sys.argv[2].split(",") if item]
ids = {component.component_id for component in manifest.components}
missing = [component_id for component_id in required if component_id not in ids]
if missing:
    raise SystemExit("Missing required installer components: " + ", ".join(missing))
for component in manifest.components:
    for url in component.urls:
        lowered = url.lower()
        if "example" in lowered or "placeholder" in lowered or "replace-with" in lowered:
            raise SystemExit(f"Component {component.component_id} contains placeholder URL: {url}")
print(f"Installer manifest check passed: {manifest.product} {manifest.version}, components={len(manifest.components)}")
'@
    $checkScript | python - $resolvedManifest $requiredList $releaseManifestPublicKey
    if ($LASTEXITCODE -ne 0) {
        throw "Installer manifest validation failed: $resolvedManifest"
    }
} finally {
    $env:PYTHONPATH = $previousPythonPath
}
