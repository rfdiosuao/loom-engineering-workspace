param(
    [Parameter(Mandatory = $true)]
    [string]$SpecPath,
    [string]$OutputPath = "",
    [string]$PublicKeyPath = "",
    [string]$PrivateKey = "",
    [string]$PrivateKeyPath = "",
    [switch]$Force
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($OutputPath)) {
    $OutputPath = Join-Path $Root "release-manifest.json"
}
if ([string]::IsNullOrWhiteSpace($PublicKeyPath)) {
    $PublicKeyPath = Join-Path $Root "release-public-key.txt"
}
if ([string]::IsNullOrWhiteSpace($PrivateKey)) {
    $PrivateKey = [string]$env:LOOM_RELEASE_MANIFEST_PRIVATE_KEY
}
if ([string]::IsNullOrWhiteSpace($PrivateKeyPath)) {
    $PrivateKeyPath = [string]$env:LOOM_RELEASE_MANIFEST_PRIVATE_KEY_PATH
}
if ([string]::IsNullOrWhiteSpace($PrivateKey) -and -not [string]::IsNullOrWhiteSpace($PrivateKeyPath)) {
    if (-not (Test-Path -LiteralPath $PrivateKeyPath -PathType Leaf)) {
        throw "Release manifest private key file is missing: $PrivateKeyPath"
    }
    $PrivateKey = (Get-Content -LiteralPath $PrivateKeyPath -Raw -Encoding UTF8).Trim()
}
if ([string]::IsNullOrWhiteSpace($PrivateKey)) {
    throw "Missing release manifest private key. Provide -PrivateKey, -PrivateKeyPath, LOOM_RELEASE_MANIFEST_PRIVATE_KEY, or LOOM_RELEASE_MANIFEST_PRIVATE_KEY_PATH."
}
if (-not (Test-Path -LiteralPath $SpecPath -PathType Leaf)) {
    throw "Release manifest spec is missing: $SpecPath"
}
if ((Test-Path -LiteralPath $OutputPath) -and -not $Force) {
    throw "Output manifest already exists. Use -Force to overwrite: $OutputPath"
}
if ((Test-Path -LiteralPath $PublicKeyPath) -and -not $Force) {
    throw "Output public key already exists. Use -Force to overwrite: $PublicKeyPath"
}

$pythonPath = Join-Path $Root "openclaw_new_launcher\python"
$previousPythonPath = $env:PYTHONPATH
$previousPrivateKey = $env:LOOM_RELEASE_MANIFEST_PRIVATE_KEY
$previousSpecPath = $env:LOOM_RELEASE_MANIFEST_SPEC_PATH
$previousOutputPath = $env:LOOM_RELEASE_MANIFEST_OUTPUT_PATH
$previousPublicKeyPath = $env:LOOM_RELEASE_MANIFEST_PUBLIC_KEY_OUTPUT_PATH

$pythonScript = @'
from __future__ import annotations

import base64
import copy
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from core.release_manifest import canonical_manifest_payload, parse_release_manifest


REQUIRED_COMPONENT_FIELDS = (
    "id",
    "name",
    "version",
    "platform",
    "arch",
    "type",
    "artifactPath",
    "urls",
    "installPath",
)


def fail(message: str) -> None:
    raise SystemExit(message)


def load_private_key(value: str) -> Ed25519PrivateKey:
    text = value.strip()
    if not text:
        fail("private key is empty")
    if text.startswith("-----BEGIN"):
        loaded = serialization.load_pem_private_key(text.encode("utf-8"), password=None)
        if not isinstance(loaded, Ed25519PrivateKey):
            fail("private key must be Ed25519")
        return loaded
    if text.lower().startswith("ed25519:"):
        text = text.split(":", 1)[1].strip()
    try:
        raw = base64.b64decode(text, validate=True)
    except Exception as exc:
        raise SystemExit(f"private key must be PEM or base64 raw Ed25519 seed: {exc}") from exc
    if len(raw) != 32:
        fail("private key must be 32 raw Ed25519 bytes when using base64")
    return Ed25519PrivateKey.from_private_bytes(raw)


def public_key_b64(private_key: Ed25519PrivateKey) -> str:
    public_key = private_key.public_key()
    raw = public_key.public_bytes(encoding=Encoding.Raw, format=PublicFormat.Raw)
    return base64.b64encode(raw).decode("ascii")


def normalize_url(url: Any, context: str) -> str:
    if not isinstance(url, str) or not url.strip():
        fail(f"{context} must be a non-empty URL")
    text = url.strip()
    lowered = text.lower()
    for marker in ("example", "placeholder", "replace-with"):
        if marker in lowered:
            fail(f"{context} must not contain placeholder marker: {text}")
    parsed = urlparse(text)
    if parsed.scheme not in ("http", "https"):
        fail(f"{context} must use http or https: {text}")
    hostname = (parsed.hostname or "").lower()
    if hostname in {"localhost", "127.0.0.1", "::1", "0.0.0.0"} or hostname.endswith(".local"):
        fail(f"{context} must not point to a local host: {text}")
    return text


