#!/bin/bash
set -euo pipefail

REMOTE_DIR="${BRIDGE_REMOTE_DIR:-/opt/openclaw-newapi-bridge}"
SERVICE_NAME="${BRIDGE_SERVICE_NAME:-openclaw-newapi-bridge}"
SERVER_UPLOAD="${BRIDGE_SERVER_UPLOAD:-/tmp/openclaw-newapi-bridge.py}"
BRIDGE_ENV_FILE="${BRIDGE_ENV_FILE:-$REMOTE_DIR/bridge.env}"
LOCAL_BASE_URL="${BRIDGE_LOCAL_BASE_URL:-http://127.0.0.1:3016}"
READY_RETRY_ATTEMPTS="${BRIDGE_READY_RETRY_ATTEMPTS:-30}"
READY_RETRY_DELAY_SEC="${BRIDGE_READY_RETRY_DELAY_SEC:-1}"

case "$REMOTE_DIR" in
  /*) ;;
  *) echo "BRIDGE_REMOTE_DIR must be absolute" >&2; exit 1 ;;
esac
if [ "$REMOTE_DIR" = "/" ]; then
  echo "refusing to deploy into filesystem root" >&2
  exit 1
fi
if ! [[ "$READY_RETRY_ATTEMPTS" =~ ^[1-9][0-9]*$ ]]; then
  echo "BRIDGE_READY_RETRY_ATTEMPTS must be a positive integer" >&2
  exit 1
fi
if ! [[ "$READY_RETRY_DELAY_SEC" =~ ^[0-9]+([.][0-9]+)?$ ]]; then
  echo "BRIDGE_READY_RETRY_DELAY_SEC must be a non-negative number" >&2
  exit 1
fi

echo "====================================="
echo "OpenClaw NewAPI bridge guarded deploy"
echo "====================================="

cd "$REMOTE_DIR"
ts="$(date -u +%Y%m%d%H%M%S)"
install -d -m 0700 "$REMOTE_DIR/backups"
backup_dir="$(mktemp -d "$REMOTE_DIR/backups/deploy-$ts.XXXXXX")"
chmod 0700 "$backup_dir"
cache="$(mktemp -d)"
next=""
switched=0

wait_for_readiness() {
  attempt=1
  while [ "$attempt" -le "$READY_RETRY_ATTEMPTS" ]; do
    if curl -fsS "$LOCAL_BASE_URL/health" > "$cache/health.json" && \
      curl -fsS "$LOCAL_BASE_URL/api/openclaw/entitlements/public-key" \
        > "$cache/entitlement-public-key.json"; then
      echo "readiness=ready attempts=$attempt"
      return 0
    fi
    if [ "$attempt" -eq "$READY_RETRY_ATTEMPTS" ]; then
      return 1
    fi
    sleep "$READY_RETRY_DELAY_SEC"
    attempt=$((attempt + 1))
  done
}

finish() {
  status=$?
  trap - EXIT
  if [ "$status" -ne 0 ] && [ "$switched" -eq 1 ]; then
    systemctl stop "$SERVICE_NAME" || true
    if [ -f "$REMOTE_DIR/.openclaw_newapi_bridge.py.pre-deploy" ]; then
      rm -f -- "$REMOTE_DIR/openclaw_newapi_bridge.py"
      mv "$REMOTE_DIR/.openclaw_newapi_bridge.py.pre-deploy" \
        "$REMOTE_DIR/openclaw_newapi_bridge.py"
    fi
    systemctl start "$SERVICE_NAME" || true
  fi
  rm -rf -- "$cache"
  if [ -n "$next" ] && [ -d "$next" ]; then
    rm -rf -- "$next"
  fi
  exit "$status"
}
trap finish EXIT

echo "[1/7] Validate current paths and create protected backup"
test -f "$REMOTE_DIR/openclaw_newapi_bridge.py"
test -f "$BRIDGE_ENV_FILE"
cp -a "$REMOTE_DIR/openclaw_newapi_bridge.py" \
  "$backup_dir/openclaw_newapi_bridge.py"
cp -a "$BRIDGE_ENV_FILE" "$backup_dir/bridge.env"
env_sha_before="$(sha256sum "$BRIDGE_ENV_FILE" | cut -d' ' -f1)"
echo "backup=$backup_dir"

echo "[2/7] Compile candidate and validate entitlement configuration"
test -f "$SERVER_UPLOAD"
PYTHONPYCACHEPREFIX="$cache" python3 -m py_compile "$SERVER_UPLOAD"
BRIDGE_ENV_FILE="$BRIDGE_ENV_FILE" \
BRIDGE_SERVER_UPLOAD="$SERVER_UPLOAD" \
python3 - <<'PY'
from __future__ import annotations

import importlib.util
import os
import shlex
from pathlib import Path
from urllib.parse import urlparse


def read_environment(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, raw_value = line.split("=", 1)
        name = name.strip()
        if not name or not name.replace("_", "A").isalnum():
            raise SystemExit("bridge environment contains an invalid variable name")
        try:
            parsed = shlex.split(raw_value, posix=True)
        except ValueError as error:
            raise SystemExit(f"bridge environment value is malformed for {name}") from error
        values[name] = parsed[0] if parsed else ""
    return values


environment_path = Path(os.environ["BRIDGE_ENV_FILE"])
candidate_path = Path(os.environ["BRIDGE_SERVER_UPLOAD"])
values = read_environment(environment_path)
required = (
    "OPENCLAW_LICENSE_ENTITLEMENT_SERVICE_TOKEN",
    "OPENCLAW_LICENSE_ENTITLEMENT_SERVICE_BASE",
    "OPENCLAW_BIND_DB",
    "OPENCLAW_BIND_TICKET_SECRET",
    "OPENCLAW_ENTITLEMENT_KEY_ID",
)
missing = [name for name in required if not values.get(name, "").strip()]
if missing:
    raise SystemExit("missing required bridge configuration: " + ", ".join(missing))

if len(values["OPENCLAW_LICENSE_ENTITLEMENT_SERVICE_TOKEN"].encode("utf-8")) < 32:
    raise SystemExit("bridge entitlement service token is too short")
if len(values["OPENCLAW_BIND_TICKET_SECRET"].encode("utf-8")) < 32:
    raise SystemExit("bridge bind-ticket secret is too short")
if values["OPENCLAW_ENTITLEMENT_KEY_ID"] != "openclaw-ed25519-v1":
    raise SystemExit("bridge entitlement key id does not match the client trust anchor")
service_url = urlparse(values["OPENCLAW_LICENSE_ENTITLEMENT_SERVICE_BASE"])
if service_url.scheme != "https" or not service_url.hostname:
    raise SystemExit("bridge entitlement service base must be an absolute HTTPS URL")
if not Path(values["OPENCLAW_BIND_DB"]).is_absolute():
    raise SystemExit("bridge bind database path must be absolute")

private_file = values.get("OPENCLAW_ENTITLEMENT_PRIVATE_KEY_FILE", "").strip()
private_b64 = values.get("OPENCLAW_ENTITLEMENT_PRIVATE_KEY_B64", "").strip()
if bool(private_file) == bool(private_b64):
    raise SystemExit("configure exactly one bridge entitlement private-key source")
if private_file and not Path(private_file).is_file():
    raise SystemExit("configured bridge entitlement private-key file is unavailable")

for name, value in values.items():
    os.environ[name] = value
spec = importlib.util.spec_from_file_location("bridge_candidate_preflight", candidate_path)
if spec is None or spec.loader is None:
    raise SystemExit("unable to load bridge candidate")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
key_payload = module.entitlement_key_payload()
if key_payload.get("keyId") != "openclaw-ed25519-v1" or not key_payload.get("publicKey"):
    raise SystemExit("bridge entitlement signing preflight failed")
print("entitlement_config=ready")
PY
sha256sum "$SERVER_UPLOAD"

echo "[3/7] Build same-filesystem staging file"
next="$(mktemp -d "$REMOTE_DIR/.deploy-next.XXXXXX")"
install -m 0755 "$SERVER_UPLOAD" "$next/openclaw_newapi_bridge.py"

echo "[4/7] Guarded atomic program switch"
systemctl stop "$SERVICE_NAME"
switched=1
mv "$REMOTE_DIR/openclaw_newapi_bridge.py" \
  "$REMOTE_DIR/.openclaw_newapi_bridge.py.pre-deploy"
mv "$next/openclaw_newapi_bridge.py" "$REMOTE_DIR/openclaw_newapi_bridge.py"
systemctl start "$SERVICE_NAME"
systemctl is-active --quiet "$SERVICE_NAME"

echo "[5/7] Read-only health, entitlement, payment and subscription route smoke"
wait_for_readiness
DEPLOY_HEALTH_JSON="$cache/health.json" \
DEPLOY_KEY_JSON="$cache/entitlement-public-key.json" \
python3 - <<'PY'
from __future__ import annotations

import base64
import json
import os
from pathlib import Path


health = json.loads(Path(os.environ["DEPLOY_HEALTH_JSON"]).read_text(encoding="utf-8"))
if health.get("success") is not True or health.get("service") != "openclaw-newapi-bridge":
    raise SystemExit("bridge health response contract failed")
payload = json.loads(Path(os.environ["DEPLOY_KEY_JSON"]).read_text(encoding="utf-8"))
data = payload.get("data") if isinstance(payload, dict) else None
if payload.get("success") is not True or not isinstance(data, dict):
    raise SystemExit("bridge entitlement public-key response contract failed")
if data.get("keyId") != "openclaw-ed25519-v1":
    raise SystemExit("bridge entitlement public-key id is unexpected")
try:
    public_key = base64.b64decode(str(data.get("publicKey") or ""), validate=True)
except ValueError as error:
    raise SystemExit("bridge entitlement public key is malformed") from error
if len(public_key) != 32:
    raise SystemExit("bridge entitlement public key has an invalid length")
print("entitlement_public_key=ready")
PY

payment_response="$(
  curl -sS \
    -X POST \
    -H "Content-Type: application/json" \
    --data '{}' \
    -w '\n%{http_code}' \
    "$LOCAL_BASE_URL/api/openclaw/payments/plans"
)"
payment_status="${payment_response##*$'\n'}"
if [ "$payment_status" != "401" ]; then
  echo "bridge payment route contract failed" >&2
  exit 1
fi
echo "payment_route=ready"

account_subscription_response="$(
  curl -sS \
    -w '\n%{http_code}' \
    "$LOCAL_BASE_URL/api/openclaw/account/subscription"
)"
account_subscription_status="${account_subscription_response##*$'\n'}"
if [ "$account_subscription_status" != "401" ]; then
  echo "bridge account subscription route contract failed" >&2
  exit 1
fi
echo "account_subscription_route=ready"

echo "[6/7] Verify environment was not changed"
env_sha_after="$(sha256sum "$BRIDGE_ENV_FILE" | cut -d' ' -f1)"
test "$env_sha_after" = "$env_sha_before"
echo "environment_unchanged=verified"

echo "[7/7] Disarm rollback and report final status"
switched=0
trap - EXIT
rm -f -- "$REMOTE_DIR/.openclaw_newapi_bridge.py.pre-deploy"
rm -rf -- "$next" "$cache"
echo "service=active"
echo "program=openclaw_newapi_bridge.py"
echo "backup=$backup_dir"
echo "Deploy complete"
