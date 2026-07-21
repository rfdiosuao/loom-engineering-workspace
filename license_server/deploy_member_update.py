#!/usr/bin/env python3
"""Deploy the license server membership update over SSH.

Usage:
  set LICENSE_SSH_PASSWORD=...
  python deploy_member_update.py
"""

from __future__ import annotations

import os
import posixpath
import shlex
import socket
import sys
from datetime import datetime, timezone
from urllib.parse import urlparse

import paramiko
import socks


HOST = os.environ.get("LICENSE_SSH_HOST", "118.145.98.220")
PORT = int(os.environ.get("LICENSE_SSH_PORT", "22"))
USER = os.environ.get("LICENSE_SSH_USER", "root")
PASSWORD = os.environ.get("LICENSE_SSH_PASSWORD", "")
REMOTE_DIR = os.environ.get("LICENSE_REMOTE_DIR", "/opt/openclaw-license")
SERVICE_NAME = os.environ.get("LICENSE_SERVICE_NAME", "openclaw-license")
LOCAL_SERVER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "server.py")
LOCAL_ADMIN_HTML = os.path.join(os.path.dirname(os.path.abspath(__file__)), "admin_console.html")
LOCAL_SERVICE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "openclaw-license.service")
SSH_PROXY = os.environ.get("LICENSE_SSH_PROXY", "").strip()
LOCAL_BASE_URL = os.environ.get("LICENSE_LOCAL_BASE_URL", "http://127.0.0.1:18791").rstrip("/")
SYSTEMD_UNIT_PATH = os.environ.get("LICENSE_SYSTEMD_UNIT_PATH", f"/etc/systemd/system/{SERVICE_NAME}.service")
RELAY_ENV_FILE = os.environ.get("LICENSE_RELAY_ENV_FILE", posixpath.join(REMOTE_DIR, "openclaw-license.env"))
RELAY_TOKEN = (
    os.environ.get("OPENCLAW_PUBLISH_RELAY_TOKEN")
    or os.environ.get("PUBLISH_RELAY_TOKEN")
    or os.environ.get("LICENSE_RELAY_TOKEN")
    or ""
).strip()
DEPLOY_SERVICE = os.environ.get("LICENSE_DEPLOY_SERVICE", "").strip().lower() in {"1", "true", "yes", "on"}


def fail(message: str) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(1)


def run(client: paramiko.SSHClient, command: str) -> str:
    stdin, stdout, stderr = client.exec_command(command, timeout=60)
    out = stdout.read().decode("utf-8", "replace")
    err = stderr.read().decode("utf-8", "replace")
    code = stdout.channel.recv_exit_status()
    if code != 0:
        fail(f"remote command failed ({code}): {command}\n{out}\n{err}")
    return out.strip()


def q(value: str) -> str:
    return shlex.quote(value)


def env_line(name: str, value: str) -> str:
    escaped = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("$", "\\$")
        .replace("`", "\\`")
        .replace("\r", "")
        .replace("\n", "")
    )
    return f'{name}="{escaped}"\n'


def write_remote_text(sftp: paramiko.SFTPClient, remote_path: str, text: str, mode: int) -> None:
    with sftp.open(remote_path, "w") as remote_file:
        remote_file.write(text)
    sftp.chmod(remote_path, mode)