def artifact_path(value: Any, spec_dir: Path, context: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        fail(f"{context}.artifactPath is required")
    path = Path(value)
    if not path.is_absolute():
        path = spec_dir / path
    path = path.resolve()
    if not path.is_file():
        fail(f"{context}.artifactPath does not exist: {path}")
    return path


def component_from_spec(raw: Any, index: int, spec_dir: Path) -> dict[str, Any]:
    context = f"components[{index}]"
    if not isinstance(raw, dict):
        fail(f"{context} must be an object")
    for field in REQUIRED_COMPONENT_FIELDS:
        if field not in raw:
            fail(f"{context}.{field} is required")
    artifact = artifact_path(raw.get("artifactPath"), spec_dir, context)
    payload = artifact.read_bytes()
    component: dict[str, Any] = {}
    for key, value in raw.items():
        if key == "artifactPath":
            continue
        component[key] = copy.deepcopy(value)
    component["size"] = len(payload)
    component["sha256"] = hashlib.sha256(payload).hexdigest()
    urls = raw.get("urls")
    if not isinstance(urls, list) or not urls:
        fail(f"{context}.urls must be a non-empty array")
    component["urls"] = [normalize_url(url, f"{context}.urls[{url_index}]") for url_index, url in enumerate(urls)]
    return component


def main() -> None:
    spec_path = Path(os.environ["LOOM_RELEASE_MANIFEST_SPEC_PATH"]).resolve()
    output_path = Path(os.environ["LOOM_RELEASE_MANIFEST_OUTPUT_PATH"]).resolve()
    public_key_path = Path(os.environ["LOOM_RELEASE_MANIFEST_PUBLIC_KEY_OUTPUT_PATH"]).resolve()
    private_key = load_private_key(os.environ["LOOM_RELEASE_MANIFEST_PRIVATE_KEY"])

    with spec_path.open("r", encoding="utf-8-sig") as handle:
        spec = json.load(handle)
    if not isinstance(spec, dict):
        fail("release manifest spec must be a JSON object")

    manifest: dict[str, Any] = {
        "schemaVersion": int(spec.get("schemaVersion", 1)),
        "product": str(spec.get("product") or "LOOM"),
        "channel": str(spec.get("channel") or "stable"),
        "version": str(spec.get("version") or "").strip(),
        "publishedAt": str(spec.get("publishedAt") or datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")),
        "minLauncherVersion": str(spec.get("minLauncherVersion") or "").strip(),
        "signature": {
            "algorithm": "ed25519",
            "value": base64.b64encode(b"\0" * 64).decode("ascii"),
        },
        "components": [],
    }
    if not manifest["version"]:
        fail("manifest.version is required")
    if not manifest["minLauncherVersion"]:
        fail("manifest.minLauncherVersion is required")

    raw_components = spec.get("components")
    if not isinstance(raw_components, list) or not raw_components:
        fail("manifest spec must include at least one component")
    manifest["components"] = [
        component_from_spec(component, index, spec_path.parent)
        for index, component in enumerate(raw_components)
    ]
    if "distribution" in spec:
        if not isinstance(spec["distribution"], dict):
            fail("manifest.distribution must be an object")
        manifest["distribution"] = copy.deepcopy(spec["distribution"])
    signature = private_key.sign(canonical_manifest_payload(manifest))
    manifest["signature"]["value"] = base64.b64encode(signature).decode("ascii")
    pubkey = public_key_b64(private_key)

    parse_release_manifest(manifest, public_key=pubkey, require_signature_verification=True)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    public_key_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    public_key_path.write_text(pubkey + "\n", encoding="utf-8")
    summary = {
        "ok": True,
        "manifest": str(output_path),
        "publicKey": str(public_key_path),
        "components": len(manifest["components"]),
        "version": manifest["version"],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
'@

try {
    if ([string]::IsNullOrWhiteSpace($previousPythonPath)) {
        $env:PYTHONPATH = $pythonPath
    } else {
        $env:PYTHONPATH = "$pythonPath$([System.IO.Path]::PathSeparator)$previousPythonPath"
    }
    $env:LOOM_RELEASE_MANIFEST_PRIVATE_KEY = $PrivateKey
    $env:LOOM_RELEASE_MANIFEST_SPEC_PATH = (Resolve-Path -LiteralPath $SpecPath).Path
    $env:LOOM_RELEASE_MANIFEST_OUTPUT_PATH = $OutputPath
    $env:LOOM_RELEASE_MANIFEST_PUBLIC_KEY_OUTPUT_PATH = $PublicKeyPath

    $pythonScript | python -
    if ($LASTEXITCODE -ne 0) {
        throw "Release manifest generation failed with exit code $LASTEXITCODE"
    }
} finally {
    $env:PYTHONPATH = $previousPythonPath
    $env:LOOM_RELEASE_MANIFEST_PRIVATE_KEY = $previousPrivateKey
    $env:LOOM_RELEASE_MANIFEST_SPEC_PATH = $previousSpecPath
    $env:LOOM_RELEASE_MANIFEST_OUTPUT_PATH = $previousOutputPath
    $env:LOOM_RELEASE_MANIFEST_PUBLIC_KEY_OUTPUT_PATH = $previousPublicKeyPath
}
