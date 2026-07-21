"""Assembled default compatibility facade for package-level CLI use."""

from __future__ import annotations

import sys

from .facade_binding import bind_facade


_BINDINGS = bind_facade(sys.modules[__name__])

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
serve = _BINDINGS.serve
create_codes = _BINDINGS.create_codes
list_codes = _BINDINGS.list_codes
build_parser = _BINDINGS.build_parser
main = _BINDINGS.main

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
    "serve",
    "update_public_settings",
]
