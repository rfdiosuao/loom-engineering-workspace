#!/bin/bash
set -euo pipefail

REMOTE_DIR="${LICENSE_REMOTE_DIR:-/opt/openclaw-license}"
SERVICE_NAME="${LICENSE_SERVICE_NAME:-openclaw-license}"
SERVER_UPLOAD="${LICENSE_SERVER_UPLOAD:-/tmp/openclaw-license-server.py}"
PACKAGE_UPLOAD="${LICENSE_PACKAGE_UPLOAD:-/tmp/openclaw-license-luming_license}"
DEPLOY_ENV_HELPER="${LICENSE_DEPLOY_ENV_HELPER:-$PACKAGE_UPLOAD/deploy_env.py}" # luming_license/deploy_env.py
ADMIN_HTML_UPLOAD="${LICENSE_ADMIN_HTML_UPLOAD:-/tmp/openclaw-license-admin_console.html}"
RELAY_ENV_FILE="${LICENSE_RELAY_ENV_FILE:-$REMOTE_DIR/openclaw-license.env}"
LICENSE_DB_PATH="${LICENSE_DB:-$REMOTE_DIR/license.db}"
LOCAL_BASE_URL="${LICENSE_LOCAL_BASE_URL:-http://127.0.0.1:18791}"
RELAY_TOKEN="${OPENCLAW_PUBLISH_RELAY_TOKEN:-${PUBLISH_RELAY_TOKEN:-}}"
HEALTH_RETRY_ATTEMPTS="${LICENSE_HEALTH_RETRY_ATTEMPTS:-30}"
HEALTH_RETRY_DELAY_SEC="${LICENSE_HEALTH_RETRY_DELAY_SEC:-1}"
REQUIRE_ZPAY_READY="${LICENSE_REQUIRE_ZPAY_READY:-0}"