def main() -> None:
    if not PASSWORD:
        fail("LICENSE_SSH_PASSWORD is required")
    if not os.path.exists(LOCAL_SERVER):
        fail(f"local server.py not found: {LOCAL_SERVER}")
    if not os.path.exists(LOCAL_ADMIN_HTML):
        fail(f"local admin_console.html not found: {LOCAL_ADMIN_HTML}")
    if DEPLOY_SERVICE and not os.path.exists(LOCAL_SERVICE):
        fail(f"local service file not found: {LOCAL_SERVICE}")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    backup_name = "server.py.bak-" + stamp
    html_backup_name = "admin_console.html.bak-" + stamp
    db_backup_name = "license.db.bak-" + stamp
    remote_server = posixpath.join(REMOTE_DIR, "server.py")
    remote_admin_html = posixpath.join(REMOTE_DIR, "admin_console.html")
    remote_db = posixpath.join(REMOTE_DIR, "license.db")
    remote_tmp = posixpath.join(REMOTE_DIR, "server.py.uploading")
    remote_html_tmp = posixpath.join(REMOTE_DIR, "admin_console.html.uploading")
    remote_service_tmp = posixpath.join(REMOTE_DIR, "openclaw-license.service.uploading")
    remote_env_tmp = posixpath.join(REMOTE_DIR, "openclaw-license.env.uploading")
    dropin_dir = f"/etc/systemd/system/{SERVICE_NAME}.service.d"
    dropin_path = posixpath.join(dropin_dir, "publish-relay.conf")
    remote_dropin_tmp = posixpath.join(REMOTE_DIR, "publish-relay.conf.uploading")
    remote_backup = posixpath.join(REMOTE_DIR, backup_name)
    remote_html_backup = posixpath.join(REMOTE_DIR, html_backup_name)
    remote_db_backup = posixpath.join(REMOTE_DIR, db_backup_name)
    unit_backup = SYSTEMD_UNIT_PATH + ".bak-" + stamp

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    sock: socket.socket | None = None
    if SSH_PROXY:
        parsed = urlparse(SSH_PROXY)
        proxy_type = socks.SOCKS5 if parsed.scheme.lower().startswith("socks") else socks.HTTP
        sock = socks.socksocket()
        sock.set_proxy(proxy_type, parsed.hostname or "127.0.0.1", parsed.port or 7897)
        sock.settimeout(30)
        sock.connect((HOST, PORT))
    client.connect(
        hostname=HOST,
        port=PORT,
        username=USER,
        password=PASSWORD,
        sock=sock,
        timeout=20,
        banner_timeout=20,
        auth_timeout=20,
    )
    try:
        run(client, f"test -d {q(REMOTE_DIR)} && test -f {q(remote_server)}")
        sftp = client.open_sftp()
        try:
            sftp.put(LOCAL_SERVER, remote_tmp)
            sftp.put(LOCAL_ADMIN_HTML, remote_html_tmp)
            if DEPLOY_SERVICE:
                sftp.put(LOCAL_SERVICE, remote_service_tmp)
                sftp.chmod(remote_service_tmp, 0o644)
            if RELAY_TOKEN:
                write_remote_text(
                    sftp,
                    remote_env_tmp,
                    "# Generated by deploy_member_update.py.\n"
                    + env_line("OPENCLAW_PUBLISH_RELAY_TOKEN", RELAY_TOKEN),
                    0o600,
                )
                write_remote_text(
                    sftp,
                    remote_dropin_tmp,
                    "[Service]\n" f"EnvironmentFile=-{RELAY_ENV_FILE}\n",
                    0o644,
                )
        finally:
            sftp.close()
        run(client, f"python3 -m py_compile {q(remote_tmp)}")
        run(
            client,
            f"cp {q(remote_server)} {q(remote_backup)} && "
            f"if [ -f {q(remote_admin_html)} ]; then cp {q(remote_admin_html)} {q(remote_html_backup)}; fi && "
            f"if [ -f {q(remote_db)} ]; then cp {q(remote_db)} {q(remote_db_backup)}; fi && "
            f"mv {q(remote_tmp)} {q(remote_server)} && mv {q(remote_html_tmp)} {q(remote_admin_html)}",
        )
        if DEPLOY_SERVICE:
            run(
                client,
                f"if [ -f {q(SYSTEMD_UNIT_PATH)} ]; then cp {q(SYSTEMD_UNIT_PATH)} {q(unit_backup)}; fi && "
                f"mv {q(remote_service_tmp)} {q(SYSTEMD_UNIT_PATH)} && chmod 0644 {q(SYSTEMD_UNIT_PATH)}",
            )
        if RELAY_TOKEN:
            run(
                client,
                f"mkdir -p {q(dropin_dir)} && "
                f"mv {q(remote_env_tmp)} {q(RELAY_ENV_FILE)} && chmod 0600 {q(RELAY_ENV_FILE)} && "
                f"mv {q(remote_dropin_tmp)} {q(dropin_path)} && chmod 0644 {q(dropin_path)}",
            )
        if DEPLOY_SERVICE or RELAY_TOKEN:
            run(client, "systemctl daemon-reload")
        run(client, f"systemctl restart {q(SERVICE_NAME)}")
        health = run(
            client,
            "python3 - <<'PY'\n"
            "import urllib.request\n"
            f"print(urllib.request.urlopen({(LOCAL_BASE_URL + '/health')!r}, timeout=10).read().decode())\n"
            "PY",
        )
        print("deployed")
        print(f"backup={remote_backup}")
        print(f"db_backup={remote_db_backup}")
        if DEPLOY_SERVICE:
            print(f"service_backup={unit_backup}")
        print(health)
        if RELAY_TOKEN:
            relay_health = run(
                client,
                f"set -a; . {q(RELAY_ENV_FILE)}; set +a; python3 - <<'PY'\n"
                "import os\n"
                "import urllib.request\n"
                f"req = urllib.request.Request({(LOCAL_BASE_URL + '/api/lumi/relay/health')!r}, headers={{'Authorization': 'Bearer ' + os.environ['OPENCLAW_PUBLISH_RELAY_TOKEN']}})\n"
                "print(urllib.request.urlopen(req, timeout=10).read().decode())\n"
                "PY",
            )
            print("relay_token=configured")
            print(relay_health)
        else:
            print("relay_token=not configured; relay endpoints remain fail-closed")
    finally:
        client.close()


if __name__ == "__main__":
    main()
