#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ARTIFACT_DIR="$ROOT/ci_artifacts"
NODE_VERSION="${NODE_VERSION:-20.12.2}"
NODE_DIR="$ROOT/.ci-tools/node-v${NODE_VERSION}-linux-x64"

cd "$ROOT"
rm -rf "$ARTIFACT_DIR"
mkdir -p "$ARTIFACT_DIR"

echo "==> Repository hygiene"
if git ls-files | grep -E '(^|/)(node_modules|release|dist|target|__pycache__)/'; then
  echo "Generated dependency/build files must not be committed."
  exit 1
fi

if git ls-files | grep -E '(^|/)(license\.db|private_key\.b64|admin_token\.txt|license\.json|install_id\.txt)$|\.zip$'; then
  echo "Sensitive runtime files or release archives must not be committed."
  exit 1
fi

echo "==> Install isolated Node.js ${NODE_VERSION}"
if [ ! -x "$NODE_DIR/bin/node" ]; then
  mkdir -p "$ROOT/.ci-tools"
  ARCHIVE="$ROOT/.ci-tools/node-v${NODE_VERSION}-linux-x64.tar.xz"
  URL="https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-x64.tar.xz"
  if command -v curl >/dev/null 2>&1; then
    curl -fsSL "$URL" -o "$ARCHIVE"
  else
    wget -q "$URL" -O "$ARCHIVE"
  fi
  tar -xJf "$ARCHIVE" -C "$ROOT/.ci-tools"
fi

export PATH="$NODE_DIR/bin:$PATH"
node --version
npm --version

echo "==> Frontend build"
cd "$ROOT/openclaw_new_launcher"
npm ci
npm run build

echo "==> Python compile"
cd "$ROOT"
PYTHON_BIN="$(command -v python3 || command -v python)"
"$PYTHON_BIN" -m py_compile \
  openclaw_new_launcher/python/bridge.py \
  openclaw_new_launcher/python/core/*.py \
  openclaw_new_launcher/python/services/*.py

if [ -f "$ROOT/license_server/server.py" ]; then
  "$PYTHON_BIN" -m py_compile "$ROOT/license_server/server.py"
fi

echo "==> Package CI artifact"
"$PYTHON_BIN" - <<'PY'
import os
import zipfile

root = os.getcwd()
artifact_dir = os.path.join(root, "ci_artifacts")
zip_path = os.path.join(artifact_dir, "openclaw-ci-web-bundle.zip")
include_roots = [
    "openclaw_new_launcher/dist",
    "openclaw_new_launcher/python",
    "openclaw_new_launcher/data/themes",
    "openclaw_new_launcher/src-tauri/capabilities",
    "docs",
    "scripts",
]
skip_dirs = {"node_modules", "target", "__pycache__", ".git", ".ci-tools", "release"}
skip_suffixes = {".pyc", ".pyo", ".zip"}

with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
    for rel_root in include_roots:
        abs_root = os.path.join(root, rel_root)
        if not os.path.exists(abs_root):
            continue
        if os.path.isfile(abs_root):
            zf.write(abs_root, rel_root.replace("\\", "/"))
            continue
        for dirpath, dirnames, filenames in os.walk(abs_root):
            dirnames[:] = [d for d in dirnames if d not in skip_dirs]
            for filename in filenames:
                if any(filename.endswith(suffix) for suffix in skip_suffixes):
                    continue
                abs_path = os.path.join(dirpath, filename)
                rel_path = os.path.relpath(abs_path, root).replace("\\", "/")
                zf.write(abs_path, rel_path)
PY

if command -v sha256sum >/dev/null 2>&1; then
  sha256sum "$ARTIFACT_DIR/openclaw-ci-web-bundle.zip" > "$ARTIFACT_DIR/openclaw-ci-web-bundle.zip.sha256.txt"
fi

{
  echo "Lumi CI/CD artifact"
  echo "Commit: $(git rev-parse HEAD)"
  echo "Branch: ${GITEE_BRANCH:-local}"
  echo "Build number: ${GITEE_PIPELINE_BUILD_NUMBER:-local}"
  echo "Generated at: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo ""
  echo "Note: This cloud artifact validates and packages source/web assets."
  echo "The full Windows offline portable package still requires a Windows builder or a local build."
} > "$ARTIFACT_DIR/CI_REPORT.txt"

echo "CI artifacts:"
find "$ARTIFACT_DIR" -maxdepth 1 -type f -print