case "$REMOTE_DIR" in
  /*) ;;
  *) echo "LICENSE_REMOTE_DIR must be absolute" >&2; exit 1 ;;
esac
if [ "$REMOTE_DIR" = "/" ]; then
  echo "refusing to deploy into filesystem root" >&2
  exit 1
fi
if ! [[ "$HEALTH_RETRY_ATTEMPTS" =~ ^[1-9][0-9]*$ ]]; then
  echo "LICENSE_HEALTH_RETRY_ATTEMPTS must be a positive integer" >&2
  exit 1
fi
if ! [[ "$HEALTH_RETRY_DELAY_SEC" =~ ^[0-9]+([.][0-9]+)?$ ]]; then
  echo "LICENSE_HEALTH_RETRY_DELAY_SEC must be a non-negative number" >&2
  exit 1
fi
if [ "$REQUIRE_ZPAY_READY" != "0" ] && [ "$REQUIRE_ZPAY_READY" != "1" ]; then
  echo "LICENSE_REQUIRE_ZPAY_READY must be 0 or 1" >&2
  exit 1
fi

echo "======================================"
echo "OpenClaw license server guarded deploy"
echo "======================================"

cd "$REMOTE_DIR"
ts="$(date -u +%Y%m%d%H%M%S)"
backup_dir="$REMOTE_DIR/backups/deploy-$ts"
cache="$(mktemp -d)"
next=""
switched=0
relay_updated=0
env_existed=0
admin_switched=0

wait_for_health() {
  attempt=1
  while [ "$attempt" -le "$HEALTH_RETRY_ATTEMPTS" ]; do
    if curl -fsS "$LOCAL_BASE_URL/health" > "$cache/health.json"; then
      echo "health=ready attempts=$attempt"
      return 0
    fi
    if [ "$attempt" -eq "$HEALTH_RETRY_ATTEMPTS" ]; then
      return 1
    fi
    sleep "$HEALTH_RETRY_DELAY_SEC"
    attempt=$((attempt + 1))
  done
}

finish() {
  status=$?
  trap - EXIT
  if [ "$status" -ne 0 ] && [ "$relay_updated" -eq 1 ]; then
    if [ "$env_existed" -eq 1 ] && [ -f "$backup_dir/openclaw-license.env" ]; then
      install -m 0600 "$backup_dir/openclaw-license.env" "$RELAY_ENV_FILE"
    else
      rm -f -- "$RELAY_ENV_FILE"
    fi
    systemctl daemon-reload || true
  fi
  if [ "$status" -ne 0 ] && [ "$switched" -eq 1 ]; then
    systemctl stop "$SERVICE_NAME" || true
    if [ -f "$REMOTE_DIR/.server.py.pre-deploy" ]; then
      rm -f -- "$REMOTE_DIR/server.py"
      mv "$REMOTE_DIR/.server.py.pre-deploy" "$REMOTE_DIR/server.py"
    fi
    if [ -d "$REMOTE_DIR/.luming_license.pre-deploy" ]; then
      rm -rf -- "$REMOTE_DIR/luming_license"
      mv "$REMOTE_DIR/.luming_license.pre-deploy" "$REMOTE_DIR/luming_license"
    fi
    if [ "$admin_switched" -eq 1 ] && [ -f "$REMOTE_DIR/.admin_console.html.pre-deploy" ]; then
      rm -f -- "$REMOTE_DIR/admin_console.html"
      mv "$REMOTE_DIR/.admin_console.html.pre-deploy" "$REMOTE_DIR/admin_console.html"
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

echo "[1/8] Validate current paths and create protected backup"
test -f "$REMOTE_DIR/server.py"
test -d "$REMOTE_DIR/luming_license"
test -f "$LICENSE_DB_PATH"
install -d -m 0700 "$backup_dir"
cp -a "$REMOTE_DIR/server.py" "$backup_dir/server.py"
cp -a "$REMOTE_DIR/luming_license" "$backup_dir/luming_license"
if [ -f "$REMOTE_DIR/admin_console.html" ]; then
  cp -a "$REMOTE_DIR/admin_console.html" "$backup_dir/admin_console.html"
fi
if [ -f "$RELAY_ENV_FILE" ]; then
  env_existed=1
  install -m 0600 "$RELAY_ENV_FILE" "$backup_dir/openclaw-license.env"
fi
DEPLOY_DB_SOURCE="$LICENSE_DB_PATH" DEPLOY_DB_BACKUP="$backup_dir/license.db" python3 - <<'PY'
import os
import sqlite3

source = sqlite3.connect(os.environ["DEPLOY_DB_SOURCE"])
target = sqlite3.connect(os.environ["DEPLOY_DB_BACKUP"])
try:
    source.backup(target)
finally:
    target.close()
    source.close()
PY
chmod 0600 "$backup_dir/license.db"
echo "backup=$backup_dir"

echo "[2/8] Validate complete modular upload"
test -f "$SERVER_UPLOAD"
test -d "$PACKAGE_UPLOAD"
test -f "$PACKAGE_UPLOAD/__init__.py"
test -f "$DEPLOY_ENV_HELPER"
test -f "$PACKAGE_UPLOAD/http/routes_payments.py"
mapfile -d '' package_files < <(find "$PACKAGE_UPLOAD" -type f -name '*.py' -print0)
test "${#package_files[@]}" -gt 0
PYTHONPYCACHEPREFIX="$cache" python3 -m py_compile "$SERVER_UPLOAD" "${package_files[@]}"
sha256sum "$SERVER_UPLOAD"
echo "package_python_files=${#package_files[@]}"

echo "[3/8] Build same-filesystem staging tree"
next="$(mktemp -d "$REMOTE_DIR/.deploy-next.XXXXXX")"
install -m 0644 "$SERVER_UPLOAD" "$next/server.py"
cp -a "$PACKAGE_UPLOAD" "$next/luming_license"
find "$next/luming_license" -type d -exec chmod 0755 {} +
find "$next/luming_license" -type f -exec chmod 0644 {} +
if [ -f "$ADMIN_HTML_UPLOAD" ]; then
  install -m 0644 "$ADMIN_HTML_UPLOAD" "$next/admin_console.html"
fi

echo "[4/8] Preserve environment and verify entitlement credential"
dropin_dir="/etc/systemd/system/${SERVICE_NAME}.service.d"
mkdir -p "$dropin_dir"
cat > "$dropin_dir/runtime-env.conf" <<EOF
[Service]
EnvironmentFile=-$RELAY_ENV_FILE
EOF
if [ -n "$RELAY_TOKEN" ]; then
  DEPLOY_ENV_FILE="$RELAY_ENV_FILE" \
  DEPLOY_ENV_NAME="OPENCLAW_PUBLISH_RELAY_TOKEN" \
  DEPLOY_ENV_VALUE="$RELAY_TOKEN" \
    python3 "$DEPLOY_ENV_HELPER"
  relay_updated=1
  echo "relay_token=configured"
fi
DEPLOY_ENV_FILE="$RELAY_ENV_FILE" \
DEPLOY_ENV_REQUIRE_NAME="LICENSE_ACCOUNT_REDEEM_SERVICE_TOKEN" \
  python3 "$DEPLOY_ENV_HELPER"
echo "entitlement_service_token=configured"
if [ "$REQUIRE_ZPAY_READY" = "1" ]; then
  DEPLOY_ENV_FILE="$RELAY_ENV_FILE" \
  DEPLOY_ENV_VALIDATE_ZPAY="1" \
    python3 "$DEPLOY_ENV_HELPER"
  echo "zpay=configured"
fi
systemctl daemon-reload

echo "[5/8] Guarded atomic program switch"
systemctl stop "$SERVICE_NAME"
switched=1
mv "$REMOTE_DIR/server.py" "$REMOTE_DIR/.server.py.pre-deploy"
mv "$REMOTE_DIR/luming_license" "$REMOTE_DIR/.luming_license.pre-deploy"
mv "$next/server.py" "$REMOTE_DIR/server.py"
mv "$next/luming_license" "$REMOTE_DIR/luming_license"
if [ -f "$next/admin_console.html" ]; then
  if [ -f "$REMOTE_DIR/admin_console.html" ]; then
    mv "$REMOTE_DIR/admin_console.html" "$REMOTE_DIR/.admin_console.html.pre-deploy"
  fi
  mv "$next/admin_console.html" "$REMOTE_DIR/admin_console.html"
  admin_switched=1
fi
systemctl start "$SERVICE_NAME"
systemctl is-active --quiet "$SERVICE_NAME"

echo "[6/8] Read-only health, database and route smoke"
wait_for_health
DEPLOY_DB_SOURCE="$LICENSE_DB_PATH" python3 - <<'PY'
import os
import sqlite3

with sqlite3.connect(os.environ["DEPLOY_DB_SOURCE"]) as connection:
    result = connection.execute("pragma quick_check").fetchone()
if not result or result[0] != "ok":
    raise SystemExit(1)
PY
route_status="$(curl -sS -o "$cache/entitlement-route.json" -w '%{http_code}' \
  -X POST "$LOCAL_BASE_URL/api/service/account-entitlements/current" \
  -H 'Content-Type: application/json' -d '{}')"
test "$route_status" = "401"
echo "entitlement_route=ready"
payment_route_status="$(curl -sS -o "$cache/payment-route.json" -w '%{http_code}' \
  -X POST "$LOCAL_BASE_URL/api/service/payments/plans" \
  -H 'Content-Type: application/json' -d '{}')"
test "$payment_route_status" = "401"
echo "payment_route=ready"
if [ -n "$RELAY_TOKEN" ]; then
  curl -fsS "$LOCAL_BASE_URL/api/lumi/relay/health" \
    -H "Authorization: Bearer $RELAY_TOKEN" >/dev/null
fi

echo "[7/8] Disarm rollback and clean superseded program paths"
switched=0
trap - EXIT
rm -f -- "$REMOTE_DIR/.server.py.pre-deploy"
rm -rf -- "$REMOTE_DIR/.luming_license.pre-deploy"
rm -f -- "$REMOTE_DIR/.admin_console.html.pre-deploy"
rm -rf -- "$next" "$cache"

echo "[8/8] Final status"
echo "service=active"
echo "database_quick_check=ok"
echo "program_files=server.py+luming_license"
echo "backup=$backup_dir"
echo "Deploy complete"
