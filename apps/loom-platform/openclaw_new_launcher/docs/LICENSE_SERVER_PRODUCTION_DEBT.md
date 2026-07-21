# License Server Production Debt

Scope: `license_server` admin console, license codes, membership plans, gateway configuration, and operations.

Current state: the service has the basic shape of a SaaS control console. It supports license editing, batch month-card updates, member refresh, audit logs, and backup-before-change behavior. The remaining work is mostly production governance.

## P0: Must Stay Closed Before Public Operations

### Audit Records

Status: implemented.

The server records creation, edit, batch update, enable/disable, delete, and clear-all admin actions. Gateway tokens are redacted in audit output.

Validation:

- Editing a license code creates an audit entry.
- Audit records include before/after fields where appropriate.
- Gateway tokens are not exposed.

### Database Backup

Status: implemented for the first production pass.

Before risky data mutations, the service copies `license.db` into `LICENSE_BACKUP_DIR`. The default production path is `/opt/openclaw-license/backups`.

Validation:

- Batch updates generate timestamped backup files.
- The audit log references the backup file where relevant.
- The rollback procedure is documented before production use.

### Admin Token Operations

Status: partially mitigated.

The current service still uses a single admin token. Audit records include a short token hash so operators can identify which token was used without exposing the token itself.

Next step:

- Document token rotation.
- Add multi-admin RBAC when team operations require it.

## P1: Production Experience

### Plan Templates

Status: implemented for the first pass.

Default plan templates include monthly, quarterly, yearly, and VIP monthly packages. Creating or batch-updating licenses can reuse these templates.

Validation:

- Selecting a plan fills duration, feature flags, default model, gateway profile, and quota fields.

### Search, Filter, and Pagination

Status: implemented for the first pass.

The admin console supports search by customer name, full code, or code suffix. It also supports enabled/disabled, activated/unactivated, member/normal filters, and paginated display.

Validation:

- 1000 license rows remain usable.
- Operators can locate a customer by name or code suffix.

### Activation Details

Status: implemented.

The license detail view shows `installId`, `deviceId`, activation time, and plan details. Single activation records can be deleted for support-side unbinding.

Validation:

- Support can unbind one device without deleting the customer license.

## P2: Long-Term Governance

### Quota Accounting

The current quota JSON is a configuration layer, not a billing engine. If monthly cards become real metered plans, add usage reporting and daily/monthly aggregation for image, video, and task consumption.

### Gateway Token Encryption

Gateway tokens should not be displayed back to the admin UI. Longer term, store sensitive gateway fields encrypted at rest.

### Multi-Tenant Roles

When sales, support, and operations teams use the console together, add roles and permissions instead of sharing one admin token.
