#!/usr/bin/env python3
"""Compatibility entry point for the modular OpenClaw license server."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


# The bundled Windows runtime uses an isolated ._pth file and does not add the
# direct script's directory automatically.
_SERVER_DIR = str(Path(__file__).resolve().parent)
if _SERVER_DIR not in sys.path:
    sys.path.insert(0, _SERVER_DIR)

from luming_license.facade_binding import bind_facade  # noqa: E402
from luming_license.cli import CliCallbacks  # noqa: E402


_BINDINGS = bind_facade(sys.modules[__name__])
_CLI_BINDINGS = _BINDINGS

# Explicit compatibility exports. The binder also installs the audited internal
# dependency graph used by routes and legacy monkeypatch-based integrations.
Handler = _BINDINGS.Handler
ActivationError = _BINDINGS.ActivationError
connect = _BINDINGS.connect
init_db = _BINDINGS.init_db
make_db_backup = _BINDINGS.make_db_backup
create_account_record = _BINDINGS.create_account_record
create_admin_session = _BINDINGS.create_admin_session
create_code_records = _BINDINGS.create_code_records
get_code_rows = _BINDINGS.get_code_rows
get_code_secret_rows = _BINDINGS.get_code_secret_rows
get_activation_rows = _BINDINGS.get_activation_rows
get_plan_rows = _BINDINGS.get_plan_rows
client_public_config = _BINDINGS.client_public_config
update_public_settings = _BINDINGS.update_public_settings
activate_code = _BINDINGS.activate_code
find_member_license = _BINDINGS.find_member_license
publish_relay_enqueue = _BINDINGS.publish_relay_enqueue
publish_relay_claim = _BINDINGS.publish_relay_claim
publish_relay_complete = _BINDINGS.publish_relay_complete
publish_relay_status = _BINDINGS.publish_relay_status


def serve(_args: argparse.Namespace) -> None:
    return _CLI_BINDINGS.serve(_args)


def create_codes(args: argparse.Namespace) -> None:
    return _CLI_BINDINGS.create_codes(args)


def list_codes(_args: argparse.Namespace) -> None:
    return _CLI_BINDINGS.list_codes(_args)


def public_key(_args: argparse.Namespace) -> None:
    return _CLI_BINDINGS.public_key(_args)


def build_parser() -> argparse.ArgumentParser:
    callbacks = CliCallbacks(
        serve=serve,
        create_codes=create_codes,
        list_codes=list_codes,
        public_key=public_key,
    )
    return _CLI_BINDINGS.build_parser(callbacks)


def main() -> None:
    args = build_parser().parse_args()
    args.func(args)


__all__ = [
    "ActivationError",
    "Handler",
    "activate_code",
    "build_parser",
    "client_public_config",
    "connect",
    "create_account_record",
    "create_admin_session",
    "create_code_records",
    "create_codes",
    "find_member_license",
    "get_activation_rows",
    "get_code_rows",
    "get_code_secret_rows",
    "get_plan_rows",
    "init_db",
    "list_codes",
    "main",
    "make_db_backup",
    "publish_relay_claim",
    "publish_relay_complete",
    "publish_relay_enqueue",
    "publish_relay_status",
    "public_key",
    "serve",
    "update_public_settings",
]


if __name__ == "__main__":
    main()
