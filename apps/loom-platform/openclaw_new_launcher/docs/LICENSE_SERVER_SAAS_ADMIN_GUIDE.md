# License Server SaaS Admin Guide

Applies to the current `license_server` member and license admin console.

Goal: give sales, support, and operations a repeatable way to create month cards, manage plan templates, configure gateway settings, and review historical license activity.

## 1. What This Console Does

The admin console manages four things:

1. Generate license codes.
2. Convert ordinary license codes into month-card or member-plan codes.
3. Batch update issued license codes.
4. Manage member gateway configuration so clients can refresh and receive the latest entitlement profile.

It is not a billing system. It does not automatically charge, deduct quota, or renew customers.

## 2. Login

Admin URL:

```text
https://license.heang.top/admin
```

The console requires an admin token from one of these sources:

- `admin_token.txt` on the server.
- `LICENSE_ADMIN_TOKEN` in the service environment.

Operational rules:

- Keep the token internal.
- Do not send the token to customers.
- Rotate the token immediately if there is any leak risk.

## 3. Recommended Plan Fields

Every paid plan should define at least:

- Customer name.
- Edition.
- Expiration date.
- Feature permissions.
- Member mode.
- Plan id.
- Gateway base URL.
- General token or API key.
- Image API key.
- Video API key.
- Default model.
- Allowed models.
- Quota JSON.

Recommended plan ids:

- `monthly`
- `quarterly`
- `yearly`
- `vip_monthly`

Do not invent new plan ids for every customer unless there is a real product difference.

Example quota:

```json
{
  "image": 100,
  "video": 20,
  "phoneAgent": true,
  "desktopAgent": true
}
```

## 4. Create A Month Card

1. Choose a plan template in the plan template section.
2. Fill customer name, edition, expiration date, activation count, and feature permissions.
3. Enable member mode when the code should carry gateway configuration.
4. Fill gateway URL, token, default model, allowed models, and quota JSON.
5. Generate the license code.
6. Save the generated code into the sales/support record.
7. Export the code for customer delivery.

Do not rely on the admin page as the only place where issued codes are remembered.

## 5. Convert Existing Codes To Month Cards

Single-code update:

1. Find the target code in the list.
2. Open edit mode.
3. Enable member mode.
4. Set the plan id, expiration date, gateway URL, model fields, and quota JSON.
5. Save changes.

Batch update:

1. Select multiple codes.
2. Open batch month-card update.
3. Fill expiration date, plan id, member mode, gateway URL, token, model fields, and quota JSON.
4. Save.

After update, the client receives new entitlement data the next time it refreshes member status or restarts.

## 6. Support Operations

### Find A Customer

Search by:

- Customer name.
- Full license code.
- License code suffix.

Useful filters:

- Enabled or disabled.
- Activated or unactivated.
- Member or normal code.

### Unbind A Device

1. Open the license detail view.
2. Review `installId`, `deviceId`, activation time, and plan.
3. Delete only the activation record that should be unbound.
4. Ask the customer to reactivate.

Do not delete the whole license unless the customer entitlement should be cancelled.

### Rotate Admin Token

1. Generate a new token.
2. Update `LICENSE_ADMIN_TOKEN` or `admin_token.txt`.
3. Restart the license service.
4. Confirm the old token no longer works.

## 7. Production Safety

- Back up `license.db` before batch updates and clear-all operations.
- Do not expose gateway tokens in screenshots or customer tickets.
- Keep audit logs enabled.
- Use `Cache-Control: no-store` for admin pages.
- Prefer a private operations machine for admin work.

Default backup path:

```text
/opt/openclaw-license/backups
```

Basic recovery shape:

```bash
cd /opt/openclaw-license
systemctl stop openclaw-license
cp backups/license.db.bak-YYYYMMDDHHMMSS license.db
systemctl start openclaw-license
systemctl status openclaw-license --no-pager
```
