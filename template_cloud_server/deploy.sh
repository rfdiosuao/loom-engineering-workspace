#!/usr/bin/env bash
set -euo pipefail

REMOTE_DIR="${TEMPLATE_CLOUD_REMOTE_DIR:-/opt/loom-template-cloud}"
SERVICE_NAME="${TEMPLATE_CLOUD_SERVICE_NAME:-loom-template-cloud}"
SERVER_UPLOAD="${TEMPLATE_CLOUD_SERVER_UPLOAD:-/tmp/loom-template-cloud-server.py}"
SERVICE_UPLOAD="${TEMPLATE_CLOUD_SERVICE_UPLOAD:-/tmp/loom-template-cloud.service}"
ENV_FILE="${TEMPLATE_CLOUD_ENV_FILE:-$REMOTE_DIR/template-cloud.env}"
PUBLIC_BASE="${TEMPLATE_CLOUD_PUBLIC_BASE:-https://api-cn.heang.top}"
TOKEN="${TEMPLATE_CLOUD_TOKEN:-}"
ALLOW_PUBLIC_UPLOAD="${TEMPLATE_CLOUD_ALLOW_PUBLIC_UPLOAD:-1}"

if [ -z "$TOKEN" ]; then
  echo "TEMPLATE_CLOUD_TOKEN is required" >&2
  exit 1
fi

mkdir -p "$REMOTE_DIR"
cd "$REMOTE_DIR"

ts="$(date -u +%Y%m%d%H%M%S)"
if [ -f server.py ]; then
  cp server.py "server.py.bak-$ts"
fi
if [ -f templates.json ]; then
  cp templates.json "templates.json.bak-$ts"
fi

python3 -m py_compile "$SERVER_UPLOAD"
install -m 0644 "$SERVER_UPLOAD" "$REMOTE_DIR/server.py"
install -m 0644 "$SERVICE_UPLOAD" "/etc/systemd/system/${SERVICE_NAME}.service"

umask 077
cat > "$ENV_FILE" <<EOF
TEMPLATE_CLOUD_TOKEN="$TOKEN"
TEMPLATE_CLOUD_PUBLIC_BASE="$PUBLIC_BASE"
TEMPLATE_CLOUD_ALLOW_PUBLIC_UPLOAD="$ALLOW_PUBLIC_UPLOAD"
EOF
chmod 600 "$ENV_FILE"

systemctl daemon-reload
systemctl enable "$SERVICE_NAME" >/dev/null
systemctl restart "$SERVICE_NAME"
sleep 1
systemctl is-active "$SERVICE_NAME"
curl -fsS "http://127.0.0.1:18793/health"
echo
